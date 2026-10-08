import copy
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest import mock

from infergrade import cuda_device_policy as policy, cuda_job_choices as choices
from infergrade.models import RunRequest
from infergrade.native_cuda_devices import Device, environment_kwargs

A = 'GPU-aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
B = 'GPU-bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb'
DEVICES = (Device(A, 0, 'pci-a', 'Card A', 16384), Device(B, 1, 'pci-b', 'Card B', 24576))


class CudaJobChoicesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name) / 'config'
        patcher = mock.patch.dict(os.environ, {'INFERGRADE_CONFIG_DIR': str(self.directory)})
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch('infergrade.cuda_device_policy.inventory', return_value=DEVICES)
        patcher.start()
        self.addCleanup(patcher.stop)

    def request(self, **change):
        return RunRequest(model='test/model', backend='llama.cpp', tier='canary', simulate=False, execution_mode='local_native', **change)

    def job(self, saved=None):
        offers, _ = choices._offers(saved, DEVICES)
        selected = next(c for c in offers['choices'] if c['revision'] == offers['all_revision'])
        return {'native_device_policy_revision': policy.descriptor(saved)['revision'] if saved else None,
                'native_device_inventory_revision': offers['inventory_revision'], 'native_device_choice': selected}

    def test_offers_are_uuid_free_and_preserve_configured_order_and_explicit_unset(self):
        unset, _ = choices._offers(None, DEVICES)
        self.assertEqual(len(unset['choices']), 3)
        self.assertNotIn('GPU-', json.dumps(unset))
        self.assertNotIn('uuid', json.dumps(unset))
        policy.set_policy([B, A])
        saved = policy.load_policy()
        offers, private = choices._offers(saved, DEVICES)
        self.assertEqual([d['uuid'] for d in private[offers['all_revision']]['devices']], [B, A])
        self.assertEqual(private[offers['preferred_single_revision']]['devices'][0]['uuid'], B)
        self.assertNotEqual(offers['inventory_revision'], unset['inventory_revision'])
        self.assertEqual(len(offers['choices']), 3)

    def test_explicit_job_choice_uses_one_fresh_probe_and_never_changes_default(self):
        policy.set_policy([B])
        saved = copy.deepcopy(policy.load_policy())
        job = self.job(saved)
        request = self.request()
        with mock.patch('infergrade.cuda_job_choices.inventory', return_value=DEVICES) as probe, mock.patch('infergrade.native_cuda_devices.inventory') as second:
            result = choices.apply_job_choice(request, job)
        self.assertEqual(result, job['native_device_choice'])
        probe.assert_called_once_with()
        second.assert_not_called()
        self.assertEqual(request.cuda_device_uuids, [B, A])
        self.assertEqual(policy.load_policy(), saved)
        policy.set_policy([A])
        self.assertEqual(environment_kwargs(request)['env']['CUDA_VISIBLE_DEVICES'], B + ',' + A)

    def test_unset_default_requires_explicit_null_and_can_request_both_without_writes(self):
        job = self.job()
        with mock.patch('infergrade.cuda_job_choices.inventory', return_value=DEVICES):
            choices.apply_job_choice(self.request(), job)
        self.assertFalse(self.directory.exists())
        for field in ('native_device_policy_revision', 'native_device_inventory_revision', 'native_device_choice'):
            incomplete = dict(job)
            incomplete.pop(field)
            with self.assertRaises(RuntimeError):
                choices.apply_job_choice(self.request(), incomplete)

    def test_stale_or_malformed_choices_fail_before_freezing(self):
        job = self.job()
        for change in ({'native_device_inventory_revision': '0' * 64}, {'native_device_choice': None},
                       {'native_device_choice': {**job['native_device_choice'], 'device_count': True}},
                       {'native_device_choice': {**job['native_device_choice'], 'uuid': A}},
                       {'native_device_choice': {**job['native_device_choice'], 'revision': '0' * 64}}):
            request = self.request()
            with mock.patch('infergrade.cuda_job_choices.inventory', return_value=DEVICES), self.assertRaises(RuntimeError):
                choices.apply_job_choice(request, {**job, **change})
            self.assertIsNone(getattr(request, '_native_cuda_selection', None))
        for physical in ((DEVICES[0],), tuple(reversed(DEVICES)),
                         (Device(A, 0, 'pci', 'Changed Card', 16384), DEVICES[1]),
                         (Device(A, 0, 'pci', 'Card A', 32768), DEVICES[1])):
            with mock.patch('infergrade.cuda_job_choices.inventory', return_value=physical), self.assertRaises(RuntimeError):
                choices.apply_job_choice(self.request(), job)

    def test_default_change_during_probe_is_rejected_and_other_lanes_preserved(self):
        job = self.job()
        def discover():
            policy.set_policy([B])
            return DEVICES
        with mock.patch('infergrade.cuda_job_choices.inventory', side_effect=discover), self.assertRaises(RuntimeError):
            choices.apply_job_choice(self.request(), job)
        for change in ({'execution_mode': 'local_container'}, {'backend': 'ollama'}, {'runtime_selector': {'accelerator': {'api': 'cpu'}}}):
            request = self.request()
            for key, value in change.items():
                setattr(request, key, value)
            self.assertIsNone(choices.apply_job_choice(request, {}))
            with self.assertRaisesRegex(RuntimeError, 'native CUDA'):
                choices.apply_job_choice(request, job)

    def test_heartbeat_does_not_wait_for_held_probe_and_never_uses_expired_inventory(self):
        entered, release = threading.Event(), threading.Event()
        now = [0.0]
        probes = []
        def discover():
            probes.append(True)
            entered.set()
            release.wait(2)
            return DEVICES
        cache = choices.InventoryCache(discover, lambda: now[0])
        self.addCleanup(release.set)
        self.assertIsNone(cache.read())
        self.assertTrue(entered.wait(1))
        with mock.patch.object(choices, '_CACHE', cache):
            result = choices.heartbeat_metadata({'native_device_policy': None, 'message': 'active job'})
            self.assertIsNone(result['native_device_choices'])
            self.assertEqual(result['message'], 'active job')
            policy.set_policy([B])
            current = policy.descriptor(policy.load_policy())
            for _ in range(10):
                self.assertIsNone(choices.heartbeat_metadata({'native_device_policy': current})['native_device_choices'])
            self.assertEqual(len(probes), 1)
            release.set()
            for _ in range(100):
                if not cache.busy:
                    break
                time.sleep(.01)
            first = choices.heartbeat_metadata({'native_device_policy': current})
            self.assertIsNotNone(first['native_device_choices'])
            all_choice = next(c for c in first['native_device_choices']['choices'] if c['revision'] == first['native_device_choices']['all_revision'])
            self.assertEqual(all_choice['devices'][0]['model'], 'Card B')
            policy.set_policy([A])
            current = policy.descriptor(policy.load_policy())
            changed = choices.heartbeat_metadata({'native_device_policy': current})
            self.assertNotEqual(changed['native_device_choices']['inventory_revision'], first['native_device_choices']['inventory_revision'])
            # An old heartbeat baseline cannot advertise a choice for a new default.
            self.assertIsNone(choices.heartbeat_metadata({'native_device_policy': None})['native_device_choices'])
            with cache.lock:
                cache.busy = True
            now[0] = choices.TTL_SECONDS + 1
            stale = choices.heartbeat_metadata({'native_device_policy': current})
            self.assertIsNone(stale['native_device_choices'])
            self.assertEqual(stale['native_device_policy'], current)
            self.assertNotIn('native_device_policy_warning', stale)

    def test_worker_rejects_stale_explicit_choice_before_doctor_or_artifacts(self):
        from infergrade.worker import execute_run_job
        job = {**self.job(), 'run_id': 'run-choice', 'run_config_id': 'config-choice',
               'native_device_inventory_revision': '0' * 64}
        request = self.request()
        with mock.patch('infergrade.cuda_job_choices.inventory', return_value=DEVICES), mock.patch('infergrade.worker.heartbeat_runner'), mock.patch('infergrade.worker.heartbeat_run_job'), mock.patch('infergrade.worker.fetch_run_config', return_value={}), mock.patch('infergrade.worker.request_from_run_config_document', return_value=request), mock.patch('infergrade.worker.resolve_worker_output_dir', return_value=str(Path(self.tmp.name) / 'bundle')), mock.patch('infergrade.worker.run_doctor') as doctor, mock.patch('infergrade.worker.run_infergrade') as execute, mock.patch('infergrade.worker.fail_run_job') as failure:
            result = execute_run_job('http://127.0.0.1:8000', job, 'worker-choice')
            self.assertFalse(result['completed'])
            self.assertIn('queue the benchmark again', result['error'])
            doctor.assert_not_called()
            execute.assert_not_called()
            failure.assert_called_once()
            self.assertIsNone(getattr(request, '_native_cuda_selection', None))
        self.assertFalse((Path(self.tmp.name) / 'bundle').exists())

    def test_exported_closed_schema_and_simulation_gate(self):
        from infergrade.contracts import load_contract_manifest, repo_root
        from infergrade.json_schema_subset import validate_json_schema
        path = repo_root() / 'schemas/json/native_cuda_job_choices.schema.json'
        self.assertIn('schemas/json/native_cuda_job_choices.schema.json', load_contract_manifest()['schema_files'])
        schema = json.loads(path.read_text())
        offers, _ = choices._offers(None, DEVICES)
        self.assertEqual(validate_json_schema(offers, schema, path), [])
        job = self.job()
        self.assertEqual(validate_json_schema(job, schema, path), [])
        for count in range(1, 17):
            candidate = copy.deepcopy(job)
            candidate['native_device_choice']['device_count'] = count
            candidate['native_device_choice']['devices'] = [copy.deepcopy(job['native_device_choice']['devices'][0]) for _ in range(count)]
            self.assertEqual(validate_json_schema(candidate, schema, path), [])
            candidate['native_device_choice']['devices'].pop()
            self.assertTrue(validate_json_schema(candidate, schema, path))
            candidate['native_device_choice']['devices'] += [copy.deepcopy(job['native_device_choice']['devices'][0])] * 2
            self.assertTrue(validate_json_schema(candidate, schema, path))
        for changed in ({**job, 'uuid': A}, {**job, 'native_device_policy_revision': False},
                        {**job, 'native_device_choice': {**job['native_device_choice'], 'device_count': True}}):
            self.assertTrue(validate_json_schema(changed, schema, path))
        request = self.request()
        request.simulate = True
        with mock.patch('infergrade.cuda_job_choices.inventory') as probe, self.assertRaises(ValueError):
            choices.apply_job_choice(request, job)
        probe.assert_not_called()

    def test_invalid_inventory_projection_and_missing_schema_never_leak_paths(self):
        tiny = (Device(A, 0, 'pci', 'Card A', 1),)
        with self.assertRaisesRegex(RuntimeError, 'no fallback'):
            choices._offers(None, tiny)
        choices._binding_schema.cache_clear()
        self.addCleanup(choices._binding_schema.cache_clear)
        with mock.patch('infergrade.cuda_job_choices.runner_root', return_value=Path(self.tmp.name) / 'private-path'):
            with self.assertRaises(RuntimeError) as failure:
                choices._binding_schema()
        self.assertNotIn('private-path', str(failure.exception))

    def test_subset_primary_order_and_maximum_inventory_are_bounded(self):
        physical = tuple(Device('GPU-%08x-aaaa-aaaa-aaaa-aaaaaaaaaaaa' % i, i, 'pci', 'Card %d' % i, 16384)
                         for i in range(16))
        saved = choices._policy([physical[7], physical[2]])
        offers, private = choices._offers(saved, physical)
        self.assertEqual(len(offers['choices']), 18)
        self.assertEqual(private[offers['all_revision']]['devices'][:2], saved['devices'])
        self.assertEqual(private[offers['preferred_single_revision']]['devices'], saved['devices'][:1])
        self.assertIn(policy.descriptor(saved)['revision'], private)
        self.assertNotIn('uuid', json.dumps(offers))

    def test_discovery_failure_clears_offer_cache_without_erasing_saved_policy(self):
        cache = choices.InventoryCache(lambda: (_ for _ in ()).throw(RuntimeError('private path')))
        cache.busy = True
        cache._refresh()
        self.assertFalse(cache.busy)
        self.assertIsNone(cache.devices)
        policy.set_policy([A])
        current = policy.descriptor(policy.load_policy())
        with mock.patch.object(choices, '_CACHE', mock.Mock(read=lambda: None)):
            metadata = choices.heartbeat_metadata({'native_device_policy': current, 'message': 'active'})
        self.assertEqual(metadata['native_device_policy'], current)
        self.assertEqual(metadata['message'], 'active')
        self.assertIsNone(metadata['native_device_choices'])
        self.assertNotIn('private path', str(metadata))
