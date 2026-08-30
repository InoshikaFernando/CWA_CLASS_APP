"""Billing serializers — the parent-facing view of what is owed and paid."""

from rest_framework import serializers

from api.serializers import UserSummarySerializer
from classroom.models import Invoice, InvoiceLineItem, InvoicePayment


class InvoiceLineItemSerializer(serializers.ModelSerializer):
    classroom_name = serializers.CharField(source='classroom.name', read_only=True,
                                           default=None)

    class Meta:
        model = InvoiceLineItem
        fields = (
            'id', 'classroom_name', 'daily_rate', 'sessions_held',
            'sessions_attended', 'sessions_charged', 'line_amount',
        )


class InvoiceSerializer(serializers.ModelSerializer):
    """An invoice as the payer sees it.

    ``rate_source`` and ``calculated_amount`` are omitted deliberately: they
    are the school's internal pricing cascade (which fee override produced
    this rate), not something a parent is being billed for.
    """

    student = UserSummarySerializer(read_only=True)
    school_name = serializers.CharField(source='school.name', read_only=True)
    line_items = InvoiceLineItemSerializer(many=True, read_only=True)

    class Meta:
        model = Invoice
        fields = (
            'id', 'invoice_number', 'student', 'school_name',
            'billing_period_start', 'billing_period_end', 'period_type',
            'amount', 'status', 'issued_at', 'due_date', 'notes',
            'stripe_payment_link', 'line_items',
        )


class InvoiceSummarySerializer(serializers.ModelSerializer):
    """List row — no line items, which are only needed on the detail screen."""

    student = UserSummarySerializer(read_only=True)
    school_name = serializers.CharField(source='school.name', read_only=True)

    class Meta:
        model = Invoice
        fields = (
            'id', 'invoice_number', 'student', 'school_name',
            'billing_period_start', 'billing_period_end',
            'amount', 'status', 'issued_at', 'due_date',
        )


class InvoicePaymentSerializer(serializers.ModelSerializer):
    student = UserSummarySerializer(read_only=True)
    invoice_number = serializers.CharField(source='invoice.invoice_number',
                                           read_only=True, default=None)

    class Meta:
        model = InvoicePayment
        fields = (
            'id', 'invoice_number', 'student', 'amount', 'payment_date',
            'payment_method', 'reference_name', 'status',
        )
