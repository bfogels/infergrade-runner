import importlib.util
import json
from pathlib import Path
import tempfile
import time
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

    def assemble_root(self):
        payload = self.prepare_payload()
        signatures = []
        for name in ("root-1", "root-2"):
            signature = self.root / (name + ".signature.json")
            CATALOG.sign_root(payload, name, self.private / (name + ".pem"), signature)
            signatures.append(signature)
        assembled = self.root / "root.json"
        CATALOG.assemble_root(payload, signatures, assembled)
        return assembled

    def test_detached_root_signatures_assemble_and_online_build_needs_no_root_keys(self):
        assembled = self.assemble_root()

        for name in CATALOG.ROOT_KEY_NAMES:
            (self.private / (name + ".pem")).unlink()
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

    def test_split_online_roles_assemble_and_timestamp_refresh_needs_one_key(self):
        assembled = self.assemble_root()
        partial = self.root / "partial"
        CATALOG.build_targets_snapshot(
            self.source,
            assembled,
            self.private / "targets.pem",
            self.private / "snapshot.pem",
            partial,
        )
        first_timestamp = partial / "timestamp.json"
        CATALOG.build_timestamp(
            self.source,
            assembled,
            partial / "snapshot.json",
            self.private / "timestamp.pem",
            first_timestamp,
        )
        complete = self.root / "complete"
        CATALOG.assemble_generation(
            partial / "root.json",
            first_timestamp,
            partial / "snapshot.json",
            partial / "targets.json",
            complete,
            self.root / "projection.json",
        )

        for name in CATALOG.ROOT_KEY_NAMES + ("snapshot", "targets"):
            (self.private / (name + ".pem")).unlink()
        refreshed = self.root / "timestamp-refreshed.json"
        CATALOG.refresh_timestamp(
            complete / "root.json",
            complete / "snapshot.json",
            complete / "timestamp.json",
            self.private / "timestamp.pem",
            int(time.time()) + 24 * 60 * 60,
            refreshed,
        )
        self.assertEqual(
            json.loads(refreshed.read_text())["signed"]["version"],
            json.loads(first_timestamp.read_text())["signed"]["version"] + 1,
        )
        refreshed_generation = self.root / "refreshed"
        CATALOG.assemble_generation(
            complete / "root.json",
            refreshed,
            complete / "snapshot.json",
            complete / "targets.json",
            refreshed_generation,
            previous_dir=complete,
        )

    def test_generation_rejects_same_version_content_change_and_wrong_timestamp_key(self):
        assembled = self.assemble_root()
        output = self.root / "signed"
        CATALOG.build_online(self.source, assembled, self.private, output)
        altered_source = json.loads(self.source.read_text())
        altered_source["signing_environment"] = "altered"
        altered_source_path = self.root / "altered-source.json"
        altered_source_path.write_text(json.dumps(altered_source))
        altered = self.root / "altered"
        CATALOG.build_online(altered_source_path, assembled, self.private, altered)
        with self.assertRaisesRegex(SystemExit, "without a version bump"):
            CATALOG.assemble_generation(
                altered / "root.json",
                altered / "timestamp.json",
                altered / "snapshot.json",
                altered / "targets.json",
                self.root / "bad-generation",
                previous_dir=output,
            )

        with self.assertRaisesRegex(SystemExit, "does not match root role"):
            CATALOG.refresh_timestamp(
                output / "root.json",
                output / "snapshot.json",
                output / "timestamp.json",
                self.private / "targets.pem",
                int(time.time()) + 24 * 60 * 60,
                self.root / "wrong-key-timestamp.json",
            )

        reformatted = self.root / "reformatted-targets.json"
        reformatted.write_text(json.dumps(json.loads((output / "targets.json").read_text())))
        with self.assertRaisesRegex(SystemExit, "targets.json reference"):
            CATALOG.assemble_generation(
                output / "root.json",
                output / "timestamp.json",
                output / "snapshot.json",
                reformatted,
                self.root / "reformatted-generation",
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

    def test_root_policy_rejects_reused_keys_and_online_role_remapping(self):
        duplicate = json.loads((self.public / "root-2.json").read_text())
        duplicate["keyid"] = "root-3"
        (self.public / "root-3.json").write_text(json.dumps(duplicate))
        with self.assertRaisesRegex(SystemExit, "distinct public keys"):
            self.prepare_payload()

        CATALOG.create_key(
            "root-3",
            self.root / "replacement-private" / "root-3.pem",
            self.root / "replacement-public" / "root-3.json",
        )
        payload = self.root / "root-payload.json"
        descriptors = [
            self.root / "replacement-public" / "root-3.json"
            if name == "root-3"
            else self.public / (name + ".json")
            for name in CATALOG.KEY_NAMES
        ]
        CATALOG.prepare_root(self.source, descriptors, payload)
        signed = json.loads(payload.read_text())
        signed["roles"]["targets"] = {"keyids": ["timestamp"], "threshold": 1}
        with self.assertRaisesRegex(SystemExit, "exact configured role policy"):
            CATALOG.verify_root({"signed": signed, "signatures": []})

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
        source = json.loads(
            (REPO_ROOT / "runtime/catalog/catalog-source.json").read_text()
        )
        active_targets = json.loads(
            (REPO_ROOT / "runtime/catalog/signed/targets.json").read_text()
        )
        self.assertEqual(source["signing_environment"], "production")
        self.assertEqual(active_targets["signed"]["signing_environment"], "review_candidate")
        self.assertGreater(
            source["versions"]["targets"], active_targets["signed"]["version"]
        )


if __name__ == "__main__":
    unittest.main()
