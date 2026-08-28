"""Billing API — read-only.

Invoices are issued by a school's own workflow (rate cascades, session counts,
number sequences, credit transactions); an API that could create or amend one
would be a second source of truth for money. So the app can read what is owed
and follow the school's Stripe payment link, and nothing here writes.

Drafts are never returned. A draft invoice is a school's working state, not a
bill anyone has been asked to pay, and showing one to a parent would be asking
for money the school has not yet asked for.
"""

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, viewsets

from api.scoping import scope_by_student
from billing.api_serializers import (
    InvoicePaymentSerializer, InvoiceSerializer, InvoiceSummarySerializer,
)
from classroom.models import Invoice, InvoicePayment


class InvoiceViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin,
                     viewsets.GenericViewSet):
    """Issued invoices for students the caller may read."""

    ordering_fields = ('issued_at', 'due_date', 'amount')

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return InvoiceSerializer
        return InvoiceSummarySerializer

    @extend_schema(parameters=[
        OpenApiParameter('student', int, description='Filter to one student id.'),
        OpenApiParameter('status', str,
                         description='issued | partially_paid | paid | cancelled'),
        OpenApiParameter('unpaid', bool, description='Only what is still owed.'),
    ])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def get_queryset(self):
        queryset = scope_by_student(
            Invoice.objects
            .exclude(status='draft')
            .select_related('student', 'school')
            .prefetch_related('line_items__classroom'),
            self.request.user,
        )
        params = self.request.query_params
        if params.get('student'):
            queryset = queryset.filter(student_id=params['student'])
        if params.get('status'):
            queryset = queryset.filter(status=params['status'])
        if params.get('unpaid') in ('1', 'true', 'True'):
            queryset = queryset.filter(status__in=['issued', 'partially_paid'])
        return queryset.order_by('-billing_period_start', 'id')


class InvoicePaymentViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """Payments recorded against students the caller may read."""

    serializer_class = InvoicePaymentSerializer
    ordering_fields = ('payment_date', 'amount')

    @extend_schema(parameters=[
        OpenApiParameter('student', int, description='Filter to one student id.'),
        OpenApiParameter('invoice', int, description='Filter to one invoice id.'),
    ])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def get_queryset(self):
        queryset = scope_by_student(
            InvoicePayment.objects.select_related('student', 'invoice'),
            self.request.user,
        )
        params = self.request.query_params
        if params.get('student'):
            queryset = queryset.filter(student_id=params['student'])
        if params.get('invoice'):
            queryset = queryset.filter(invoice_id=params['invoice'])
        return queryset.order_by('-payment_date', 'id')
