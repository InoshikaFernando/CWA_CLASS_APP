#!/usr/bin/env bash
# ops_metrics.sh — emits droplet health metrics as KEY=VALUE lines.
#
# Designed to be piped over SSH from the ops-dashboard workflow:
#     ssh <droplet> 'bash -s' < scripts/ops_metrics.sh
# so it does NOT need to be deployed to the box first. Read-only; no side effects.
set -uo pipefail

# --- Memory / swap (MB) ---
echo "MEM_TOTAL=$(free -m | awk '/^Mem:/{print $2}')"
echo "MEM_USED=$(free -m  | awk '/^Mem:/{print $3}')"
echo "MEM_AVAIL=$(free -m | awk '/^Mem:/{print $7}')"
echo "SWAP_TOTAL=$(free -m | awk '/^Swap:/{print $2}')"
echo "SWAP_USED=$(free -m  | awk '/^Swap:/{print $3}')"

# --- Disk (root fs) ---
echo "DISK_USED_PCT=$(df -P / | awk 'NR==2{gsub(/%/,"",$5); print $5}')"
echo "DISK_AVAIL=$(df -Ph / | awk 'NR==2{print $4}')"

# --- Load average (1m) ---
echo "LOAD1=$(awk '{print $1}' /proc/loadavg)"
echo "NPROC=$(nproc)"

# --- OOM kills in the last 24h (kernel ring buffer via journald) ---
oom=$(journalctl --since '24 hours ago' -k --no-pager 2>/dev/null | grep -ic 'out of memory' || true)
echo "OOM_24H=${oom:-0}"

# --- Service health (active/inactive/failed/unknown) ---
svc() { systemctl is-active "$1" 2>/dev/null || echo unknown; }
echo "SVC_GUNICORN=$(svc cwa-gunicorn-test.service)"
echo "SVC_WORKER=$(svc cwa-rqworker-test.service)"
echo "SVC_REDIS=$(svc redis-server.service)"
echo "SVC_CADDY=$(svc caddy.service)"

# --- RQ queue depth (best-effort; empty if redis-cli/DB differ) ---
echo "RQ_DEFAULT=$(redis-cli -n 1 llen rq:queue:default 2>/dev/null || echo '?')"
echo "RQ_HIGH=$(redis-cli -n 1 llen rq:queue:high 2>/dev/null || echo '?')"

echo "COLLECTED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
