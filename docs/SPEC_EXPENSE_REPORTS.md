# Expense Reports (CPP-297)

## Overview

Adds expense tracking and reporting for school administrators. Follows the same pattern as Student/Teacher reports: filterable list view with HTMX partial refresh, role-based access, and multi-tenant school isolation.

## Access Control

| Role | View Report | Add/Edit/Delete |
|------|-------------|-----------------|
| Superuser | All schools | Yes |
| Institute Owner | Own schools | Yes |
| Head of Institute | Own schools | Yes |
| Head of Department | Own departments only | No |

## Data Model

`classroom.Expense` with fields: school (FK), department (FK, optional), category (choices), description, amount (decimal 10,2), date, created_by, timestamps.

**Categories:** rent, utilities, salaries, supplies, transport, maintenance, marketing, other.

## Views

- **ExpenseReportView** (`/reports/expenses/`) — filterable list with category, department, date range. HTMX partial at `_partials/expense_report_table.html`. Summary row shows count + total. Paginated (50/page).
- **ExpenseCreateView** (`/expenses/add/`) — form with school auto-set from user context.
- **ExpenseEditView** (`/expenses/<pk>/edit/`) — scoped to user's schools.
- **ExpenseDeleteView** (`/expenses/<pk>/delete/`) — POST-only delete with redirect.

## Templates

- `reports/expenses.html` — main page with filters and HTMX container
- `reports/_partials/expense_report_table.html` — partial table for HTMX swap
- `reports/expense_form.html` — shared add/edit form

## Navigation

Sidebar link added under Reports section in both `sidebar_hoi.html` and `sidebar_hod.html` with banknotes icon.

## Tests

24 pytest-django tests covering: access control (4 roles), filtering (category, department, date range), CRUD operations, school isolation, pagination, empty states.
