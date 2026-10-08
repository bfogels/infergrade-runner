import io
import getpass
import warnings
import unittest
from contextlib import redirect_stdout, redirect_stderr
from types import SimpleNamespace
from unittest import mock

from infergrade.cli import _resolve_pair_code, main
from infergrade.transport import authorize_runner_device, DeviceAuthorizationUnavailable


class DevicePairingTests(unittest.TestCase):
    def issued(self):
        return {'device_code': 'secret-' + 'x' * 40, 'user_code': 'K7QM-4F2X',
                'verification_uri': 'https://infergrade.com/connect', 'expires_in': 600, 'interval': 5}

    def test_poll_pending_slowdown_then_connected_keeps_secret_private(self):
        issued = self.issued()
        profile = {'runner_profile': {'access_token': 'runner-secret', 'runner_id': 'r1', 'api_url': 'https://api.infergrade.com'}}
        responses = [(200, issued), (400, {'error': 'authorization_pending'}),
                     (400, {'error': 'slow_down'}), (200, profile)]
        callback = mock.Mock()
        with mock.patch('infergrade.transport._json_request', side_effect=responses) as request, \
                mock.patch('infergrade.transport.time.sleep') as sleep:
            self.assertEqual(authorize_runner_device('https://api.infergrade.com', {}, callback), profile)
        self.assertEqual(sleep.call_args_list, [mock.call(5), mock.call(5), mock.call(10)])
        self.assertNotIn('device_code', callback.call_args.args[0])
        self.assertEqual(request.call_args.kwargs['payload'], {'device_code': issued['device_code']})

    def test_terminal_errors_never_fallback(self):
        for code in ('access_denied', 'expired_token', 'invalid_grant', 'unknown'):
            with self.subTest(code=code), mock.patch('infergrade.transport._json_request',
                    side_effect=[(200, self.issued()), (400, {'error': code})]), \
                    mock.patch('infergrade.transport.time.sleep'):
                with self.assertRaises(RuntimeError) as caught:
                    authorize_runner_device('https://api.infergrade.com', {})
                self.assertNotIsInstance(caught.exception, DeviceAuthorizationUnavailable)
                self.assertNotIn(self.issued()['device_code'], str(caught.exception))

    def test_incomplete_or_insecure_profile_never_reports_connected(self):
        for profile in ({'access_token': 'secret'},
                        {'access_token': 'secret', 'runner_id': 'r1', 'api_url': 'http://evil.example'}):
            with mock.patch('infergrade.transport._json_request',
                            side_effect=[(200, self.issued()), (200, {'runner_profile': profile})]), \
                    mock.patch('infergrade.transport.time.sleep'):
                with self.assertRaisesRegex(RuntimeError, 'runner profile'):
                    authorize_runner_device('https://api.infergrade.com', {})

    def test_local_deadline_stops_polling(self):
        with mock.patch('infergrade.transport._json_request', return_value=(200, self.issued())) as request, \
                mock.patch('infergrade.transport.time.monotonic', side_effect=[0, 600]):
            with self.assertRaisesRegex(RuntimeError, 'expired'):
                authorize_runner_device('https://api.infergrade.com', {})
        self.assertEqual(request.call_count, 1)

    def test_only_missing_endpoint_allows_legacy_fallback(self):
        for status in (404, 501):
            with mock.patch('infergrade.transport._json_request', return_value=(status, {})):
                with self.assertRaises(DeviceAuthorizationUnavailable):
                    authorize_runner_device('https://api.infergrade.com', {})

    def test_invalid_response_and_http_verification_url_are_rejected(self):
        for field, value in [('interval', True), ('expires_in', 99999),
                             ('verification_uri', 'http://evil.example/connect'), ('device_code', 'short')]:
            issued = self.issued()
            issued[field] = value
            with self.subTest(field=field), mock.patch('infergrade.transport._json_request', return_value=(200, issued)):
                with self.assertRaisesRegex(RuntimeError, 'invalid'):
                    authorize_runner_device('https://api.infergrade.com', {})

    def test_hidden_input_does_not_echo_code_and_requires_tty(self):
        args = SimpleNamespace(prompt_pair_code=True)
        with mock.patch.dict('os.environ', {'INFERGRADE_PAIR_CODE': ''}), \
                mock.patch('infergrade.cli.sys.stdin.isatty', return_value=True), \
                mock.patch('infergrade.cli.getpass.getpass', return_value=' secret '):
            self.assertEqual(_resolve_pair_code(args), 'secret')
        with mock.patch.dict('os.environ', {'INFERGRADE_PAIR_CODE': ''}), \
                mock.patch('infergrade.cli.sys.stdin.isatty', return_value=False):
            with self.assertRaisesRegex(SystemExit, 'terminal'):
                _resolve_pair_code(args)

    def test_hidden_input_fails_closed_if_echo_cannot_be_disabled(self):
        def no_terminal(*args):
            warnings.warn("Cannot control echo", getpass.GetPassWarning)
            self.fail("must stop before echoed fallback reads a secret")
        with mock.patch.dict('os.environ', {'INFERGRADE_PAIR_CODE': ''}), \
                mock.patch('infergrade.cli.sys.stdin.isatty', return_value=True), \
                mock.patch('infergrade.cli.getpass.getpass', side_effect=no_terminal):
            with self.assertRaisesRegex(SystemExit, 'Unable to hide'):
                _resolve_pair_code(SimpleNamespace(prompt_pair_code=True))

    def test_bare_pair_saves_profile_and_json_never_displays_token(self):
        out, err = io.StringIO(), io.StringIO()
        profile = {'runner_id': 'r1', 'api_url': 'https://api.infergrade.com', 'access_token': 'runner-secret'}
        def authorize(api_url, details, on_issued):
            self.assertEqual(api_url, 'https://api.infergrade.com')
            on_issued(self.issued())
            return {'runner_profile': profile}
        with mock.patch.dict('os.environ', {'INFERGRADE_PAIR_CODE': ''}), \
                mock.patch('infergrade.cli.capture_environment', return_value={}), \
                mock.patch('infergrade.cli.authorize_runner_device', side_effect=authorize), \
                mock.patch('infergrade.cli.save_runner_profile', return_value='/tmp/profile') as save, \
                redirect_stdout(out), redirect_stderr(err):
            self.assertEqual(main(['pair', '--json']), 0)
        save.assert_called_once_with(profile)
        self.assertIn('K7QM-4F2X', err.getvalue())
        self.assertNotIn('runner-secret', out.getvalue() + err.getvalue())
        self.assertNotIn(self.issued()['device_code'], out.getvalue() + err.getvalue())

    def test_device_pair_and_start_checks_runtime_before_listening(self):
        profile = {'runner_id': 'r1', 'api_url': 'https://api.infergrade.com', 'access_token': 'runner-secret'}
        with mock.patch.dict('os.environ', {'INFERGRADE_PAIR_CODE': ''}), \
                mock.patch('infergrade.cli.capture_environment', return_value={}), \
                mock.patch('infergrade.cli.authorize_runner_device', return_value={'runner_profile': profile}) as authorize, \
                mock.patch('infergrade.cli.save_runner_profile', return_value='/tmp/profile') as save, \
                mock.patch('infergrade.cli.preferred_local_execution_mode', return_value='local_native'), \
                mock.patch('infergrade.cli.resolve_runner_api_token', return_value='runner-secret'), \
                mock.patch('infergrade.cli.prepare_native_listener_runtime') as prepare, \
                mock.patch('infergrade.cli.run_worker_loop', return_value={}) as listen, \
                redirect_stdout(io.StringIO()):
            order = mock.Mock()
            for name, operation in [('save', save), ('prepare', prepare), ('listen', listen)]:
                order.attach_mock(operation, name)
            self.assertEqual(main(['pair', '--start']), 0)
        authorize.assert_called_once()
        self.assertEqual([call[0] for call in order.mock_calls], ['save', 'prepare', 'listen'])

    def test_legacy_fallback_pair_and_start_preserves_profile_when_runtime_fails(self):
        profile = {'runner_id': 'r1', 'api_url': 'https://api.infergrade.com', 'access_token': 'runner-secret'}
        with mock.patch.dict('os.environ', {'INFERGRADE_PAIR_CODE': ''}), \
                mock.patch('infergrade.cli.capture_environment', return_value={}), \
                mock.patch('infergrade.cli.authorize_runner_device', side_effect=DeviceAuthorizationUnavailable()), \
                mock.patch('infergrade.cli.sys.stdin.isatty', return_value=True), \
                mock.patch('infergrade.cli.getpass.getpass', return_value='legacy-code'), \
                mock.patch('infergrade.cli.redeem_runner_pairing', return_value={'runner_profile': profile}) as redeem, \
                mock.patch('infergrade.cli.save_runner_profile', return_value='/tmp/profile') as save, \
                mock.patch('infergrade.cli.preferred_local_execution_mode', return_value='local_native'), \
                mock.patch('infergrade.cli.resolve_runner_api_token', return_value='runner-secret'), \
                mock.patch('infergrade.cli.prepare_native_listener_runtime', side_effect=RuntimeError('runtime unavailable')), \
                mock.patch('infergrade.cli.run_worker_loop') as listen, \
                mock.patch('infergrade.cli.clear_runner_profile') as clear, \
                redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(SystemExit, 'Runner setup failed: runtime unavailable'):
                main(['pair', '--start'])
        self.assertEqual(redeem.call_args.kwargs['pair_code'], 'legacy-code')
        save.assert_called_once_with(profile)
        listen.assert_not_called()
        clear.assert_not_called()

    def test_tty_stdin_pair_code_preserves_hidden_input_failure_policy(self):
        def no_echo(*args):
            warnings.warn('Cannot control echo', getpass.GetPassWarning)
            self.fail('must stop before echoed input')
        with mock.patch.dict('os.environ', {'INFERGRADE_PAIR_CODE': ''}), \
                mock.patch('infergrade.cli.sys.stdin.isatty', return_value=True), \
                mock.patch('infergrade.cli.getpass.getpass', side_effect=no_echo):
            with self.assertRaisesRegex(SystemExit, 'Unable to hide'):
                _resolve_pair_code(SimpleNamespace(pair_code_stdin=True))
