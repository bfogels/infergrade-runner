import json
import os
import re
import unittest


class DesktopRunnerCapabilityTests(unittest.TestCase):
    def _api_url_validators(self):
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
        path = os.path.join(root, "apps/desktop-runner/src-tauri/capabilities/default.json")
        with open(path, "r", encoding="utf-8") as handle:
            capability = json.load(handle)
        validators = []
        for permission in capability["permissions"]:
            if not isinstance(permission, dict):
                continue
            for command in permission.get("allow", []):
                args = command.get("args") or []
                for index, arg in enumerate(args[:-1]):
                    if arg == "--api-url":
                        validators.append(args[index + 1]["validator"])
        return validators

    def test_api_url_validators_allow_https_and_local_http_only(self):
        validators = self._api_url_validators()
        self.assertEqual(len(validators), 3)
        for validator in validators:
            pattern = re.compile(validator)
            self.assertRegex("https://hub.example.com", pattern)
            self.assertRegex("http://localhost:8000", pattern)
            self.assertRegex("http://127.0.0.1:8000", pattern)
            self.assertRegex("http://127.1.2.3:8000", pattern)
            self.assertRegex("http://[::1]:8000", pattern)
            self.assertNotRegex("http://hub.example.com", pattern)
            self.assertNotRegex("http://192.168.1.25:8000", pattern)
            self.assertNotRegex("http://localhost.example.com", pattern)


if __name__ == "__main__":
    unittest.main()
