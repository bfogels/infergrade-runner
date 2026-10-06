"""Exercise the desktop listener's profile handoff against a token-bound Hub."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[3]


class DesktopListenerIdentityTests(unittest.TestCase):
    def test_canonical_desktop_profile_overrides_missing_or_stale_home_identity(self):
        source = (ROOT / 'apps/desktop-runner/src-tauri/src/lib.rs').read_text()
        launch = source.split('fn start_runner_listener(', 1)[1].split('fn ', 1)[0]
        self.assertIn('.env("INFERGRADE_CONFIG_DIR", runner_config_dir()?)', launch)
        self.assertIn('.args(listener_start_arguments(&plan, &normalized_api_url)?)', launch)
        requests = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                requests.append((self.path, body, self.headers.get('Authorization')))
                identity = body.get('runner_id') if self.path.endswith('/register') else self.path.split('/')[-2]
                valid = identity == 'runner_desktop' and self.headers.get('Authorization') == 'Bearer fixture-token'
                payload = {'runner': {'runner_id': identity}} if valid else {'detail': 'runner token is bound to another runner'}
                data = json.dumps(payload).encode()
                self.send_response(200 if valid else 403)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp) / 'home'
            stale = home / '.config/infergrade'
            canonical = Path(temp) / 'AppData/Roaming/infergrade'
            for path, identity in [(stale, 'runner_stale'), (canonical, 'runner_desktop')]:
                path.mkdir(parents=True)
                (path / 'runner_profile.json').write_text(json.dumps({'runner_id': identity, 'label': identity,
                                                                     'preferred_execution_mode': 'local_native'}))
            env = dict(os.environ, HOME=str(home), USERPROFILE=str(home), APPDATA=str(canonical.parent),
                       PYTHONPATH=str(ROOT / 'python/runner-core/src'), INFERGRADE_HUB_TOKEN='fixture-token')
            env.pop('INFERGRADE_CONFIG_DIR', None)
            env.pop('XDG_CONFIG_HOME', None)
            # Bound the listener before any job claim, generation, or model download.
            command = [sys.executable, '-m', 'infergrade', 'start', '--api-url',
                       'http://127.0.0.1:%s' % server.server_port, '--max-jobs', '0', '--json']
            rejected = subprocess.run(command, env=env, capture_output=True, text=True, timeout=30)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn('bound to another runner', rejected.stderr)
            requests.clear()
            env['INFERGRADE_CONFIG_DIR'] = str(canonical)
            accepted = subprocess.run(command, env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(accepted.returncode, 0, accepted.stderr)
            self.assertEqual([entry[0] for entry in requests], ['/v1/runners/register', '/v1/runners/runner_desktop/heartbeat'])
            self.assertEqual(requests[0][1]['runner_id'], 'runner_desktop')
            self.assertEqual(requests[0][1]['execution_modes'], ['local_native'])
            self.assertEqual(requests[0][1]['label'], 'runner_desktop')
            self.assertTrue(all(entry[2] == 'Bearer fixture-token' for entry in requests))
