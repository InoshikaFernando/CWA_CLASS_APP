"""
Management command: check_email_queue_health

Alerts when queued email is not going out. Mirrors check_unpaid_access: prints
a report, POSTs to a webhook when something is wrong, and exits non-zero so a
cron wrapper treats it as an alert condition.

Every invoice email is force-queued at issue time, so the process_email_queue
cron is the delivery path. When it stopped in June 2026 the queue held 316
undelivered invoices for ten weeks with nothing to notice — invoices read as
issued, and no surface reported the backlog. This command is the watchdog that
makes a repeat visible in minutes.

It deliberately does not send email: if delivery is broken, an emailed alert
would be stuck in the same queue.

Usage:
    python manage.py check_email_queue_health
    python manage.py check_email_queue_health --webhook "$FEEDBACK_DISCORD_WEBHOOK"
    python manage.py check_email_queue_health --quiet   # print only when unhealthy
"""
import json
import urllib.request

from django.core.management.base import BaseCommand

from classroom.email_health import (
    STATUS_CRITICAL, STATUS_OK, STATUS_WARNING, get_email_queue_health,
)

ICON = {STATUS_OK: ':white_check_mark:',
        STATUS_WARNING: ':warning:',
        STATUS_CRITICAL: ':rotating_light:'}


class Command(BaseCommand):
    help = 'Report (and optionally alert on) email queue backlog.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--webhook', default='',
            help='Slack/Discord webhook to POST a summary to when unhealthy.')
        parser.add_argument(
            '--quiet', action='store_true',
            help='Print nothing when the queue is healthy (for noisy crons).')
        parser.add_argument(
            '--fail-on', default=STATUS_WARNING,
            choices=[STATUS_WARNING, STATUS_CRITICAL],
            help='Minimum status that alerts and exits non-zero (default: warning).')

    def handle(self, *args, **opts):
        health = get_email_queue_health()
        status = health['status']

        unhealthy = (
            status == STATUS_CRITICAL
            or (status == STATUS_WARNING and opts['fail_on'] == STATUS_WARNING)
        )

        if not (opts['quiet'] and status == STATUS_OK):
            self.stdout.write(self._report(health))

        if not unhealthy:
            return

        if opts['webhook']:
            self._alert(opts['webhook'], health)

        # Non-zero so a cron wrapper can treat this as an alert condition.
        raise SystemExit(1)

    def _report(self, health):
        lines = [
            f'Email queue: {health["status"].upper()}',
            f'  pending:      {health["pending"]}',
            f'  failed:       {health["failed"]}',
            f'  sent today:   {health["sent_today"]}',
        ]
        if health['oldest_pending_at']:
            lines.append(
                f'  oldest wait:  {health["oldest_pending_min"]} min '
                f'(queued {health["oldest_pending_at"]:%Y-%m-%d %H:%M} UTC)')
        if health['last_sent_at']:
            lines.append(
                f'  last sent:    {health["last_sent_at"]:%Y-%m-%d %H:%M} UTC '
                f'({health["last_sent_min"]} min ago)')
        else:
            lines.append('  last sent:    never')
        if health['pending_by_type']:
            lines.append(f'  by type:      {health["pending_by_type"]}')
        for reason in health['reasons']:
            lines.append(f'  ! {reason}')
        return '\n'.join(lines)

    def _alert(self, url, health):
        detail = '; '.join(health['reasons']) or 'queue unhealthy'
        msg = (
            f'{ICON.get(health["status"], "")} CWA email queue '
            f'{health["status"].upper()}: {detail}. '
            f'{health["pending"]} pending, {health["failed"]} failed, '
            f'{health["sent_today"]} sent today. '
            f'Queued email is NOT being delivered — check the '
            f'process_email_queue cron (/etc/cron.d/cwa-email).'
        )
        payload = json.dumps({'text': msg, 'content': msg}).encode()
        try:
            req = urllib.request.Request(
                url, data=payload, headers={'Content-Type': 'application/json'})
            urllib.request.urlopen(req, timeout=10)
            self.stdout.write('Alert posted to webhook.')
        except Exception as exc:  # noqa: BLE001 — surface, don't crash the cron
            self.stderr.write(f'Failed to post webhook alert: {exc}')
