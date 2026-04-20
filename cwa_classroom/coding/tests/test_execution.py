"""
test_execution.py
~~~~~~~~~~~~~~~~~
Tests for coding.execution module (Piston code execution API wrapper).
"""
import unittest
from unittest.mock import MagicMock, patch

from coding import execution


class TestRunCode(unittest.TestCase):

    def test_success(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            'run': {'stdout': 'Hello', 'stderr': '', 'code': 0}
        }
        mock_response.raise_for_status.return_value = None
        with patch('coding.execution.requests.post', return_value=mock_response):
            result = execution.run_code('python', 'print("Hello")')
        self.assertEqual(result['stdout'], 'Hello')
        self.assertEqual(result['stderr'], '')
        self.assertEqual(result['exit_code'], 0)
        self.assertNotIn('error', result)

    def test_success_with_run_output_fallback(self):
        """Some executor builds return run.output instead of run.stdout."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            'run': {'output': 'Hello from output\n', 'stderr': '', 'exit_code': 0}
        }
        mock_response.raise_for_status.return_value = None
        with patch('coding.execution.requests.post', return_value=mock_response):
            result = execution.run_code('python', 'print("Hello")')
        self.assertEqual(result['stdout'], 'Hello from output\n')
        self.assertEqual(result['stderr'], '')
        self.assertEqual(result['exit_code'], 0)

    def test_success_with_top_level_fallback(self):
        """Fallback for adapters that return stdout/stderr/code at top-level."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            'stdout': 'Top-level hello\n', 'stderr': '', 'code': 0
        }
        mock_response.raise_for_status.return_value = None
        with patch('coding.execution.requests.post', return_value=mock_response):
            result = execution.run_code('python', 'print("Hello")')
        self.assertEqual(result['stdout'], 'Top-level hello\n')
        self.assertEqual(result['stderr'], '')
        self.assertEqual(result['exit_code'], 0)

    def test_timeout(self):
        with patch('coding.execution.requests.post',
                   side_effect=execution.requests.exceptions.Timeout):
            result = execution.run_code('python', 'while True: pass')
        self.assertEqual(result['exit_code'], 1)
        self.assertEqual(result['error'], 'timeout')

    def test_connection_error(self):
        with patch('coding.execution.requests.post',
                   side_effect=execution.requests.exceptions.ConnectionError):
            result = execution.run_code('python', 'print("hi")')
        self.assertEqual(result['exit_code'], 1)
        self.assertEqual(result['error'], 'connection_error')

    def test_unexpected_error_returns_exception_message(self):
        # run_code returns {'error': str(exc)}, NOT 'unexpected_error'.
        with patch('coding.execution.requests.post',
                   side_effect=Exception('fail')):
            result = execution.run_code('python', 'print("hi")')
        self.assertEqual(result['exit_code'], 1)
        self.assertEqual(result['error'], 'fail')   # str(Exception('fail')) == 'fail'

    def test_no_language_returns_error(self):
        result = execution.run_code('', 'print("hi")')
        self.assertEqual(result['exit_code'], 1)
        self.assertTrue(result['error'])

    def test_clamps_timeout_and_memory_to_runner_caps(self):
        """Oversized per-problem limits must be clamped to safe runner maxima."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            'run': {'stdout': 'ok', 'stderr': '', 'code': 0}
        }
        mock_response.raise_for_status.return_value = None
        with patch('coding.execution.requests.post', return_value=mock_response) as mock_post:
            result = execution.run_code(
                'python',
                'print("ok")',
                stdin='x',
                timeout_seconds=999,
                memory_limit_mb=4096,
            )

        self.assertEqual(result['exit_code'], 0)
        payload = mock_post.call_args.kwargs['json']
        self.assertEqual(payload['run_timeout'], execution.RUN_TIMEOUT_SECONDS * 1000)
        self.assertEqual(payload['compile_timeout'], execution.COMPILE_TIMEOUT_SECONDS * 1000)
        self.assertEqual(payload['run_memory_limit'], execution.MEMORY_LIMIT_BYTES)
        self.assertEqual(payload['stdin'], 'x')

    def test_invalid_limits_fall_back_to_defaults(self):
        """Non-numeric limits should not crash and must fall back safely."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            'run': {'stdout': 'ok', 'stderr': '', 'code': 0}
        }
        mock_response.raise_for_status.return_value = None
        with patch('coding.execution.requests.post', return_value=mock_response) as mock_post:
            execution.run_code(
                'python',
                'print("ok")',
                timeout_seconds='bad',
                memory_limit_mb='bad',
            )

        payload = mock_post.call_args.kwargs['json']
        self.assertEqual(payload['run_timeout'], execution.RUN_TIMEOUT_SECONDS * 1000)
        self.assertEqual(payload['run_memory_limit'], execution.MEMORY_LIMIT_BYTES)


class TestPistonHealthCheck(unittest.TestCase):

    def test_ok(self):
        mock_response = MagicMock()
        mock_response.json.return_value = [
            {'language': 'python'}, {'language': 'javascript'}
        ]
        mock_response.raise_for_status.return_value = None
        with patch('coding.execution.requests.get', return_value=mock_response):
            ok, detail = execution.piston_health_check()
        self.assertTrue(ok)
        self.assertIn('Piston OK', detail)

    def test_missing_runtime(self):
        mock_response = MagicMock()
        mock_response.json.return_value = [{'language': 'python'}]
        mock_response.raise_for_status.return_value = None
        with patch('coding.execution.requests.get', return_value=mock_response):
            ok, detail = execution.piston_health_check()
        self.assertFalse(ok)
        self.assertIn('missing runtimes', detail)

    def test_connection_error(self):
        with patch('coding.execution.requests.get',
                   side_effect=execution.requests.exceptions.ConnectionError):
            ok, detail = execution.piston_health_check()
        self.assertFalse(ok)
        self.assertIn('Cannot connect', detail)

    def test_unexpected_error(self):
        with patch('coding.execution.requests.get',
                   side_effect=Exception('fail')):
            ok, detail = execution.piston_health_check()
        self.assertFalse(ok)
        self.assertIn('fail', detail)


class TestAuthHeaders(unittest.TestCase):
    """_auth_headers builds the Bearer header only when a token is configured."""

    def test_no_token_returns_empty_dict(self):
        with patch('coding.execution.PISTON_TOKEN', ''):
            self.assertEqual(execution._auth_headers(), {})

    def test_token_returns_bearer_header(self):
        with patch('coding.execution.PISTON_TOKEN', 'abc123'):
            self.assertEqual(
                execution._auth_headers(),
                {'Authorization': 'Bearer abc123'},
            )

    def test_run_code_attaches_bearer_header_when_token_set(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            'run': {'stdout': 'ok', 'stderr': '', 'code': 0}
        }
        mock_response.raise_for_status.return_value = None
        with patch('coding.execution.PISTON_TOKEN', 'tok'), \
             patch('coding.execution.requests.post', return_value=mock_response) as mock_post:
            execution.run_code('python', 'print("ok")')
        self.assertEqual(
            mock_post.call_args.kwargs['headers'],
            {'Authorization': 'Bearer tok'},
        )

    def test_run_code_sends_no_auth_header_when_no_token(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            'run': {'stdout': 'ok', 'stderr': '', 'code': 0}
        }
        mock_response.raise_for_status.return_value = None
        with patch('coding.execution.PISTON_TOKEN', ''), \
             patch('coding.execution.requests.post', return_value=mock_response) as mock_post:
            execution.run_code('python', 'print("ok")')
        self.assertEqual(mock_post.call_args.kwargs['headers'], {})

    def test_health_check_attaches_bearer_header_when_token_set(self):
        mock_response = MagicMock()
        mock_response.json.return_value = [
            {'language': 'python'}, {'language': 'javascript'}
        ]
        mock_response.raise_for_status.return_value = None
        with patch('coding.execution.PISTON_TOKEN', 'tok'), \
             patch('coding.execution.requests.get', return_value=mock_response) as mock_get:
            execution.piston_health_check()
        self.assertEqual(
            mock_get.call_args.kwargs['headers'],
            {'Authorization': 'Bearer tok'},
        )


class TestPistonTimeoutCap(unittest.TestCase):
    """Self-hosted Piston caps run_timeout at 3000ms and compile_timeout at 10000ms.

    Verified against piston.wizardslearninghub.co.nz — sending higher values
    returns HTTP 400 ("run_timeout cannot exceed the configured limit of 3000").
    These tests lock the client's payload within those caps so future changes
    can't silently break production.
    """

    PISTON_RUN_CAP_MS = 3_000
    PISTON_COMPILE_CAP_MS = 10_000

    def test_default_payload_timeouts_within_piston_caps(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            'run': {'stdout': 'ok', 'stderr': '', 'code': 0}
        }
        mock_response.raise_for_status.return_value = None
        with patch('coding.execution.requests.post', return_value=mock_response) as mock_post:
            execution.run_code('python', 'print("ok")')
        payload = mock_post.call_args.kwargs['json']
        self.assertLessEqual(payload['run_timeout'], self.PISTON_RUN_CAP_MS)
        self.assertLessEqual(payload['compile_timeout'], self.PISTON_COMPILE_CAP_MS)

    def test_oversized_per_problem_timeout_clamped_within_piston_run_cap(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            'run': {'stdout': 'ok', 'stderr': '', 'code': 0}
        }
        mock_response.raise_for_status.return_value = None
        with patch('coding.execution.requests.post', return_value=mock_response) as mock_post:
            execution.run_code('python', 'print("ok")', timeout_seconds=999)
        payload = mock_post.call_args.kwargs['json']
        self.assertLessEqual(payload['run_timeout'], self.PISTON_RUN_CAP_MS)
        self.assertLessEqual(payload['compile_timeout'], self.PISTON_COMPILE_CAP_MS)

    def test_compile_timeout_independent_of_per_problem_timeout(self):
        """compile_timeout must not be clamped by the per-problem run limit —
        a problem asking for run_timeout=1 must still allow a full compile."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            'run': {'stdout': 'ok', 'stderr': '', 'code': 0}
        }
        mock_response.raise_for_status.return_value = None
        with patch('coding.execution.requests.post', return_value=mock_response) as mock_post:
            execution.run_code('python', 'print("ok")', timeout_seconds=1)
        payload = mock_post.call_args.kwargs['json']
        self.assertEqual(payload['run_timeout'], 1 * 1000)
        self.assertEqual(
            payload['compile_timeout'], execution.COMPILE_TIMEOUT_SECONDS * 1000,
        )


class TestRuntimeVersion(unittest.TestCase):
    """RUNTIME_VERSIONS uses '*' so Piston picks the latest installed version."""

    def test_python_uses_wildcard_version(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            'run': {'stdout': 'ok', 'stderr': '', 'code': 0}
        }
        mock_response.raise_for_status.return_value = None
        with patch('coding.execution.requests.post', return_value=mock_response) as mock_post:
            execution.run_code('python', 'print("ok")')
        self.assertEqual(mock_post.call_args.kwargs['json']['version'], '*')

    def test_javascript_uses_wildcard_version(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            'run': {'stdout': 'ok', 'stderr': '', 'code': 0}
        }
        mock_response.raise_for_status.return_value = None
        with patch('coding.execution.requests.post', return_value=mock_response) as mock_post:
            execution.run_code('javascript', 'console.log("ok")')
        self.assertEqual(mock_post.call_args.kwargs['json']['version'], '*')


class TestHTTPErrorSurfacesPistonBody(unittest.TestCase):
    """4xx responses surface Piston's body so failures are diagnosable."""

    @staticmethod
    def _http_error(message_in_json='', text='', json_parses=True):
        """Build an HTTPError whose response carries the given body."""
        resp = MagicMock()
        if json_parses:
            resp.json.return_value = {'message': message_in_json} if message_in_json else {}
        else:
            resp.json.side_effect = ValueError('not json')
        resp.text = text
        return execution.requests.exceptions.HTTPError(
            '400 Client Error: Bad Request', response=resp,
        )

    def _post_raising(self, exc):
        """Make requests.post return a response whose raise_for_status() raises."""
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = exc
        return patch('coding.execution.requests.post', return_value=mock_response)

    def test_400_with_json_message_includes_body_in_stderr(self):
        exc = self._http_error(message_in_json='Runtime python-3.10.0 not found')
        with self._post_raising(exc):
            result = execution.run_code('python', 'print("hi")')
        self.assertEqual(result['exit_code'], 1)
        self.assertIn('Runtime python-3.10.0 not found', result['stderr'])
        self.assertIn('Runtime python-3.10.0 not found', result['error'])
        self.assertIn('400 Client Error', result['stderr'])

    def test_400_with_non_json_body_falls_back_to_text(self):
        exc = self._http_error(text='Bad Gateway plain text', json_parses=False)
        with self._post_raising(exc):
            result = execution.run_code('python', 'print("hi")')
        self.assertEqual(result['exit_code'], 1)
        self.assertIn('Bad Gateway plain text', result['stderr'])

    def test_400_with_empty_body_returns_status_text_only(self):
        exc = self._http_error(message_in_json='', text='')
        with self._post_raising(exc):
            result = execution.run_code('python', 'print("hi")')
        self.assertEqual(result['exit_code'], 1)
        self.assertIn('400 Client Error', result['stderr'])

    def test_400_body_truncated_to_500_chars(self):
        exc = self._http_error(message_in_json='X' * 1000)
        with self._post_raising(exc):
            result = execution.run_code('python', 'print("hi")')
        self.assertEqual(result['stderr'].count('X'), 500)
