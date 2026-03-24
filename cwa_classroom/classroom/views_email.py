from django.core.paginator import Paginator
from django.shortcuts import render, redirect, get_object_or_404
from django.views import View
from django.contrib import messages
from django.utils import timezone
from django.db.models import Count, Q

from accounts.models import Role
from .views import RoleRequiredMixin
from .models import (
    School, SchoolTeacher, SchoolStudent, ClassRoom,
    EmailCampaign, EmailLog, EmailPreference,
)
from .email_service import send_bulk_emails


class EmailDashboardView(RoleRequiredMixin, View):
    """Email management overview with stats and recent campaigns."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def get(self, request):
        school = School.objects.filter(admin=request.user).first()
        if not school:
            messages.error(request, 'No school found.')
            return redirect('admin_dashboard')

        total_sent = EmailLog.objects.filter(status='sent').count()
        total_failed = EmailLog.objects.filter(status='failed').count()
        recent_campaigns = EmailCampaign.objects.filter(school=school)[:10]

        return render(request, 'admin_dashboard/email_dashboard.html', {
            'school': school,
            'total_sent': total_sent,
            'total_failed': total_failed,
            'recent_campaigns': recent_campaigns,
        })


class EmailComposeView(RoleRequiredMixin, View):
    """Compose and send a bulk email campaign."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def get(self, request):
        school = School.objects.filter(admin=request.user).first()
        if not school:
            messages.error(request, 'No school found.')
            return redirect('admin_dashboard')

        classes = ClassRoom.objects.filter(school=school, is_active=True).order_by('name')

        return render(request, 'admin_dashboard/email_compose.html', {
            'school': school,
            'classes': classes,
        })

    def post(self, request):
        school = School.objects.filter(admin=request.user).first()
        if not school:
            messages.error(request, 'No school found.')
            return redirect('admin_dashboard')

        name = request.POST.get('name', '').strip()
        subject = request.POST.get('subject', '').strip()
        html_body = request.POST.get('html_body', '').strip()

        if not name or not subject or not html_body:
            messages.error(request, 'Please fill in all required fields.')
            return redirect('email_compose')

        # Build recipient filter
        recipient_filter = {}
        roles = request.POST.getlist('roles')
        if roles:
            recipient_filter['roles'] = roles

        class_ids = request.POST.getlist('class_ids')
        if class_ids:
            recipient_filter['class_ids'] = [int(c) for c in class_ids]

        campaign = EmailCampaign.objects.create(
            name=name,
            subject=subject,
            html_body=html_body,
            school=school,
            recipient_filter=recipient_filter,
            created_by=request.user,
        )

        action = request.POST.get('action', 'send')
        if action == 'draft':
            messages.success(request, f'Campaign "{name}" saved as draft.')
            return redirect('email_campaign_list')

        # Send immediately
        send_bulk_emails(campaign)
        messages.success(
            request,
            f'Campaign "{name}" sent to {campaign.sent_count} recipients '
            f'({campaign.failed_count} failed).',
        )
        return redirect('email_campaign_detail', campaign_id=campaign.id)


class EmailCampaignListView(RoleRequiredMixin, View):
    """List all email campaigns for the school."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def get(self, request):
        school = School.objects.filter(admin=request.user).first()
        if not school:
            messages.error(request, 'No school found.')
            return redirect('admin_dashboard')

        campaigns = EmailCampaign.objects.filter(school=school).order_by('-created_at')
        paginator = Paginator(campaigns, 25)
        page = paginator.get_page(request.GET.get('page'))

        return render(request, 'admin_dashboard/email_campaign_list.html', {
            'school': school,
            'campaigns': page,
            'page': page,
        })


class EmailCampaignDetailView(RoleRequiredMixin, View):
    """Detail view for a single campaign with delivery logs."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def get(self, request, campaign_id):
        campaign = get_object_or_404(EmailCampaign, id=campaign_id)
        logs = campaign.logs.select_related('recipient').all()[:100]

        return render(request, 'admin_dashboard/email_campaign_detail.html', {
            'campaign': campaign,
            'logs': logs,
        })


class UnsubscribeView(View):
    """Public view for users to unsubscribe from campaign emails."""

    def get(self, request, token):
        pref = get_object_or_404(EmailPreference, unsubscribe_token=token)
        pref.receive_campaigns = False
        pref.save()

        return render(request, 'email/unsubscribe_page.html', {
            'site_name': 'Wizards Learning Hub',
        })
