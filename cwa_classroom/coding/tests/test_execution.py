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
