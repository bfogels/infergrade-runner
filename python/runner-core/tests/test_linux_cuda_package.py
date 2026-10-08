import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from scripts.verify_linux_cuda_package import BUNDLED_LIBRARIES, verify_package


class LinuxCudaPackageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.package = self.root / 'package'
        self.package.mkdir()
        for name in (*BUNDLED_LIBRARIES, 'libggml-cuda.so', 'LICENSE.nccl'):
            (self.package / name).write_bytes(b'fixture')

    def inspect(self, detail):
        with mock.patch('scripts.verify_linux_cuda_package.subprocess.run',
                        return_value=subprocess.CompletedProcess([], 0, detail, '')) as run:
            verify_package(self.package, self.root / 'diagnostics')
            return run

    def test_only_absent_host_driver_is_allowed(self):
        run = self.inspect('libcuda.so.1 => not found\nlibnccl.so.2 => %s/libnccl.so.2 (0x0)\n' % self.package)
        self.assertEqual(run.call_count, 5)

    def test_missing_nccl_archive_member_fails_before_loader_smoke(self):
        (self.package / 'libnccl.so.2').unlink()
        with self.assertRaisesRegex(ValueError, 'missing libnccl.so.2'):
            self.inspect('libnccl.so.2 => /usr/lib/libnccl.so.2 (0x0)\n')

    def test_nccl_free_build_does_not_require_nccl(self):
        (self.package / 'libnccl.so.2').unlink()
        (self.package / 'LICENSE.nccl').unlink()
        self.assertEqual(self.inspect('libcuda.so.1 => not found\n').call_count, 4)

    def test_missing_transitive_library_is_not_treated_as_an_absent_driver(self):
        with self.assertRaisesRegex(ValueError, 'unresolved dependency: libnccl.so.2'):
            self.inspect('libcuda.so.1 => not found\nlibnccl.so.2 => not found\n')

    def test_build_host_nccl_cannot_mask_broken_package(self):
        with self.assertRaisesRegex(ValueError, 'relies on a host library: libnccl.so.2'):
            self.inspect('libnccl.so.2 => /usr/lib/libnccl.so.2 (0x0)\n')

    def test_bundled_driver_is_rejected(self):
        (self.package / 'libcuda.so.1').write_bytes(b'stub')
        with self.assertRaisesRegex(ValueError, 'host-owned'):
            self.inspect('')

    def test_missing_license_is_rejected(self):
        (self.package / 'LICENSE.nccl').unlink()
        with self.assertRaisesRegex(ValueError, 'missing LICENSE.nccl'):
            self.inspect('')

    @mock.patch.dict(os.environ, {'LD_LIBRARY_PATH': '/host/cuda', 'LD_PRELOAD': '/host/library.so'})
    def test_loader_overrides_are_removed(self):
        run = self.inspect('')
        self.assertNotIn('LD_LIBRARY_PATH', run.call_args.kwargs['env'])
        self.assertNotIn('LD_PRELOAD', run.call_args.kwargs['env'])


if __name__ == '__main__':
    unittest.main()
