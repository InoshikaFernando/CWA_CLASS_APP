"""
Super Admin Billing Management views.

All views require superuser access via SuperuserRequiredMixin.
"""
import logging
from decimal import Decimal, InvalidOperation

from django.shortcuts import render, redirect, get_object_or_404
from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.utils.text import slugify
from django.utils import timezone
from django.db.models import Sum, Count, Q

from .models import (
    InstitutePlan, InstituteDiscountCode, ModuleProduct,
    SchoolSubscription, ModuleSubscription, PromoCode,
    DiscountCode, Package, DURATION_CHOICES,
)
from audit.services import log_event

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Mixin
# ---------------------------------------------------------------------------

class SuperuserRequiredMixin(LoginRequiredMixin):
    """Restrict access to superusers only. Redirects with error if not."""

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not request.user.is_superuser:
            messages.error(request, 'You do not have permission to access this page.')
            return redirect('subjects_hub')
        return super().dispatch(request, *args, **kwargs)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

class BillingAdminDashboardView(SuperuserRequiredMixin, View):
    def get(self, request):
        total_plans = InstitutePlan.objects.count()
        active_plans = InstitutePlan.objects.filter(is_active=True).count()
        active_subs = SchoolSubscription.objects.filter(
            status__in=['active', 'trialing'],
        ).count()
        active_discounts = InstituteDiscountCode.objects.filter(is_active=True).count()

        # Estimated MRR from active subscriptions
        mrr = SchoolSubscription.objects.filter(
            status__in=['active', 'trialing'],
            plan__isnull=False,
        ).aggregate(total=Sum('plan__price'))['total'] or Decimal('0.00')

        return render(request, 'admin_dashboard/billing/dashboard.html', {
            'total_plans': total_plans,
            'active_plans': active_plans,
            'active_subs': active_subs,
            'active_discounts': active_discounts,
            'mrr': mrr,
        })


# ---------------------------------------------------------------------------
# Plans
# ---------------------------------------------------------------------------

class PlanListView(SuperuserRequiredMixin, View):
    def get(self, request):
        plans = InstitutePlan.objects.all()
        return render(request, 'admin_dashboard/billing/plan_list.html', {
            'plans': plans,
        })


class PlanCreateView(SuperuserRequiredMixin, View):
    def get(self, request):
        return render(request, 'admin_dashboard/billing/plan_form.html', {
            'form_data': {},
        })

    def post(self, request):
        data = request.POST
        errors = {}
        name = data.get('name', '').strip()
        price = data.get('price', '').strip()
        class_limit = data.get('class_limit', '0').strip()
        student_limit = data.get('student_limit', '0').strip()
        invoice_limit_yearly = data.get('invoice_limit_yearly', '0').strip()
        extra_invoice_rate = data.get('extra_invoice_rate', '0').strip()
        trial_days = data.get('trial_days', '14').strip()
        order = data.get('order', '0').strip()

        if not name:
            errors['name'] = 'Name is required.'
        try:
            price_val = Decimal(price)
            if price_val <= 0:
                errors['price'] = 'Price must be greater than 0.'
        except (InvalidOperation, ValueError):
            errors['price'] = 'Enter a valid price.'

        try:
            class_limit_val = int(class_limit)
            if class_limit_val < 0:
                errors['class_limit'] = 'Must be 0 or greater.'
        except ValueError:
            errors['class_limit'] = 'Enter a valid number.'

        try:
            student_limit_val = int(student_limit)
            if student_limit_val < 0:
                errors['student_limit'] = 'Must be 0 or greater.'
        except ValueError:
            errors['student_limit'] = 'Enter a valid number.'

        try:
            invoice_limit_val = int(invoice_limit_yearly)
            if invoice_limit_val < 0:
                errors['invoice_limit_yearly'] = 'Must be 0 or greater.'
        except ValueError:
            errors['invoice_limit_yearly'] = 'Enter a valid number.'

        try:
            extra_rate_val = Decimal(extra_invoice_rate)
            if extra_rate_val < 0:
                errors['extra_invoice_rate'] = 'Must be 0 or greater.'
        except (InvalidOperation, ValueError):
            errors['extra_invoice_rate'] = 'Enter a valid rate.'

        try:
            trial_days_val = int(trial_days)
        except ValueError:
            trial_days_val = 14

        try:
            order_val = int(order)
        except ValueError:
            order_val = 0

        if errors:
            return render(request, 'admin_dashboard/billing/plan_form.html', {
                'form_data': data,
                'errors': errors,
            })

        # Generate unique slug
        base_slug = slugify(name)
        slug = base_slug
        counter = 2
        while InstitutePlan.objects.filter(slug=slug).exists():
            slug = f'{base_slug}-{counter}'
            counter += 1

        plan = InstitutePlan.objects.create(
            name=name,
            slug=slug,
            price=price_val,
            class_limit=class_limit_val,
            student_limit=student_limit_val,
            invoice_limit_yearly=invoice_limit_val,
            extra_invoice_rate=extra_rate_val,
            trial_days=trial_days_val,
            order=order_val,
        )

        log_event(
            user=request.user, school=None, category='data_change',
            action='billing_plan_created',
            detail={'plan_id': plan.id, 'plan_name': plan.name, 'plan_slug': slug, 'price': str(price_val)},
            request=request,
        )
        messages.success(request, f'Plan "{plan.name}" created.')
        return redirect('billing_admin_plan_list')


class PlanEditView(SuperuserRequiredMixin, View):
    def get(self, request, pk):
        plan = get_object_or_404(InstitutePlan, pk=pk)
        return render(request, 'admin_dashboard/billing/plan_form.html', {
            'plan': plan,
            'form_data': {
                'name': plan.name,
                'price': str(plan.price),
                'class_limit': str(plan.class_limit),
                'student_limit': str(plan.student_limit),
                'invoice_limit_yearly': str(plan.invoice_limit_yearly),
                'extra_invoice_rate': str(plan.extra_invoice_rate),
                'trial_days': str(plan.trial_days),
                'order': str(plan.order),
            },
        })

    def post(self, request, pk):
        plan = get_object_or_404(InstitutePlan, pk=pk)
        data = request.POST
        errors = {}

        name = data.get('name', '').strip()
        price = data.get('price', '').strip()
        class_limit = data.get('class_limit', '0').strip()
        student_limit = data.get('student_limit', '0').strip()
        invoice_limit_yearly = data.get('invoice_limit_yearly', '0').strip()
        extra_invoice_rate = data.get('extra_invoice_rate', '0').strip()
        trial_days = data.get('trial_days', '14').strip()
        order = data.get('order', '0').strip()

        if not name:
            errors['name'] = 'Name is required.'
        try:
            price_val = Decimal(price)
            if price_val <= 0:
                errors['price'] = 'Price must be greater than 0.'
        except (InvalidOperation, ValueError):
            errors['price'] = 'Enter a valid price.'

        try:
            class_limit_val = int(class_limit)
            if class_limit_val < 0:
                errors['class_limit'] = 'Must be 0 or greater.'
        except ValueError:
            errors['class_limit'] = 'Enter a valid number.'

        try:
            student_limit_val = int(student_limit)
            if student_limit_val < 0:
                errors['student_limit'] = 'Must be 0 or greater.'
        except ValueError:
            errors['student_limit'] = 'Enter a valid number.'

        try:
            invoice_limit_val = int(invoice_limit_yearly)
            if invoice_limit_val < 0:
                errors['invoice_limit_yearly'] = 'Must be 0 or greater.'
        except ValueError:
            errors['invoice_limit_yearly'] = 'Enter a valid number.'

        try:
            extra_rate_val = Decimal(extra_invoice_rate)
            if extra_rate_val < 0:
                errors['extra_invoice_rate'] = 'Must be 0 or greater.'
        except (InvalidOperation, ValueError):
            errors['extra_invoice_rate'] = 'Enter a valid rate.'

        try:
            trial_days_val = int(trial_days)
        except ValueError:
            trial_days_val = 14

        try:
            order_val = int(order)
        except ValueError:
            order_val = 0

        if errors:
            return render(request, 'admin_dashboard/billing/plan_form.html', {
                'plan': plan,
                'form_data': data,
                'errors': errors,
            })

        plan.name = name
        plan.price = price_val
        plan.class_limit = class_limit_val
        plan.student_limit = student_limit_val
        plan.invoice_limit_yearly = invoice_limit_val
        plan.extra_invoice_rate = extra_rate_val
        plan.trial_days = trial_days_val
        plan.order = order_val
        plan.save()

        log_event(
            user=request.user, school=None, category='data_change',
            action='billing_plan_edited',
            detail={'plan_id': plan.id, 'plan_name': plan.name, 'price': str(price_val)},
            request=request,
        )
        messages.success(request, f'Plan "{plan.name}" updated.')
        return redirect('billing_admin_plan_list')


class PlanToggleActiveView(SuperuserRequiredMixin, View):
    def post(self, request, pk):
        plan = get_object_or_404(InstitutePlan, pk=pk)

        if plan.is_active:
            # Block deactivation if active subscriptions exist
            active_count = SchoolSubscription.objects.filter(
                plan=plan, status__in=['active', 'trialing'],
            ).count()
            if active_count > 0:
                messages.error(
                    request,
                    f'Cannot deactivate "{plan.name}" — {active_count} active subscription(s) use this plan.',
                )
                return redirect('billing_admin_plan_list')
            plan.is_active = False
            messages.success(request, f'Plan "{plan.name}" deactivated.')
        else:
            plan.is_active = True
            messages.success(request, f'Plan "{plan.name}" activated.')

        plan.save(update_fields=['is_active'])
        log_event(
            user=request.user, school=None, category='data_change',
            action='billing_plan_toggled',
            detail={'plan_id': plan.id, 'plan_name': plan.name, 'is_active': plan.is_active},
            request=request,
        )
        return redirect('billing_admin_plan_list')


class PlanSyncStripeView(SuperuserRequiredMixin, View):
    def post(self, request, pk):
        plan = get_object_or_404(InstitutePlan, pk=pk)
        try:
            from .stripe_service import sync_plan_to_stripe
            price_id = sync_plan_to_stripe(plan)
            log_event(
                user=request.user, school=None, category='data_change',
                action='billing_plan_stripe_synced',
                detail={'plan_id': plan.id, 'plan_name': plan.name, 'stripe_price_id': price_id},
                request=request,
            )
            messages.success(request, f'Plan "{plan.name}" synced to Stripe. Price ID: {price_id}')
        except Exception as e:
            messages.error(request, f'Stripe sync failed: {e}')
        return redirect('billing_admin_plan_list')


# ---------------------------------------------------------------------------
# Discount Codes
# ---------------------------------------------------------------------------

class DiscountCodeListView(SuperuserRequiredMixin, View):
    def get(self, request):
        codes = InstituteDiscountCode.objects.all()
        return render(request, 'admin_dashboard/billing/discount_code_list.html', {
            'codes': codes,
        })


class DiscountCodeCreateView(SuperuserRequiredMixin, View):
    def get(self, request):
        return render(request, 'admin_dashboard/billing/discount_code_form.html', {
            'form_data': {},
        })

    def post(self, request):
        data = request.POST
        errors = {}

        code = data.get('code', '').strip().upper().replace(' ', '')
        description = data.get('description', '').strip()
        discount_percent = data.get('discount_percent', '100').strip()
        max_uses = data.get('max_uses', '1').strip()
        override_class_limit = data.get('override_class_limit', '').strip()
        override_student_limit = data.get('override_student_limit', '').strip()
        expires_at = data.get('expires_at', '').strip()

        if not code:
            errors['code'] = 'Code is required.'
        elif InstituteDiscountCode.objects.filter(code=code).exists():
            errors['code'] = 'This code already exists.'

        try:
            percent_val = int(discount_percent)
            if percent_val < 0 or percent_val > 100:
                errors['discount_percent'] = 'Must be 0-100.'
        except ValueError:
            errors['discount_percent'] = 'Enter a valid number.'

        try:
            max_uses_val = int(max_uses) if max_uses else None
            if max_uses_val is not None and max_uses_val < 1:
                errors['max_uses'] = 'Must be at least 1.'
        except ValueError:
            errors['max_uses'] = 'Enter a valid number.'

        override_class_val = None
        if override_class_limit:
            try:
                override_class_val = int(override_class_limit)
                if override_class_val < 0:
                    errors['override_class_limit'] = 'Must be 0 or greater.'
            except ValueError:
                errors['override_class_limit'] = 'Enter a valid number.'

        override_student_val = None
        if override_student_limit:
            try:
                override_student_val = int(override_student_limit)
                if override_student_val < 0:
                    errors['override_student_limit'] = 'Must be 0 or greater.'
            except ValueError:
                errors['override_student_limit'] = 'Enter a valid number.'

        expires_at_val = None
        if expires_at:
            try:
                from django.utils.dateparse import parse_datetime
                expires_at_val = parse_datetime(expires_at)
                if expires_at_val is None:
                    # Try date-only
                    from django.utils.dateparse import parse_date
                    d = parse_date(expires_at)
                    if d:
                        from datetime import datetime, time
                        expires_at_val = timezone.make_aware(
                            datetime.combine(d, time.max)
                        )
            except (ValueError, TypeError):
                pass

        if errors:
            return render(request, 'admin_dashboard/billing/discount_code_form.html', {
                'form_data': data,
                'errors': errors,
            })

        dc = InstituteDiscountCode.objects.create(
            code=code,
            description=description,
            discount_percent=percent_val,
            max_uses=max_uses_val,
            override_class_limit=override_class_val,
            override_student_limit=override_student_val,
            expires_at=expires_at_val,
        )

        # Auto-sync to Stripe for non-100% discounts
        if not dc.is_fully_free:
            try:
                from .stripe_service import sync_discount_to_stripe, _stripe_configured
                if _stripe_configured():
                    sync_discount_to_stripe(dc)
            except Exception as e:
                logger.warning('Stripe discount sync failed: %s', e)

        log_event(
            user=request.user, school=None, category='data_change',
            action='discount_code_created',
            detail={'discount_id': dc.id, 'code': dc.code, 'discount_percent': percent_val},
            request=request,
        )
        messages.success(request, f'Discount code "{dc.code}" created.')
        return redirect('billing_admin_discount_list')


class DiscountCodeEditView(SuperuserRequiredMixin, View):
    def get(self, request, pk):
        dc = get_object_or_404(InstituteDiscountCode, pk=pk)
        return render(request, 'admin_dashboard/billing/discount_code_form.html', {
            'discount': dc,
            'form_data': {
                'code': dc.code,
                'description': dc.description,
                'discount_percent': str(dc.discount_percent),
                'max_uses': str(dc.max_uses) if dc.max_uses else '',
                'override_class_limit': str(dc.override_class_limit) if dc.override_class_limit is not None else '',
                'override_student_limit': str(dc.override_student_limit) if dc.override_student_limit is not None else '',
                'expires_at': dc.expires_at.strftime('%Y-%m-%dT%H:%M') if dc.expires_at else '',
                'duration': dc.duration or 'forever',
                'duration_in_months': str(dc.duration_in_months) if dc.duration_in_months else '',
            },
            'plans': InstitutePlan.objects.filter(is_active=True),
            'modules': ModuleProduct.objects.filter(is_active=True),
            'selected_plans': list(dc.applicable_plans.values_list('id', flat=True)),
            'selected_modules': list(dc.applicable_modules.values_list('id', flat=True)),
        })

    def post(self, request, pk):
        dc = get_object_or_404(InstituteDiscountCode, pk=pk)
        data = request.POST
        errors = {}

        # Code and percent are locked after creation
        description = data.get('description', '').strip()
        max_uses = data.get('max_uses', '1').strip()
        override_class_limit = data.get('override_class_limit', '').strip()
        override_student_limit = data.get('override_student_limit', '').strip()
        expires_at = data.get('expires_at', '').strip()
        duration = data.get('duration', dc.duration or 'forever').strip()
        duration_in_months = data.get('duration_in_months', '').strip()

        try:
            max_uses_val = int(max_uses) if max_uses else None
            if max_uses_val is not None and max_uses_val < 1:
                errors['max_uses'] = 'Must be at least 1.'
        except ValueError:
            errors['max_uses'] = 'Enter a valid number.'

        override_class_val = None
        if override_class_limit:
            try:
                override_class_val = int(override_class_limit)
                if override_class_val < 0:
                    errors['override_class_limit'] = 'Must be 0 or greater.'
            except ValueError:
                errors['override_class_limit'] = 'Enter a valid number.'

        override_student_val = None
        if override_student_limit:
            try:
                override_student_val = int(override_student_limit)
                if override_student_val < 0:
                    errors['override_student_limit'] = 'Must be 0 or greater.'
            except ValueError:
                errors['override_student_limit'] = 'Enter a valid number.'

        if duration not in ('forever', 'once', 'repeating'):
            duration = 'forever'

        duration_in_months_val = None
        if duration == 'repeating':
            if not duration_in_months:
                errors['duration_in_months'] = 'Number of months is required.'
            else:
                try:
                    duration_in_months_val = int(duration_in_months)
                    if duration_in_months_val < 1:
                        errors['duration_in_months'] = 'Must be at least 1.'
                except ValueError:
                    errors['duration_in_months'] = 'Enter a valid number.'

        # Warn if duration changed on already-synced coupon
        if dc.stripe_coupon_id and duration != (dc.duration or 'forever'):
            errors['duration'] = 'Duration cannot be changed after Stripe sync. Create a new code instead.'

        expires_at_val = None
        if expires_at:
            try:
                from django.utils.dateparse import parse_datetime
                expires_at_val = parse_datetime(expires_at)
                if expires_at_val is None:
                    from django.utils.dateparse import parse_date
                    d = parse_date(expires_at)
                    if d:
                        from datetime import datetime, time
                        expires_at_val = timezone.make_aware(
                            datetime.combine(d, time.max)
                        )
            except (ValueError, TypeError):
                pass

        if errors:
            return render(request, 'admin_dashboard/billing/discount_code_form.html', {
                'discount': dc,
                'form_data': data,
                'errors': errors,
                'plans': InstitutePlan.objects.filter(is_active=True),
                'modules': ModuleProduct.objects.filter(is_active=True),
                'selected_plans': list(dc.applicable_plans.values_list('id', flat=True)),
                'selected_modules': list(dc.applicable_modules.values_list('id', flat=True)),
            })

        dc.description = description
        dc.max_uses = max_uses_val
        dc.override_class_limit = override_class_val
        dc.override_student_limit = override_student_val
        dc.duration = duration
        dc.duration_in_months = duration_in_months_val
        dc.expires_at = expires_at_val
        dc.save()

        dc.applicable_plans.set(data.getlist('applicable_plans'))
        dc.applicable_modules.set(data.getlist('applicable_modules'))

        log_event(
            user=request.user, school=None, category='data_change',
            action='discount_code_edited',
            detail={'discount_id': dc.id, 'code': dc.code},
            request=request,
        )
        messages.success(request, f'Discount code "{dc.code}" updated.')
        return redirect('billing_admin_coupon_list')


class DiscountCodeToggleActiveView(SuperuserRequiredMixin, View):
    def post(self, request, pk):
        dc = get_object_or_404(InstituteDiscountCode, pk=pk)
        dc.is_active = not dc.is_active
        dc.save(update_fields=['is_active'])
        state = 'activated' if dc.is_active else 'deactivated'
        log_event(
            user=request.user, school=None, category='data_change',
            action='discount_code_toggled',
            detail={'discount_id': dc.id, 'code': dc.code, 'is_active': dc.is_active},
            request=request,
        )
        messages.success(request, f'Discount code "{dc.code}" {state}.')
        return redirect('billing_admin_discount_list')


# ---------------------------------------------------------------------------
# Module Products
# ---------------------------------------------------------------------------

class ModuleProductListView(SuperuserRequiredMixin, View):
    def get(self, request):
        modules = ModuleProduct.objects.all()
        return render(request, 'admin_dashboard/billing/module_list.html', {
            'modules': modules,
        })


class ModuleProductEditView(SuperuserRequiredMixin, View):
    def get(self, request, pk):
        module = get_object_or_404(ModuleProduct, pk=pk)
        return render(request, 'admin_dashboard/billing/module_form.html', {
            'module': module,
            'form_data': {
                'name': module.name,
                'price': str(module.price),
            },
        })

    def post(self, request, pk):
        module = get_object_or_404(ModuleProduct, pk=pk)
        data = request.POST
        errors = {}

        name = data.get('name', '').strip()
        price = data.get('price', '').strip()

        if not name:
            errors['name'] = 'Name is required.'

        try:
            price_val = Decimal(price)
            if price_val < 0:
                errors['price'] = 'Price must be 0 or greater.'
        except (InvalidOperation, ValueError):
            errors['price'] = 'Enter a valid price.'

        if errors:
            return render(request, 'admin_dashboard/billing/module_form.html', {
                'module': module,
                'form_data': data,
                'errors': errors,
            })

        module.name = name
        module.price = price_val
        module.save()

        log_event(
            user=request.user, school=None, category='data_change',
            action='module_product_edited',
            detail={'module_id': module.id, 'module_name': module.name, 'price': str(price_val)},
            request=request,
        )
        messages.success(request, f'Module "{module.name}" updated.')
        return redirect('billing_admin_module_list')


class ModuleProductToggleActiveView(SuperuserRequiredMixin, View):
    def post(self, request, pk):
        module = get_object_or_404(ModuleProduct, pk=pk)
        module.is_active = not module.is_active
        module.save(update_fields=['is_active'])
        state = 'activated' if module.is_active else 'deactivated'
        log_event(
            user=request.user, school=None, category='data_change',
            action='module_product_toggled',
            detail={'module_id': module.id, 'module_name': module.name, 'is_active': module.is_active},
            request=request,
        )
        messages.success(request, f'Module "{module.name}" {state}.')
        return redirect('billing_admin_module_list')


class ModuleProductSyncStripeView(SuperuserRequiredMixin, View):
    def post(self, request, pk):
        module = get_object_or_404(ModuleProduct, pk=pk)
        try:
            from .stripe_service import sync_module_to_stripe
            price_id = sync_module_to_stripe(module)
            log_event(
                user=request.user, school=None, category='data_change',
                action='module_product_stripe_synced',
                detail={'module_id': module.id, 'module_name': module.name, 'stripe_price_id': price_id},
                request=request,
            )
            messages.success(request, f'Module "{module.name}" synced to Stripe. Price ID: {price_id}')
        except Exception as e:
            messages.error(request, f'Stripe sync failed: {e}')
        return redirect('billing_admin_module_list')


# ---------------------------------------------------------------------------
# Subscriptions
# ---------------------------------------------------------------------------

class SubscriptionListView(SuperuserRequiredMixin, View):
    def get(self, request):
        subs = SchoolSubscription.objects.select_related('school', 'plan', 'discount_code').all()

        # Gather usage data
        from classroom.models import ClassRoom, SchoolStudent
        sub_data = []
        for sub in subs:
            classes_count = ClassRoom.objects.filter(school=sub.school, is_active=True).count()
            students_count = SchoolStudent.objects.filter(school=sub.school, is_active=True).count()
            sub_data.append({
                'sub': sub,
                'classes_count': classes_count,
                'students_count': students_count,
            })

        return render(request, 'admin_dashboard/billing/subscription_list.html', {
            'sub_data': sub_data,
        })


class SubscriptionDetailView(SuperuserRequiredMixin, View):
    def get(self, request, pk):
        sub = get_object_or_404(
            SchoolSubscription.objects.select_related('school', 'plan', 'discount_code'),
            pk=pk,
        )

        from classroom.models import ClassRoom, SchoolStudent
        classes_count = ClassRoom.objects.filter(school=sub.school, is_active=True).count()
        students_count = SchoolStudent.objects.filter(school=sub.school, is_active=True).count()
        active_modules = sub.modules.filter(is_active=True)
        plans = InstitutePlan.objects.filter(is_active=True)

        class_limit = sub.plan.class_limit if sub.plan else 0
        student_limit = sub.plan.student_limit if sub.plan else 0
        invoice_limit = sub.plan.invoice_limit_yearly if sub.plan else 0

        return render(request, 'admin_dashboard/billing/subscription_detail.html', {
            'sub': sub,
            'classes_count': classes_count,
            'students_count': students_count,
            'class_limit': class_limit,
            'student_limit': student_limit,
            'invoice_limit': invoice_limit,
            'active_modules': active_modules,
            'plans': plans,
        })


class SubscriptionOverrideView(SuperuserRequiredMixin, View):
    def post(self, request, pk):
        sub = get_object_or_404(SchoolSubscription, pk=pk)
        data = request.POST
        action = data.get('action', '')

        if action == 'change_plan':
            plan_id = data.get('plan_id', '')
            if plan_id:
                plan = InstitutePlan.objects.filter(pk=plan_id).first()
                if plan:
                    sub.plan = plan
                    sub.save(update_fields=['plan', 'updated_at'])
                    log_event(
                        user=request.user, school=sub.school, category='data_change',
                        action='subscription_plan_overridden',
                        detail={'subscription_id': sub.id, 'plan_id': plan.id, 'plan_name': plan.name, 'school_name': str(sub.school)},
                        request=request,
                    )
                    messages.success(request, f'Plan changed to "{plan.name}".')

        elif action == 'extend_trial':
            days = data.get('days', '14')
            try:
                days_val = int(days)
                sub.trial_end = timezone.now() + timezone.timedelta(days=days_val)
                sub.status = SchoolSubscription.STATUS_TRIALING
                sub.save(update_fields=['trial_end', 'status', 'updated_at'])
                log_event(
                    user=request.user, school=sub.school, category='data_change',
                    action='subscription_trial_extended',
                    detail={'subscription_id': sub.id, 'days': days_val, 'school_name': str(sub.school)},
                    request=request,
                )
                messages.success(request, f'Trial extended by {days_val} days.')
            except (ValueError, TypeError):
                messages.error(request, 'Invalid number of days.')

        elif action == 'reset_invoices':
            sub.invoices_used_this_year = 0
            sub.save(update_fields=['invoices_used_this_year', 'updated_at'])
            log_event(
                user=request.user, school=sub.school, category='data_change',
                action='subscription_invoices_reset',
                detail={'subscription_id': sub.id, 'school_name': str(sub.school)},
                request=request,
            )
            messages.success(request, 'Invoice counter reset to 0.')

        elif action == 'change_status':
            new_status = data.get('status', '')
            valid = dict(SchoolSubscription.STATUS_CHOICES)
            if new_status in valid:
                sub.status = new_status
                sub.save(update_fields=['status', 'updated_at'])
                log_event(
                    user=request.user, school=sub.school, category='data_change',
                    action='subscription_status_changed',
                    detail={'subscription_id': sub.id, 'new_status': new_status, 'school_name': str(sub.school)},
                    request=request,
                )
                messages.success(request, f'Status changed to "{valid[new_status]}".')
            else:
                messages.error(request, 'Invalid status.')

        return redirect('billing_admin_subscription_detail', pk=sub.pk)


# ---------------------------------------------------------------------------
# Promo Codes
# ---------------------------------------------------------------------------

class PromoCodeListView(SuperuserRequiredMixin, View):
    def get(self, request):
        promos = PromoCode.objects.all()
        return render(request, 'admin_dashboard/billing/promo_code_list.html', {
            'promos': promos,
        })


class PromoCodeCreateView(SuperuserRequiredMixin, View):
    def get(self, request):
        return render(request, 'admin_dashboard/billing/promo_code_form.html', {
            'form_data': {},
        })

    def post(self, request):
        data = request.POST
        errors = {}

        code = data.get('code', '').strip().upper().replace(' ', '')
        description = data.get('description', '').strip()
        discount_percent = data.get('discount_percent', '100').strip()
        grant_days = data.get('grant_days', '').strip()
        class_limit = data.get('class_limit', '0').strip()
        max_uses = data.get('max_uses', '').strip()
        expires_at = data.get('expires_at', '').strip()

        if not code:
            errors['code'] = 'Code is required.'
        elif PromoCode.objects.filter(code=code).exists():
            errors['code'] = 'This code already exists.'

        try:
            discount_percent_val = int(discount_percent)
            if discount_percent_val < 0 or discount_percent_val > 100:
                errors['discount_percent'] = 'Must be 0-100.'
        except ValueError:
            errors['discount_percent'] = 'Enter a valid number.'
            discount_percent_val = 100

        grant_days_val = None
        if grant_days:
            try:
                grant_days_val = int(grant_days)
                if grant_days_val < 1:
                    errors['grant_days'] = 'Must be at least 1.'
            except ValueError:
                errors['grant_days'] = 'Enter a valid number.'

        try:
            class_limit_val = int(class_limit)
            if class_limit_val < 0:
                errors['class_limit'] = 'Must be 0 or greater.'
        except ValueError:
            errors['class_limit'] = 'Enter a valid number.'

        max_uses_val = None
        if max_uses:
            try:
                max_uses_val = int(max_uses)
                if max_uses_val < 1:
                    errors['max_uses'] = 'Must be at least 1.'
            except ValueError:
                errors['max_uses'] = 'Enter a valid number.'

        expires_at_val = None
        if expires_at:
            try:
                from django.utils.dateparse import parse_datetime, parse_date
                expires_at_val = parse_datetime(expires_at)
                if expires_at_val is None:
                    d = parse_date(expires_at)
                    if d:
                        from datetime import datetime, time
                        expires_at_val = timezone.make_aware(
                            datetime.combine(d, time.max)
                        )
            except (ValueError, TypeError):
                pass

        if errors:
            return render(request, 'admin_dashboard/billing/promo_code_form.html', {
                'form_data': data,
                'errors': errors,
            })

        promo = PromoCode.objects.create(
            code=code,
            description=description,
            discount_percent=discount_percent_val,
            grant_days=grant_days_val,
            class_limit=class_limit_val,
            max_uses=max_uses_val,
            expires_at=expires_at_val,
        )

        log_event(
            user=request.user, school=None, category='data_change',
            action='promo_code_created',
            detail={'promo_id': promo.id, 'code': code, 'class_limit': class_limit_val},
            request=request,
        )
        messages.success(request, f'Promo code "{code}" created.')
        return redirect('billing_admin_promo_list')


class PromoCodeEditView(SuperuserRequiredMixin, View):
    def get(self, request, pk):
        promo = get_object_or_404(PromoCode, pk=pk)
        return render(request, 'admin_dashboard/billing/promo_code_form.html', {
            'promo': promo,
            'form_data': {
                'code': promo.code,
                'description': promo.description,
                'discount_percent': str(promo.discount_percent),
                'grant_days': str(promo.grant_days) if promo.grant_days else '',
                'class_limit': str(promo.class_limit),
                'max_uses': str(promo.max_uses) if promo.max_uses else '',
                'expires_at': promo.expires_at.strftime('%Y-%m-%dT%H:%M') if promo.expires_at else '',
                'duration': promo.duration or 'forever',
                'duration_in_months': str(promo.duration_in_months) if promo.duration_in_months else '',
            },
            'packages': Package.objects.filter(is_active=True),
            'selected_packages': list(promo.applicable_packages.values_list('id', flat=True)),
        })

    def post(self, request, pk):
        promo = get_object_or_404(PromoCode, pk=pk)
        data = request.POST
        errors = {}

        description = data.get('description', '').strip()
        discount_percent = data.get('discount_percent', '100').strip()
        grant_days = data.get('grant_days', '').strip()
        class_limit = data.get('class_limit', '0').strip()
        max_uses = data.get('max_uses', '').strip()
        expires_at = data.get('expires_at', '').strip()
        duration = data.get('duration', promo.duration or 'forever').strip()
        duration_in_months = data.get('duration_in_months', '').strip()

        try:
            discount_percent_val = int(discount_percent)
            if discount_percent_val < 0 or discount_percent_val > 100:
                errors['discount_percent'] = 'Must be 0-100.'
        except ValueError:
            errors['discount_percent'] = 'Enter a valid number.'
            discount_percent_val = promo.discount_percent

        grant_days_val = None
        if grant_days:
            try:
                grant_days_val = int(grant_days)
                if grant_days_val < 1:
                    errors['grant_days'] = 'Must be at least 1.'
            except ValueError:
                errors['grant_days'] = 'Enter a valid number.'

        try:
            class_limit_val = int(class_limit)
            if class_limit_val < 0:
                errors['class_limit'] = 'Must be 0 or greater.'
        except ValueError:
            errors['class_limit'] = 'Enter a valid number.'

        max_uses_val = None
        if max_uses:
            try:
                max_uses_val = int(max_uses)
                if max_uses_val < 1:
                    errors['max_uses'] = 'Must be at least 1.'
            except ValueError:
                errors['max_uses'] = 'Enter a valid number.'

        if duration not in ('forever', 'once', 'repeating'):
            duration = 'forever'

        duration_in_months_val = None
        if duration == 'repeating':
            if not duration_in_months:
                errors['duration_in_months'] = 'Number of months is required.'
            else:
                try:
                    duration_in_months_val = int(duration_in_months)
                    if duration_in_months_val < 1:
                        errors['duration_in_months'] = 'Must be at least 1.'
                except ValueError:
                    errors['duration_in_months'] = 'Enter a valid number.'

        expires_at_val = None
        if expires_at:
            try:
                from django.utils.dateparse import parse_datetime, parse_date
                expires_at_val = parse_datetime(expires_at)
                if expires_at_val is None:
                    d = parse_date(expires_at)
                    if d:
                        from datetime import datetime, time
                        expires_at_val = timezone.make_aware(
                            datetime.combine(d, time.max)
                        )
            except (ValueError, TypeError):
                pass

        if errors:
            return render(request, 'admin_dashboard/billing/promo_code_form.html', {
                'promo': promo,
                'form_data': data,
                'errors': errors,
                'packages': Package.objects.filter(is_active=True),
                'selected_packages': list(promo.applicable_packages.values_list('id', flat=True)),
            })

        promo.description = description
        promo.discount_percent = discount_percent_val
        promo.grant_days = grant_days_val
        promo.class_limit = class_limit_val
        promo.max_uses = max_uses_val
        promo.duration = duration
        promo.duration_in_months = duration_in_months_val
        promo.expires_at = expires_at_val
        promo.save()

        promo.applicable_packages.set(data.getlist('applicable_packages'))

        log_event(
            user=request.user, school=None, category='data_change',
            action='promo_code_edited',
            detail={'promo_id': promo.id, 'code': promo.code},
            request=request,
        )
        messages.success(request, f'Promo code "{promo.code}" updated.')
        return redirect('billing_admin_coupon_list')


class PromoCodeToggleActiveView(SuperuserRequiredMixin, View):
    def post(self, request, pk):
        promo = get_object_or_404(PromoCode, pk=pk)
        promo.is_active = not promo.is_active
        promo.save(update_fields=['is_active'])
        state = 'activated' if promo.is_active else 'deactivated'
        log_event(
            user=request.user, school=None, category='data_change',
            action='promo_code_toggled',
            detail={'promo_id': promo.id, 'code': promo.code, 'is_active': promo.is_active},
            request=request,
        )
        messages.success(request, f'Promo code "{promo.code}" {state}.')
        return redirect('billing_admin_promo_list')


class StudentDiscountCodeEditView(SuperuserRequiredMixin, View):
    """Edit a Student Billing DiscountCode (code and discount % locked after creation)."""

    def get(self, request, pk):
        dc = get_object_or_404(DiscountCode, pk=pk)
        return render(request, 'admin_dashboard/billing/student_discount_form.html', {
            'discount': dc,
            'form_data': {
                'max_uses': str(dc.max_uses) if dc.max_uses else '',
                'grant_days': str(dc.grant_days) if dc.grant_days else '',
                'expires_at': dc.expires_at.strftime('%Y-%m-%dT%H:%M') if dc.expires_at else '',
                'duration': dc.duration or 'forever',
                'duration_in_months': str(dc.duration_in_months) if dc.duration_in_months else '',
            },
            'packages': Package.objects.filter(is_active=True),
            'selected_packages': list(dc.applicable_packages.values_list('id', flat=True)),
        })

    def post(self, request, pk):
        dc = get_object_or_404(DiscountCode, pk=pk)
        data = request.POST
        errors = {}

        max_uses = data.get('max_uses', '').strip()
        grant_days = data.get('grant_days', '').strip()
        expires_at = data.get('expires_at', '').strip()
        duration = data.get('duration', dc.duration or 'forever').strip()
        duration_in_months = data.get('duration_in_months', '').strip()

        max_uses_val = None
        if max_uses:
            try:
                max_uses_val = int(max_uses)
                if max_uses_val < 1:
                    errors['max_uses'] = 'Must be at least 1.'
            except ValueError:
                errors['max_uses'] = 'Enter a valid number.'

        grant_days_val = None
        if grant_days:
            try:
                grant_days_val = int(grant_days)
                if grant_days_val < 1:
                    errors['grant_days'] = 'Must be at least 1.'
            except ValueError:
                errors['grant_days'] = 'Enter a valid number.'

        if duration not in ('forever', 'once', 'repeating'):
            duration = 'forever'

        duration_in_months_val = None
        if duration == 'repeating':
            if not duration_in_months:
                errors['duration_in_months'] = 'Number of months is required.'
            else:
                try:
                    duration_in_months_val = int(duration_in_months)
                    if duration_in_months_val < 1:
                        errors['duration_in_months'] = 'Must be at least 1.'
                except ValueError:
                    errors['duration_in_months'] = 'Enter a valid number.'

        if dc.stripe_coupon_id and duration != (dc.duration or 'forever'):
            errors['duration'] = 'Duration cannot be changed after Stripe sync. Create a new code instead.'

        expires_at_val = None
        if expires_at:
            try:
                from django.utils.dateparse import parse_datetime, parse_date
                expires_at_val = parse_datetime(expires_at)
                if expires_at_val is None:
                    d = parse_date(expires_at)
                    if d:
                        from datetime import datetime, time
                        expires_at_val = timezone.make_aware(
                            datetime.combine(d, time.max)
                        )
            except (ValueError, TypeError):
                pass

        if errors:
            return render(request, 'admin_dashboard/billing/student_discount_form.html', {
                'discount': dc,
                'form_data': data,
                'errors': errors,
                'packages': Package.objects.filter(is_active=True),
                'selected_packages': list(dc.applicable_packages.values_list('id', flat=True)),
            })

        dc.max_uses = max_uses_val
        dc.grant_days = grant_days_val
        dc.duration = duration
        dc.duration_in_months = duration_in_months_val
        dc.expires_at = expires_at_val
        dc.save()

        dc.applicable_packages.set(data.getlist('applicable_packages'))

        log_event(
            user=request.user, school=None, category='data_change',
            action='student_discount_code_edited',
            detail={'discount_id': dc.id, 'code': dc.code},
            request=request,
        )
        messages.success(request, f'Discount code "{dc.code}" updated.')
        return redirect('billing_admin_coupon_list')


class StudentDiscountCodeToggleActiveView(SuperuserRequiredMixin, View):
    def post(self, request, pk):
        dc = get_object_or_404(DiscountCode, pk=pk)
        dc.is_active = not dc.is_active
        dc.save(update_fields=['is_active'])
        state = 'activated' if dc.is_active else 'deactivated'
        log_event(
            user=request.user, school=None, category='data_change',
            action='student_discount_code_toggled',
            detail={'discount_id': dc.id, 'code': dc.code, 'is_active': dc.is_active},
            request=request,
        )
        messages.success(request, f'Discount code "{dc.code}" {state}.')
        return redirect('billing_admin_coupon_list')


# ---------------------------------------------------------------------------
# Unified Coupon Codes
# ---------------------------------------------------------------------------

def _duration_display(obj):
    d = getattr(obj, 'duration', 'forever') or 'forever'
    if d == 'repeating':
        months = getattr(obj, 'duration_in_months', None)
        return f'{months} months' if months else 'Repeating'
    return d.capitalize()


class CouponCodeListView(SuperuserRequiredMixin, View):
    def get(self, request):
        from django.urls import reverse

        codes = []

        for dc in InstituteDiscountCode.objects.all():
            plans = list(dc.applicable_plans.values_list('name', flat=True))
            modules = list(dc.applicable_modules.values_list('name', flat=True))
            products = plans + modules
            codes.append({
                'id': dc.pk, 'type': 'institute', 'type_label': 'Institute',
                'code': dc.code, 'description': dc.description,
                'discount_percent': dc.discount_percent,
                'duration_display': _duration_display(dc),
                'max_uses': dc.max_uses, 'uses': dc.uses,
                'is_active': dc.is_active, 'expires_at': dc.expires_at,
                'stripe_synced': bool(dc.stripe_coupon_id) if not dc.is_fully_free else None,
                'products': ', '.join(products) if products else 'All',
                'created_at': dc.created_at,
                'edit_url': reverse('billing_admin_discount_edit', args=[dc.pk]),
                'toggle_url': reverse('billing_admin_discount_toggle', args=[dc.pk]),
            })

        for promo in PromoCode.objects.all():
            pkgs = list(promo.applicable_packages.values_list('name', flat=True))
            codes.append({
                'id': promo.pk, 'type': 'student_promo', 'type_label': 'Student Promo',
                'code': promo.code, 'description': promo.description,
                'discount_percent': promo.discount_percent,
                'duration_display': _duration_display(promo),
                'max_uses': promo.max_uses, 'uses': promo.uses,
                'is_active': promo.is_active, 'expires_at': promo.expires_at,
                'stripe_synced': None,
                'products': ', '.join(pkgs) if pkgs else 'All',
                'created_at': promo.created_at,
                'edit_url': reverse('billing_admin_promo_edit', args=[promo.pk]),
                'toggle_url': reverse('billing_admin_promo_toggle', args=[promo.pk]),
            })

        for dc in DiscountCode.objects.all():
            pkgs = list(dc.applicable_packages.values_list('name', flat=True))
            codes.append({
                'id': dc.pk, 'type': 'student_discount', 'type_label': 'Student Billing',
                'code': dc.code, 'description': '',
                'discount_percent': dc.discount_percent,
                'duration_display': _duration_display(dc),
                'max_uses': dc.max_uses, 'uses': dc.uses,
                'is_active': dc.is_active, 'expires_at': dc.expires_at,
                'stripe_synced': bool(dc.stripe_coupon_id) if not dc.is_fully_free else None,
                'products': ', '.join(pkgs) if pkgs else 'All',
                'created_at': dc.created_at,
                'edit_url': reverse('billing_admin_student_discount_edit', args=[dc.pk]),
                'toggle_url': reverse('billing_admin_student_discount_toggle', args=[dc.pk]),
            })

        codes.sort(key=lambda c: c['created_at'], reverse=True)

        return render(request, 'admin_dashboard/billing/coupon_code_list.html', {
            'codes': codes,
        })


class CouponCodeCreateView(SuperuserRequiredMixin, View):
    def get(self, request):
        return render(request, 'admin_dashboard/billing/coupon_code_form.html', {
            'form_data': {},
            'packages': Package.objects.filter(is_active=True),
            'plans': InstitutePlan.objects.filter(is_active=True),
            'modules': ModuleProduct.objects.filter(is_active=True),
        })

    def post(self, request):
        data = request.POST
        errors = {}

        target_type = data.get('target_type', 'institute')
        code = data.get('code', '').strip().upper().replace(' ', '')
        description = data.get('description', '').strip()
        discount_percent = data.get('discount_percent', '100').strip()
        max_uses = data.get('max_uses', '').strip()
        expires_at = data.get('expires_at', '').strip()
        duration = data.get('duration', 'forever').strip()
        duration_in_months = data.get('duration_in_months', '').strip()

        # Validate code
        if not code:
            errors['code'] = 'Code is required.'
        else:
            # Check uniqueness across all 3 models
            if (InstituteDiscountCode.objects.filter(code=code).exists()
                    or PromoCode.objects.filter(code=code).exists()
                    or DiscountCode.objects.filter(code=code).exists()):
                errors['code'] = 'This code already exists.'

        # Validate discount percent
        try:
            percent_val = int(discount_percent)
            if percent_val < 0 or percent_val > 100:
                errors['discount_percent'] = 'Must be 0-100.'
        except ValueError:
            errors['discount_percent'] = 'Enter a valid number.'
            percent_val = 100

        # Validate max uses
        max_uses_val = None
        if max_uses:
            try:
                max_uses_val = int(max_uses)
                if max_uses_val < 1:
                    errors['max_uses'] = 'Must be at least 1.'
            except ValueError:
                errors['max_uses'] = 'Enter a valid number.'

        # Validate duration
        if duration not in ('forever', 'once', 'repeating'):
            duration = 'forever'

        duration_in_months_val = None
        if duration == 'repeating':
            if not duration_in_months:
                errors['duration_in_months'] = 'Number of months is required for repeating duration.'
            else:
                try:
                    duration_in_months_val = int(duration_in_months)
                    if duration_in_months_val < 1:
                        errors['duration_in_months'] = 'Must be at least 1.'
                except ValueError:
                    errors['duration_in_months'] = 'Enter a valid number.'

        # Validate expires_at
        expires_at_val = None
        if expires_at:
            try:
                from django.utils.dateparse import parse_datetime, parse_date
                expires_at_val = parse_datetime(expires_at)
                if expires_at_val is None:
                    d = parse_date(expires_at)
                    if d:
                        from datetime import datetime, time
                        expires_at_val = timezone.make_aware(
                            datetime.combine(d, time.max)
                        )
            except (ValueError, TypeError):
                pass

        # Type-specific fields
        override_class_limit = data.get('override_class_limit', '').strip()
        override_student_limit = data.get('override_student_limit', '').strip()
        grant_days = data.get('grant_days', '').strip()
        class_limit = data.get('class_limit', '0').strip()

        override_class_val = None
        override_student_val = None
        grant_days_val = None
        class_limit_val = 0

        if target_type == 'institute':
            if override_class_limit:
                try:
                    override_class_val = int(override_class_limit)
                    if override_class_val < 0:
                        errors['override_class_limit'] = 'Must be 0 or greater.'
                except ValueError:
                    errors['override_class_limit'] = 'Enter a valid number.'
            if override_student_limit:
                try:
                    override_student_val = int(override_student_limit)
                    if override_student_val < 0:
                        errors['override_student_limit'] = 'Must be 0 or greater.'
                except ValueError:
                    errors['override_student_limit'] = 'Enter a valid number.'

        if target_type == 'student_promo':
            if grant_days:
                try:
                    grant_days_val = int(grant_days)
                    if grant_days_val < 1:
                        errors['grant_days'] = 'Must be at least 1.'
                except ValueError:
                    errors['grant_days'] = 'Enter a valid number.'
            try:
                class_limit_val = int(class_limit)
                if class_limit_val < 0:
                    errors['class_limit'] = 'Must be 0 or greater.'
            except ValueError:
                errors['class_limit'] = 'Enter a valid number.'

        if errors:
            return render(request, 'admin_dashboard/billing/coupon_code_form.html', {
                'form_data': data,
                'errors': errors,
                'packages': Package.objects.filter(is_active=True),
                'plans': InstitutePlan.objects.filter(is_active=True),
                'modules': ModuleProduct.objects.filter(is_active=True),
            })

        # Create based on target type
        selected_plans = data.getlist('applicable_plans')
        selected_modules = data.getlist('applicable_modules')
        selected_packages = data.getlist('applicable_packages')

        if target_type == 'institute':
            dc = InstituteDiscountCode.objects.create(
                code=code, description=description,
                discount_percent=percent_val,
                max_uses=max_uses_val if max_uses_val else 1,
                override_class_limit=override_class_val,
                override_student_limit=override_student_val,
                duration=duration,
                duration_in_months=duration_in_months_val,
                expires_at=expires_at_val,
            )
            if selected_plans:
                dc.applicable_plans.set(selected_plans)
            if selected_modules:
                dc.applicable_modules.set(selected_modules)

            if not dc.is_fully_free:
                try:
                    from .stripe_service import sync_discount_to_stripe, _stripe_configured
                    if _stripe_configured():
                        sync_discount_to_stripe(dc)
                except Exception as e:
                    logger.warning('Stripe discount sync failed: %s', e)

            log_event(
                user=request.user, school=None, category='data_change',
                action='coupon_code_created',
                detail={'type': 'institute', 'code': code, 'discount_percent': percent_val},
                request=request,
            )

        elif target_type == 'student_promo':
            promo = PromoCode.objects.create(
                code=code, description=description,
                discount_percent=percent_val,
                grant_days=grant_days_val,
                class_limit=class_limit_val,
                max_uses=max_uses_val,
                duration=duration,
                duration_in_months=duration_in_months_val,
                expires_at=expires_at_val,
            )
            if selected_packages:
                promo.applicable_packages.set(selected_packages)

            log_event(
                user=request.user, school=None, category='data_change',
                action='coupon_code_created',
                detail={'type': 'student_promo', 'code': code, 'discount_percent': percent_val},
                request=request,
            )

        elif target_type == 'student_discount':
            dc = DiscountCode.objects.create(
                code=code, discount_percent=percent_val,
                max_uses=max_uses_val,
                duration=duration,
                duration_in_months=duration_in_months_val,
                expires_at=expires_at_val,
            )
            if selected_packages:
                dc.applicable_packages.set(selected_packages)

            if not dc.is_fully_free:
                try:
                    from .stripe_service import sync_individual_discount_to_stripe, _stripe_configured
                    if _stripe_configured():
                        sync_individual_discount_to_stripe(dc)
                except Exception as e:
                    logger.warning('Stripe discount sync failed: %s', e)

            log_event(
                user=request.user, school=None, category='data_change',
                action='coupon_code_created',
                detail={'type': 'student_discount', 'code': code, 'discount_percent': percent_val},
                request=request,
            )

        messages.success(request, f'Coupon code "{code}" created.')
        return redirect('billing_admin_coupon_list')
