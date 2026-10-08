import json
import os
import subprocess
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

from infergrade import native_cuda_devices as policy
from infergrade.adapters.llama_cpp import LlamaCppAdapter, _require_native_cuda_offload, native_cuda_required
from infergrade.models import RunRequest
from infergrade.request import request_from_dict, request_to_dict
from infergrade.runner import _build_result_record
from infergrade.json_schema_subset import validate_json_schema
from infergrade.paths import runner_root
from infergrade.runtime_placement import record_runtime_placement, validated_runtime_placement

A = 'GPU-aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
B = 'GPU-bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb'
ROWS = f'{A}, 2, 00000000:01:00.0, Card A, 16384\n{B}, 7, 00000000:02:00.0, Card B, 24564\n'


class NativeCudaDevicesTests(unittest.TestCase):
    def request(self, values=None):
        return RunRequest(model='test/model', backend='llama.cpp', tier='canary',
                          simulate=False, execution_mode='local_native',
                          cuda_device_uuids=values if values is not None else [])

    def prepare(self, request):
        with mock.patch('infergrade.native_cuda_devices.subprocess.run', return_value=mock.Mock(stdout=ROWS)):
            return policy.prepare(request)

    def test_inventory_is_bounded_named_model_only_and_preserves_physical_indices(self):
        with mock.patch('infergrade.native_cuda_devices.subprocess.run', return_value=mock.Mock(stdout=ROWS)) as run:
            devices = policy.inventory()
        self.assertEqual([device.index for device in devices], [2, 7])
        self.assertEqual([device.uuid for device in devices], [A, B])
        run.assert_called_once_with(policy.QUERY, check=True, capture_output=True, text=True, timeout=5)
        self.assertNotIn('serial', ','.join(policy.QUERY).lower())

    def test_single_card_remaps_to_cuda_zero_without_global_env_changes(self):
        request = self.request([B])
        self.prepare(request)
        with mock.patch.dict(os.environ, {'CUDA_VISIBLE_DEVICES': 'previous', 'POLICY_TEST_VALUE': 'preserved'}):
            kwargs = policy.environment_kwargs(request)
            self.assertEqual(kwargs['env']['CUDA_VISIBLE_DEVICES'], B)
            self.assertEqual(kwargs['env']['CUDA_DEVICE_ORDER'], 'PCI_BUS_ID')
            self.assertEqual(kwargs['env']['POLICY_TEST_VALUE'], 'preserved')
            self.assertEqual(os.environ['CUDA_VISIBLE_DEVICES'], 'previous')
        self.assertEqual(policy.namespace_devices(request), ('CUDA0',))
        self.assertEqual(policy.placement_flags(request, ['--fit', 'on']),
                         ['--fit', 'on', '--device', 'CUDA0', '--split-mode', 'none'])
        self.assertTrue(native_cuda_required(request))

    def test_both_cards_keep_requested_order_and_capacity_weighted_split(self):
        request = self.request([B, A])
        first = self.prepare(request)
        with mock.patch('infergrade.native_cuda_devices.inventory', side_effect=AssertionError('must stay frozen')):
            self.assertIs(policy.prepare(request), first)
        self.assertEqual(policy.environment_kwargs(request)['env']['CUDA_VISIBLE_DEVICES'], B + ',' + A)
        flags = policy.placement_flags(request, [])
        self.assertEqual(flags, ['--device', 'CUDA0,CUDA1', '--split-mode', 'layer', '--main-gpu', '0', '--tensor-split', '24564,16384'])
        original = {'accelerator_count': 3, 'memory_gb': 64, 'cpu_model': 'Host CPU', 'hardware_id': 'old'}
        selected = policy.selected_environment(request, original)
        self.assertEqual(selected['accelerator_count'], 2)
        self.assertEqual(selected['accelerator_model'], 'Card B')
        self.assertEqual(selected['accelerator_vram_total_gb'], round((24564 + 16384) / 1024, 2))
        self.assertEqual(original['accelerator_count'], 3)
        self.assertNotIn('uuid', json.dumps(selected).lower())

    def test_clearing_replacing_or_reordering_frozen_selection_is_rejected(self):
        request = self.request([A, B])
        self.prepare(request)
        for changed in ([], [B], [B, A]):
            request.cuda_device_uuids = changed
            with self.assertRaises(RuntimeError):
                policy.environment_kwargs(request)
            with self.assertRaises(RuntimeError):
                policy.prepare(request)

    def test_invalid_duplicate_unsupported_and_missing_selections_do_not_fallback(self):
        for values in (None, False, {}, [A, A.upper().replace('GPU-', 'GPU-')], ['CUDA1'], [A] * 17):
            request = self.request()
            request.cuda_device_uuids = values
            with self.subTest(values=values), self.assertRaises(ValueError):
                policy.requested_uuids(request)
        request = self.request([A])
        for mode in ('local_container', 'cloud_container', 'manual_external'):
            request.execution_mode = mode
            with self.assertRaises(ValueError):
                policy.prepare(request)
        request.execution_mode = 'local_native'
        request.runtime_selector = {'accelerator': {'api': 'metal'}}
        with self.assertRaises(ValueError):
            policy.prepare(request)
        request.runtime_selector = {}
        request.cuda_device_uuids = ['GPU-cccccccc-cccc-cccc-cccc-cccccccccccc']
        with self.assertRaisesRegex(RuntimeError, 'unavailable'):
            self.prepare(request)

    def test_inventory_failures_expose_fixed_error_without_private_output(self):
        invalid = ['', ROWS + ROWS, ROWS.replace('16384', 'nan'), ROWS.replace('Card A', 'Bad\x01Name'), 'x' * 65537]
        for text in invalid:
            with mock.patch('infergrade.native_cuda_devices.subprocess.run', return_value=mock.Mock(stdout=text)):
                with self.assertRaises(RuntimeError):
                    policy.inventory()
        with mock.patch('infergrade.native_cuda_devices.subprocess.run', side_effect=subprocess.TimeoutExpired('probe', 5, output='private failure')):
            with self.assertRaisesRegex(RuntimeError, 'No device fallback') as failure:
                policy.inventory()
            self.assertNotIn('private failure', str(failure.exception))

    def test_placement_overrides_and_unprepared_or_simulated_requests_fail_before_execution(self):
        request = self.request([A])
        with self.assertRaisesRegex(RuntimeError, 'not frozen'):
            policy.environment_kwargs(request)
        request.simulate = True
        with self.assertRaisesRegex(ValueError, 'simulation'):
            self.prepare(request)
        request.simulate = False
        for flags in (['--device=CUDA0'], ['-ts', '1'], ['--split-mode', 'row'], ['-mg', '0']):
            request.backend_flags = flags
            with mock.patch('infergrade.native_cuda_devices.inventory', side_effect=AssertionError('no probe for conflicting request')):
                with self.assertRaisesRegex(ValueError, 'placement overrides'):
                    policy.prepare(request)

    def test_default_shape_and_environment_are_unchanged_but_physical_selection_is_hashed(self):
        request = self.request()
        self.assertNotIn('cuda_device_uuids', request_to_dict(request))
        self.assertEqual(policy.environment_kwargs(request), {})
        request.cuda_device_uuids = [A]
        first = request_to_dict(request)
        request.cuda_device_uuids = [B]
        second = request_to_dict(request)
        self.assertNotEqual(first, second)
        self.assertEqual(second['cuda_device_uuids'], [B])

    def test_real_child_receives_only_its_visibility_mask_without_changing_parent(self):
        request = self.request([B])
        self.prepare(request)
        with mock.patch.dict(os.environ, {'CUDA_VISIBLE_DEVICES': 'parent'}):
            command = [sys.executable, '-c', 'import os,json;print(json.dumps([os.environ["CUDA_VISIBLE_DEVICES"],os.environ["CUDA_DEVICE_ORDER"]]))']
            child = subprocess.run(command, check=True, capture_output=True, text=True, **policy.environment_kwargs(request))
            self.assertEqual(json.loads(child.stdout), [B, 'PCI_BUS_ID'])
            self.assertEqual(os.environ['CUDA_VISIBLE_DEVICES'], 'parent')

    def test_each_tool_uses_selected_namespace_and_both_require_positive_allocations(self):
        request = self.request([A, B])
        self.prepare(request)
        adapter = LlamaCppAdapter()
        with mock.patch('infergrade.adapters.llama_cpp._supports_automatic_fit', return_value=True), \
             mock.patch.object(adapter, '_native_completion_path', return_value='completion'), \
             mock.patch.object(adapter, '_native_server_path', return_value='server'), \
             mock.patch.object(adapter, '_native_perplexity_path', return_value='perplexity'):
            for tool in ('completion', 'server', 'perplexity'):
                flags = adapter._backend_flags(request, tool)
                self.assertEqual(flags[flags.index('--device') + 1], 'CUDA0,CUDA1')
                self.assertIn('--fit', flags)
        logs = 'load_tensors: CUDA0 model buffer size = 4 MiB\nload_tensors: CUDA1 model buffer size = 4 MiB\nload_tensors: offloaded 3/5 layers'
        _require_native_cuda_offload(request, logs)
        with self.assertRaisesRegex(RuntimeError, 'Device fallback'):
            _require_native_cuda_offload(request, logs.replace('CUDA1 model buffer size = 4', 'CUDA1 model buffer size = 0'))
        receipt = record_runtime_placement(request, flags, logs, 'preflight')
        self.assertEqual(receipt['requested_devices'], ['CUDA0', 'CUDA1'])
        self.assertEqual(receipt['native_device_policy_fingerprint'], request._native_cuda_selection.fingerprint)
        self.assertIsNotNone(validated_runtime_placement(receipt))
        self.assertNotIn(A, json.dumps(receipt))
        receipt['native_device_policy_fingerprint'] = 'f' * 64
        self.assertIsNone(validated_runtime_placement(receipt))

    def test_layout_distinguishes_split_but_does_not_publish_card_uuid(self):
        layouts = []
        for values in ([A], [B], [A, B], [B, A]):
            request = self.request(values)
            self.prepare(request)
            layouts.append(policy.logical_layout(request))
        self.assertEqual(layouts[0], layouts[1])
        self.assertNotEqual(layouts[0], layouts[2])
        self.assertNotEqual(layouts[2], layouts[3])
        self.assertNotIn(A, json.dumps(layouts))
        self.assertIsNone(policy.logical_layout(self.request()))

    def test_selected_memory_excludes_other_cards_and_missing_or_invalid_is_unknown(self):
        request = self.request([B])
        self.prepare(request)
        valid = f'{A}, 16000\n{B}, 2000\n'
        with mock.patch('infergrade.native_cuda_devices.subprocess.run', return_value=mock.Mock(stdout=valid)):
            self.assertEqual(policy.sample_selected_memory_used_mb(request), 2000)
        for text in (f'{A}, 16000\n', valid + f'{B}, 2000\n', valid.replace('2000', 'nan'),
                     valid.replace('2000', '-1'), valid.replace('2000', '30000'), 'x' * 65537):
            with self.subTest(text=text[:80]), mock.patch('infergrade.native_cuda_devices.subprocess.run', return_value=mock.Mock(stdout=text)):
                self.assertIsNone(policy.sample_selected_memory_used_mb(request))
        with mock.patch('infergrade.native_cuda_devices.subprocess.run', side_effect=subprocess.TimeoutExpired('probe', 5)):
            self.assertIsNone(policy.sample_selected_memory_used_mb(request))

    def test_adapter_version_child_gets_the_frozen_mask(self):
        request = self.request([B])
        self.prepare(request)
        adapter = LlamaCppAdapter()
        with mock.patch.object(adapter, '_ensure_backend_model_compatibility'), \
             mock.patch.object(adapter, '_native_command_path', return_value='cli'), \
             mock.patch('infergrade.adapters.llama_cpp.subprocess.run', return_value=mock.Mock(returncode=0, stdout=b'version: b10069', stderr=b'')) as run:
            adapter.resolve_version(simulate=False, request=request)
        self.assertEqual(run.call_args.kwargs['env']['CUDA_VISIBLE_DEVICES'], B)
        self.assertEqual(run.call_args.args[0], ['cli', '--version'])

    def test_document_does_not_coerce_invalid_policy_types_to_device_lists(self):
        for values in ({A: True}, None, A, False):
            request = request_from_dict({'run': {'model': 'test/model', 'backend': 'llama.cpp', 'execution_mode': 'local_native'},
                                         'overrides': {'cuda_device_uuids': values}}, simulate=False)
            with self.subTest(values=values), self.assertRaises(ValueError):
                policy.requested_uuids(request)
        request = request_from_dict({'run': {'model': 'test/model', 'backend': 'llama.cpp', 'execution_mode': 'local_native'},
                                     'overrides': {'cuda_device_uuids': [B, A]}}, simulate=False)
        self.assertEqual(policy.requested_uuids(request), (B, A))

    def test_real_result_builder_binds_layout_without_physical_identifiers(self):
        records = []
        schema = json.loads((runner_root() / 'schemas/json/result_record.schema.json').read_text())
        for values in ([], [A], [B], [A, B]):
            request = self.request(values)
            self.prepare(request)
            capability = SimpleNamespace(status='skipped', score=None, task_performance={})
            fidelity = SimpleNamespace(state='not_yet_measured', reason_codes=[], context={}, metrics={}, artifacts={})
            deployment = dict.fromkeys(['ttft_p50_ms', 'ttft_p95_ms', 'latency_p50_ms', 'latency_p95_ms',
                                       'decode_tokens_per_second_p50', 'decode_tokens_per_second_p95',
                                       'request_throughput_per_minute', 'peak_vram_mb', 'load_time_ms',
                                       'oom_or_failure_rate', 'deployment_confidence'], None)
            with mock.patch('infergrade.runner.summarize_capability_execution', return_value={}):
                record = _build_result_record('bundle', request, {}, {}, 'b10069', {}, capability, fidelity,
                                              deployment, 'interactive_chat_v1', '2026-10-08T00:00:00Z', '2026-10-08T00:00:01Z')
            config = record['configuration']
            self.assertEqual(validate_json_schema(config, schema['properties']['configuration'], runner_root() / 'schemas/json/result_record.schema.json'), [])
            self.assertNotIn(A, json.dumps(config))
            self.assertNotIn(B, json.dumps(config))
            records.append(config)
        self.assertNotIn('cuda_device_layout', records[0])
        self.assertEqual(records[1]['configuration_id'], records[2]['configuration_id'])
        self.assertNotEqual(records[0]['configuration_id'], records[1]['configuration_id'])
        self.assertNotEqual(records[1]['configuration_id'], records[3]['configuration_id'])

    def test_layout_schema_requires_exact_split_weight_count(self):
        schema_path = runner_root() / 'schemas/json/result_record.schema.json'
        schema = json.loads(schema_path.read_text())['properties']['configuration']['properties']['cuda_device_layout']
        for count in range(2, 17):
            value = {'policy': 'native_cuda_uuid_mask_v1', 'device_count': count,
                     'split_mode': 'layer', 'tensor_split_weights_mib': [16384] * count}
            self.assertEqual(validate_json_schema(value, schema, schema_path), [])
            for wrong_count in (count - 1, count + 1):
                invalid = {**value, 'tensor_split_weights_mib': [16384] * wrong_count}
                with self.subTest(count=count, wrong_count=wrong_count):
                    self.assertTrue(validate_json_schema(invalid, schema, schema_path))


if __name__ == '__main__':
    unittest.main()
