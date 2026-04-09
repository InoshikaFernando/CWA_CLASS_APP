import json
from unittest.mock import patch

import pytest
from django.urls import reverse

from coding.models import calculate_coding_points


def test_calculate_coding_points_full_pass_reflects_speed():
    assert calculate_coding_points(5, 5, 0) == 100.0
    assert calculate_coding_points(5, 5, 15) < 100.0
    assert calculate_coding_points(5, 5, 30) < calculate_coding_points(5, 5, 15)


def test_calculate_coding_points_partial_pass_still_penalises_time():
    points = calculate_coding_points(3, 5, 20)
    assert points < 100.0
    assert points > 0.0


def test_api_submit_problem_uses_execution_runtime(auth_client, problem_with_cases):
    url = reverse('coding:api_submit_problem', args=[problem_with_cases.id])
    code = 'print(input()[::-1])'

    with patch('coding.execution.run_code') as mock_run_code:
        # Two submissions × two test cases each = four run_code calls.
        # Piston returns the same execution time on both attempts because
        # the code is identical — the score must be identical too, regardless
        # of the user-provided time_taken_seconds.
        mock_run_code.side_effect = [
            {'stdout': 'olleh', 'stderr': '', 'exit_code': 0, 'run_time_seconds': 0.10},
            {'stdout': 'a', 'stderr': '', 'exit_code': 0, 'run_time_seconds': 0.05},
            {'stdout': 'olleh', 'stderr': '', 'exit_code': 0, 'run_time_seconds': 0.10},
            {'stdout': 'a', 'stderr': '', 'exit_code': 0, 'run_time_seconds': 0.05},
        ]

        response = auth_client.post(
            url,
            data=json.dumps({'code': code, 'time_taken_seconds': 500}),
            content_type='application/json',
        )
        assert response.status_code == 200
        data = response.json()
        assert data['attempt_points'] == calculate_coding_points(2, 2, 0.15)

        response2 = auth_client.post(
            url,
            data=json.dumps({'code': code, 'time_taken_seconds': 10}),
            content_type='application/json',
        )
        assert response2.status_code == 200
        data2 = response2.json()
        assert data2['attempt_points'] == calculate_coding_points(2, 2, 0.15)
        assert data2['attempt_points'] == data['attempt_points']
