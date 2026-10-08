import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
for name in ('prepare_desktop_python_runtime','prepare_native_ifeval_bundle','reseal_native_ifeval_bundle'):
    spec = importlib.util.spec_from_file_location(name, ROOT/'scripts'/(name+'.py'))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
BUILDER=sys.modules['prepare_native_ifeval_bundle']
RESEAL=sys.modules['reseal_native_ifeval_bundle']


class NativeIFEvalResealTests(unittest.TestCase):
    def fixture(self, root):
        bundle=root/'bundle'
        bundle.mkdir()
        (bundle/'python-runtime/bin').mkdir(parents=True)
        (bundle/'dependencies').mkdir()
        (bundle/'dependencies/module.py').write_text('original Python source')
        (bundle/'python-runtime/bin/python3.12').write_bytes(b'\x7fELF original reviewed binary')
        (bundle/'bootstrap.py').write_text('trusted source')
        files={p.relative_to(bundle).as_posix():BUILDER.digest(p) for p in bundle.rglob('*') if p.is_file()}
        receipt={'target':'x86_64-unknown-linux-gnu','manifest_sha256':BUILDER.digest(BUILDER.MANIFEST),
                 'files':files,'links':{},'transformable_binaries':{'python-runtime/bin/python3.12':'elf'}}
        (bundle/BUILDER.RECEIPT).write_text(json.dumps(receipt))
        identity=root/'identity.py'
        BUILDER.write_trusted_identity(bundle,identity)
        return bundle,identity

    def test_explicit_binary_transform_reanchors_final_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            bundle,identity=self.fixture(Path(temporary))
            previous=BUILDER.digest(bundle/BUILDER.RECEIPT)
            (bundle/'python-runtime/bin/python3.12').write_bytes(b'\x7fELF reviewed packaging transform')
            RESEAL.reseal(bundle,identity,'linuxdeploy_appimage_v1')
            receipt=json.loads((bundle/BUILDER.RECEIPT).read_text())
            self.assertEqual(receipt['packaging_transform']['previous_receipt_sha256'],previous)
            self.assertEqual(RESEAL._trusted_identity(identity)['receipt_sha256'],BUILDER.digest(bundle/BUILDER.RECEIPT))
            self.assertEqual(receipt['files']['python-runtime/bin/python3.12'],BUILDER.digest(bundle/'python-runtime/bin/python3.12'))

    def test_source_change_is_not_a_signing_transform(self):
        with tempfile.TemporaryDirectory() as temporary:
            bundle,identity=self.fixture(Path(temporary))
            (bundle/'dependencies/module.py').write_text('MZ = \"valid Python source\"')
            with self.assertRaisesRegex(ValueError,'non-code evaluator assets'):
                RESEAL.reseal(bundle,identity,'linuxdeploy_appimage_v1')

    def test_self_rehashed_receipt_wrong_platform_and_new_files_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            bundle,identity=self.fixture(Path(temporary))
            with self.assertRaisesRegex(ValueError,'platform'):
                RESEAL.reseal(bundle,identity,'windows_authenticode')
            (bundle/'injected.py').write_text('pass')
            with self.assertRaisesRegex(ValueError,'added or removed'):
                RESEAL.reseal(bundle,identity,'linuxdeploy_appimage_v1')
            (bundle/'injected.py').unlink()
            receipt=json.loads((bundle/BUILDER.RECEIPT).read_text())
            receipt['fake']='new inventory'
            (bundle/BUILDER.RECEIPT).write_text(json.dumps(receipt))
            with self.assertRaisesRegex(ValueError,'trusted package anchor'):
                RESEAL.reseal(bundle,identity,'linuxdeploy_appimage_v1')

    def test_identity_is_parsed_without_executing_packager_code(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            path=root/'identity.py'
            marker=root/'marker'
            path.write_text('IDENTITY = {}\nopen('+repr(str(marker))+',"w").write("unsafe")')
            with self.assertRaises(ValueError):
                RESEAL._trusted_identity(path)
            self.assertFalse(marker.exists())


if __name__=='__main__':
    unittest.main()
