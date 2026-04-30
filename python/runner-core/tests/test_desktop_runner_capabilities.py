import json
import os
import re
import unittest


class DesktopRunnerCapabilityTests(unittest.TestCase):
    def _repo_root(self):
        return os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))

    def _api_url_validators(self):
        root = self._repo_root()
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

    def test_desktop_runner_surfaces_release_and_update_gates(self):
        root = self._repo_root()
        html_path = os.path.join(root, "apps/desktop-runner/index.html")
        js_path = os.path.join(root, "apps/desktop-runner/src/main.js")
        css_path = os.path.join(root, "apps/desktop-runner/src/styles.css")
        with open(html_path, "r", encoding="utf-8") as handle:
            html = handle.read()
        with open(js_path, "r", encoding="utf-8") as handle:
            js = handle.read()
        with open(css_path, "r", encoding="utf-8") as handle:
            css = handle.read()

        self.assertIn("data-app-version", html)
        self.assertIn("data-update-channel", html)
        self.assertIn("data-update-status", html)
        self.assertIn("Blocked on platform sidecar artifacts and signing.", html)
        self.assertIn('const UPDATE_CHANNEL = "dogfood";', js)
        self.assertIn("signed Tauri artifacts and rollback policy", js)
        self.assertIn("function renderReleaseStatus()", js)
        self.assertIn(".release-card", css)
        self.assertIn(".status-list", css)


if __name__ == "__main__":
    unittest.main()
