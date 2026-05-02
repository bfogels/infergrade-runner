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
        self.assertIn("data-runner-cli-version", html)
        self.assertIn("data-runtime-runner-version", html)
        self.assertIn("Current release", html)
        self.assertIn("Keep your machine ready for Hub runs.", html)
        self.assertIn("Installers are planned after the macOS lane is verified.", html)
        self.assertIn("Local companion app for InferGrade Hub runs", open(os.path.join(root, "apps/desktop-runner/src-tauri/tauri.conf.json"), "r", encoding="utf-8").read())
        self.assertIn('const UPDATE_CHANNEL = "release";', js)
        self.assertIn("verified updates", js)
        self.assertIn("Paired and listening for Hub runs.", js)
        self.assertNotIn("listening for Hub jobs", js)
        self.assertNotIn("Runner sidecar error", js)
        self.assertIn("function renderReleaseStatus()", js)
        self.assertIn("function refreshRunnerCliVersion()", js)
        self.assertIn('Command.sidecar(SIDECAR_NAME, ["--version"])', js)
        self.assertIn(".release-card", css)
        self.assertIn(".status-list", css)

    def test_desktop_runner_validates_hub_url_like_sidecar_permissions(self):
        root = self._repo_root()
        html_path = os.path.join(root, "apps/desktop-runner/index.html")
        js_path = os.path.join(root, "apps/desktop-runner/src/main.js")

        with open(html_path, "r", encoding="utf-8") as handle:
            html = handle.read()
        with open(js_path, "r", encoding="utf-8") as handle:
            js = handle.read()

        self.assertIn("Use HTTPS for hosted Hubs", html)
        self.assertIn("function readApiUrl()", js)
        self.assertIn('parsed.protocol !== "https:" && !isLocalHttp', js)
        self.assertIn("localhost", js)
        self.assertIn("ipv4Octet", js)
        self.assertIn("^127", js)
        self.assertIn("Hub URL must use HTTPS", js)

    def test_desktop_runner_has_explicit_system_theme_mode(self):
        root = self._repo_root()
        html_path = os.path.join(root, "apps/desktop-runner/index.html")
        js_path = os.path.join(root, "apps/desktop-runner/src/main.js")
        css_path = os.path.join(root, "apps/desktop-runner/src/styles.css")

        def read(path):
            with open(path, "r", encoding="utf-8") as handle:
                return handle.read()

        html = read(html_path)
        js = read(js_path)
        css = read(css_path)

        self.assertIn('data-theme-choice="system"', html)
        self.assertIn('data-theme-choice="light"', html)
        self.assertIn('data-theme-choice="dark"', html)
        self.assertIn("function preferredThemeMode()", js)
        self.assertIn('return "system";', js)
        self.assertIn("function applyThemeMode(mode)", js)
        self.assertIn("document.documentElement.dataset.themeMode", js)
        self.assertIn("addEventListener(\"change\", refreshSystemTheme)", js)
        self.assertIn(".theme-control", css)
        self.assertIn('[aria-pressed="true"]', css)

    def test_desktop_runner_can_read_sidecar_version(self):
        root = self._repo_root()
        path = os.path.join(root, "apps/desktop-runner/src-tauri/capabilities/default.json")
        with open(path, "r", encoding="utf-8") as handle:
            capability = json.load(handle)
        allowed_args = []
        for permission in capability["permissions"]:
            if not isinstance(permission, dict) or permission.get("identifier") != "shell:allow-execute":
                continue
            for command in permission.get("allow", []):
                allowed_args.append(command.get("args"))
        self.assertIn(["--version"], allowed_args)


if __name__ == "__main__":
    unittest.main()
