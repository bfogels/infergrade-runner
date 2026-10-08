import hashlib
import importlib.util
import io
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest import mock
import zipfile

ROOT = Path(__file__).resolve().parents[3]
# Import build helpers without touching user caches or downloading anything.
for name in ('prepare_desktop_python_runtime', 'prepare_native_ifeval_bundle'):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
BUILDER = sys.modules['prepare_native_ifeval_bundle']


class NativeIFEvalBundleTests(unittest.TestCase):
    def test_archive_paths_and_links_fail_closed(self):
        for name in ('../escape', '/absolute', 'folder\\escape', 'C:escape'):
            with self.assertRaises(ValueError):
                BUILDER.safe_relative(name)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name, mode in [('safe', 0o120777), ('../escape', 0o100644)]:
                archive = root / 'wheel.zip'
                with zipfile.ZipFile(archive, 'w') as wheel:
                    info = zipfile.ZipInfo(name)
                    info.external_attr = mode << 16
                    wheel.writestr(info, 'outside')
                with self.assertRaises(ValueError):
                    BUILDER.extract_wheel(archive, root / 'output')
            self.assertFalse((root.parent / 'escape').exists())

    def test_wheel_conflicts_do_not_replace_existing_dependency(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / 'dependencies'
            output.mkdir()
            (output / 'same.py').write_text('trusted')
            archive = root / 'wheel.zip'
            with zipfile.ZipFile(archive, 'w') as wheel:
                wheel.writestr('same.py', 'replacement')
            with self.assertRaises(ValueError):
                BUILDER.extract_wheel(archive, output)
            self.assertEqual((output / 'same.py').read_text(), 'trusted')

    def test_language_detector_preserves_metadata_without_running_setup(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / 'source.tar.gz'
            with tarfile.open(archive, 'w:gz') as tar:
                for name, value in [('langdetect/__init__.py', 'pass'),
                                    ('langdetect.egg-info/PKG-INFO', 'Name: langdetect\nVersion: 1.0.9\n'),
                                    ('LICENSE', 'notice'), ('setup.py', 'raise AssertionError')]:
                    payload = value.encode()
                    info = tarfile.TarInfo('langdetect-1.0.9/' + name)
                    info.size = len(payload)
                    tar.addfile(info, io.BytesIO(payload))
            output = root / 'dependencies'
            BUILDER.extract_langdetect(archive, output)
            self.assertTrue((output / 'langdetect.egg-info/PKG-INFO').is_file())
            self.assertTrue((output / 'langdetect-notices/LICENSE').is_file())
            self.assertFalse((output / 'setup.py').exists())

    def test_cached_assets_require_digest_and_size(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            value = b'reviewed'
            sha = hashlib.sha256(value).hexdigest()
            (root / sha).write_bytes(value)
            asset = {'sha256': sha, 'size_bytes': len(value), 'url': 'https://example.test/asset'}
            with mock.patch.object(BUILDER.subprocess, 'run', side_effect=AssertionError('network')):
                self.assertEqual(BUILDER.fetch(asset, root).read_bytes(), value)
            asset['url'] = 'http://example.test/asset'
            (root / sha).write_bytes(b'changed')
            with self.assertRaises(ValueError):
                BUILDER.fetch(asset, root)

    def test_targets_require_unique_abi_and_langdetect_uses_reviewed_source(self):
        import json
        manifest = json.loads(BUILDER.MANIFEST.read_text())
        for target, tag in BUILDER.TARGET_TAGS.items():
            self.assertIn(tag, BUILDER.select_asset(manifest['packages']['regex'], target)['filename'])
        self.assertTrue(BUILDER.select_asset(manifest['packages']['langdetect'], 'aarch64-apple-darwin')['filename'].endswith('.tar.gz'))
        self.assertEqual(manifest['container_parity'], 'unqualified_distinct_protocol')
        self.assertIn('tokenizers/punkt/README', manifest['nltk_resources'])
        self.assertIn('tokenizers/punkt_tab/README', manifest['nltk_resources'])
        for name, sha in manifest['source_files'].items():
            self.assertEqual(hashlib.sha256((ROOT / name).read_bytes()).hexdigest(), sha, name)


if __name__ == '__main__':
    unittest.main()
