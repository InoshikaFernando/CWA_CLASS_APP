import json
from django.http import JsonResponse
from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils import timezone
from datetime import date, timedelta
from .models import TimeLog


class UpdateTimeLogView(LoginRequiredMixin, View):
    def post(self, request):
        try:
            data = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            data = {}

        seconds = int(data.get('seconds', 30))
        if seconds < 1 or seconds > 300:
            return JsonResponse({'error': 'invalid'}, status=400)

        log, _ = TimeLog.objects.get_or_create(student=request.user)
        today = timezone.localdate()
        # Reset daily counter if new day
        if log.last_daily_reset != today:
            log.daily_seconds = 0
            log.last_daily_reset = today
        # Reset weekly counter if new week (Monday)
        week_start = today - timedelta(days=today.weekday())
        if log.last_weekly_reset != week_start:
            log.weekly_seconds = 0
            log.last_weekly_reset = week_start

        log.daily_seconds += seconds
        log.weekly_seconds += seconds
        log.save()

        return JsonResponse({
            'daily_seconds': log.daily_seconds,
            'weekly_seconds': log.weekly_seconds,
        })
