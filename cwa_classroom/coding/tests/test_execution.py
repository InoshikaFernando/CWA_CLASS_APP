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
        self.assertEqual(payload['run_timeout'], execution.EXECUTION_TIMEOUT_SECONDS * 1000)
        self.assertEqual(payload['compile_timeout'], execution.EXECUTION_TIMEOUT_SECONDS * 1000)
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
        self.assertEqual(payload['run_timeout'], execution.EXECUTION_TIMEOUT_SECONDS * 1000)
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
