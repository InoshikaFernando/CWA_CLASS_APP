# CWA Classroom — Student Invoicing System
# Specification Document

**Application:** CWA Classroom
**Version:** 1.1
**Date:** 2026-03-17
**Status:** Draft — Pending Review

---

## Table of Contents

1. [Overview](#1-overview)
2. [Terminology](#2-terminology)
3. [Fee Configuration](#3-fee-configuration)
4. [Attendance Calculation Mode](#4-attendance-calculation-mode)
5. [Invoice Generation](#5-invoice-generation)
6. [Payment Reconciliation (Bank CSV Import)](#6-payment-reconciliation-bank-csv-import)
7. [Manual Payment Entry](#7-manual-payment-entry)
8. [Student Credit Balance](#8-student-credit-balance)
9. [Data Model](#9-data-model)
10. [Workflow Summary](#10-workflow-summary)
11. [Business Rules](#11-business-rules)
12. [UI Screens](#12-ui-screens)
13. [Open Items](#13-open-items)

---

## 1. Overview

### 1.1 Purpose

This specification defines the student invoicing system for CWA Classroom. It enables a Head of Institute (HoI) or Accountant to:

1. **Configure fees** — per-student or per-department daily rate
2. **Generate invoices** — based on attendance data for a selected period
3. **Reconcile payments** — by importing bank transfer CSV files and mapping payer names to students
4. **Record manual payments** — for cash, cheque, or other non-CSV payments

### 1.2 Scope

- Fee configuration at department and student level
- Attendance-based invoice calculation (two modes)
- Invoice generation (draft → issued), viewing, and status tracking
- Bank CSV upload with fuzzy name matching, payment splitting, and auto-mapping
- Manual payment recording
- Student credit balance tracking (overpayments)
- HoI and Accountant access (school-scoped)

### 1.3 Out of Scope

- Stripe/online payment collection (existing billing module handles subscriptions)
- PDF invoice rendering (future enhancement)
- Email delivery of invoices (future enhancement)
- Tax calculation
- Multi-currency support (all amounts in NZD)
- Parent/guardian billing accounts

---

## 2. Terminology

| Term | Definition |
|------|-----------|
| **Daily Rate** | The fee charged per class day (either attended or held). Can be $0 for scholarships. |
| **Billing Period** | A date range for which an invoice is generated (e.g., a term or month) |
| **Class Days Held** | Total number of `ClassSession` records with `status=completed` for a class in the billing period |
| **Days Attended** | Number of sessions where the student's `StudentAttendance.status` is `present` or `late` in the billing period |
| **Attendance Mode** | Whether the invoice counts all class days held or only days the student attended |
| **Reference Name** | The payer name as it appears in the bank CSV (may differ from student name) |
| **Credit Balance** | Overpayment amount held on a student's account, auto-applied to future invoices |

---

## 3. Fee Configuration

### 3.1 Fee Hierarchy

Fees are resolved per **invoice line item** (per class/department). Resolution order (first match wins):

1. **Student-specific fee** — a daily rate set on a specific student, overrides everything
2. **Department fee** — a default daily rate set on the department the class belongs to

If neither is set for a given class, that class is flagged as "no fee configured" and excluded from the invoice.

**Rate resolution date:** The active rate is determined by `effective_from <= billing_period_end`. This ensures that when generating invoices for a past period, the rate that was active at the end of that period is used.

### 3.2 Department Fee

**Set by:** HoI or Accountant
**Scope:** Per department, per school

| Field | Type | Description |
|-------|------|-------------|
| `department` | FK | The department |
| `daily_rate` | Decimal(10,2) | Default fee per class day for students in this department |
| `effective_from` | Date | When this rate takes effect |
| `created_by` | FK(User) | Who set the rate |
| `created_at` | Timestamp | When the rate was created |

**Rules:**
- Active rate = latest `effective_from <= billing_period_end`
- Rate changes create a new record (audit trail); old rates are kept for historical invoices
- Rate can be $0 (e.g., free department/programme)

### 3.3 Student Fee Override

**Set by:** HoI or Accountant
**Scope:** Per student, per school

| Field | Type | Description |
|-------|------|-------------|
| `student` | FK(User) | The student |
| `school` | FK(School) | Scoped to a school |
| `daily_rate` | Decimal(10,2) | Student-specific fee per class day |
| `reason` | Text | Why this student has a custom rate (e.g., "scholarship", "sibling discount") |
| `effective_from` | Date | When this rate takes effect |
| `created_by` | FK(User) | Who set the rate |
| `created_at` | Timestamp | When created |

**Rules:**
- Overrides the department rate for **all** this student's classes
- Active rate = latest `effective_from <= billing_period_end`
- Rate can be $0 (full scholarship — invoice is generated with $0 amount for record-keeping)

---

## 4. Attendance Calculation Mode

When generating an invoice, the HoI selects one of two modes:

### 4.1 Mode A — All Class Days

**Charge for every day the class was held**, regardless of whether the student attended. Only sessions **after the student's enrollment date** are counted.

```
Line Amount = Daily Rate × Class Days Held (after enrollment, in billing period)
```

**Use case:** The student is committed to all classes; absences don't reduce the fee.

### 4.2 Mode B — Attended Days Only

**Charge only for days the student was present** (status = `present` or `late`).

```
Line Amount = Daily Rate × Days Attended (in billing period)
```

**Use case:** Pay-per-attendance model where absences reduce the fee.

### 4.3 Mode Selection

- The mode is selected **per invoice generation run** (not per student or per department)
- The selected mode is stored on the `Invoice` record for audit purposes
- Different invoices for different periods can use different modes

### 4.4 Mid-Period Enrollment

In **both modes**, only sessions on or after the student's `ClassStudent.joined_at` date are counted. A student who enrolled on the 15th of a month is only charged for sessions from the 15th onward.

---

## 5. Invoice Generation

### 5.1 Pre-Conditions

Before invoices can be generated, the system checks:

1. **All attendance must be marked** — Every `ClassSession` with `status=completed` in the billing period must have a `StudentAttendance` record for every enrolled student. If any sessions have unmarked attendance, generation is **blocked** with a list of the unmarked sessions and their classes.
2. **No overlapping invoices** — No existing non-cancelled invoice for the same student may have an overlapping billing period. Cancelled invoices are excluded from this check.

### 5.2 Generation Flow

```
1. HoI/Accountant navigates to Invoicing → Generate Invoices
2. Selects: School, Billing Period (start date → end date)
3. Selects: Attendance Mode (All Class Days / Attended Days Only)
4. Optionally filters by: Department, specific students
5. System validates pre-conditions (§5.1)
   - If blocked → shows errors with actionable details
6. System calculates:
   a. For each student in scope, for each of their classes:
      - Resolve daily rate per class (student override → department default)
      - Count sessions (based on mode + enrollment date)
      - Line amount = rate × sessions_charged
   b. Invoice amount = SUM(line amounts) for the student
   c. Students/classes with no fee configured are listed separately as warnings
7. HoI reviews the preview (can edit amount and notes per student)
8. Clicking "Preview" saves invoices as status = "draft"
9. HoI confirms → draft invoices move to status = "issued"
   - If HoI abandons, drafts remain and can be deleted or issued later
```

### 5.3 Invoice Record

| Field | Type | Description |
|-------|------|-------------|
| `invoice_number` | String | Auto-generated, unique (e.g., `INV-1-2026-0001`) |
| `school` | FK(School) | The school this invoice belongs to |
| `student` | FK(User) | The billed student |
| `billing_period_start` | Date | Start of the billing period |
| `billing_period_end` | Date | End of the billing period |
| `attendance_mode` | String | `all_class_days` or `attended_days_only` |
| `calculated_amount` | Decimal(10,2) | System-calculated amount (sum of line items) |
| `amount` | Decimal(10,2) | Final invoice amount (may differ from calculated if HoI adjusted) |
| `status` | String | `draft` / `issued` / `partially_paid` / `paid` / `cancelled` |
| `notes` | Text | Optional notes (editable on preview) |
| `cancelled_by` | FK(User) | Who cancelled this invoice (nullable) |
| `cancelled_at` | Timestamp | When cancelled (nullable) |
| `cancellation_reason` | Text | Why cancelled (nullable) |
| `created_by` | FK(User) | Who generated the invoice |
| `created_at` | Timestamp | |
| `updated_at` | Timestamp | |

**Note:** `daily_rate` and `day_count` are removed from the Invoice level. Each line item carries its own rate. The invoice `amount` is the sum of line item amounts (or a manually adjusted total).

### 5.4 Invoice Line Items

Each invoice has line items detailing the per-class breakdown:

| Field | Type | Description |
|-------|------|-------------|
| `invoice` | FK(Invoice) | Parent invoice |
| `classroom` | FK(ClassRoom) | The class |
| `department` | FK(Department) | The department (denormalized for reporting) |
| `daily_rate` | Decimal(10,2) | The rate used for this class (snapshotted at generation time) |
| `rate_source` | String | `student_override` or `department_default` — where the rate came from |
| `sessions_held` | Integer | Total completed sessions for this class in the period (after enrollment) |
| `sessions_attended` | Integer | Sessions the student attended (present/late) |
| `sessions_charged` | Integer | Sessions actually charged (depends on attendance mode) |
| `line_amount` | Decimal(10,2) | daily_rate × sessions_charged |

**Rules:**
- `Invoice.calculated_amount = SUM(line_items.line_amount)`
- `Invoice.amount` defaults to `calculated_amount` but can be adjusted by HoI
- Line items are read-only after invoice is issued

### 5.5 Invoice Number Format

```
INV-{school_id}-{YYYY}-{sequential_number:04d}
```

Example: `INV-1-2026-0042` — School 1, year 2026, 42nd invoice.

Sequential counter resets annually per school. Managed by `InvoiceNumberSequence` model with DB-level locking to prevent race conditions.

### 5.6 Invoice Cancellation

- Issued invoices cannot be edited — they must be cancelled and re-issued
- Cancellation requires a reason
- If the invoice has confirmed payments, those payments become **unlinked credits** on the student's credit balance (see §8)
- Cancelled invoices are excluded from the overlapping period check, allowing re-generation

---

## 6. Payment Reconciliation (Bank CSV Import)

### 6.1 Overview

HoI/Accountant uploads a bank statement CSV to match payments against outstanding invoices. The system uses fuzzy name matching and tokenization to auto-match, and allows manual payment splitting for multi-child references.

### 6.2 CSV Upload Constraints

- **Maximum file size:** 10MB
- **Maximum rows:** 10,000
- **Encoding:** UTF-8 (with auto-detection fallback for Latin-1)
- **Only credit/positive amounts are processed.** During column mapping, HoI specifies whether the amount column represents credits or debits. Rows with negative/zero amounts or non-credit rows are auto-skipped and shown in a "Skipped" section.

### 6.3 CSV Upload Flow

```
1. HoI/Accountant uploads a bank transfer CSV file
2. System validates file size and row count
3. System reads first 5 rows as preview for column mapping
4. HoI maps columns (or selects a saved template):
   - Date column → transaction date
   - Amount column → payment amount
   - Reference/Description column → payer reference name
   - Transaction ID column (optional, for dedup)
   - Amount type: Credit / Debit (to filter correctly)
5. [Save as template] for future uploads
6. System processes each valid row:
   a. Normalize reference: trim whitespace, collapse spaces
   b. Try exact match against saved PaymentReferenceMapping
   c. If no exact match → tokenize reference (split by spaces, commas, "&", "and")
      and fuzzy-match tokens against enrolled student names (first name, last name)
   d. If single student matched → auto-match
   e. If multiple students matched → flag for manual split
   f. If no match → add to "unmatched" list
7. HoI reviews matches and resolves unmatched/multi-match entries
8. HoI confirms → Payments are recorded
```

### 6.4 Reference Name Matching

**Normalization:** All reference names are normalized before matching:
- Trim leading/trailing whitespace
- Collapse multiple spaces to single space
- Case-insensitive comparison (stored lowercase)

**Fuzzy matching:** When no exact mapping exists, the system:
1. Tokenizes the reference by splitting on spaces, commas, `&`, and `and`
2. Compares each token against first names and last names of enrolled students (using similarity scoring)
3. Returns candidate matches above a confidence threshold
4. If one student matches with high confidence → auto-match
5. If multiple students match → show all candidates for manual resolution

### 6.5 Multi-Child Payment Splitting

When a reference matches multiple students (e.g., "Sam Sig" matching Sam Smith and Sig Smith):

```
┌─────────────────────────────────────────────────────────────────┐
│ Reference: "SAM SIG"   Total: $300.00                           │
│                                                                  │
│ Matched students:                                                │
│ ☑ Sam Smith  — oldest unpaid: INV-1-2026-0012 ($180 due)        │
│   Amount: [$180.00 ]                                             │
│ ☑ Sig Smith  — oldest unpaid: INV-1-2026-0015 ($120 due)        │
│   Amount: [$120.00 ]                                             │
│                                                                  │
│ Allocated: $300.00 / $300.00  ✅                                 │
│ [Confirm Split]                                                  │
└─────────────────────────────────────────────────────────────────┘
```

- System pre-fills each student's amount with their oldest unpaid invoice amount (capped at remaining total)
- HoI can adjust amounts manually
- Total allocated must equal the CSV row amount

### 6.6 Saved Reference Mapping

| Field | Type | Description |
|-------|------|-------------|
| `school` | FK(School) | Scoped to school |
| `reference_name` | String | Normalized reference name (lowercase, trimmed) |
| `student` | FK(User) | The mapped student (nullable — null means "ignored") |
| `is_ignored` | Boolean | If true, this reference is a known non-student transfer |
| `created_by` | FK(User) | Who created the mapping |
| `created_at` | Timestamp | |

**Rules:**
- `unique_together: (school, reference_name)`
- Mappings persist across imports — once mapped, future CSVs auto-match
- HoI can edit/delete mappings from a management page
- When a student is deleted, the mapping's student is set to null (not cascaded)

### 6.7 CSV Column Mapping Template

Saved per school so HoI doesn't re-map columns every upload:

| Field | Type | Description |
|-------|------|-------------|
| `school` | FK(School) | |
| `name` | String | Template name (e.g., "ASB Bank", "ANZ Statement") |
| `column_mapping` | JSON | `{date_col, amount_col, reference_col, transaction_id_col, amount_type}` |
| `created_by` | FK(User) | |
| `created_at` | Timestamp | |

### 6.8 Payment Record (from CSV)

| Field | Type | Description |
|-------|------|-------------|
| `invoice` | FK(Invoice) | The invoice this payment applies to (nullable for credits) |
| `student` | FK(User) | The paying student |
| `school` | FK(School) | |
| `amount` | Decimal(10,2) | Payment amount |
| `payment_date` | Date | Date of the bank transaction |
| `payment_method` | String | `bank_transfer` / `cash` / `cheque` / `other` |
| `reference_name` | String | Original reference from CSV (empty for manual payments) |
| `bank_transaction_id` | String | Optional, for deduplication |
| `csv_import` | FK(CSVImport) | Which import batch this came from (nullable for manual) |
| `status` | String | `matched` / `confirmed` / `rejected` |
| `notes` | Text | Optional notes |
| `created_by` | FK(User) | |
| `created_at` | Timestamp | |

### 6.9 CSV Import Record

| Field | Type | Description |
|-------|------|-------------|
| `school` | FK(School) | |
| `file_name` | String | Original uploaded file name |
| `uploaded_by` | FK(User) | |
| `uploaded_at` | Timestamp | |
| `column_mapping` | JSON | The column mapping used for this import |
| `total_rows` | Integer | Total rows in CSV |
| `credit_rows` | Integer | Rows with positive amounts (processed) |
| `skipped_rows` | Integer | Rows skipped (negative/zero amounts) |
| `matched_count` | Integer | Auto-matched rows |
| `unmatched_count` | Integer | Rows needing manual mapping |
| `ignored_count` | Integer | Rows marked as ignored |
| `confirmed_count` | Integer | Rows confirmed as payments |
| `status` | String | `pending` / `processing` / `completed` |

### 6.10 Unmatched Entry Resolution

When a CSV row cannot be auto-matched, the HoI sees:

```
┌──────────────────────────────────────────────────────────────┐
│ Unmatched Transactions                                       │
├──────────────────────────────────────────────────────────────┤
│ Reference: "J SMITH PAYMENT"   Amount: $120.00  Date: 01/03 │
│ Suggestions: John Smith (82%), Jane Smith (71%)              │
│ → [Search student...▼]  [Ignore this transfer]              │
│                                                              │
│ Reference: "VODAFONE NZ"       Amount: $49.99   Date: 05/03 │
│ No student match found                                       │
│ → [Search student...▼]  [Ignore this transfer]              │
└──────────────────────────────────────────────────────────────┘
```

- **Search student**: type-ahead search of students in the school. Selecting a student creates a `PaymentReferenceMapping` for future auto-match.
- **Suggestions**: fuzzy match candidates shown with confidence percentage.
- **Ignore**: marks this reference as non-student. Creates a mapping with `is_ignored=True` so it's auto-ignored in future imports.

---

## 7. Manual Payment Entry

For cash, cheque, or payments not captured in bank CSV:

```
1. HoI/Accountant navigates to an invoice's detail page
2. Clicks "Record Payment"
3. Enters: amount, payment date, payment method (cash/cheque/other), notes
4. Payment is created with status = "confirmed" (no matching step needed)
5. Invoice status auto-updates based on total payments
```

Manual payments have `csv_import = null` and `reference_name = ""`.

---

## 8. Student Credit Balance

### 8.1 How Credits Arise

- **Overpayment:** Payment amount exceeds the invoice's outstanding balance. The excess becomes a credit.
- **Invoice cancellation:** If a cancelled invoice had confirmed payments, those payments become unlinked credits.

### 8.2 Credit Application

- When a new invoice is issued, the system checks if the student has a credit balance
- If credit exists, it is auto-applied to reduce the invoice amount due
- A `CreditTransaction` record tracks each credit addition and usage

### 8.3 Credit Balance Model

| Field | Type | Description |
|-------|------|-------------|
| `student` | FK(User) | |
| `school` | FK(School) | |
| `amount` | Decimal(10,2) | Positive = credit added, Negative = credit used |
| `reason` | String | `overpayment` / `invoice_cancelled` / `applied_to_invoice` |
| `related_payment` | FK(InvoicePayment) | The payment that created this credit (nullable) |
| `related_invoice` | FK(Invoice) | The invoice this credit was applied to (nullable) |
| `created_at` | Timestamp | |

**Rules:**
- Student's current credit balance = SUM of all `CreditTransaction.amount` for that student+school
- Credit balance must never go negative (validation)
- Credits are applied automatically when invoices are issued (creates a negative CreditTransaction)
- HoI can view credit balances per student on the Invoice List page

---

## 9. Data Model

### 9.1 New Models

```python
class DepartmentFee(models.Model):
    department = models.ForeignKey('Department', on_delete=models.CASCADE,
                                   related_name='fees')
    daily_rate = models.DecimalField(max_digits=10, decimal_places=2)
    effective_from = models.DateField()
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                    null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-effective_from']

    def __str__(self):
        return f"{self.department} - ${self.daily_rate} from {self.effective_from}"


class StudentFeeOverride(models.Model):
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                 related_name='fee_overrides')
    school = models.ForeignKey('School', on_delete=models.CASCADE,
                                related_name='student_fee_overrides')
    daily_rate = models.DecimalField(max_digits=10, decimal_places=2)
    reason = models.TextField(blank=True)
    effective_from = models.DateField()
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                    null=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-effective_from']


class InvoiceNumberSequence(models.Model):
    """Tracks the next invoice number per school per year. Uses select_for_update() for concurrency."""
    school = models.ForeignKey('School', on_delete=models.CASCADE,
                                related_name='invoice_sequences')
    year = models.PositiveIntegerField()
    last_number = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ('school', 'year')


class Invoice(models.Model):
    ATTENDANCE_MODE_CHOICES = [
        ('all_class_days', 'All Class Days'),
        ('attended_days_only', 'Attended Days Only'),
    ]
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('issued', 'Issued'),
        ('partially_paid', 'Partially Paid'),
        ('paid', 'Paid'),
        ('cancelled', 'Cancelled'),
    ]

    invoice_number = models.CharField(max_length=50, unique=True)
    school = models.ForeignKey('School', on_delete=models.CASCADE,
                                related_name='invoices')
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                 related_name='invoices')
    billing_period_start = models.DateField()
    billing_period_end = models.DateField()
    attendance_mode = models.CharField(max_length=20, choices=ATTENDANCE_MODE_CHOICES)
    calculated_amount = models.DecimalField(max_digits=10, decimal_places=2,
                                             help_text='System-calculated sum of line items')
    amount = models.DecimalField(max_digits=10, decimal_places=2,
                                  help_text='Final amount (may be adjusted by HoI)')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    notes = models.TextField(blank=True)
    cancelled_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                      null=True, blank=True, related_name='+')
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                    null=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    @property
    def amount_paid(self):
        return self.payments.filter(status='confirmed').aggregate(
            total=models.Sum('amount'))['total'] or 0

    @property
    def amount_due(self):
        return self.amount - self.amount_paid


class InvoiceLineItem(models.Model):
    RATE_SOURCE_CHOICES = [
        ('student_override', 'Student Override'),
        ('department_default', 'Department Default'),
    ]

    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE,
                                 related_name='line_items')
    classroom = models.ForeignKey('ClassRoom', on_delete=models.SET_NULL, null=True)
    department = models.ForeignKey('Department', on_delete=models.SET_NULL, null=True,
                                    help_text='Denormalized for reporting')
    daily_rate = models.DecimalField(max_digits=10, decimal_places=2)
    rate_source = models.CharField(max_length=20, choices=RATE_SOURCE_CHOICES)
    sessions_held = models.PositiveIntegerField()
    sessions_attended = models.PositiveIntegerField()
    sessions_charged = models.PositiveIntegerField()
    line_amount = models.DecimalField(max_digits=10, decimal_places=2)


class CSVColumnTemplate(models.Model):
    """Saved CSV column mapping templates per school."""
    school = models.ForeignKey('School', on_delete=models.CASCADE,
                                related_name='csv_column_templates')
    name = models.CharField(max_length=100)
    column_mapping = models.JSONField(
        help_text='{"date_col": 0, "amount_col": 2, "reference_col": 3, '
                  '"transaction_id_col": null, "amount_type": "credit"}')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                    null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('school', 'name')


class CSVImport(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
    ]

    school = models.ForeignKey('School', on_delete=models.CASCADE,
                                related_name='csv_imports')
    file_name = models.CharField(max_length=255)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                     null=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    column_mapping = models.JSONField(default=dict,
                                       help_text='The column mapping used for this import')
    total_rows = models.PositiveIntegerField(default=0)
    credit_rows = models.PositiveIntegerField(default=0)
    skipped_rows = models.PositiveIntegerField(default=0)
    matched_count = models.PositiveIntegerField(default=0)
    unmatched_count = models.PositiveIntegerField(default=0)
    ignored_count = models.PositiveIntegerField(default=0)
    confirmed_count = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')


class PaymentReferenceMapping(models.Model):
    school = models.ForeignKey('School', on_delete=models.CASCADE,
                                related_name='payment_reference_mappings')
    reference_name = models.CharField(max_length=255,
                                       help_text='Normalized: lowercase, trimmed')
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                 null=True, blank=True,
                                 related_name='payment_reference_mappings')
    is_ignored = models.BooleanField(default=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                    null=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('school', 'reference_name')
        indexes = [
            models.Index(fields=['school', 'reference_name']),
        ]


class InvoicePayment(models.Model):
    STATUS_CHOICES = [
        ('matched', 'Matched'),
        ('confirmed', 'Confirmed'),
        ('rejected', 'Rejected'),
    ]
    PAYMENT_METHOD_CHOICES = [
        ('bank_transfer', 'Bank Transfer'),
        ('cash', 'Cash'),
        ('cheque', 'Cheque'),
        ('other', 'Other'),
    ]

    invoice = models.ForeignKey(Invoice, on_delete=models.SET_NULL,
                                 null=True, blank=True,
                                 related_name='payments')
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                 related_name='invoice_payments')
    school = models.ForeignKey('School', on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    payment_date = models.DateField()
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES,
                                       default='bank_transfer')
    reference_name = models.CharField(max_length=255, blank=True)
    bank_transaction_id = models.CharField(max_length=255, blank=True)
    csv_import = models.ForeignKey(CSVImport, on_delete=models.SET_NULL,
                                    null=True, blank=True, related_name='payments')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='matched')
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                    null=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)


class CreditTransaction(models.Model):
    REASON_CHOICES = [
        ('overpayment', 'Overpayment'),
        ('invoice_cancelled', 'Invoice Cancelled'),
        ('applied_to_invoice', 'Applied to Invoice'),
    ]

    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                 related_name='credit_transactions')
    school = models.ForeignKey('School', on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=10, decimal_places=2,
                                  help_text='Positive = credit added, Negative = credit used')
    reason = models.CharField(max_length=30, choices=REASON_CHOICES)
    related_payment = models.ForeignKey(InvoicePayment, on_delete=models.SET_NULL,
                                         null=True, blank=True)
    related_invoice = models.ForeignKey(Invoice, on_delete=models.SET_NULL,
                                         null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
```

### 9.2 Relationship Diagram

```
DepartmentFee ──> Department
StudentFeeOverride ──> User (student) + School

InvoiceNumberSequence ──> School

Invoice ──> School + User (student)
  ├── InvoiceLineItem ──> ClassRoom + Department
  ├── InvoicePayment ──> CSVImport (nullable)
  └── CreditTransaction ──> InvoicePayment (nullable)

CSVColumnTemplate ──> School
CSVImport ──> School
PaymentReferenceMapping ──> School + User (student, nullable via SET_NULL)

CreditTransaction ──> User (student) + School + Invoice (nullable) + InvoicePayment (nullable)
```

---

## 10. Workflow Summary

### 10.1 First-Time Setup

```
1. HoI/Accountant sets department default fees (§3.2)
2. Optionally sets student-specific overrides (§3.3)
3. Optionally saves CSV column mapping templates (§6.7)
```

### 10.2 Monthly/Termly Invoice Generation

```
1. HoI/Accountant → Invoicing → Generate Invoices
2. Select billing period + attendance mode
3. System validates pre-conditions (attendance marked, no overlaps)
4. Preview calculated amounts (invoices saved as "draft")
5. Adjust amounts/notes if needed
6. Confirm → drafts move to "issued"
7. Credits auto-applied to reduce amounts due
```

### 10.3 Payment Reconciliation (CSV)

```
1. HoI/Accountant → Invoicing → Import Payments
2. Upload bank CSV (max 10MB / 10K rows)
3. Map CSV columns (or select saved template)
4. Review auto-matched payments + fuzzy-match suggestions
5. Resolve unmatched entries (map to student, split between students, or ignore)
6. Confirm → Payments recorded, invoice statuses updated
7. Overpayments auto-create credit balances
```

### 10.4 Manual Payment

```
1. HoI/Accountant → Invoice detail page
2. Click "Record Payment"
3. Enter amount, date, method, notes
4. Payment confirmed immediately, invoice status updates
```

---

## 11. Business Rules

### 11.1 Fee Rules

| # | Rule |
|---|------|
| F1 | Student-specific fee overrides department fee for all that student's classes |
| F2 | Fee rates are snapshotted per line item at generation time (rate changes don't affect existing invoices) |
| F3 | Students/classes with no fee configured are excluded from invoice generation (shown as warnings) |
| F4 | Fee rates must be >= 0 ($0 allowed for scholarships) |
| F5 | Active rate = latest `effective_from <= billing_period_end` |

### 11.2 Invoice Rules

| # | Rule |
|---|------|
| I1 | HoI and Accountant can generate invoices |
| I2 | Only `completed` sessions count (cancelled/scheduled sessions excluded) |
| I3 | `late` attendance counts as attended (for "attended days only" mode) |
| I4 | No overlapping billing periods allowed per student (cancelled invoices excluded from check) |
| I5 | Invoice amount and notes can be adjusted by HoI/Accountant before issuing (on draft preview) |
| I6 | Cancelled invoices cannot receive payments |
| I7 | Invoice status auto-updates: `issued` → `partially_paid` (when 0 < paid < amount) → `paid` (when paid >= amount) |
| I8 | All attendance must be marked for sessions in the billing period before generation (blocks otherwise) |
| I9 | Mid-period enrollment: only sessions on or after `ClassStudent.joined_at` are counted |
| I10 | Issued invoices are immutable — cancel and re-issue to correct |
| I11 | $0 invoices are generated (for scholarship students and zero-session periods) |
| I12 | Preview saves as draft; Confirm changes draft to issued; Abandoned drafts can be deleted or issued later |

### 11.3 Payment Rules

| # | Rule |
|---|------|
| P1 | CSV rows with duplicate `bank_transaction_id` (if provided) are flagged and skipped |
| P2 | A payment is matched to the student's oldest unpaid invoice by default |
| P3 | If a payment exceeds the invoice amount, the excess becomes a credit on the student's balance |
| P4 | Payment reference mappings persist and improve auto-matching over time |
| P5 | Ignored references are auto-skipped in future imports |
| P6 | Multi-child references are tokenized and fuzzy-matched; HoI can split the amount between matched students |
| P7 | Manual payments (cash/cheque) are recorded directly on the invoice detail page |
| P8 | Only credit/positive amounts from CSV are processed; negative/zero rows are skipped |
| P9 | When an invoice is cancelled, its confirmed payments become unlinked student credits |

### 11.4 Credit Rules

| # | Rule |
|---|------|
| C1 | Credits are auto-applied when new invoices are issued |
| C2 | Credit balance must never go negative |
| C3 | All credit additions and usages are tracked via `CreditTransaction` for audit |

---

## 12. UI Screens

### 12.1 Access

Both **HoI** and **Accountant** roles have full access to all invoicing features.

### 12.2 Navigation

Under HoI/Accountant dashboard sidebar:

```
Invoicing
  ├── Fee Configuration
  ├── Generate Invoices
  ├── Invoice List
  ├── Import Payments
  └── Reference Mappings
```

### 12.3 Fee Configuration Page

- Tab view: **Department Fees** | **Student Overrides**
- Department Fees tab: table of departments with current rate, rate history expandable, "Set Rate" button
- Student Overrides tab: table of students with custom rates, "Add Override" button
- Modal/inline form for setting rates
- **Empty state:** "No department fees configured yet. Set a daily rate per department to start generating invoices."

### 12.4 Generate Invoices Page

```
Step 1: Select Parameters
  ┌─────────────────────────────────────────────────┐
  │ Billing Period:  [Start Date] → [End Date]      │
  │ Attendance Mode: (●) All Class Days              │
  │                  ( ) Attended Days Only           │
  │ Filter by Department: [All ▼]                   │
  │                                                  │
  │ [Preview Invoices]                               │
  └─────────────────────────────────────────────────┘

  ⛔ Blocked (if applicable):
  ┌─────────────────────────────────────────────────┐
  │ Attendance not marked for 3 sessions:            │
  │ • Mon 3 Mar — Maths Y7 (Teacher X)              │
  │ • Wed 5 Mar — Science (Teacher Y)               │
  │ • Fri 7 Mar — Guitar (Teacher Z)                │
  │ Please mark attendance before generating.        │
  └─────────────────────────────────────────────────┘

Step 2: Preview & Confirm (saved as draft)
  ┌──────────────────────────────────────────────────────────────────────┐
  │ Student          │ Classes  │ Calculated │ Amount  │ Notes │ Action │
  ├──────────────────┼──────────┼────────────┼─────────┼───────┼────────┤
  │ Alice Smith      │ 3        │ $450.00    │ $450.00 │       │ [Edit] │
  │   ├ Maths Y7     │ $15 × 20│            │ $300.00 │       │        │
  │   ├ Guitar       │ $10 × 10│            │ $100.00 │       │        │
  │   └ Flute        │ $10 × 5 │            │  $50.00 │       │        │
  │ Bob Jones        │ 1        │ $216.00    │ $216.00 │       │ [Edit] │
  │   └ Maths Y7     │ $12 × 18│            │ $216.00 │       │        │
  ├──────────────────┴──────────┴────────────┴─────────┴───────┴────────┤
  │ ⚠ No fee configured:                                                │
  │   Dave Wilson — Python class (no department fee)                     │
  ├─────────────────────────────────────────────────────────────────────┤
  │                                        Total: $666.00               │
  │                                                                     │
  │ [Delete Drafts]                           [Confirm & Issue]         │
  └─────────────────────────────────────────────────────────────────────┘
```

- **[Edit]** opens inline editing for amount and notes only (rate and days are locked)
- Expandable rows show per-class line item breakdown

### 12.5 Invoice List Page

- Table: Invoice #, Student, Period, Amount, Paid, Credit Applied, Due, Status
- Filters: status, date range, department, student search
- Pagination: 25 per page
- Click row → Invoice detail view
- **Invoice Detail View:** line items, payment history, credit applications, "Record Payment" button, "Cancel Invoice" button (with reason dialog)
- **Empty state:** "No invoices generated yet."

### 12.6 Import Payments Page

```
Step 1: Upload CSV
  [Choose file...] [Upload]  (max 10MB)
  Saved templates: [ASB Bank ▼] [Use Template]

Step 2: Map Columns (or auto-filled from template)
  Date column:      [Column A ▼]
  Amount column:    [Column C ▼]
  Reference column: [Column D ▼]
  Transaction ID:   [Column B ▼] (optional)
  Amount type:      (●) Credits  ( ) Debits

  [Save as template: [________]]  [Continue]

  ℹ Skipped: 5 rows with non-credit amounts

Step 3: Review Matches
  ┌─────────────────────────────────────────────────────────────┐
  │ ✅ Auto-Matched (12)                                        │
  │ "A SMITH"     → Alice Smith   │ $120 │ INV-1-2026-0042     │
  │ "B JONES PAY" → Bob Jones     │ $216 │ INV-1-2026-0043     │
  │ ...                                                         │
  ├─────────────────────────────────────────────────────────────┤
  │ 👥 Multi-Student Match (1)                                  │
  │ "SAM SIG"  $300  → Sam Smith + Sig Smith                   │
  │ [Split Payment...]                                          │
  ├─────────────────────────────────────────────────────────────┤
  │ ❓ Unmatched (2)                                            │
  │ "J SMITH PAYMENT"  $120  │ Suggestions: John Smith (82%)   │
  │ → [Search student ▼] [Ignore]                              │
  │ "VODAFONE NZ"      $49  │ No student match                 │
  │ → [Search student ▼] [Ignore]                              │
  ├─────────────────────────────────────────────────────────────┤
  │ [Cancel]                              [Confirm Payments]    │
  └─────────────────────────────────────────────────────────────┘
```

### 12.7 Reference Mappings Page

- Table: Reference Name, Mapped Student (or "Ignored"), Created By, Date
- Actions: Edit mapping, Delete mapping
- Search/filter by reference name or student

---

## 13. Open Items

| # | Item | Notes |
|---|------|-------|
| OI-1 | PDF invoice generation | Future: render invoices as PDF for download/email |
| OI-2 | Email invoice delivery | Future: email invoices to students/parents |
| OI-3 | Parent/guardian billing | Should invoices be linked to parent contacts? |
| OI-4 | Bank CSV format presets | Pre-configured templates for common NZ banks (ASB, ANZ, BNZ, Westpac, Kiwibank) |
| OI-5 | Billing frequency enforcement | Should the system suggest/enforce monthly or termly billing periods? |
| OI-6 | Fuzzy match threshold | What similarity score threshold should be used for auto-matching vs suggesting? Needs tuning with real data. |
| OI-7 | Rounding rules | Define rounding strategy for decimal calculations (round per line item vs on total). Default: round per line item to 2 decimal places. |
| OI-8 | Date format handling | Bank CSV date formats vary (DD/MM/YYYY, MM/DD/YYYY, YYYY-MM-DD). Add format selection to column mapping step. |
| OI-9 | Bulk actions on Invoice List | Select multiple invoices for bulk cancel, bulk export, etc. |
