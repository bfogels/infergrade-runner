import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts/build_runtime_catalog.py"
SPEC = importlib.util.spec_from_file_location("build_runtime_catalog", SCRIPT_PATH)
CATALOG = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CATALOG)


class RuntimeCatalogSigningTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.private = self.root / "private"
        self.public = self.root / "public"
        self.source = self.root / "source.json"
        self.source.write_text(
            json.dumps(
                {
                    "versions": {"root": 1, "timestamp": 1, "snapshot": 1, "targets": 1},
                    "expires_unix": {
                        "root": 2000000000,
                        "timestamp": 1900000000,
                        "snapshot": 1900000000,
                        "targets": 1900000000,
                    },
                    "signing_environment": "production",
                    "publisher_policies": {
                        "infergrade": {
                            "target_prefix": "infergrade/",
                            "allowed_origins": ["upstream_official"],
                        }
                    },
                    "targets": {},
                }
            ),
            encoding="utf-8",
        )
        for name in CATALOG.KEY_NAMES:
            CATALOG.create_key(
                name,
                self.private / (name + ".pem"),
                self.public / (name + ".json"),
            )

    def tearDown(self):
        self.temporary.cleanup()

    def prepare_payload(self):
        payload = self.root / "root-payload.json"
        CATALOG.prepare_root(
            self.source,
            [self.public / (name + ".json") for name in CATALOG.KEY_NAMES],
            payload,
        )
        return payload

    def test_detached_root_signatures_assemble_and_online_build_needs_no_root_keys(self):
        payload = self.prepare_payload()
        signatures = []
        for name in ("root-1", "root-2"):
            signature = self.root / (name + ".signature.json")
            CATALOG.sign_root(payload, name, self.private / (name + ".pem"), signature)
            signatures.append(signature)
        assembled = self.root / "root.json"
        CATALOG.assemble_root(payload, signatures, assembled)

        (self.private / "root-1.pem").unlink()
        (self.private / "root-2.pem").unlink()
        output = self.root / "signed"
        projection = self.root / "projection.json"
        CATALOG.build_online(self.source, assembled, self.private, output, projection)

        self.assertEqual(
            json.loads((output / "root.json").read_text()),
            json.loads(assembled.read_text()),
        )
        self.assertEqual(
            json.loads(projection.read_text())["signing_environment"],
            "production",
        )

    def test_assemble_rejects_signature_for_a_changed_payload(self):
        payload = self.prepare_payload()
        signatures = []
        for name in ("root-1", "root-2"):
            signature = self.root / (name + ".signature.json")
            CATALOG.sign_root(payload, name, self.private / (name + ".pem"), signature)
            signatures.append(signature)
        changed = json.loads(payload.read_text())
        changed["version"] = 2
        payload.write_text(json.dumps(changed), encoding="utf-8")

        with self.assertRaisesRegex(SystemExit, "does not match"):
            CATALOG.assemble_root(payload, signatures, self.root / "root.json")

    def test_sign_root_rejects_the_wrong_custodian_key(self):
        payload = self.prepare_payload()
        with self.assertRaisesRegex(SystemExit, "does not match"):
            CATALOG.sign_root(
                payload,
                "root-1",
                self.private / "root-2.pem",
                self.root / "bad-signature.json",
            )

    def test_staged_production_root_meets_threshold_and_is_not_active_early(self):
        production_root = json.loads(
            (REPO_ROOT / "runtime/catalog/roots/production-v1.json").read_text()
        )
        active_root = json.loads(
            (REPO_ROOT / "runtime/catalog/signed/root.json").read_text()
        )

        CATALOG.verify_root(production_root)
        self.assertEqual(production_root["signed"]["roles"]["root"]["threshold"], 2)
        self.assertEqual(len(production_root["signed"]["roles"]["root"]["keyids"]), 3)
        self.assertNotEqual(production_root["signed"]["keys"], active_root["signed"]["keys"])


if __name__ == "__main__":
    unittest.main()
