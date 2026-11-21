"""Model-free checks for the launcher. Run: python3 -m unittest discover -s docker/strix-halo."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import launch


class TestLauncher(unittest.TestCase):
    def test_missing_asset_stops_only_the_requested_launch(self):
        with tempfile.TemporaryDirectory() as tmp, patch('launch.invocation') as runtime:
            missing = str(Path(tmp) / 'absent.gguf')
            with self.assertRaisesRegex(RuntimeError, 'absent.gguf'):
                launch.exec_native('llama', ['--model', missing])
            runtime.assert_not_called()

    def test_flash_engine_and_api_share_native_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            checkpoint = root / 'model.hgn'
            table = root / 'table.hgn'
            tokenizer = root / 'tokenizer'
            tokenizer.mkdir()
            for path in (checkpoint, table, tokenizer / 'tokenizer.json'):
                path.touch()
            with patch('launch.invocation', return_value=(root, ['loader'], {})), \
                    patch('launch.supervise') as supervise:
                launch.halogen('flash', ['--port', '5801', '--checkpoint', str(checkpoint),
                                         '--tokenizer', str(tokenizer), '--table', str(table),
                                         '--context', '262144', '--kv-pool', '262144', '--slots', '1',
                                         '--prefill', '16384', '--reply-tokens', '16384'])
            engine, api, env, backend_port = supervise.call_args.args
            self.assertNotEqual(backend_port, 5801)
            self.assertEqual(engine[engine.index('--ctx') + 1], '262144')
            self.assertEqual(engine[engine.index('--kv-pool') + 1], '262144')
            self.assertEqual(engine[engine.index('--slots') + 1], '1')
            self.assertEqual(engine[engine.index('--max-tok') + 1], '16384')
            self.assertEqual(api[api.index('--context') + 1], '262144')
            self.assertEqual(api[api.index('--engine') + 1], f'127.0.0.1:{backend_port}')
            self.assertEqual(api[api.index('--port') + 1], '5801')
            self.assertEqual(env['HALOGEN_NGRAM_TABLE'], str(table))
            self.assertEqual(env['HALOGEN_MAX_TOKENS_DEFAULT'], '16384')
            self.assertEqual(env['HALOGEN_KV_POOL_FIT'], '0')

    def test_supervisor_reaps_both_children_when_api_exits(self):
        engine, api = Mock(), Mock()
        engine.poll.return_value = None
        api.poll.return_value = 1
        with patch('launch.subprocess.Popen', side_effect=[engine, api]), \
                patch('launch.socket.create_connection'), patch('launch.signal.signal'):
            with self.assertRaisesRegex(RuntimeError, 'API exited'):
                launch.supervise(['engine'], ['api'], {}, 5800)
        engine.terminate.assert_called_once()
        api.terminate.assert_not_called()
        engine.wait.assert_called_once_with(timeout=5)
        api.wait.assert_called_once_with(timeout=5)

    def test_no_inherited_download(self):
        with patch.dict('os.environ', {'HALOGEN_DOWNLOAD': 'must-not-be-used'}):
            env = launch.offline_env()
        self.assertNotIn('HALOGEN_DOWNLOAD', env)
        self.assertEqual(env['HF_HUB_OFFLINE'], '1')
        self.assertEqual(env['TRANSFORMERS_OFFLINE'], '1')
