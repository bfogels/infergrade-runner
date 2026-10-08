import copy
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from infergrade import cuda_device_policy as policy
from infergrade.models import RunRequest
from infergrade.native_cuda_devices import Device, environment_kwargs, namespace_devices

A = 'GPU-aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
B = 'GPU-bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb'
DEVICES = (Device(A, 2, '00000000:01:00.0', 'Card A', 16384),
           Device(B, 7, '00000000:02:00.0', 'Card B', 24576))


class CudaDevicePolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name) / 'config'
        patcher = mock.patch.dict(os.environ, {'INFERGRADE_CONFIG_DIR': str(self.directory)})
        patcher.start()
        self.addCleanup(patcher.stop)
        for target in ('infergrade.cuda_device_policy.inventory', 'infergrade.native_cuda_devices.inventory'):
            patcher = mock.patch(target, return_value=DEVICES)
            patcher.start()
            self.addCleanup(patcher.stop)

    def request(self, **kwargs):
        return RunRequest(model='test/model', backend='llama.cpp', tier='canary', simulate=False,
                          execution_mode='local_native', **kwargs)

    def test_unset_preserves_existing_execution_without_creating_state(self):
        request = self.request()
        self.assertIsNone(policy.load_policy())
        self.assertIsNone(policy.apply_policy(request, hub_job=True))
        self.assertEqual(request.cuda_device_uuids, [])
        self.assertFalse(self.directory.exists())

    def test_ordered_choice_is_atomic_private_and_uuid_free_in_heartbeat(self):
        descriptor = policy.set_policy([B, A])
        self.assertEqual(descriptor['device_count'], 2)
        self.assertEqual(descriptor['devices'][0], {'model': 'Card B', 'vram_gb': 24.0})
        state = policy.load_policy()
        self.assertEqual([d['uuid'] for d in state['devices']], [B, A])
        if os.name != 'nt':
            self.assertEqual((self.directory / 'cuda-device-policy.json').stat().st_mode & 0o777, 0o600)
        metadata = policy.policy_heartbeat_metadata({'message': 'still listening'})
        self.assertEqual(metadata['native_device_policy'], descriptor)
        self.assertNotIn('GPU-', json.dumps(metadata))
        self.assertNotIn('uuid', json.dumps(metadata))
        self.assertFalse(list(self.directory.glob('.cuda-policy-*')))

    def test_hub_job_requires_exact_revision_before_device_query(self):
        first = policy.set_policy([A])
        policy.set_policy([B])
        for expected in (None, first['revision'], 'future'):
            with self.subTest(expected=expected), mock.patch('infergrade.cuda_device_policy.prepare') as prepare:
                with self.assertRaisesRegex(RuntimeError, 'queue it again'):
                    policy.apply_policy(self.request(), expected, hub_job=True)
                prepare.assert_not_called()
        policy.set_policy([])
        with self.assertRaisesRegex(RuntimeError, 'queue it again'):
            policy.apply_policy(self.request(), first['revision'], hub_job=True)

    def test_matching_hub_snapshot_freezes_remapped_devices_and_survives_next_preference_change(self):
        first = policy.set_policy([B])
        request = self.request()
        self.assertEqual(policy.apply_policy(request, first['revision'], hub_job=True), first)
        self.assertEqual(namespace_devices(request), ('CUDA0',))
        policy.set_policy([A])
        self.assertEqual(environment_kwargs(request)['env']['CUDA_VISIBLE_DEVICES'], B)
        self.assertEqual(request.cuda_device_uuids, [B])

    def test_hardware_capacity_or_model_change_requires_new_consent(self):
        current = policy.set_policy([A])
        for devices in ((Device(A, 2, '00000000:01:00.0', 'Card A', 8192),),
                        (Device(A, 2, '00000000:01:00.0', 'Other Card', 16384),), ()):
            with self.subTest(devices=devices), mock.patch('infergrade.native_cuda_devices.inventory', return_value=devices):
                with self.assertRaises(RuntimeError):
                    policy.apply_policy(self.request(), current['revision'], hub_job=True)

    def test_invalid_selection_cannot_replace_saved_policy(self):
        original = policy.set_policy([A])
        for values in ([A, A], ['CUDA0'], [None], 'not-a-list', ['GPU-' + 'c' * 36]):
            with self.subTest(values=values), self.assertRaises(ValueError):
                policy.set_policy(values)
            self.assertEqual(policy.descriptor(policy.load_policy()), original)

    def test_invalid_closed_state_and_unknown_metadata_do_not_default_to_another_device(self):
        policy.set_policy([A])
        valid = policy.load_policy()
        invalid = []
        for field, value in (('model', None), ('memory_mib', True), ('memory_mib', 0), ('uuid', 'CUDA0')):
            candidate = copy.deepcopy(valid)
            candidate['devices'][0][field] = value
            invalid.append(candidate)
        invalid += [{**valid, 'extra': True}, {**valid, 'devices': valid['devices'] * 2}, 'x' * 17000]
        path = self.directory / 'cuda-device-policy.json'
        for value in invalid:
            path.write_text(json.dumps(value))
            with self.subTest(value=type(value)), self.assertRaises(ValueError):
                policy.load_policy()
            metadata = policy.policy_heartbeat_metadata({'message': 'active work continues'})
            self.assertIsNone(metadata['native_device_policy'])
            self.assertIn('native_device_policy_warning', metadata)
        self.assertIsNone(policy.set_policy([]))
        self.assertIsNone(policy.load_policy())

    @unittest.skipIf(os.name == 'nt', 'POSIX special file and permission checks')
    def test_special_link_and_shared_files_are_refused_without_blocking(self):
        policy.set_policy([A])
        path = self.directory / 'cuda-device-policy.json'
        os.chmod(path, 0o644)
        with self.assertRaisesRegex(ValueError, 'owner'):
            policy.load_policy()
        path.unlink()
        os.mkfifo(path)
        with self.assertRaises(ValueError):
            policy.load_policy()
        with self.assertRaises(RuntimeError):
            policy.set_policy([])
        path.unlink()
        target = self.directory / 'outside.json'
        target.write_text('{}')
        path.symlink_to(target)
        with self.assertRaises((OSError, ValueError)):
            policy.load_policy()
        with self.assertRaises(RuntimeError):
            policy.set_policy([])
        self.assertEqual(target.read_text(), '{}')

    def test_reordered_choices_have_distinct_consent_and_clear_needs_no_inventory(self):
        first = policy.set_policy([A, B])
        second = policy.set_policy([B, A])
        self.assertNotEqual(first['revision'], second['revision'])
        self.assertNotEqual(first['selection_fingerprint'], second['selection_fingerprint'])
        with mock.patch('infergrade.cuda_device_policy.inventory', side_effect=RuntimeError('offline')):
            status = policy.policy_status()
            self.assertFalse(status['available'])
            self.assertEqual(status['policy'], second)
            policy.set_policy([])
        self.assertIsNone(policy.load_policy())

    def test_conflicting_raw_request_and_simulation_do_not_weaken_selection(self):
        current = policy.set_policy([A])
        with self.assertRaises(ValueError):
            policy.apply_policy(self.request(cuda_device_uuids=[B]), current['revision'], hub_job=True)
        request = self.request()
        request.simulate = True
        with self.assertRaises(ValueError):
            policy.apply_policy(request)

    def test_other_execution_lanes_preserve_behavior_even_when_native_state_is_invalid(self):
        current = policy.set_policy([A])
        variants = ({"execution_mode": "local_container"}, {"execution_mode": "cloud_container"},
                    {"backend": "ollama"}, {"runtime_selector": {"accelerator": {"api": "cpu"}}},
                    {"runtime_selector": {"accelerator": {"api": "metal"}}})
        for corrupt in (False, True):
            if corrupt:
                (self.directory / 'cuda-device-policy.json').write_text('{invalid')
            for variant in variants:
                with self.subTest(corrupt=corrupt, variant=variant):
                    request = self.request()
                    for key, value in variant.items():
                        setattr(request, key, value)
                    self.assertIsNone(policy.apply_policy(request, hub_job=True))
                    self.assertEqual(request.cuda_device_uuids, [])
                    with self.assertRaisesRegex(RuntimeError, 'native CUDA'):
                        policy.apply_policy(request, current['revision'], hub_job=True)

    def test_cli_selection_reset_and_invalid_arguments_use_real_persisted_state(self):
        from infergrade.cli import main
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(['gpu-choice', 'select', '--cuda-device', B, '--json']), 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result['policy']['device_count'], 1)
        self.assertEqual([d['uuid'] for d in result['devices'] if d['selected']], [B])
        with self.assertRaises(SystemExit):
            main(['gpu-choice', 'select'])
        with self.assertRaises(SystemExit):
            main(['gpu-choice', 'status', '--cuda-device', A])
        self.assertEqual(policy.load_policy()['devices'][0]['uuid'], B)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['gpu-choice', 'reset', '--json']), 0)
        self.assertIsNone(policy.load_policy())

    @unittest.skipIf(os.name == 'nt', 'POSIX directory ownership boundary')
    def test_shared_writable_or_linked_config_directory_cannot_select_or_read(self):
        self.directory.mkdir(mode=0o777)
        os.chmod(self.directory, 0o777)
        for operation in (policy.load_policy, lambda: policy.set_policy([A])):
            with self.assertRaises(RuntimeError):
                operation()
        self.directory.rmdir()
        target = Path(self.tmp.name) / 'other'
        target.mkdir()
        self.directory.symlink_to(target, target_is_directory=True)
        with self.assertRaises(RuntimeError):
            policy.set_policy([])
        with self.assertRaises(RuntimeError):
            policy.load_policy()
        self.assertEqual(list(target.iterdir()), [])

    def test_unpinned_hub_job_reports_failure_before_doctor_or_model_execution(self):
        from infergrade.worker import execute_run_job
        policy.set_policy([B])
        request = self.request()
        with contextlib.ExitStack() as stack:
            for name in ('heartbeat_runner', 'heartbeat_run_job', 'fetch_run_config'):
                stack.enter_context(mock.patch('infergrade.worker.' + name, return_value={}))
            stack.enter_context(mock.patch('infergrade.worker.request_from_run_config_document', return_value=request))
            stack.enter_context(mock.patch('infergrade.worker.resolve_worker_output_dir', return_value=str(Path(self.tmp.name) / 'bundle')))
            doctor = stack.enter_context(mock.patch('infergrade.worker.run_doctor'))
            execute = stack.enter_context(mock.patch('infergrade.worker.run_infergrade'))
            failure = stack.enter_context(mock.patch('infergrade.worker.fail_run_job'))
            result = execute_run_job('http://127.0.0.1:8000', {'run_id': 'run-policy', 'run_config_id': 'config-policy'},
                                     'owned-worker', api_token=None)
            self.assertFalse(result['completed'])
            self.assertIn('queue it again', result['error'])
            doctor.assert_not_called()
            execute.assert_not_called()
            self.assertEqual(failure.call_args.args[1:3], ('run-policy', 'owned-worker'))
        self.assertFalse((Path(self.tmp.name) / 'bundle').exists())


if __name__ == '__main__':
    unittest.main()
