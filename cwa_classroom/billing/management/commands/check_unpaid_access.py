"""
Detect users who keep accessing restricted pages while their personal
subscription is delinquent (card failed / cancelled / expired) — i.e. the
exact leak that TrialExpiryMiddleware._check_personal_subscription closes.

Cross-checks each currently-delinquent ``billing.Subscription`` against the
``usage.PageHit`` log: any 200 response on a NON-billing path within the
lookback window means the user navigated somewhere they shouldn't while unpaid.

Intended to run as a cron on PROD (where live PageHits accrue) so a bypass is
noticed immediately; also useful on demand. Exits non-zero when leaks are found
so a wrapper/cron can alert, and can POST a summary to a webhook directly.

Examples:
    python manage.py check_unpaid_access                 # all delinquent users, 7-day window
    python manage.py check_unpaid_access --username Ovindik --days 30
    python manage.py check_unpaid_access --webhook "$FEEDBACK_DISCORD_WEBHOOK"
"""
import json
import urllib.request

from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta

from accounts.models import CustomUser
from billing.models import Subscription
from usage.models import PageHit
from cwa_classroom.middleware import TrialExpiryMiddleware

# Paths a gated user is legitimately allowed to reach (mirror the middleware's
# allow-list, plus onboarding/static that never count as "restricted").
ALLOWED_PREFIXES = TrialExpiryMiddleware.ALLOWED_PATHS + (
    '/accounts/complete-profile/', '/accounts/blocked/', '/accounts/login/',
    '/static/', '/media/', '/favicon',
)

DELINQUENT = (
    Subscription.STATUS_PAST_DUE,
    Subscription.STATUS_EXPIRED,
    Subscription.STATUS_CANCELLED,
)


def _is_restricted(path):
    return not any(path.startswith(p) for p in ALLOWED_PREFIXES)


class Command(BaseCommand):
    help = 'Flag delinquent-subscription users who accessed restricted pages.'

    def add_arguments(self, parser):
        parser.add_argument('--username', help='Only check this username.')
        parser.add_argument('--days', type=int, default=7,
                            help='Lookback window for PageHits (default 7).')
        parser.add_argument('--webhook', default='',
                            help='Optional Slack/Discord webhook to POST a summary to.')

    def handle(self, *args, **opts):
        since = timezone.now() - timedelta(days=opts['days'])

        subs = Subscription.objects.select_related('user').filter(status__in=DELINQUENT)
        if opts['username']:
            subs = subs.filter(user__username=opts['username'])

        leaks = []
        for sub in subs:
            user = sub.user
            if user is None or not user.is_active:
                continue
            hits = (PageHit.objects
                    .filter(user=user, status_code=200, created_at__gte=since)
                    .order_by('-created_at'))
            restricted = [h for h in hits if _is_restricted(h.path)]
            if not restricted:
                continue
            leaks.append({
                'username': user.username,
                'name': user.get_full_name() or user.username,
                'status': sub.status,
                'count': len(restricted),
                'last_seen': restricted[0].created_at,
                'last_path': restricted[0].path,
            })

        if not leaks:
            self.stdout.write(self.style.SUCCESS(
                f'OK — no delinquent user accessed a restricted page in the last {opts["days"]} day(s).'
            ))
            return

        self.stdout.write(self.style.ERROR(
            f'LEAK — {len(leaks)} delinquent user(s) accessed restricted pages '
            f'in the last {opts["days"]} day(s):'
        ))
        lines = []
        for lk in sorted(leaks, key=lambda x: x['last_seen'], reverse=True):
            line = (f"  {lk['username']} ({lk['name']}) [{lk['status']}] — "
                    f"{lk['count']} hit(s), last {lk['last_seen']:%Y-%m-%d %H:%M} at {lk['last_path']}")
            self.stdout.write(line)
            lines.append(line.strip())

        if opts['webhook']:
            self._alert(opts['webhook'], len(leaks), lines)

        # Non-zero exit so a cron wrapper treats this as an alert condition.
        raise SystemExit(1)

    def _alert(self, url, n, lines):
        msg = ':rotating_light: CWA billing leak — {} delinquent user(s) reached restricted pages:\n{}'.format(
            n, '\n'.join(lines),
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
