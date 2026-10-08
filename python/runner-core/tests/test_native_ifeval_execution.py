import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from infergrade import native_ifeval
from infergrade.capabilities import _benchmark_spec_for_request, capability_images_for_request
from infergrade.models import RunRequest


class NativeIFEvalExecutionTests(unittest.TestCase):
    def _fixture(self, root):
        manifest = {'source_files': {}, 'nltk_resources': {}, 'dataset': {'sha256': hashlib.sha256(b'fixture').hexdigest()}}
        (root / 'manifest.json').write_text(json.dumps(manifest))
        data = root / 'source/instruction_following_eval/data/input_data.jsonl'
        data.parent.mkdir(parents=True)
        data.write_bytes(b'fixture')
        (root / 'bootstrap.py').write_text('raise AssertionError("must not execute")')
        (root / 'python').write_text('not an interpreter')
        manifest_sha = native_ifeval._digest(root / 'manifest.json')
        receipt = {'schema_version':'infergrade.native_ifeval_receipt.v1', 'protocol_id':native_ifeval.PROTOCOL_ID,
                   'container_parity':'unqualified_distinct_protocol', 'target':'fixture', 'python_version':'3.12.13',
                   'manifest_sha256':manifest_sha, 'executable':'python', 'links':{},
                   'files':{p.relative_to(root).as_posix():native_ifeval._digest(p) for p in root.rglob('*') if p.is_file()}}
        path = root / native_ifeval.RECEIPT_NAME
        path.write_text(json.dumps(receipt))
        trusted = SimpleNamespace(IDENTITY={'target':'fixture','manifest_sha256':manifest_sha,'receipt_sha256':native_ifeval._digest(path)})
        return receipt, trusted, manifest_sha

    def test_self_rehashed_receipt_cannot_authorize_changed_bootstrap(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt, trusted, manifest_sha = self._fixture(root)
            with mock.patch.object(native_ifeval, '_target', return_value='fixture'), mock.patch.object(native_ifeval, 'MANIFEST_SHA256', manifest_sha), mock.patch.dict(sys.modules, {'infergrade._native_ifeval_identity':trusted}):
                native_ifeval.verify_bundle(root)
                (root / 'bootstrap.py').write_text('changed executable code')
                receipt['files']['bootstrap.py'] = native_ifeval._digest(root / 'bootstrap.py')
                (root / native_ifeval.RECEIPT_NAME).write_text(json.dumps(receipt))
                with mock.patch.object(native_ifeval, '_execute', side_effect=AssertionError('must not execute')):
                    with self.assertRaisesRegex(ValueError, 'trusted package identity'):
                        native_ifeval.preflight(root)

    def test_unrecorded_dependency_and_manifest_change_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt, trusted, manifest_sha = self._fixture(root)
            with mock.patch.object(native_ifeval, '_target', return_value='fixture'), mock.patch.object(native_ifeval, 'MANIFEST_SHA256', manifest_sha), mock.patch.dict(sys.modules, {'infergrade._native_ifeval_identity':trusted}):
                (root / 'injected.py').write_text('pass')
                with self.assertRaisesRegex(ValueError, 'unrecorded file'):
                    native_ifeval.verify_bundle(root)
                (root / 'injected.py').unlink()
                (root / 'manifest.json').write_text('{}')
                with self.assertRaisesRegex(ValueError, 'file verification'):
                    native_ifeval.verify_bundle(root)

    def test_native_assistant_selection_does_not_mutate_container_spec(self):
        native = RunRequest(model='fixture', backend='llama.cpp', use_case='general_assistant', tier='canary', capability='auto', execution_mode='local_native')
        container = RunRequest(model='fixture', backend='llama.cpp', use_case='general_assistant', tier='canary', capability='auto', execution_mode='local_container')
        self.assertEqual(_benchmark_spec_for_request(native,'ifeval').execution_mode,'native_evaluator')
        self.assertEqual(_benchmark_spec_for_request(container,'ifeval').execution_mode,'container')
        self.assertEqual(capability_images_for_request(native),[])
        self.assertEqual(capability_images_for_request(container)[0]['benchmark_id'],'ifeval')

    def test_child_environment_drops_credentials_and_host_python_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'bootstrap.py').write_text('import os;assert "HF_TOKEN" not in os.environ;assert "PYTHONPATH" not in os.environ;print("ok")')
            with mock.patch.dict(os.environ, {'HF_TOKEN':'fixture-only', 'PYTHONPATH':'fixture-only'}):
                result = native_ifeval._execute(root, {'executable':sys.executable}, [])
            self.assertEqual(result.strip(), b'ok')

    def test_probe_failure_does_not_replay_evaluated_text(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'bootstrap.py').write_text('import sys;sys.stderr.write("fixture sensitive response");raise SystemExit(1)')
            with self.assertRaisesRegex(RuntimeError, 'no score was accepted') as error:
                native_ifeval._execute(root, {'executable':sys.executable}, [])
            self.assertNotIn('fixture sensitive response',str(error.exception))


if __name__ == '__main__':
    unittest.main()
