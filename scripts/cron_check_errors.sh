#!/bin/bash
# Daily error log checker — creates Jira CPP tasks for new errors
# Install: add to crontab on DO server: 0 0 * * * /home/cwa/scripts/cron_check_errors.sh
#
# Required env vars (set in /etc/cwa/cron_jira.env):
#   JIRA_BASE_URL   - e.g. https://yoursite.atlassian.net
#   JIRA_USER_EMAIL - Jira account email
#   JIRA_API_TOKEN  - Jira API token (https://id.atlassian.com/manage-profile/security/api-tokens)

set -euo pipefail

ENV_FILE="/etc/cwa/cron_jira.env"
LOG_DIR="/var/log/cwa"
PROJECT_KEY="CPP"
ISSUE_TYPE="Bug"
STATE_FILE="/var/log/cwa/.last_error_check"

if [[ ! -f "$ENV_FILE" ]]; then
    echo "ERROR: $ENV_FILE not found. Create it with JIRA_BASE_URL, JIRA_USER_EMAIL, JIRA_API_TOKEN."
    exit 1
fi

source "$ENV_FILE"

if [[ -z "${JIRA_BASE_URL:-}" || -z "${JIRA_USER_EMAIL:-}" || -z "${JIRA_API_TOKEN:-}" ]]; then
    echo "ERROR: Missing required env vars in $ENV_FILE"
    exit 1
fi

# Find errors from the last 24 hours
SINCE=$(date -d '24 hours ago' '+%Y-%m-%d %H:%M:%S' 2>/dev/null || date -v-24H '+%Y-%m-%d %H:%M:%S')

ERRORS_FILE=$(mktemp)
trap "rm -f $ERRORS_FILE" EXIT

# Grep for ERROR/CRITICAL/Traceback in log files modified in last 24h
find "$LOG_DIR" -name "*.log" -mmin -1440 -exec grep -l -i "error\|critical\|traceback" {} \; | while read -r logfile; do
    # Extract error blocks (lines with ERROR/CRITICAL + following traceback lines)
    awk -v since="$SINCE" '
    /^[0-9]{4}-[0-9]{2}-[0-9]{2}/ {
        timestamp = substr($0, 1, 19)
        if (timestamp >= since) in_range = 1; else in_range = 0
    }
    in_range && /ERROR|CRITICAL|Traceback/ {
        printing = 1
        error_block = ""
    }
    printing {
        error_block = error_block $0 "\n"
        lines++
    }
    printing && lines > 30 {
        printing = 0
        lines = 0
        print error_block
        print "---"
    }
    /^[0-9]{4}-[0-9]{2}-[0-9]{2}/ && printing && !/ERROR|CRITICAL|Traceback/ {
        printing = 0
        lines = 0
        print error_block
        print "---"
    }
    ' "$logfile" >> "$ERRORS_FILE"
done

# Also check journalctl for gunicorn errors
journalctl -u cwa-gunicorn.service --since "24 hours ago" --no-pager -p err 2>/dev/null | head -100 >> "$ERRORS_FILE"

# Exit if no errors found
if [[ ! -s "$ERRORS_FILE" ]]; then
    echo "$(date): No errors found in last 24 hours."
    exit 0
fi

# Deduplicate: count unique error signatures
ERROR_COUNT=$(grep -c -i "error\|critical\|traceback" "$ERRORS_FILE" || echo "0")
SUMMARY="[Auto] $ERROR_COUNT error(s) detected in prod logs — $(date '+%Y-%m-%d')"

# Truncate description to fit Jira (max ~30KB)
DESCRIPTION=$(head -c 25000 "$ERRORS_FILE" | sed 's/"/\\"/g' | sed ':a;N;$!ba;s/\n/\\n/g')

# Create Jira issue
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST \
    "${JIRA_BASE_URL}/rest/api/3/issue" \
    -H "Authorization: Basic $(echo -n "${JIRA_USER_EMAIL}:${JIRA_API_TOKEN}" | base64)" \
    -H "Content-Type: application/json" \
    -d "{
        \"fields\": {
            \"project\": {\"key\": \"${PROJECT_KEY}\"},
            \"summary\": \"${SUMMARY}\",
            \"description\": {
                \"type\": \"doc\",
                \"version\": 1,
                \"content\": [{
                    \"type\": \"codeBlock\",
                    \"attrs\": {\"language\": \"text\"},
                    \"content\": [{\"type\": \"text\", \"text\": \"${DESCRIPTION}\"}]
                }]
            },
            \"issuetype\": {\"name\": \"${ISSUE_TYPE}\"},
            \"labels\": [\"auto-detected\", \"prod-error\"]
        }
    }")

HTTP_CODE=$(echo "$RESPONSE" | tail -1)
BODY=$(echo "$RESPONSE" | sed '$d')

if [[ "$HTTP_CODE" == "201" ]]; then
    ISSUE_KEY=$(echo "$BODY" | grep -o '"key":"[^"]*"' | head -1 | cut -d'"' -f4)
    echo "$(date): Created Jira issue ${ISSUE_KEY} with ${ERROR_COUNT} error(s)."

    # Optionally announce the filed issue on Discord. Skipped when the webhook
    # is unset; a failed post must not fail the cron run (|| true).
    if [[ -n "${FEEDBACK_DISCORD_WEBHOOK:-}" ]]; then
        ISSUE_URL="${JIRA_BASE_URL}/browse/${ISSUE_KEY}"
        curl -s -X POST \
            -H 'Content-Type: application/json' \
            -d "{\"content\":\"🐞 Error-log bug filed: ${ISSUE_KEY} ${SUMMARY} ${ISSUE_URL}\"}" \
            "$FEEDBACK_DISCORD_WEBHOOK" >/dev/null || true
    fi
else
    echo "$(date): ERROR creating Jira issue. HTTP ${HTTP_CODE}: ${BODY}"
    exit 1
fi
