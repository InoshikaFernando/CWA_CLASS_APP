"""
test_execution.py
~~~~~~~~~~~~~~~~~
Pytest for coding.execution module (Piston code execution API wrapper).
"""
import pytest
from unittest.mock import patch, MagicMock
from coding import execution


def test_run_code_success():
    mock_response = MagicMock()
    mock_response.json.return_value = {
        'run': {'stdout': 'Hello', 'stderr': '', 'code': 0}
    }
    mock_response.raise_for_status.return_value = None
    with patch('coding.execution.requests.post', return_value=mock_response):
        result = execution.run_code('python', 'print("Hello")')
        assert result['stdout'] == 'Hello'
        assert result['stderr'] == ''
        assert result['exit_code'] == 0
        assert 'error' not in result


def test_run_code_timeout():
    with patch('coding.execution.requests.post', side_effect=execution.requests.exceptions.Timeout):
        result = execution.run_code('python', 'while True: pass')
        assert result['exit_code'] == 1
        assert result['error'] == 'timeout'


def test_run_code_connection_error():
    with patch('coding.execution.requests.post', side_effect=execution.requests.exceptions.ConnectionError):
        result = execution.run_code('python', 'print("hi")')
        assert result['exit_code'] == 1
        assert result['error'] == 'connection_error'


def test_run_code_unexpected_error():
    with patch('coding.execution.requests.post', side_effect=Exception('fail')):
        result = execution.run_code('python', 'print("hi")')
        assert result['exit_code'] == 1
        assert result['error'] == 'unexpected_error'


def test_run_code_no_language():
    result = execution.run_code('', 'print("hi")')
    assert result['exit_code'] == 1
    assert result['error']


def test_piston_health_check_ok():
    mock_response = MagicMock()
    mock_response.json.return_value = [
        {'language': 'python'}, {'language': 'node'}
    ]
    mock_response.raise_for_status.return_value = None
    with patch('coding.execution.requests.get', return_value=mock_response):
        ok, detail = execution.piston_health_check()
        assert ok is True
        assert 'Piston OK' in detail


def test_piston_health_check_missing_runtime():
    mock_response = MagicMock()
    mock_response.json.return_value = [
        {'language': 'python'}
    ]
    mock_response.raise_for_status.return_value = None
    with patch('coding.execution.requests.get', return_value=mock_response):
        ok, detail = execution.piston_health_check()
        assert ok is False
        assert 'missing runtimes' in detail


def test_piston_health_check_connection_error():
    with patch('coding.execution.requests.get', side_effect=execution.requests.exceptions.ConnectionError):
        ok, detail = execution.piston_health_check()
        assert ok is False
        assert 'Cannot connect' in detail


def test_piston_health_check_unexpected_error():
    with patch('coding.execution.requests.get', side_effect=Exception('fail')):
        ok, detail = execution.piston_health_check()
        assert ok is False
        assert 'fail' in detail
