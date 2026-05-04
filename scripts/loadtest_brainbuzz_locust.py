#!/usr/bin/env python3
"""
loadtest_brainbuzz_locust.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Locust load testing script for BrainBuzz.

Alternative to k6; Locust is Python-based and more flexible.

Scenario:
- 100 concurrent participants join a session
- Each polls /api/session/{code}/state/ at 1 Hz for 60 seconds
- Measures p95 response time (must be < 200ms)

Requirements:
- Locust installed: `pip install locust`

Execution:
- locust -f loadtest_brainbuzz_locust.py -u 100 -r 10 --run-time 60s
- locust -f loadtest_brainbuzz_locust.py -u 100 --headless -r 10 --run-time 60s

Web UI:
- locust -f loadtest_brainbuzz_locust.py
  Then visit http://localhost:8089

Output:
- Real-time metrics (RPS, response times, error rates)
- CSV export with detailed timing
- Pass/fail on SLOs
"""

import time
import os
from datetime import datetime
from locust import HttpUser, task, between, events, constant_pacing


# ============================================================================
# Configuration
# ============================================================================

BASE_URL = os.getenv('BASE_URL', 'http://localhost:8000')
SESSION_CODE = os.getenv('SESSION_CODE', 'LOAD01')
POLL_INTERVAL = 1  # seconds (1 Hz)

# Performance SLOs
P95_THRESHOLD_MS = 200
P99_THRESHOLD_MS = 500
ERROR_RATE_THRESHOLD = 0.01  # 1%


# ============================================================================
# Metrics Collection
# ============================================================================

class PerformanceMetrics:
    """Collect and report performance metrics."""
    
    def __init__(self):
        self.response_times = []
        self.errors = 0
        self.total_requests = 0
        self.status_codes = {}
        self.start_time = time.time()
    
    def record_response(self, response_time_ms, status_code, error=False):
        """Record a response."""
        self.response_times.append(response_time_ms)
        self.total_requests += 1
        
        if error:
            self.errors += 1
        
        self.status_codes[status_code] = self.status_codes.get(status_code, 0) + 1
    
    def percentile(self, p):
        """Calculate percentile (e.g., p95, p99)."""
        if not self.response_times:
            return 0
        sorted_times = sorted(self.response_times)
        index = int(len(sorted_times) * (p / 100))
        return sorted_times[min(index, len(sorted_times) - 1)]
    
    def summary(self):
        """Return formatted summary."""
        elapsed = time.time() - self.start_time
        error_rate = self.errors / self.total_requests if self.total_requests > 0 else 0
        
        return {
            'elapsed_seconds': elapsed,
            'total_requests': self.total_requests,
            'rps': self.total_requests / elapsed if elapsed > 0 else 0,
            'errors': self.errors,
            'error_rate': error_rate,
            'min_ms': min(self.response_times) if self.response_times else 0,
            'max_ms': max(self.response_times) if self.response_times else 0,
            'avg_ms': sum(self.response_times) / len(self.response_times) if self.response_times else 0,
            'p50_ms': self.percentile(50),
            'p95_ms': self.percentile(95),
            'p99_ms': self.percentile(99),
            'status_codes': self.status_codes,
        }
    
    def check_slos(self):
        """Verify SLOs are met."""
        p95 = self.percentile(95)
        p99 = self.percentile(99)
        error_rate = self.errors / self.total_requests if self.total_requests > 0 else 0
        
        slos_met = True
        results = []
        
        if p95 < P95_THRESHOLD_MS:
            results.append(f"✓ p95 response time: {p95:.0f}ms < {P95_THRESHOLD_MS}ms")
        else:
            results.append(f"✗ p95 response time: {p95:.0f}ms >= {P95_THRESHOLD_MS}ms")
            slos_met = False
        
        if p99 < P99_THRESHOLD_MS:
            results.append(f"✓ p99 response time: {p99:.0f}ms < {P99_THRESHOLD_MS}ms")
        else:
            results.append(f"✗ p99 response time: {p99:.0f}ms >= {P99_THRESHOLD_MS}ms")
            slos_met = False
        
        if error_rate < ERROR_RATE_THRESHOLD:
            results.append(f"✓ Error rate: {error_rate:.2%} < {ERROR_RATE_THRESHOLD:.0%}")
        else:
            results.append(f"✗ Error rate: {error_rate:.2%} >= {ERROR_RATE_THRESHOLD:.0%}")
            slos_met = False
        
        return slos_met, results


# Global metrics
metrics = PerformanceMetrics()


# ============================================================================
# Locust User Class
# ============================================================================

class BrainBuzzParticipant(HttpUser):
    """
    Simulates a student polling the BrainBuzz session state endpoint.
    """
    
    wait_time = constant_pacing(POLL_INTERVAL)  # Poll at exactly 1 Hz
    
    def on_start(self):
        """Startup: Generate unique ID for this VU."""
        self.participant_id = self.client.request_event.user.uid if hasattr(self.client, 'request_event') else 0
    
    @task
    def poll_session_state(self):
        """
        Task: Poll /api/session/{code}/state/ endpoint.
        Simulates student continuously checking for state updates.
        """
        url = f'/brainbuzz/api/session/{SESSION_CODE}/state/'
        
        start_time = time.time()
        
        try:
            response = self.client.get(
                url,
                timeout=5,
                headers={
                    'Accept': 'application/json',
                    'User-Agent': f'locust-participant-{self.participant_id}',
                }
            )
            
            end_time = time.time()
            response_time_ms = (end_time - start_time) * 1000
            
            # Check response
            is_error = False
            
            if response.status_code == 200:
                # Full state response
                try:
                    data = response.json()
                    if 'state_version' not in data or 'status' not in data:
                        is_error = True
                except:
                    is_error = True
            
            elif response.status_code == 304:
                # Not modified (state unchanged)
                pass
            
            else:
                # Unexpected status
                is_error = True
                response.failure(f'Unexpected status code: {response.status_code}')
            
            # Record metrics
            metrics.record_response(response_time_ms, response.status_code, error=is_error)
            
            # Log slow responses
            if response_time_ms > P95_THRESHOLD_MS:
                print(f'[SLOW] p{self.participant_id}: {response_time_ms:.0f}ms')
        
        except Exception as e:
            end_time = time.time()
            response_time_ms = (end_time - start_time) * 1000
            metrics.record_response(response_time_ms, 0, error=True)
            print(f'[ERROR] p{self.participant_id}: {e}')


# ============================================================================
# Event Handlers
# ============================================================================

@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    """Called when load test starts."""
    print('\n' + '=' * 60)
    print('BrainBuzz Load Test Starting')
    print('=' * 60)
    print(f'Base URL: {BASE_URL}')
    print(f'Session Code: {SESSION_CODE}')
    print(f'Poll Interval: {POLL_INTERVAL}s (1 Hz)')
    print(f'P95 Target: < {P95_THRESHOLD_MS}ms')
    print(f'Error Rate Target: < {ERROR_RATE_THRESHOLD:.0%}')
    print('=' * 60 + '\n')


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    """Called when load test completes."""
    print('\n' + '=' * 60)
    print('BrainBuzz Load Test Summary')
    print('=' * 60)
    
    summary = metrics.summary()
    
    print(f"\nDuration: {summary['elapsed_seconds']:.1f}s")
    print(f"Total Requests: {summary['total_requests']}")
    print(f"RPS: {summary['rps']:.1f}")
    print(f"Errors: {summary['errors']} ({summary['error_rate']:.2%})")
    
    print(f"\nResponse Times (ms):")
    print(f"  Min:   {summary['min_ms']:.0f}")
    print(f"  Avg:   {summary['avg_ms']:.0f}")
    print(f"  p50:   {summary['p50_ms']:.0f}")
    print(f"  p95:   {summary['p95_ms']:.0f}")
    print(f"  p99:   {summary['p99_ms']:.0f}")
    print(f"  Max:   {summary['max_ms']:.0f}")
    
    print(f"\nStatus Codes:")
    for code, count in sorted(summary['status_codes'].items()):
        print(f"  {code}: {count}")
    
    print(f"\n{'SLO Compliance:':.<40}")
    slos_met, slo_results = metrics.check_slos()
    
    for result in slo_results:
        print(f"  {result}")
    
    print('\n' + '=' * 60)
    if slos_met:
        print('✓ ALL SLOS MET - LOAD TEST PASSED')
    else:
        print('✗ SOME SLOS FAILED - LOAD TEST FAILED')
    print('=' * 60 + '\n')
    
    environment.exit_code = 0 if slos_met else 1


# ============================================================================
# For CSV Output
# ============================================================================

@events.request.add_listener
def on_request(request_type, name, response_time, response_length, response, context, exception, **kwargs):
    """Locust event hook for detailed logging."""
    # Could output to CSV here if desired
    pass


if __name__ == '__main__':
    print("Usage: locust -f loadtest_brainbuzz_locust.py [options]")
    print("\nExamples:")
    print("  locust -f loadtest_brainbuzz_locust.py -u 100 -r 10 --run-time 60s")
    print("  locust -f loadtest_brainbuzz_locust.py --headless -u 100 -r 10 --run-time 60s")
    print("\nEnvironment variables:")
    print(f"  BASE_URL={BASE_URL}")
    print(f"  SESSION_CODE={SESSION_CODE}")
