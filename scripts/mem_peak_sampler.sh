#!/usr/bin/env bash
# mem_peak_sampler.sh — maintains a memory high-water mark on the droplet.
#
# The ops dashboard only polls every ~30 min, so it would miss short-lived
# memory spikes (e.g. a PDF upload being classified). Run this from cron every
# minute or two so the peak is captured regardless of when the dashboard looks:
#
#   # crontab -e  (as the cwa user)
#   */2 * * * * /home/cwa/CWA_CLASS_APP_TEST/scripts/mem_peak_sampler.sh
#
# It records the highest "used" memory (total - available, in MB) ever seen,
# plus the UTC timestamp, in $HOME/.cwa-ops-mem-peak. Delete that file to reset.
set -uo pipefail

mt=$(free -m | awk '/^Mem:/{print $2}')
ma=$(free -m | awk '/^Mem:/{print $7}')
used=$(( ${mt:-0} - ${ma:-0} ))

PEAK_FILE="${OPS_MEM_PEAK_FILE:-$HOME/.cwa-ops-mem-peak}"
prev=$(cut -d' ' -f1 "$PEAK_FILE" 2>/dev/null); prev=${prev:-0}

if [ "${used:-0}" -gt "${prev:-0}" ]; then
    printf '%s %s\n' "$used" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$PEAK_FILE"
fi
