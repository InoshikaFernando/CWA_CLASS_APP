"""
Detect users who keep accessing restricted pages while their personal
subscription is delinquent (card failed / cancelled / expired) — i.e. the
exact leak that TrialExpiryMiddleware._check_personal_subscription closes.

The detection itself lives in ``billing.subscription_health`` so this command,
the Ops dashboard and the deep health endpoint all agree on what a leak is.
This layer is the alerting: it prints a report, POSTs to a webhook when
something is wrong, and exits non-zero so a cron wrapper treats it as an alert
condition (mirrors check_email_queue_health).

Runs daily on PROD (``/etc/cron.d/cwa-unpaid-access``, written by
deploy/setup-app-prod.sh) — that is where live PageHits accrue, so a bypass is
noticed the next morning rather than at the next revenue review. Also useful on
demand.

Examples:
    python manage.py check_unpaid_access                 # all delinquent users, 7-day window
    python manage.py check_unpaid_access --username Ovindik --days 30
    python manage.py check_unpaid_access --webhook "$FEEDBACK_DISCORD_WEBHOOK"
"""
import json
import urllib.request

from django.core.management.base import BaseCommand

from billing.subscription_health import (
    DEFAULT_LOOKBACK_DAYS, STATUS_CRITICAL, STATUS_OK, STATUS_WARNING,
    get_unpaid_access_health,
)

ICON = {STATUS_OK: ':white_check_mark:',
        STATUS_WARNING: ':warning:',
        STATUS_CRITICAL: ':rotating_light:'}


class Command(BaseCommand):
    help = 'Flag delinquent-subscription users who accessed restricted pages.'

    def add_arguments(self, parser):
        parser.add_argument('--username', help='Only check this username.')
        parser.add_argument('--days', type=int, default=DEFAULT_LOOKBACK_DAYS,
                            help=f'Lookback window for PageHits (default {DEFAULT_LOOKBACK_DAYS}).')
        parser.add_argument('--webhook', default='',
                            help='Optional Slack/Discord webhook to POST a summary to.')
        parser.add_argument('--quiet', action='store_true',
                            help='Print nothing when there is no leak (for noisy crons).')

    def handle(self, *args, **opts):
        health = get_unpaid_access_health(
            days=opts['days'], username=opts['username'],
        )
        days = health['window_days']

        if health['status'] == STATUS_OK:
            if not opts['quiet']:
                self.stdout.write(self.style.SUCCESS(
                    f'OK — no delinquent user accessed a restricted page in '
                    f'the last {days} day(s) '
                    f'({health["delinquent"]} delinquent account(s) checked).'
                ))
            return

        self.stdout.write(self.style.ERROR(
            f'LEAK — {health["leak_count"]} delinquent user(s) accessed '
            f'restricted pages in the last {days} day(s):'
        ))
        lines = []
        for leak in health['leaks']:
            line = (f"  {leak['username']} ({leak['name']}) [{leak['status']}] — "
                    f"{leak['count']} hit(s), last "
                    f"{leak['last_seen']:%Y-%m-%d %H:%M} at {leak['last_path']}")
            self.stdout.write(line)
            lines.append(line.strip())
        if health['truncated']:
            note = (f'  … and {health["leak_count"] - len(health["leaks"])} '
                    f'more not listed')
            self.stdout.write(note)
            lines.append(note.strip())

        if opts['webhook']:
            self._alert(opts['webhook'], health, lines)

        # Non-zero exit so a cron wrapper treats this as an alert condition.
        raise SystemExit(1)

    def _alert(self, url, health, lines):
        msg = '{} CWA billing leak — {} delinquent user(s) reached restricted pages:\n{}'.format(
            ICON.get(health['status'], ''), health['leak_count'], '\n'.join(lines),
        )
        payload = json.dumps({'text': msg, 'content': msg}).encode()
        try:
            req = urllib.request.Request(
                url, data=payload, headers={'Content-Type': 'application/json'},
            )
            urllib.request.urlopen(req, timeout=10)
            self.stdout.write('Alert posted to webhook.')
        except Exception as exc:  # noqa: BLE001 — surface, don't crash the cron
            self.stderr.write(f'Failed to post webhook alert: {exc}')
