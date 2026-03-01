import json
from django.http import JsonResponse
from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin


class SubmitTopicAnswerView(LoginRequiredMixin, View):
    def post(self, request):
        return JsonResponse({'status': 'stub'})


class TopicNextQuestionView(LoginRequiredMixin, View):
    def get(self, request, session_id):
        return JsonResponse({'status': 'stub'})


class TimesTablesAnswerView(LoginRequiredMixin, View):
    def post(self, request):
        return JsonResponse({'status': 'stub'})


class TimesTablesNextView(LoginRequiredMixin, View):
    def get(self, request, session_id):
        return JsonResponse({'status': 'stub'})
