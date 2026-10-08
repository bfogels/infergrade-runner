"""UUID-free per-job intent offers; heartbeat never waits for hardware discovery."""
import json
from functools import lru_cache
import threading
import time

from infergrade.cuda_device_policy import apply_policy, descriptor, load_policy
from infergrade.native_cuda_devices import inventory, prepare
from infergrade.json_schema_subset import validate_json_schema
from infergrade.paths import runner_root
from infergrade.utils import stable_hash

SCHEMA = 'infergrade.cuda_job_choices.v1'
TTL_SECONDS = 60.0
REFRESH_SECONDS = 30.0
ERROR = 'GPU choices changed or are unavailable. Review this machine and queue the benchmark again; no fallback is allowed.'


def _snapshot(devices):
    return [{'uuid': d.uuid, 'model': d.model, 'memory_mib': d.memory_mib} for d in devices]


def _policy(devices):
    return {'schema_version': 'infergrade.cuda_device_policy.v1', 'devices': _snapshot(devices)}


def _offers(saved, devices):
    if not devices:
        raise RuntimeError(ERROR)
    by_uuid = {device.uuid: device for device in devices}
    if saved and any(by_uuid.get(d['uuid']) is None or _snapshot([by_uuid[d['uuid']]])[0] != d for d in saved['devices']):
        raise RuntimeError(ERROR)
    primary = [by_uuid[d['uuid']] for d in saved['devices']] if saved else []
    primary += [device for device in devices if device not in primary]
    policies = [_policy([device]) for device in devices] + [_policy(primary)]
    if saved:
        policies.append(saved)
    choices = {}
    private = {}
    for policy in policies:
        public = descriptor(policy)
        choices[public['revision']] = public
        private[public['revision']] = policy
    default = descriptor(saved)
    offers = {'schema_version': SCHEMA,
            'inventory_revision': stable_hash({'devices': _snapshot(devices), 'default_revision': default['revision'] if default else None}, length=64),
            'preferred_single_revision': descriptor(_policy(primary[:1]))['revision'],
            'all_revision': descriptor(_policy(primary))['revision'],
            'choices': list(choices.values())}
    schema, path = _binding_schema()
    if validate_json_schema(offers, schema, path):
        raise RuntimeError(ERROR)
    return offers, private


class InventoryCache:
    """One bounded daemon probe; failed/expired snapshots never advertise choices."""
    def __init__(self, discover=inventory, clock=time.monotonic):
        self.discover, self.clock = discover, clock
        self.lock = threading.Lock()
        self.devices = None
        self.captured = None
        self.last_attempt = None
        self.busy = False

    def _refresh(self):
        devices = None
        try:
            devices = self.discover()
        except Exception:
            # Discovery diagnostics are never forwarded, and background failure
            # cannot leave the single-flight flag held.
            devices = None
        finally:
            with self.lock:
                self.devices = devices
                self.captured = self.clock() if devices else None
                self.busy = False

    def read(self):
        with self.lock:
            now = self.clock()
            if not self.busy and (self.last_attempt is None or now - self.last_attempt >= REFRESH_SECONDS):
                self.busy = True
                self.last_attempt = now
                try:
                    threading.Thread(target=self._refresh, daemon=True, name='infergrade-gpu-inventory').start()
                except RuntimeError:
                    self.busy = False
            if self.devices is None or self.captured is None or now - self.captured > TTL_SECONDS:
                return None
            return self.devices


_CACHE = InventoryCache()


def heartbeat_metadata(metadata=None):
    result = dict(metadata or {})
    result['native_device_choices'] = None
    try:
        if result.get('native_device_policy_warning') is not None:
            raise RuntimeError(ERROR)
        saved = load_policy()
        if descriptor(saved) != result.get('native_device_policy'):
            raise RuntimeError(ERROR)
        devices = _CACHE.read()
        if devices is None:
            raise RuntimeError(ERROR)
        result['native_device_choices'], _ = _offers(saved, devices)
        result.pop('native_device_choices_warning', None)
    except (OSError, ValueError, RuntimeError, RecursionError):
        # A discovery failure cannot erase the saved policy or interrupt active work.
        result['native_device_choices_warning'] = 'GPU choices are not currently available. Refresh the machine before selecting devices.'
    return result


@lru_cache(maxsize=1)
def _binding_schema():
    path = runner_root() / 'schemas/json/native_cuda_job_choices.schema.json'
    try:
        return json.loads(path.read_text()), path
    except (OSError, ValueError, RecursionError):
        raise RuntimeError(ERROR) from None


def apply_job_choice(request, job):
    fields = ('native_device_choice', 'native_device_inventory_revision')
    if not any(key in job for key in fields):
        return apply_policy(request, job.get('native_device_policy_revision'), hub_job=True)
    api = ((request.runtime_selector or {}).get('accelerator') or {}).get('api')
    if request.backend != 'llama.cpp' or request.execution_mode != 'local_native' or api not in (None, 'unknown', 'cuda'):
        raise RuntimeError('GPU choice requires native CUDA llama.cpp execution.')
    if request.simulate:
        raise ValueError("Physical CUDA selection requires real execution.")
    if not all(key in job for key in (*fields, 'native_device_policy_revision')):
        raise RuntimeError(ERROR)
    schema, path = _binding_schema()
    if validate_json_schema({key: job[key] for key in (*fields, 'native_device_policy_revision')}, schema, path):
        raise RuntimeError(ERROR)
    choice = job['native_device_choice']
    saved = load_policy()
    baseline = descriptor(saved)
    if job['native_device_policy_revision'] != (baseline['revision'] if baseline else None):
        raise RuntimeError(ERROR)
    # Execution always fresh-probes; the heartbeat TTL cache is never admission proof.
    physical = inventory()
    offers, policies = _offers(saved, physical)
    if (job['native_device_inventory_revision'] != offers['inventory_revision']
            or not isinstance(choice.get('revision'), str)
            or choice not in offers['choices']):
        raise RuntimeError(ERROR)
    selected = policies[choice['revision']]
    # Detect a default change while the bounded probe was running.
    if descriptor(load_policy()) != baseline:
        raise RuntimeError(ERROR)
    uuids = [device['uuid'] for device in selected['devices']]
    if request.cuda_device_uuids and request.cuda_device_uuids != uuids:
        raise RuntimeError(ERROR)
    request.cuda_device_uuids = list(uuids)
    selection = prepare(request, device_inventory=physical)
    if _snapshot(selection.devices) != selected['devices']:
        raise RuntimeError(ERROR)
    return descriptor(selected)
