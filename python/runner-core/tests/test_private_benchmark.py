import io
import json
import os
import stat
import struct
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from infergrade.cli import main
from infergrade.private_benchmark import CHECKS, run_private_benchmark


class PrivateBenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.model = self.root / 'private model.gguf'
        self.model.write_bytes(b'GGUF' + struct.pack('<IQQ', 3, 0, 0))
        self.cli = self.root / 'llama-cli'
        self.server = self.root / 'llama-server'
        for path in (self.cli, self.server):
            path.write_bytes(b'operator-selected runtime')
            path.chmod(0o700)
        self.config = self.root / 'config'
        patcher = mock.patch.dict(os.environ, {'INFERGRADE_CONFIG_DIR': str(self.config)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def execute(self, **overrides):
        args = dict(model_file=str(self.model), use_case='general_assistant', tier='canary',
                    cli_path=str(self.cli), server_path=str(self.server))
        args.update(overrides)
        return run_private_benchmark(**args)

    def pipeline(self, request, **kwargs):
        self.request = request
        directory = Path(request.output_dir)
        directory.mkdir()
        (directory / 'report.md').write_text('Canonical scorer report')
        return {'bundle_id': 'real_bundle', 'report_path': str(directory / 'report.md'),
                'validation': {'valid': True}}

    def test_local_identity_and_native_inventory_never_resolve_hub_credentials(self):
        with mock.patch('infergrade.private_benchmark.run_infergrade', side_effect=self.pipeline), \
             mock.patch('infergrade.cli.resolve_runner_api_token', side_effect=AssertionError('credential lookup')), \
             mock.patch('urllib.request.urlopen', side_effect=AssertionError('network')), \
             mock.patch('infergrade.pairing.load_runner_profile', side_effect=AssertionError('pairing lookup')):
            receipt = self.execute()
        request = self.request
        self.assertFalse(request.simulate)
        self.assertFalse(request.upload)
        self.assertEqual(request.execution_mode, 'local_native')
        self.assertEqual(request.model, 'local/sha256-' + receipt['artifact_sha256'])
        self.assertEqual(request.quant_artifact, str(self.model.resolve()))
        self.assertEqual(request.llama_cpp_cli_path, str(self.cli.resolve()))
        self.assertEqual(request.llama_cpp_server_path, str(self.server.resolve()))
        self.assertEqual(request.benchmark_check_ids, CHECKS['general_assistant'] + ['interactive_chat_v1'])
        self.assertEqual(receipt['status'], 'completed')
        self.assertFalse(receipt['uploaded'])
        self.assertEqual(receipt['bundle_id'], 'real_bundle')
        self.assertEqual(receipt['artifact_sha256'], request.quant_artifact_sha256)
        if os.name != 'nt':
            self.assertEqual(stat.S_IMODE(Path(receipt['receipt_path']).stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(Path(receipt['report_path']).stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(Path(receipt['output_dir']).stat().st_mode), 0o700)

    def test_coding_and_reasoning_inventory_preserve_partial_surface_truth(self):
        for use_case in ('agentic_coding', 'reasoning'):
            with self.subTest(use_case=use_case), mock.patch('infergrade.private_benchmark.run_infergrade', side_effect=self.pipeline):
                receipt = self.execute(use_case=use_case, tier='standard')
                self.assertEqual(receipt['benchmark_check_ids'], CHECKS[use_case] + ['interactive_chat_v1'])
                self.assertEqual(self.request.tier, 'standard')
                self.assertTrue(self.request.tier_was_explicit)
                self.assertNotIn('score', receipt)

    def test_reject_remote_and_non_gguf_files_before_compute(self):
        bad = self.root / 'not a model.gguf'
        bad.write_bytes(b'not GGUF' * 10)
        with mock.patch('infergrade.private_benchmark.run_infergrade') as pipeline:
            for value in (str(bad), 'https://example.com/private.gguf', str(self.root)):
                with self.subTest(value=value), self.assertRaises((ValueError, OSError)):
                    self.execute(model_file=value)
            pipeline.assert_not_called()
        self.assertFalse((self.config / 'private-runs').exists())

    @unittest.skipIf(os.name == 'nt', 'Unix FIFO and umask semantics')
    def test_fifo_does_not_block_and_permissions_restore_after_failure(self):
        fifo = self.root / 'pipe.gguf'
        os.mkfifo(fifo)
        with self.assertRaises(ValueError):
            self.execute(model_file=str(fifo))
        previous = os.umask(0o022)
        try:
            with mock.patch('infergrade.private_benchmark.run_infergrade', side_effect=KeyboardInterrupt), self.assertRaises(KeyboardInterrupt):
                self.execute()
            restored = os.umask(0o022)
            self.assertEqual(restored, 0o022)
        finally:
            os.umask(previous)
        receipt = json.loads(next((self.config / 'private-runs').glob('*/receipt.json')).read_text())
        self.assertEqual(receipt['status'], 'failed')
        self.assertFalse(receipt['uploaded'])

    @unittest.skipIf(os.name == 'nt', 'Unix FIFO transition')
    def test_metadata_uses_verified_handle_and_rejects_replaced_fifo(self):
        from infergrade.gguf import read_gguf_architecture_stream
        def replace_after_hash(handle):
            self.model.unlink()
            os.mkfifo(self.model)
            return read_gguf_architecture_stream(handle)
        with mock.patch('infergrade.private_benchmark.read_gguf_architecture_stream', side_effect=replace_after_hash), \
             mock.patch('infergrade.private_benchmark.run_infergrade') as pipeline, self.assertRaises(ValueError):
            self.execute()
        pipeline.assert_not_called()

    def test_cache_lease_survives_identity_check_and_entire_pipeline(self):
        from contextlib import contextmanager
        active = []
        @contextmanager
        def lease(request):
            self.assertFalse(request.simulate)
            active.append(request.quant_artifact)
            try:
                yield
            finally:
                active.clear()
        def pipeline(request, **kwargs):
            self.assertEqual(active, [str(self.model.absolute())])
            return self.pipeline(request, **kwargs)
        with mock.patch('infergrade.private_benchmark.request_cache_lease', side_effect=lease), \
             mock.patch('infergrade.private_benchmark.run_infergrade', side_effect=pipeline):
            self.execute()
        self.assertEqual(active, [])

    def test_failed_validation_is_not_a_completed_local_result(self):
        with mock.patch('infergrade.private_benchmark.run_infergrade', return_value={'validation': {'valid': False}}), self.assertRaises(RuntimeError):
            self.execute()
        receipt = json.loads(next((self.config / 'private-runs').glob('*/receipt.json')).read_text())
        self.assertEqual(receipt['status'], 'failed')
        self.assertIsNone(receipt['bundle_id'])

    @unittest.skipIf(os.name == 'nt', 'Windows symlink creation requires special privileges')
    def test_linked_private_storage_is_not_followed(self):
        self.config.mkdir()
        target = self.root / 'outside'
        target.mkdir()
        (self.config / 'private-runs').symlink_to(target, target_is_directory=True)
        with mock.patch('infergrade.private_benchmark.run_infergrade') as pipeline, self.assertRaises(ValueError):
            self.execute()
        pipeline.assert_not_called()
        self.assertEqual(list(target.iterdir()), [])

    def test_cli_has_no_upload_or_api_parameters_and_keeps_json_clean(self):
        out = io.StringIO()
        argv = ['benchmark-local', '--model-file', str(self.model), '--llama-cpp-cli-path', str(self.cli),
                '--llama-cpp-server-path', str(self.server), '--json']
        with mock.patch('infergrade.private_benchmark.run_infergrade', side_effect=self.pipeline), redirect_stdout(out):
            self.assertEqual(main(argv), 0)
        self.assertFalse(json.loads(out.getvalue())['uploaded'])
        for extra in ('--upload', '--api-token', '--request-file'):
            with self.subTest(extra=extra), redirect_stdout(io.StringIO()), mock.patch('sys.stderr', new=io.StringIO()), self.assertRaises(SystemExit):
                main(argv + [extra, 'unsafe'])


if __name__ == '__main__':
    unittest.main()
