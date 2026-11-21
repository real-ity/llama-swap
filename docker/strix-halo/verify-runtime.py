"""Relocate donor symlinks and check engine entry points without model weights."""

import os
from pathlib import Path
import runpy
import subprocess

launcher = runpy.run_path('/usr/local/bin/strix-launch')
root = launcher['RUNTIMES']


def fix_links(prefix):
    for directory, dirs, files in os.walk(prefix, followlinks=False):
        for name in dirs + files:
            path = Path(directory) / name
            if path.is_symlink():
                target = os.readlink(path)
                relocated = prefix / target.lstrip('/')
                if target.startswith('/') and os.path.lexists(relocated):
                    path.unlink()
                    path.symlink_to(os.path.relpath(relocated, path.parent))


def check(command, expected=(), env=None):
    run = subprocess.run(command, env=env, text=True, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, timeout=120)
    if run.returncode or any(flag not in run.stdout for flag in expected):
        raise RuntimeError(f'{command} failed or lacked {expected}:\n{run.stdout}')
    print(f'checked: {" ".join(command)}', flush=True)


llama = root / 'llama'
if not (llama / 'lib64').is_symlink():
    (llama / 'lib64').symlink_to('usr/lib64')
for donor in ('llama', 'flash', 'halogen'):
    fix_links(root / donor)

check(['strix-launch', 'llama', '--help'], ('--ctx-size', '--parallel', '--no-kv-unified',
                                           '--n-gpu-layers', '--load-mode', '--flash-attn'))
check(['strix-launch', 'sd', '--help'], ('--listen-ip', '--llm', '--diffusion-model', '--vae'))
check(['strix-launch', 'sd-cli', '--help'], ('--diffusion-model',))
check(['strix-launch', 'comfyui', '--help'], ('--extra-model-paths-config', '--user-directory', '--database-url'))
for donor, engine in (('halogen', 'halogen'), ('flash', 'flash_serve')):
    path, loading, env = launcher['invocation'](donor)
    check([*loading, '--list', str(path / 'usr/local/bin' / engine)], env=env)
    flags = ('--tokenizer', '--engine', '--max-tokens-cap')
    if donor == 'flash':
        flags += ('--context',)
    check([*loading, str(path / 'usr/local/bin/python3.12'),
           str(path / 'halogen/tools/serve_api.py'), '--help'], flags, env)
