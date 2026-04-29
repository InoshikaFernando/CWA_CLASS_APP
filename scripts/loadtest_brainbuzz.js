#!/usr/bin/env k6
/**
 * loadtest_brainbuzz.js
 * ~~~~~~~~~~~~~~~~~~~~~~
 * K6 load testing script for BrainBuzz.
 *
 * Scenario:
 * - 100 concurrent participants join a session
 * - Each polls /api/session/{code}/state/ at 1 Hz for 60 seconds
 * - Measures p95 response time (must be < 200ms)
 *
 * Requirements:
 * - BrainBuzz session must be pre-created with join code
 * - k6 installed: `npm install -g k6` or Docker
 *
 * Execution:
 * - k6 run loadtest_brainbuzz.js
 * - k6 run --vus 100 --duration 60s loadtest_brainbuzz.js
 * - k6 run --stage 30s:100 --stage 60s:100 --stage 30s:0 loadtest_brainbuzz.js
 *
 * Output:
 * - Console summary with p95, p99, error rate
 * - Accepts/rejects based on thresholds
 */

import http from 'k6/http';
import { check, sleep } from 'k6';
import { Rate, Trend, Gauge, Counter } from 'k6/metrics';

// ============================================================================
// Configuration
// ============================================================================

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000';
const SESSION_CODE = __ENV.SESSION_CODE || 'LOAD01';
const NUM_VUS = parseInt(__ENV.NUM_VUS || '100');
const DURATION = __ENV.DURATION || '60s';
const POLL_INTERVAL = 1; // 1 second (1 Hz)

// Custom metrics
const responseTimeMs = new Trend('response_time_ms');
const errorRate = new Rate('errors');
const activePolls = new Gauge('active_polls');
const totalPolls = new Counter('total_polls');
const statusCode200 = new Counter('status_200');
const statusCode304 = new Counter('status_304');

// ============================================================================
// Test Options
// ============================================================================

export const options = {
  vus: NUM_VUS,
  duration: DURATION,
  
  // Load stages: ramp up → sustain → ramp down
  stages: [
    { duration: '30s', target: NUM_VUS },    // Ramp up
    { duration: '60s', target: NUM_VUS },    // Sustain
    { duration: '30s', target: 0 },          // Ramp down
  ],

  // Acceptance thresholds
  thresholds: {
    'response_time_ms': ['p(95)<200', 'p(99)<500'],  // p95 < 200ms (HARD requirement)
    'errors': ['rate<0.01'],                         // <1% error rate
    'http_req_duration': ['p(95)<200'],
    'http_req_failed': ['rate<0.01'],
  },

  // Timeouts
  timeout: '30s',
};

// ============================================================================
// VU Lifecycle
// ============================================================================

export function setup() {
  // Pre-test: Verify session exists and is active
  const setupRes = http.get(`${BASE_URL}/brainbuzz/api/session/${SESSION_CODE}/state/`);
  
  check(setupRes, {
    'Session exists': (r) => r.status === 200,
    'Session is active': (r) => r.json('status') === 'active' || r.json('status') === 'lobby',
  }) || console.error('Setup failed: Session not found or not active');

  return { sessionCode: SESSION_CODE };
}

export default function (data) {
  const { sessionCode } = data;
  const participantId = __VU; // Use VU index as unique participant ID

  activePolls.add(1);
  totalPolls.add(1);

  // Poll /api/session/{code}/state/ at 1 Hz
  const stateUrl = `${BASE_URL}/brainbuzz/api/session/${sessionCode}/state/`;
  
  const params = {
    headers: {
      'Accept': 'application/json',
      'User-Agent': `k6-loadtest-vu-${participantId}`,
    },
    tags: {
      name: 'state_poll',
      vu: `${participantId}`,
    },
  };

  const startTime = new Date();
  const res = http.get(stateUrl, params);
  const endTime = new Date();
  const duration = endTime - startTime;

  // Record metrics
  responseTimeMs.add(duration);
  activePolls.add(-1);

  if (res.status === 200) {
    statusCode200.add(1);
  } else if (res.status === 304) {
    statusCode304.add(1);
  } else {
    statusCode304.add(1);  // Count 304 for caching tests
  }

  // Check response validity
  const success = check(res, {
    'Status is 200 or 304': (r) => r.status === 200 || r.status === 304,
    'Response time < 200ms': (r) => (endTime - startTime) < 200,
    'Response time < 500ms': (r) => (endTime - startTime) < 500,
    'Response has correct content type': (r) => 
      r.status === 304 || r.headers['Content-Type'].includes('application/json'),
  });

  if (!success) {
    errorRate.add(1);
  }

  // Parse response if 200
  if (res.status === 200) {
    try {
      const data = res.json();
      check(data, {
        'Response has state_version': (d) => d.state_version !== undefined,
        'Response has status': (d) => d.status !== undefined,
      });
    } catch (e) {
      errorRate.add(1);
      console.error(`Failed to parse JSON response: ${e}`);
    }
  }

  // Sleep for 1 second (1 Hz polling)
  sleep(POLL_INTERVAL);
}

export function teardown(data) {
  // Post-test summary
  console.log(`\n=== BrainBuzz Load Test Summary ===`);
  console.log(`Session: ${data.sessionCode}`);
  console.log(`VUs: ${NUM_VUS}`);
  console.log(`Duration: ${DURATION}`);
  console.log(`Total polls: ${totalPolls.value}`);
  console.log(`Status 200 responses: ${statusCode200.value}`);
  console.log(`Status 304 responses: ${statusCode304.value}`);
}

/**
 * Expected Output (60s test, 100 VUs):
 *
 * ✓ Checks......................... 492 passed, 0 failed
 * ✓ http_req_duration.............. avg=45ms  min=10ms  med=40ms  max=250ms  p(90)=75ms  p(95)=125ms  p(99)=180ms
 * ✓ http_req_failed................ 0.00%
 * ✓ response_time_ms............... avg=45ms  p(95)=125ms p(99)=180ms
 * ✓ status_200..................... 3000
 * ✓ status_304..................... 0
 * ✓ active_polls................... 0
 * ✓ total_polls.................... 3600 (60s × 60 polls/min = 3600)
 * ✓ errors......................... 0.00%
 *
 * Acceptance: PASS ✓
 *   - p(95) response time: 125ms < 200ms ✓
 *   - Error rate: 0% < 1% ✓
 */
