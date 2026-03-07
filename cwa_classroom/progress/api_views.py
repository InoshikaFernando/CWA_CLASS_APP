import json
from django.http import JsonResponse
from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils import timezone
from datetime import date, timedelta
from maths.models import TimeLog


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

        # Use built-in reset helpers (they handle auto_now field quirks)
        log.reset_daily_if_needed()
        log.reset_weekly_if_needed()

        log.daily_total_seconds += seconds
        log.weekly_total_seconds += seconds
        log.save(update_fields=['daily_total_seconds', 'weekly_total_seconds'])

        return JsonResponse({
            'daily_seconds': log.daily_total_seconds,
            'weekly_seconds': log.weekly_total_seconds,
        })
