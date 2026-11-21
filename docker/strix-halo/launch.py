#!/opt/venv/bin/python
"""Run one Strix engine on demand inside the Compose container."""

import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time

RUNTIMES = Path('/opt/strix-engines')
COMFY = Path('/opt/ComfyUI')
DRM = Path('/sys/class/drm')
GIB = 1 << 30


def offline_env():
    env = dict(os.environ, HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
               HF_HUB_DISABLE_TELEMETRY='1', PYTHONDONTWRITEBYTECODE='1')
    for key in ('HALOGEN_DOWNLOAD', 'LD_LIBRARY_PATH', 'PYTHONHOME', 'PYTHONPATH'):
        env.pop(key, None)
    return env


def invocation(engine):
    env = offline_env()
    donor = 'llama' if engine in ('llama', 'sd', 'sd-cli') else engine
    root = RUNTIMES / donor
    if donor == 'llama':
        rocm = root / 'opt/rocm/core'
        system_lib = root / 'usr/lib64'
        extra_libs = [root / 'usr/local/lib64']
        env['ROCM_PATH'] = env['HIP_PATH'] = str(root / 'opt/rocm')
    else:
        site = root / 'usr/local/lib/python3.12/site-packages'
        rocm = site / '_rocm_sdk_core'
        system_lib = root / 'lib/x86_64-linux-gnu'
        extra_libs = [site / '_rocm_sdk_libraries/lib']
        defaults = json.loads((root / 'defaults.json').read_text())
        for key, value in defaults.items():
            if value.startswith(('/usr/local/', '/opt/halogen/')):
                value = str(root / value.lstrip('/'))
            env.setdefault(key, value)
        env['PYTHONHOME'] = str(root / 'usr/local')
        env['ROCM_PATH'] = env['HIP_PATH'] = str(rocm)
    libs = [root / 'usr/local/lib', *extra_libs, system_lib, rocm / 'lib',
            rocm / 'lib/rocm_sysdeps/lib', rocm / 'lib/llvm/lib']
    paths = ':'.join(map(str, libs))
    env['LD_LIBRARY_PATH'] = paths
    loader = [str(system_lib / 'ld-linux-x86-64.so.2'), '--library-path', paths]
    return root, loader, env


def require_files(*paths):
    missing = [str(path) for path in paths if not Path(path).is_file()]
    if missing:
        raise RuntimeError('missing local model files: ' + ', '.join(missing))


def exec_native(engine, args):
    # Check the documented local paths before starting an engine. Help/version
    # need no model, and llama-swap leaves other routes available if this fails.
    flags = ('--model',) if engine == 'llama' else ('--diffusion-model', '--llm', '--vae')
    require_files(*(args[args.index(flag) + 1] for flag in flags if flag in args))
    root, loader, env = invocation(engine)
    binary = (root / 'usr/local/bin/llama-server' if engine == 'llama' else
              RUNTIMES / 'sd/bin' / ('sd-server' if engine == 'sd' else engine))
    os.execve(loader[0], [*loader, str(binary), *args], env)


def exec_comfy(args):
    env = dict(offline_env(), TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL='1',
               TORCH_BLAS_PREFER_HIPBLASLT='1')
    python = '/opt/venv/bin/python'
    main = str(COMFY / 'main.py')
    os.chdir(COMFY)
    if args == ['--help']:
        os.execve(python, [python, main, '--help'], env)
    # ComfyUI may write state and images, but never into the shared models bind.
    scratch = Path('/tmp/strix-comfyui')
    directories = []
    for name in ('input', 'output', 'temp', 'user'):
        path = scratch / name
        path.mkdir(parents=True, exist_ok=True)
        directories += [f'--{name}-directory', str(path)]
    os.execve(python, [python, main, *args, '--disable-auto-launch',
                      '--disable-all-custom-nodes', *directories,
                      '--extra-model-paths-config', '/etc/llama-swap/comfy-models.yaml',
                      '--database-url', f'sqlite:///{scratch}/user/comfyui.db'], env)


def supervise(backend, frontend, env, port):
    children = []

    def stop(signum, _frame):
        raise SystemExit(128 + signum)

    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, stop)
    try:
        engine = subprocess.Popen(backend, env=env)
        children.append(engine)
        deadline = time.monotonic() + 590  # llama-swap has a 600 s readiness window
        while engine.poll() is None and time.monotonic() < deadline:
            try:
                with socket.create_connection(('127.0.0.1', port), timeout=0.25):
                    break
            except OSError:
                time.sleep(0.2)
        else:
            raise RuntimeError('Halogen engine exited or did not open its backend port')
        api = subprocess.Popen(frontend, env=env)
        children.append(api)
        while all(child.poll() is None for child in children):
            time.sleep(0.2)
        raise RuntimeError('Halogen engine or API exited; stopping the pair')
    finally:
        # The controller also signals the process group. Reap both children even
        # if only the launcher was signalled, then let the router start the next model.
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, signal.SIG_IGN)
        for child in children:
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


def check_flash_gtt(pool, slots, prefill):
    # Estimate for the pinned Flash Next v2 checkpoint and 0.18.22 backend:
    # 29,500 bytes per BF16 pool position, 115 MiB per slot, and 4.4 GiB
    # of device scratch at a 16,384-token prefill chunk. This is not a check
    # of host RAM or fragmentation and does not reserve GPU memory.
    scratch = prefill * 44 * GIB // (16384 * 10)
    required = pool * 29500 + slots * (115 << 20) + scratch
    counters = list(DRM.glob('card*/device/mem_info_gtt_total'))
    if len(counters) != 1:
        print('strix-launch: need exactly one AMD GPU with GTT counters to check Flash headroom',
              file=sys.stderr)
        return
    try:
        total = int(counters[0].read_text())
        used = int(counters[0].with_name('mem_info_gtt_used').read_text())
        if total <= 0 or used < 0:
            raise ValueError('invalid GTT counters')
    except (OSError, ValueError):
        print('strix-launch: cannot read AMD GTT counters; Flash headroom is unverified',
              file=sys.stderr)
        return
    available = max(0, total - used)
    if available < required:
        raise RuntimeError(f'Flash needs about {required / GIB:.1f} GiB of free GPU GTT; '
                           f'found {available / GIB:.1f} GiB. '
                           'Check GPU workload and the firmware UMA carve-out before retrying.')


def halogen(engine, args):
    flash = engine == 'flash'
    parser = argparse.ArgumentParser(prog=f'strix-launch {engine}')
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--checkpoint', type=Path, required=True)
    parser.add_argument('--tokenizer', type=Path, required=True)
    if flash:
        parser.add_argument('--table', type=Path, required=True)
        for arg in ('context', 'kv-pool', 'slots', 'prefill', 'reply-tokens'):
            parser.add_argument('--' + arg, type=int, required=True)
    cfg = parser.parse_args(args)
    require_files(cfg.checkpoint, cfg.tokenizer / 'tokenizer.json', *([cfg.table] if flash else []))
    if not 1 <= cfg.port <= 65535:
        parser.error('API port must be 1..65535')
    if flash and not (0 < cfg.reply_tokens <= min(65536, cfg.context) and
                      0 < cfg.prefill <= cfg.context <= 262144 and
                      cfg.kv_pool >= cfg.context and cfg.slots > 0):
        parser.error('invalid native Flash context, pool or token budget')
    if flash:
        check_flash_gtt(cfg.kv_pool, cfg.slots, cfg.prefill)
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1', 0))
        backend_port = reservation.getsockname()[1]
    if backend_port == cfg.port:
        raise RuntimeError('could not reserve a port distinct from the Halogen API port; retry')

    root, loader, env = invocation(engine)
    env.update(HALOGEN_CHECKPOINT=str(cfg.checkpoint), HALOGEN_TOKENIZER=str(cfg.tokenizer),
               HALOGEN_PORT=str(backend_port), HALOGEN_API_PORT=str(cfg.port), HALOGEN_BIND='127.0.0.1')
    backend = [*loader, str(root / 'usr/local/bin' / ('flash_serve' if flash else 'halogen'))]
    if flash:
        backend += ['--ck', str(cfg.checkpoint), '--ctx', str(cfg.context), '--slots', str(cfg.slots),
                    '--kv-pool', str(cfg.kv_pool), '--max-tok', str(cfg.prefill)]
        env.update(HALOGEN_CTX=str(cfg.context), HALOGEN_KV_SLOTS=str(cfg.slots),
                   HALOGEN_KV_POOL_POSITIONS=str(cfg.kv_pool), HALOGEN_KV_POOL_FIT='0',
                   HALOGEN_MAX_TOK=str(cfg.prefill), HALOGEN_PREFILL_CHUNK=str(cfg.prefill),
                   HALOGEN_MAX_TOKENS_DEFAULT=str(cfg.reply_tokens), HALOGEN_NGRAM_TABLE=str(cfg.table))
    else:
        backend += ['--checkpoint', str(cfg.checkpoint), '--serve']
    backend += ['--bind', '127.0.0.1', '--port', str(backend_port)]
    frontend = [*loader, str(root / 'usr/local/bin/python3.12'), str(root / 'halogen/tools/serve_api.py'),
                '--tokenizer', str(cfg.tokenizer), '--engine', f'127.0.0.1:{backend_port}',
                '--host', '127.0.0.1', '--port', str(cfg.port),
                '--max-tokens-cap', env.get('HALOGEN_MAX_TOKENS_CAP', '65536'),
                '--queue-timeout', env.get('HALOGEN_QUEUE_TIMEOUT', '3600')]
    if flash:
        frontend += ['--context', str(cfg.context)]
    with tempfile.TemporaryDirectory(prefix='strix-halogen-') as scratch:
        tuning = env.get('HALOGEN_MATMUL_TUNING_FILE')
        if tuning and Path(tuning).is_file():
            env['HALOGEN_MATMUL_TUNING_FILE'] = shutil.copy(tuning, scratch)
        supervise(backend, frontend, env, backend_port)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('engine', choices=('llama', 'sd', 'sd-cli', 'halogen', 'flash', 'comfyui'))
    parser.add_argument('args', nargs=argparse.REMAINDER)
    cfg = parser.parse_args()
    try:
        if cfg.engine in ('llama', 'sd', 'sd-cli'):
            exec_native(cfg.engine, cfg.args)
        elif cfg.engine == 'comfyui':
            exec_comfy(cfg.args)
        else:
            halogen(cfg.engine, cfg.args)
    except (OSError, RuntimeError) as error:
        print(f'strix-launch: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
