import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from infergrade.private_benchmark import CHECKS, SCHEMA, private_benchmark_history


class PrivateHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.config = Path(self.temporary.name) / 'config'
        patcher = mock.patch.dict(os.environ, {'INFERGRADE_CONFIG_DIR': str(self.config)})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.identifier = 'private_' + 'a' * 32
        self.bundle_id = 'qb_20261008_061454_d4c2fd93'

    def fixture(self, status='completed'):
        root = self.config / 'private-runs'
        root.mkdir(mode=0o700, parents=True)
        directory = root / self.identifier
        directory.mkdir(mode=0o700)
        bundle = directory / 'bundle'
        (bundle / 'results').mkdir(parents=True)
        (bundle / 'report.md').write_text('Real local report')
        self.receipt = {'schema_version': SCHEMA, 'id': self.identifier,
                        'created_at': '2026-10-08T06:14:54Z', 'status': status,
                        'use_case': 'general_assistant', 'tier': 'canary',
                        'model_filename': '<private & model>.gguf', 'artifact_sha256': 'f' * 64,
                        'benchmark_check_ids': CHECKS['general_assistant'] + ['interactive_chat_v1'],
                        'uploaded': False, 'bundle_id': self.bundle_id if status == 'completed' else None}
        self.receipt_path = directory / 'receipt.json'
        self.receipt_path.write_text(json.dumps(self.receipt))
        self.record = {'bundle_id': self.bundle_id, 'result_id': self.bundle_id + '_interactive_chat_v1',
                       'configuration': {'quant_artifact_sha256': 'f' * 64},
                       'capability': {'capability_status': 'partial', 'capability_score': 0.9,
                                      'capability_score_details': {'score_ready': False},
                                      'capability_component_scores': {'ifeval': 0.4, 'assistant_compositional_instruction_v2': 0.25,
                                                                      'unrequested': 0.99}}}
        self.record_path = bundle / 'results' / 'interactive_chat_v1.json'
        self.record_path.write_text(json.dumps(self.record))
        return directory

    def test_empty_history_does_not_create_storage(self):
        self.assertEqual(private_benchmark_history()['results'], [])
        self.assertFalse(self.config.exists())

    def test_preserves_components_and_suppresses_unready_headline(self):
        self.fixture()
        value = private_benchmark_history()
        self.assertEqual(value['unreadable_count'], 0)
        row = value['results'][0]
        self.assertIsNone(row['score'])
        self.assertEqual(row['component_scores'], {'ifeval': 0.4, 'assistant_compositional_instruction_v2': 0.25})
        self.assertEqual(row['model_filename'], '<private & model>.gguf')
        self.assertTrue(row['report_available'])
        self.assertNotIn('configuration', row)
        self.assertNotIn('prompt', row)

    def test_validated_ready_score_and_failed_reports_are_separate(self):
        self.fixture('failed')
        row = private_benchmark_history()['results'][0]
        self.assertEqual(row['status'], 'failed')
        self.assertIsNone(row['score'])
        self.assertEqual(row['component_scores'], {})
        self.assertTrue(row['report_available'])
        self.receipt.update(status='completed', bundle_id=self.bundle_id)
        self.receipt_path.write_text(json.dumps(self.receipt))
        self.record['capability']['capability_score_details']['score_ready'] = True
        self.record_path.write_text(json.dumps(self.record))
        self.assertEqual(private_benchmark_history()['results'][0]['score'], 0.9)

    def test_receipt_and_result_identity_mismatch_fail_closed(self):
        self.fixture()
        for key, value in [('id', '../outside'), ('uploaded', True), ('artifact_sha256', 'unknown')]:
            with self.subTest(key=key):
                bad = dict(self.receipt)
                bad[key] = value
                self.receipt_path.write_text(json.dumps(bad))
                result = private_benchmark_history()
                self.assertEqual(result['results'], [])
                self.assertEqual(result['unreadable_count'], 1)
        self.receipt_path.write_text(json.dumps(self.receipt))
        self.record['configuration']['quant_artifact_sha256'] = 'e' * 64
        self.record_path.write_text(json.dumps(self.record))
        self.assertEqual(private_benchmark_history()['results'], [])

    def test_status_objects_and_deep_json_are_not_projected(self):
        self.fixture()
        self.record['capability']['capability_status'] = {'private_prompt': 'must not cross'}
        self.record_path.write_text(json.dumps(self.record))
        self.assertEqual(private_benchmark_history()['results'], [])
        self.receipt_path.write_text('[' * 2000 + '0' + ']' * 2000)
        self.assertEqual(private_benchmark_history()['unreadable_count'], 1)

    def test_not_comparable_preserves_report_without_promoting_scores(self):
        self.fixture()
        self.record['capability']['capability_status'] = 'not_comparable'
        self.record['capability']['capability_score_details']['score_ready'] = True
        self.record_path.write_text(json.dumps(self.record))
        result = private_benchmark_history()
        self.assertEqual(result['unreadable_count'], 0)
        row = result['results'][0]
        self.assertTrue(row['report_available'])
        self.assertEqual(row['capability_status'], 'not_comparable')
        self.assertIsNone(row['score'])
        self.assertEqual(row['component_scores'], {})

    def test_scan_bound_counts_unrecognized_entries(self):
        from contextlib import nullcontext
        from types import SimpleNamespace
        self.fixture('failed')
        entries = [SimpleNamespace(name='unrecognized')] * 10002
        with mock.patch('infergrade.private_benchmark.os.scandir', return_value=nullcontext(iter(entries))):
            result = private_benchmark_history()
        self.assertTrue(result['truncated'])
        self.assertEqual(result['results'], [])

    @unittest.skipIf(os.name == 'nt', 'Unix symlink privilege')
    def test_links_and_nonregular_receipts_do_not_escape_or_block(self):
        self.fixture('failed')
        self.receipt_path.unlink()
        os.mkfifo(self.receipt_path)
        self.assertEqual(private_benchmark_history()['unreadable_count'], 1)
        self.receipt_path.unlink()
        external = Path(self.temporary.name) / 'external.json'
        external.write_text(json.dumps(self.receipt))
        self.receipt_path.symlink_to(external)
        self.assertEqual(private_benchmark_history()['results'], [])


if __name__ == '__main__':
    unittest.main()
