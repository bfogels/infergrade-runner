import json
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from infergrade import cache_budget as budget
from infergrade.cache_control import process_lock, record_install, set_keep


class CacheBudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        patcher = mock.patch.object(budget, 'GIB', 1)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_metadata_growth_after_stat_is_bounded(self):
        budget.set_limit(25, self.root)
        path = self.root / budget.CONTROL / 'budget.json'
        real_fstat = os.fstat

        def growing(fd):
            info = real_fstat(fd)
            if info.st_ino == path.stat().st_ino:
                with path.open('ab') as stream:
                    stream.write(b' ' * 5000)
            return info

        with mock.patch.object(budget.os, 'fstat', side_effect=growing):
            with self.assertRaisesRegex(RuntimeError, 'Invalid download budget metadata'):
                budget._read(self.root, 'budget.json')

    @unittest.skipUnless(hasattr(os, 'mkfifo'), 'FIFO requires Unix')
    def test_metadata_replaced_with_fifo_before_open_never_blocks(self):
        budget.set_limit(25, self.root)
        path = self.root / budget.CONTROL / 'budget.json'
        real_open = os.open

        def replacing(name, flags, *args, **kwargs):
            if Path(name) == path:
                path.unlink()
                os.mkfifo(path)
            return real_open(name, flags, *args, **kwargs)

        with mock.patch.object(budget.os, 'open', side_effect=replacing):
            with self.assertRaisesRegex(RuntimeError, 'Invalid download budget metadata'):
                budget._read(self.root, 'budget.json')

    def test_metadata_replaced_with_link_before_open_is_rejected(self):
        budget.set_limit(25, self.root)
        path = self.root / budget.CONTROL / 'budget.json'
        target = self.root / 'outside.json'
        target.write_text(json.dumps({'schema_version': budget.SCHEMA, 'limit_gb': None}))
        real_open = os.open

        def replacing(name, flags, *args, **kwargs):
            if Path(name) == path:
                path.unlink()
                try:
                    path.symlink_to(target)
                except OSError:
                    self.skipTest('Symlinks unavailable')
            return real_open(name, flags, *args, **kwargs)

        with mock.patch.object(budget.os, 'open', side_effect=replacing):
            with self.assertRaisesRegex(RuntimeError, 'Invalid download budget metadata'):
                budget._read(self.root, 'budget.json')

    def test_mixed_cli_trim_keep_preserves_file_metadata_and_policy(self):
        from infergrade.cli import main
        path, key = self.install('requested-keep.gguf', 30)
        budget.set_limit(50, self.root)
        policy = (self.root / budget.CONTROL / 'budget.json').read_bytes()
        metadata = budget._read_metadata(self.root)
        with self.assertRaisesRegex(SystemExit, 'Choose one cache action'):
            main(['cache', '--artifact-cache-dir', str(self.root), '--limit-gb', '25',
                  '--trim-oldest', '--keep', 'yes', '--artifact-id', key])
        self.assertEqual(path.read_bytes(), b'x' * 30)
        self.assertEqual((self.root / budget.CONTROL / 'budget.json').read_bytes(), policy)
        self.assertEqual(budget._read_metadata(self.root), metadata)

    def install(self, name, size):
        path = self.root / name
        path.write_bytes(b'x' * size)
        return path, record_install(self.root, path, 'a' * 64)

    def test_default_policy_capacity_and_unmanaged_files_are_distinct(self):
        self.install('owned.gguf', 10)
        (self.root / 'legacy.gguf').write_bytes(b'x' * 40)
        (self.root / 'partial.tmp').write_bytes(b'x' * 30)
        self.assertIsNone(budget.budget_status(self.root)['limit_gb'])
        self.assertEqual(budget.set_limit(25, self.root)['budget']['managed_bytes'], 10)
        with budget.download_budget(self.root, 15):
            state = budget.budget_status(self.root)
            self.assertEqual(state['reserved_bytes'], 15)
            self.assertTrue(state['producer_active'])
        with self.assertRaisesRegex(RuntimeError, 'limit reached'):
            with budget.download_budget(self.root, 16):
                self.fail('over-cap producer admitted')
        for unknown in (None, True, 0, -1):
            with self.assertRaisesRegex(RuntimeError, 'verified artifact byte size'):
                with budget.download_budget(self.root, unknown):
                    self.fail('unknown-size producer admitted')
        self.assertEqual(budget.budget_status(self.root)['reserved_bytes'], 0)
        self.assertEqual((self.root / 'legacy.gguf').stat().st_size, 40)

    def test_oldest_first_trim_keeps_models_and_never_removes_replacements(self):
        first, first_id = self.install('first.gguf', 10)
        kept, kept_id = self.install('kept.gguf', 10)
        newest, _ = self.install('newest.gguf', 10)
        set_keep(kept_id, True, self.root)
        replacement, _ = self.install('replacement.gguf', 10)
        replacement.write_bytes(b'changed ownership')
        (self.root / 'legacy.gguf').write_bytes(b'legacy')
        result = budget.set_limit(25, self.root, trim=True)
        self.assertEqual([r['artifact_id'] for r in result['removed']], [first_id])
        self.assertFalse(first.exists())
        self.assertTrue(kept.exists() and newest.exists() and replacement.exists())
        self.assertEqual(result['budget']['kept_bytes'], 10)
        self.assertEqual(result['budget']['managed_bytes'], 20)

    def test_unsatisfiable_kept_or_nontrim_budget_never_changes_policy_or_files(self):
        first, first_id = self.install('first.gguf', 20)
        second, second_id = self.install('second.gguf', 20)
        budget.set_limit(50, self.root)
        for key in (first_id, second_id):
            set_keep(key, True, self.root)
        for trim in (False, True):
            with self.assertRaisesRegex(RuntimeError, 'kept files are preserved'):
                budget.set_limit(25, self.root, trim=trim)
        self.assertEqual(budget.budget_status(self.root)['limit_gb'], 50)
        self.assertTrue(first.exists() and second.exists())
        with process_lock(self.root):
            with self.assertRaisesRegex(RuntimeError, 'Cache is in use'):
                budget.set_limit(25, self.root, trim=True)
            budget.set_limit(None, self.root)

    def test_failure_and_crash_reservations_do_not_hold_future_capacity(self):
        budget.set_limit(25, self.root)
        with self.assertRaisesRegex(ValueError, 'failed'):
            with budget.download_budget(self.root, 20):
                raise ValueError('failed')
        self.assertEqual(budget.budget_status(self.root)['reserved_bytes'], 0)
        child = self.producer('crashed.gguf')
        self.assertEqual(child.stdout.readline().strip(), 'reserved')
        self.assertEqual(budget.budget_status(self.root)['reserved_bytes'], 20)
        child.kill()
        child.communicate(timeout=10)
        self.assertEqual(budget.budget_status(self.root)['reserved_bytes'], 0)
        with budget.download_budget(self.root, 25):
            pass

    def producer(self, name):
        code = '''import sys
from pathlib import Path
from infergrade import cache_budget as b
from infergrade.cache_control import record_install
b.GIB=1
try:
 with b.download_budget(sys.argv[1],20):
  print('reserved',flush=True)
  sys.stdin.readline()
  p=Path(sys.argv[1])/sys.argv[2];p.write_bytes(b'x'*20)
  record_install(sys.argv[1],p,'a'*64)
except RuntimeError:
 print('rejected',flush=True)
'''
        env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / 'src'))
        child = subprocess.Popen([sys.executable, '-c', code, str(self.root), name],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        self.addCleanup(lambda: child.kill() if child.poll() is None else None)
        return child

    def test_concurrent_producers_are_serialized_and_cap_cannot_change_mid_download(self):
        budget.set_limit(25, self.root)
        first = self.producer('first.gguf')
        self.assertEqual(first.stdout.readline().strip(), 'reserved')
        second = self.producer('second.gguf')
        with self.assertRaisesRegex(RuntimeError, 'Cache is in use'):
            budget.set_limit(None, self.root)
        first.stdin.write('\n')
        first.stdin.flush()
        first.communicate(timeout=10)
        out, err = second.communicate(timeout=10)
        self.assertEqual(out.strip(), 'rejected', err)
        self.assertEqual(first.returncode, 0)
        self.assertTrue((self.root / 'first.gguf').exists())
        self.assertFalse((self.root / 'second.gguf').exists())
        self.assertEqual(budget.budget_status(self.root)['managed_bytes'], 20)

    def test_existing_race_winner_is_reusable_at_capacity_and_foreign_path_rejected(self):
        winner, _ = self.install('winner.gguf', 25)
        budget.set_limit(25, self.root)
        with budget.download_budget(self.root, 25, [winner]) as existing:
            self.assertEqual(existing, str(winner))
        with self.assertRaisesRegex(RuntimeError, 'Invalid cache producer destination'):
            with budget.download_budget(self.root, 1, ['/outside/cache.gguf']):
                self.fail('foreign cache winner admitted')

    def test_resolver_enforces_budget_before_tempfile_or_network_and_preserves_cache_hits(self):
        from infergrade.artifacts import resolve_quant_artifact
        from infergrade.models import RunRequest
        budget.set_limit(25, self.root)
        payload = b'x' * 20
        def request(name, size=20):
            return RunRequest(model='test', backend='llama.cpp', tier='canary', simulate=False,
                              quant_artifact='https://example.invalid/'+name, quant_artifact_cache_dir=str(self.root),
                              quant_artifact_sha256=hashlib.sha256(payload).hexdigest(), quant_artifact_download_size_bytes=size)
        def download(url, destination, **kwargs):
            self.assertEqual(kwargs['expected_size_bytes'], 20)
            Path(destination).write_bytes(payload)
        with mock.patch('infergrade.artifacts.ensure_min_free_space'), mock.patch('infergrade.artifacts._download_remote_artifact', side_effect=download) as network:
            installed = resolve_quant_artifact(request('first.gguf'))
            self.assertFalse(installed.cache_hit)
            self.assertTrue(resolve_quant_artifact(request('first.gguf')).cache_hit)
            with self.assertRaisesRegex(RuntimeError, 'limit reached'):
                resolve_quant_artifact(request('second.gguf'))
            with self.assertRaisesRegex(RuntimeError, 'verified artifact byte size'):
                resolve_quant_artifact(request('unknown.gguf', None))
            self.assertEqual(network.call_count, 1)
        self.assertEqual(list(self.root.glob('infergrade-artifact-*.tmp')), [])
        self.assertEqual(budget.budget_status(self.root)['managed_bytes'], 20)
        self.assertTrue(Path(installed.resolved_path).exists())

    def test_invalid_and_linked_budget_metadata_fail_closed(self):
        budget.set_limit(25, self.root)
        path = self.root / '.infergrade-cache-control/budget.json'
        for malformed in ({'schema_version':budget.SCHEMA,'limit_gb':True},
                          {'schema_version':budget.SCHEMA,'limit_gb':25,'extra':None}, [], {}):
            path.write_text(json.dumps(malformed))
            with self.assertRaises(RuntimeError):
                with budget.download_budget(self.root, 1):
                    self.fail('bad budget admitted')
        path.unlink()
        try:
            path.symlink_to(self.root / 'missing.json')
        except OSError:
            self.skipTest('symlinks unavailable')
        with self.assertRaises(RuntimeError):
            budget.budget_status(self.root)
