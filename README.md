# Requirements Specification
## CWA School — Classroom

**Application Name:** Classroom  
**Hosted at:** classroom.wizardslearninghub.co.nz  
**Version:** 2.0 (Revised — all gaps resolved)  
**Technology Stack:** Django 4.2+, Python 3.10, MySQL 8.0, Pillow, django-storages, stripe  
**Timezone:** Pacific/Auckland (New Zealand)  
**Last Revised:** 2026-02-28  

---

## Revision Log (v1 → v2)

| Gap | Topic | Resolution |
|-----|-------|------------|
| 1 | Student self-registration | **`student` role:** No self-registration. Registered exclusively by teachers via bulk upload or Django admin. **`individual_student` role:** Can self-register at `/register/individual-student/` and select a subscription package. |
| 2 | Payment timing | Account created first → class selection immediately → Stripe checkout activates package. |
| 3 | Times Tables storage | **Runtime-generated.** Not stored in the database. Consistent with Basic Facts. |
| 4 | Colour coding — insufficient data | Colour requires minimum **2 attempts** on the platform. Below threshold: no colour, raw score only. |
| 4b | Colour coding — dual indicator | Dashboard shows **two separate indicators**: (a) personal trend vs own attempt history, (b) platform average via TopicLevelStatistics. |
| 5 | Teacher class progress | **Both** class averages and individual student drill-down. Mixed Quiz results include per-topic breakdown (e.g. "80% Measurements, 20% Fractions"). |
| 6 | Text answer validation | Numeric tolerance: fixed global default **±0.05**. Multiple valid answers: teacher defines comma-separated alternatives in the answer text field. |
| 7 | Practice Mode feedback | Full feedback shown (correct/incorrect + explanations). Results **not saved** to database. |
| 8 | Drag & drop question type | `drag_drop` is a **first-class DB question type**. Student sorts answer tiles into the correct sequence. |
| 9 | Image storage | Local disk (`MEDIA_ROOT`) in development; AWS S3 via `django-storages` in production (`USE_S3` env var). |
| 10 | Discount codes | 100% discount codes at registration skip Stripe entirely and activate the package immediately. |
| 11 | Trial period | 14-day free trial on all paid packages. No card required upfront. After trial: no card or payment failure = Basic Facts only access. |
| 12 | Billing cycle | Starts from trial end date. First charge exactly 14 days after registration. |
| 13 | Package upgrade | Existing class selections kept. Student adds more up to new limit. |
| 14 | Package downgrade | Student must manually remove excess classes before downgrade is confirmed. Takes effect at billing period end. |
| 15 | Mixed Quiz topic tracking | `StudentAnswer` stores `topic` FK, enabling per-topic breakdown in teacher progress views. |
| 16 | Question ingestion | Teachers upload **one JSON file per topic/level** via `/upload-questions/` UI or Django admin. Duplicate detection by question text — identical text overwrites. Images referenced by file path in JSON. |
| 17 | Drag & drop interaction | Student **sorts tiles into the correct sequence** by dragging. |

---

## Table of Contents

1. [Introduction](#1-introduction)
2. [System Overview](#2-system-overview)
3. [User Roles and Authentication](#3-user-roles-and-authentication)
4. [Functional Requirements](#4-functional-requirements)
   - 4.1 [Registration and Authentication](#41-registration-and-authentication)
   - 4.2 [Classroom Management](#42-classroom-management)
   - 4.3 [Student Dashboard](#43-student-dashboard)
   - 4.4 [Teacher Dashboard](#44-teacher-dashboard)
   - 4.4a [HeadOfDepartment Dashboard](#44a-headofdepartment-dashboard)
   - 4.4b [Accountant Dashboard](#44b-accountant-dashboard)
   - 4.5 [Year-Level Subject and Topic System](#45-year-level-subject-and-topic-system)
   - 4.6 [Basic Facts Module](#46-basic-facts-module)
   - 4.7 [Topic-Based Quizzes](#47-topic-based-quizzes)
   - 4.8 [Mixed (Take Quiz) Quizzes](#48-mixed-take-quiz-quizzes)
   - 4.9 [Times Tables](#49-times-tables-multiplication-and-division)
   - 4.10 [Practice Mode](#410-practice-mode)
   - 4.11 [Scoring and Points System](#411-scoring-and-points-system)
   - 4.12 [Progress Tracking and Statistics](#412-progress-tracking-and-statistics)
   - 4.13 [Time Tracking](#413-time-tracking)
   - 4.14 [User Profile Management](#414-user-profile-management)
   - 4.15 [Question Management](#415-question-management)
   - 4.16 [Payments and Subscriptions](#416-payments-and-subscriptions-stripe)
5. [Non-Functional Requirements](#5-non-functional-requirements)
6. [Data Model](#6-data-model)
7. [API Endpoints](#7-api-endpoints)
8. [Appendix A: Mathematics Year-Topic Mapping](#8-appendix-a-mathematics-year-topic-mapping)
9. [Appendix B: JSON Upload Field Reference](#9-appendix-b-json-upload-field-reference)

---

## 1. Introduction

### 1.1 Purpose

This document specifies the functional and non-functional requirements for the **Classroom** web application — an educational platform for primary and intermediate school students (Years 1–8) to practise curriculum content. **Mathematics is the first supported subject**, designed for expansion to additional subjects in the future. The system supports class-based learning managed by teachers, and self-directed individual students with subscription packages.

### 1.2 Scope

- Flexible, extensible role-based access control (Admin, Teacher, Student, IndividualStudent, Accountant, HeadOfDepartment, plus custom roles).
- Class-centric management with many-to-many teacher/student relationships.
- **`student` role:** Registered exclusively by teachers (bulk upload or Django admin) — no self-registration.
- **`individual_student` role:** Can self-register, select a subscription package, and choose their own classes.
- Subscription packages for Individual Students (1, 3, 5, or unlimited classes) with Stripe recurring billing, 14-day free trial (no card required upfront), and 100% discount codes for complimentary access.
- Curriculum structured by Year (1–8), Subject (Mathematics first), and Topic.
- Mathematics modules: Basic Facts drills, Times Tables (both runtime-generated), Topic-Based Quizzes, Mixed Quizzes, and Practice Mode.
- Timed quizzes with points formula rewarding accuracy and speed.
- Dual colour-coded progress tracking: personal trend + platform average comparison.
- Teacher question management via JSON file upload (one file per topic/level) with image path support.
- Media storage: local disk in development, AWS S3 in production.

### 1.3 Intended Audience

Developers building or maintaining the system, teachers and administrators evaluating it, and QA testers validating functionality.

---

## 2. System Overview

Classroom is a server-rendered Django web application. The core app is named `classroom`. Content is organised into **Levels** (Year 1–8; `level_number` ≥ 100 for Basic Facts), **Subjects**, and **Topics**. Each role receives a dedicated dashboard and permission set.

### 2.1 High-Level Architecture

```
Browser (HTML / CSS / JS)
    |
Django Application  (core app: `classroom`)
    |
MySQL 8.0 Database
    |
Media Storage
    ├── Development : Local disk  (MEDIA_ROOT)
    └── Production  : AWS S3      (django-storages, USE_S3=true)
    |
Stripe API  (Checkout, Subscriptions, Webhooks)
```

### 2.2 Deployment

| Concern | Detail |
|---------|--------|
| Production host | classroom.wizardslearninghub.co.nz |
| Database | MySQL 8.0 (all environments) |
| Email | Console backend (dev) · Gmail SMTP (production) |
| Media | `USE_S3` env var switches local ↔ S3 |
| Stripe keys | `STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY`, `STRIPE_WEBHOOK_SECRET` — env vars only, never committed to source control |

---

## 3. User Roles and Authentication

### 3.1 User Model (`CustomUser` extends `AbstractUser`)

| Field | Type | Description |
|-------|------|-------------|
| `date_of_birth` | Date (optional) | Age-based Basic Facts statistics |
| `country` | String (optional) | User's country |
| `region` | String (optional) | User's region/state/province |
| `package` | FK → `Package` (optional) | Active subscription package; null for non-IndividualStudent roles |
| `roles` | M2M → `Role` via `UserRole` | One or more assigned roles |

### 3.2 Role Model

Stored in a dedicated `Role` table. New roles added via Django admin without code changes.

| Field | Type | Description |
|-------|------|-------------|
| `name` | String (unique) | Machine identifier e.g. `teacher`, `individual_student` |
| `display_name` | String | Human-readable label |
| `description` | Text (optional) | Role purpose |
| `is_active` | Boolean | Whether available for assignment |
| `created_at` | DateTime | Creation timestamp |

### 3.3 Built-in Roles

| Role | Identifier | Key Capabilities |
|------|------------|-----------------|
| Admin | `admin` | Full Django admin, role management, package config, system settings |
| Teacher | `teacher` | Create classes, bulk-register students, manage questions (JSON upload + manual form), view class progress |
| Student | `student` | Take quizzes, view personal progress. Access limited to class-assigned levels. **Registered by teachers only — no self-registration.** |
| IndividualStudent | `individual_student` | **Self-registers** at `/register/individual-student/`. Selects a subscription package; accesses classes up to package limit. Take quizzes, view personal progress. |
| Accountant | `accountant` | Financial reports, package/billing management, refunds |
| HeadOfDepartment | `head_of_department` | Assign classes to teachers, view all classes and departmental reports |

### 3.4 Permission Resolution

- Checks use `user.roles.filter(name='...').exists()`.
- Multiple roles → union of all capabilities.
- Primary role priority (dashboard redirect): Admin > HeadOfDepartment > Accountant > Teacher > IndividualStudent > Student.
- No roles assigned → redirect to "contact administrator" page.

### 3.5 Authentication Flows

- **Login:** `/accounts/login/` → role-specific dashboard.
- **Logout:** `/accounts/logout/` → `/`.
- **Password Reset:** Email-based. Token valid 3600 s (configurable via `PASSWORD_RESET_TIMEOUT`).
- **Session:** Django session auth. `LOGIN_REDIRECT_URL = LOGOUT_REDIRECT_URL = '/'`.

---

## 4. Functional Requirements

### 4.1 Registration and Authentication

#### FR-4.1.1 Student Self-Registration — NOT SUPPORTED

Users with the `student` role cannot self-register. `/signup/student/` is not implemented. Class-enrolled students are registered exclusively by teachers (FR-4.1.4) or via Django admin.

This does **not** apply to Individual Students — see FR-4.1.5 for Individual Student self-registration.

#### FR-4.1.2 Teacher Self-Registration

- **URL:** `/signup/teacher/`
- **Fields:** Username, Email, Password, Password Confirmation.
- **Behaviour:** Creates `CustomUser` with `teacher` role. Logs in and redirects to teacher dashboard.

#### FR-4.1.3 Teacher Center Registration

- **URL:** `/register/teacher-center/`
- **Fields:** Username, Email, Password, Password Confirmation, Center/School Name.
- **Behaviour:** Creates `teacher` role user. Displays success message with center name. Redirects to dashboard.

#### FR-4.1.4 Bulk Student Registration (Teacher Only)

- **URL:** `/bulk-student-registration/`
- **Access:** `teacher` role only.
- **Input:** Textarea — one student per line: `username,email,password`.
- **Validation:** Exactly 3 comma-separated values · non-empty username · email contains `@` · password ≥ 8 characters.
- **Behaviour:** Creates all `student` role accounts atomically within a transaction. Reports success count. Individual failures reported as error messages without rolling back other creations. Note: `individual_student` accounts cannot be bulk-registered this way — they must self-register.

#### FR-4.1.5 Individual Student Registration

- **URL:** `/register/individual-student/`
- **Fields:** Username, Email, Password, Password Confirmation, Package Selection, Discount Code (optional).

**Three-step registration flow:**

```
Step 1 — Account creation
    CustomUser created with `individual_student` role + selected package.
    User logged in immediately.

Step 2 — Class selection  (available immediately, before payment)
    Redirected to /select-classes/.
    Student selects classes up to their package limit straight away.

Step 3 — Payment
    If valid 100% discount code entered:
        → Stripe skipped entirely. Package activated immediately.
        → DiscountCode.uses incremented atomically.

    If paid package, no discount code:
        → Stripe Checkout Session created with 14-day trial period.
        → Student redirected to Stripe-hosted checkout (card entry optional).
        → Trial begins immediately. Full package access during trial.
        → 3 days before trial ends: reminder email sent.
        → On trial end day: notification email sent.
        → After trial ends:
            Card provided  → Stripe auto-charges monthly from trial end date.
            No card        → Access downgraded to Basic Facts only.
            Payment fails  → Access downgraded to Basic Facts only.
```

**Billing cycle:** Starts from trial end date. First charge = exactly 14 days after registration.

**Discount Code model (`DiscountCode`):**

| Field | Type | Description |
|-------|------|-------------|
| `code` | String (unique) | Code entered at registration |
| `discount_percent` | Integer | 100 = fully free |
| `max_uses` | Integer (null = unlimited) | Maximum redemptions allowed |
| `uses` | Integer | Current redemption count |
| `is_active` | Boolean | Whether the code can be used |
| `expires_at` | DateTime (optional) | Expiry date/time |

**Package change rules:**
- **Upgrade:** Existing class selections kept. Student can add more up to new limit. Stripe handles price difference.
- **Downgrade:** Student must manually remove classes to meet new limit before downgrade is confirmed. Takes effect at end of current billing period.

#### FR-4.1.6 Role Assignment (Admin Only)

Via Django admin. Admins assign/remove any role to/from any user. Users may hold multiple roles simultaneously.

---

### 4.2 Classroom Management

#### FR-4.2.1 Create Class (Teacher Only)

- **URL:** `/create-class/`
- **Access:** `teacher` role.
- **Fields:** Class Name, Levels (multi-select).
- **Behaviour:** Generates unique 8-character class code (UUID hex prefix). Creating teacher added as member automatically. Redirects to teacher dashboard.

#### FR-4.2.2 Assign Students to Class (Teacher Only)

- **URL:** `/class/<class_id>/assign-students/`
- **Access:** `teacher` role, must be a member of the class.
- **Behaviour:** Adds student(s) to the class, preventing duplicates. Students cannot add themselves.

#### FR-4.2.3 Assign Teachers to Class

- **URL:** `/class/<class_id>/assign-teachers/`
- **Access:** `teacher` (must be class member) **or** `head_of_department` (can act on any class).
- **Behaviour:** Adds teacher(s) as class members. Multiple teachers can co-manage a class.

#### FR-4.2.4 HeadOfDepartment Class-Teacher Management

- **URL:** `/department/manage-classes/`
- **Access:** `head_of_department` role.
- **Behaviour:** Overview of all classes. HoD can assign/remove teachers from any class and view teacher workload (classes per teacher).

#### FR-4.2.5 Individual Student Class Selection

- **URL:** `/select-classes/`
- **Access:** `individual_student` role.
- **Behaviour:** Lists all available classes. Student selects up to their package limit. Available immediately after registration, before payment. Removing a class frees up a slot.

#### FR-4.2.6 Level Access Control

| Role / State | Access |
|--------------|--------|
| `student` | Levels assigned to their class(es) — union across all classes |
| `individual_student` — active or in trial | Levels assigned to selected classes (up to package limit) |
| `individual_student` — trial expired, no payment | **Basic Facts only** (level_number ≥ 100) |
| `teacher` | All levels — no restriction |
| `head_of_department` | All levels — no restriction |
| `accountant` | No quiz content — reporting only |

Basic Facts levels (level_number ≥ 100) are **always accessible** to all students regardless of payment status.

---

### 4.3 Student Dashboard

#### FR-4.3.1 Home Dashboard (`/`)

- **Access:** `@login_required`, `student` or `individual_student` role (others redirected to their dashboards).
- **Content:**
  - Info box: package + trial status + class count (IndividualStudent) or assigned classes (Student).
  - **Basic Facts section:** Grid cards for Addition, Subtraction, Multiplication, Division, Place Value Facts. Each shows available levels.
  - **Year-level sections:** Accordion grouped by Year 1–8. Each expands to show topic cards plus a "Take Quiz" card for the Mixed Quiz.
  - No progress table on home page (progress is on `/dashboard/`).

#### FR-4.3.2 Detailed Dashboard (`/dashboard/`)

- **Access:** `@login_required`, `student` or `individual_student`.
- **Content:** Same layout as home, plus:
  - **Year-Level Progress Table:** Best points, time, date, attempt count per topic-level combination attempted.
  - **Basic Facts Progress Table:** Accordion per subtopic with level-by-level progress.
  - **Dual colour coding** (see FR-4.12.3).
- **Data source priority:** `StudentFinalAnswer` first; fallback to `StudentAnswer` for older records.

---

### 4.4 Teacher Dashboard

#### FR-4.4.1 Teacher Home Dashboard (`/`)

- **Access:** `@login_required`, `teacher` role.
- **Content:**
  - All classes the teacher belongs to: name, code, student count, co-teacher count.
  - Per-class actions: Manage Students · Manage Teachers · View Class Progress.
  - Global actions: Create Class · Bulk Register Students · Browse Topics · Upload Questions.

#### FR-4.4.2 Class Progress View (`/class/<class_id>/progress/`)

- **Access:** `@login_required`, `teacher` role, member of the class.
- **Content:**
  - **Class averages panel:** Average best score per topic/level across all students in the class.
  - **Individual student drill-down:** Expandable rows per student showing best score, attempt count, and last attempt date per topic/level.
  - **Mixed Quiz topic breakdown:** For Mixed Quiz attempts, a percentage-correct summary per topic sourced from `StudentAnswer.topic` (e.g. "Measurements 80% · Fractions 40% · Place Values 100%").
  - Colour coding consistent with student dashboard (FR-4.12.3).

---

### 4.4a HeadOfDepartment Dashboard

#### FR-4.4a.1 HoD Dashboard (`/department/`)

- **Access:** `@login_required`, `head_of_department` role.
- **Content:** All classes table (name, code, teachers, student count, levels) · Teacher workload list (classes per teacher) · Class-teacher assignment controls · Departmental progress reports (average scores, completion rates by level/topic).

---

### 4.4b Accountant Dashboard

#### FR-4.4b.1 Accountant Dashboard (`/accounting/`)

- **Access:** `@login_required`, `accountant` role.
- **Content:**
  - Package subscription overview: students grouped by package tier with counts and revenue.
  - Trial status overview: students in active trial · trial-expired with no payment.
  - User statistics: total by role · active (logged in within last 30 days) · new registrations over time.
  - Class statistics: total classes · average students per class · average teachers per class.
  - Financial reports: subscription billing data.
  - Actions: Manage Packages · Export Reports (CSV/PDF).

---

### 4.5 Year-Level Subject and Topic System

- **Levels:** `level_number` 1–8 for Years 1–8. `level_number` ≥ 100 for Basic Facts.
- **Subjects:** e.g. Mathematics. Designed for multiple subjects over time.
- **Topics:** Sub-areas within a subject (e.g. Measurements, Fractions, BODMAS/PEMDAS).

#### FR-4.5.1 Topic Browsing

- `/topics/` — all Mathematics topics (current implementation).
- `/topic/<topic_id>/levels/` — levels for a topic, filtered to student's allowed levels.
- `/subjects/` and `/subject/<id>/topics/` — reserved for future multi-subject expansion.

#### FR-4.5.2 Level Detail

- **URL:** `/level/<level_number>/`
- **Access:** `@login_required`, level access control enforced.

---

### 4.6 Basic Facts Module

#### FR-4.6.1 Overview

Drill-based arithmetic module. Questions are **dynamically generated at runtime — never stored in the database**. Accessible to all students regardless of class membership or payment status.

| Subtopic | Internal Levels | Display Levels | Questions/Quiz |
|----------|----------------|----------------|----------------|
| Addition | 100–106 | 1–7 | 10 |
| Subtraction | 107–113 | 1–7 | 10 |
| Multiplication | 114–120 | 1–7 | 10 |
| Division | 121–127 | 1–7 | 10 |
| Place Value Facts | 128–132 | 1–5 | 10 |

#### FR-4.6.2 Subtopic Selection

- **URL:** `/basic-facts/<subtopic_name>/`
- **Access:** `@login_required`.
- Displays level selection page. Selecting a level starts the quiz.

#### FR-4.6.3 Dynamic Question Generation

**Addition (100–106):**
Level 100: digits 1–5 · 101: digits 0–9 · 102: 2-digit no carry · 103: 2-digit with carry (units ≥ 10) · 104: 3-digit + 3-digit · 105: 4-digit + 4-digit · 106: 5-digit + 5-digit

**Subtraction (107–113):**
Level 107: single-digit (result ≥ 0) · 108: 2d−1d no borrow · 109: 2d−1d with borrow · 110: 2d−2d (result ≥ 0) · 111: 2d−2d (may be negative) · 112: 3-digit · 113: 4-digit

**Multiplication (114–120):**
Level 114: ×1 or ×10 · 115: ×1/10/100 · 116: ×5/10 · 117: ×2/3/5/10 · 118: ×2–5/10 (2–3 digit base) · 119: ×2–7/10 (2–3 digit base) · 120: ×2–10 (3-digit base)

**Division (121–127):**
Level 121: ÷1/10 (exact) · 122: ÷1/10/100 (exact) · 123: ÷5/10 · 124: ÷2/3/5/10 · 125: ÷2–5/10 · 126: ÷2–7/10 · 127: ÷2–11

**Place Value Facts (128–132):**
Level 128: make 10 · 129: make 100 · 130: make 1,000 · 131: make 10,000 · 132: make 100,000

Each Place Value question randomly uses one of three formats: `a + b = ?` · `a + ? = target` · `? + b = target`

#### FR-4.6.4 Basic Facts Quiz Flow

1. GET → 10 questions generated, stored in session, server timer starts.
2. All 10 questions displayed at once; student fills in numeric answers.
3. POST → graded, time calculated, points computed (FR-4.11), results saved to `BasicFactsResult`.
4. Completion screen: score, time, points, new-record indicator, question review popup.
5. Duplicate prevention: result saved within last 5 s → show existing result instead.
6. Refresh within 30 s of completion → show completion screen again.

---

### 4.7 Topic-Based Quizzes

#### FR-4.7.1 Overview

Questions stored in the database per topic/level. Selected via stratified random sampling, presented one at a time with AJAX answer submission.

**Supported Mathematics Topics:** Measurements · Whole Numbers · Factors · Angles · Place Values · Fractions · BODMAS/PEMDAS · Date and Time · Finance · Integers · Trigonometry *(extensible — additional topics can be added without code changes)*

#### FR-4.7.2 Question Selection

Stratified random sampling: question pool divided into equal-sized blocks, one selected per block. Excluded: questions with no answers, no correct answer, or (for multiple choice) no wrong answers. Answer order randomised per question.

| Year | Questions per Quiz |
|------|--------------------|
| 1 | 12 |
| 2 | 10 |
| 3 | 12 |
| 4 | 15 |
| 5 | 17 |
| 6 | 20 |
| 7 | 22 |
| 8 | 25 |

#### FR-4.7.3 Quiz Flow (Client-Side Rendering)

1. **Initial Load:** All selected questions + shuffled answers serialised as JSON to client. Server timer starts.
2. **Navigation:** Rendered client-side one question at a time (JavaScript).
3. **Answer submission:** AJAX POST to `/api/submit-topic-answer/`. Server returns: `is_correct`, `correct_answer`, `explanation`.
4. **Completion:** All answered → client redirects to `?completed=1`. Server calculates final score, time, points, and renders results page.

#### FR-4.7.4 Question Types

| Type | `question_type` DB value | Student Input |
|------|--------------------------|---------------|
| Multiple Choice | `multiple_choice` | Radio buttons (one correct answer) |
| True / False | `true_false` | Radio buttons (True / False) |
| Short Answer | `short_answer` | Text input |
| Fill in the Blank | `fill_blank` | Text input |
| Calculation | `calculation` | Text input |
| Drag & Drop | `drag_drop` | Drag tiles into the correct sequence |

#### FR-4.7.5 Text Answer Validation

Applies to `short_answer`, `fill_blank`, `calculation` types:

- **Multiple valid answers:** Teacher stores comma-separated alternatives in `Answer.text` (e.g. `"6,six,Six"`). Any matching value is accepted.
- **Numeric tolerance:** A global default of **±0.05** is applied when the correct answer is numeric. No per-question configuration.

#### FR-4.7.6 Drag & Drop Questions

- **Interaction:** Student is presented with answer tiles in a randomised order and must drag them into the correct sequence.
- **Storage:** Each `Answer` record for a `drag_drop` question stores `text` (tile content) and `display_order` (correct position in sequence). `is_correct` is always `true` for all answers — correctness is determined by whether the student's submitted order matches `display_order` values.
- **Validation:** Submitted order (array of answer IDs) compared against correct `display_order` sequence. Fully correct = full points. No partial credit.
- **Images:** Drag & drop questions support an optional image on the question stem; tile content is text only.

#### FR-4.7.7 Question Attributes

| Field | Required | Description |
|-------|----------|-------------|
| `question_text` | Yes | The question text |
| `question_type` | Yes | See FR-4.7.4 (default: `multiple_choice`) |
| `difficulty` | Yes | 1 = Easy · 2 = Medium · 3 = Hard |
| `points` | Yes | Default: 1 |
| `explanation` | No | Shown to student after answering |
| `image` | No | Optional image (local or S3) |
| `topic` | Yes | FK to `Topic` |
| `level` | Yes | FK to `Level` |

---

### 4.8 Mixed (Take Quiz) Quizzes

- **URL:** `/level/<level_number>/quiz/`
- **Access:** `@login_required`, level access control applies.
- **Behaviour:** Selects random questions from **all topics** for the given level using the same question count limits as topic-based quizzes (FR-4.7.2). Presents all questions at once. On submission, grades answers, calculates points, saves to `StudentAnswer` (with `topic` FK populated per question) and `StudentFinalAnswer` (topic label = "Quiz").
- **Topic tracking:** Each `StudentAnswer` stores the `topic` FK from its source question, enabling per-topic breakdown in the teacher progress view.
- **Results page:** Score, time, points, record status, question review, explanations, and a **per-topic summary** (e.g. "Measurements: 8/10 · Fractions: 4/5 · Place Values: 3/5").

---

### 4.9 Times Tables (Multiplication and Division)

#### FR-4.9.1 Overview

Structured multiplication and division practice. Questions are **runtime-generated — not stored in the database**. Consistent with Basic Facts approach.

#### FR-4.9.2 Available Tables by Year

| Year | Available Tables |
|------|-----------------|
| 1 | 1× |
| 2 | 1×, 2×, 10× |
| 3 | 1×–5×, 10× |
| 4 | 1×–10× |
| 5–8 | 1×–12× |

#### FR-4.9.3 Quiz Generation

- **Multiplication:** Table N generates N×1 through N×12 (12 questions).
- **Division:** Table N generates (N×1)÷N through (N×12)÷N (12 questions).
- Format: multiple choice with 1 correct answer and 3 plausible distractors (nearby numbers).
- Questions generated fresh on each load — never cached or stored.

#### FR-4.9.4 URLs

- Table selection: `/level/<level_number>/multiplication/` · `/level/<level_number>/division/`
- Quiz: `/level/<level_number>/multiplication/<table_number>/` · `/level/<level_number>/division/<table_number>/`
- Uses the same AJAX-based quiz flow as topic quizzes (FR-4.7.3).

---

### 4.10 Practice Mode

- **URL:** `/level/<level_number>/practice/`
- **Access:** `@login_required`, level access control applies.
- **Behaviour:** Selects up to 10 random questions from all topics for the level (stratified sampling if >10 available). Displays all questions at once. No timer.
- **Results are NOT saved** to any table. No time tracking.
- **Feedback after submission:** Full feedback — correct/incorrect per question plus explanations. Student can review all answers before navigating away.

---

### 4.11 Scoring and Points System

#### FR-4.11.1 Points Formula

```
Points = (Percentage_Correct × 100 × 60) / Time_Taken_Seconds
```

Where:
- `Percentage_Correct` = Correct / Total (value 0–1)
- `Time_Taken_Seconds` = Elapsed seconds from quiz start to submission (minimum 1)

**Basic Facts (10 questions — shorter quiz):**
```
Basic Facts Points = ((Percentage_Correct × 100 × 60) / Time_Taken_Seconds) / 10
```

#### FR-4.11.2 Record Tracking

- Each attempt tracked with a unique `session_id` (UUID).
- Current attempt compared against student's **previous best** for the same level-topic combination.
- Completion screen labels: "First attempt" · "New record!" · "Previous best: X pts".

---

### 4.12 Progress Tracking and Statistics

#### FR-4.12.1 StudentFinalAnswer

One record per quiz attempt (`session_id`). `attempt_number` auto-increments per student-topic-level combination. Helper methods: `get_best_result()`, `get_latest_attempt()`, `get_next_attempt_number()`. Saved within an atomic transaction with retry logic to prevent race conditions.

#### FR-4.12.2 TopicLevelStatistics

For each topic-level combination, stores:
- `avg_points` — average across all students' best results
- `sigma` — standard deviation
- `student_count` — number of students with data

Updated **asynchronously** in a background thread after each quiz completion. Never blocks quiz responses.

**Basic Facts statistics** additionally grouped by student age (`level_number = 2000 + age`).

#### FR-4.12.3 Dual Colour Coding

The student progress dashboard (`/dashboard/`) displays **two separate visual indicators** per topic-level row.

**Indicator A — Personal Trend** (student's latest score vs their own history):

| Indicator | Condition | Meaning |
|-----------|-----------|---------|
| ↑ Green arrow | Latest > previous best | Improving |
| → Grey arrow | Latest = previous best | Steady |
| ↓ Orange arrow | Latest < previous best | Declining |
| — (none) | Fewer than 2 personal attempts | Not enough data |

**Indicator B — Platform Average** (student's best score vs `TopicLevelStatistics`):

| Colour | Condition | Meaning |
|--------|-----------|---------|
| No colour | Fewer than 2 total attempts on platform | Not enough data — raw score shown only |
| Dark Green | Points > avg + 2σ | Exceptional |
| Green | avg + σ < Points ≤ avg + 2σ | Above average |
| Light Green | avg − σ < Points ≤ avg + σ | Average |
| Yellow | avg − 2σ < Points ≤ avg − σ | Below average |
| Orange | avg − 3σ < Points ≤ avg − 2σ | Significantly below average |
| Red | Points ≤ avg − 3σ | Needs significant improvement |

The threshold for both indicators is **2 attempts**. Below this threshold no colour/arrow is shown — only the raw score is displayed.

#### FR-4.12.4 Student Progress Detail

- **URL:** `/level/<level_number>/student-progress/`
- **Access:** `@login_required`.
- Shows all topics at a specific level with full attempt history.

---

### 4.13 Time Tracking

#### FR-4.13.1 TimeLog Model

One `TimeLog` record per student (1-to-1 with `CustomUser`). Tracks:
- `daily_seconds` — time on platform today (resets at midnight NZT)
- `weekly_seconds` — time on platform this week (resets Monday midnight NZT)
- `last_updated` — last update timestamp

#### FR-4.13.2 Update Time Log API

See FR-7.1.

---

### 4.14 User Profile Management

#### FR-4.14.1 Profile Page

- **URL:** `/profile/`
- **Access:** `@login_required`.
- **View/edit:** Date of birth, country, region, email, first name, last name.
- **Change password:** Current password, new password, confirm (minimum 8 characters). Uses `update_session_auth_hash` to maintain authenticated session.
- **IndividualStudent extras:** Current package name, trial status, trial end date, next billing date, and a link to `/account/change-package/`.

---

### 4.15 Question Management

#### FR-4.15.1 View Level Questions

- **URL:** `/level/<level_number>/questions/`
- **Access:** `@login_required`.
- Displays all database questions for a level: text, type, difficulty, answer count.

#### FR-4.15.2 Manual Add Question (Teacher)

- **URL:** `/level/<level_number>/add-question/`
- **Access:** `teacher` role.
- **Fields:** Question text, type, difficulty (1–3), points, explanation, optional image, up to 4 answers (text, is_correct, display_order).
- For `drag_drop`, all answers have `is_correct = true`; `display_order` defines the correct sequence.
- **Behaviour:** Creates question and answers atomically. Redirects to level questions page.

#### FR-4.15.3 Edit / Delete Question (Teacher)

- **URLs:** `/question/<question_id>/edit/` · `/question/<question_id>/delete/`
- **Access:** `teacher` role.
- Edit updates question and all answers atomically.
- Delete removes the question, all associated `Answer` records, and all associated `StudentAnswer` records.

#### FR-4.15.4 JSON Question Upload

**Purpose:** Primary method for loading question banks into the database. One JSON file per topic/level combination.

**Access:**
- Teacher-facing UI: `/upload-questions/` (requires `teacher` role)
- Admin: Django admin interface

**File naming convention (recommended, not enforced):** `<topic>_year<level>.json` e.g. `fractions_year3.json`

**JSON File Format:**

```json
{
  "topic": "Fractions",
  "year_level": 3,
  "questions": [
    {
      "question_text": "What is 1/2 of 10?",
      "question_type": "multiple_choice",
      "difficulty": 1,
      "points": 1,
      "explanation": "Half of 10 is 5. Divide 10 by 2.",
      "image_path": "images/fractions/half_of_10.png",
      "answers": [
        { "text": "5",  "is_correct": true,  "display_order": 1 },
        { "text": "2",  "is_correct": false, "display_order": 2 },
        { "text": "4",  "is_correct": false, "display_order": 3 },
        { "text": "20", "is_correct": false, "display_order": 4 }
      ]
    },
    {
      "question_text": "Order these fractions from smallest to largest.",
      "question_type": "drag_drop",
      "difficulty": 2,
      "points": 2,
      "explanation": "1/4 < 1/2 < 3/4 < 1. Think of pieces of a pie.",
      "image_path": null,
      "answers": [
        { "text": "1/4", "is_correct": true, "display_order": 1 },
        { "text": "1/2", "is_correct": true, "display_order": 2 },
        { "text": "3/4", "is_correct": true, "display_order": 3 },
        { "text": "1",   "is_correct": true, "display_order": 4 }
      ]
    },
    {
      "question_text": "0.5 + ___ = 1.0",
      "question_type": "fill_blank",
      "difficulty": 2,
      "points": 1,
      "explanation": "1.0 − 0.5 = 0.5",
      "image_path": null,
      "answers": [
        { "text": "0.5,1/2,half", "is_correct": true, "display_order": 1 }
      ]
    }
  ]
}
```

**Image path handling:**
- `image_path` is relative to `MEDIA_ROOT` (dev) or the S3 bucket root (production).
- Images must be uploaded to media storage separately before the JSON is processed.
- If `image_path` is provided but the file does not exist: question is still imported, a warning is logged, the image field is left blank.
- `image_path: null` means no image.

**Duplicate handling (matched by `question_text` + topic + level):**
- Identical text for the same topic/level → **silently overwrite** all fields (type, difficulty, points, explanation, image, answers).
- No match → insert as new question.

**Upload response shows:**
- Count of newly inserted questions.
- Count of overwritten (updated) questions.
- Count of failed questions (with validation error details per question).

**Per-question validation errors (question skipped on failure):**
- Missing `question_text`
- Invalid `question_type` value
- No answers provided
- `drag_drop` answers missing `display_order`

---

### 4.16 Payments and Subscriptions (Stripe)

#### FR-4.16.1 Stripe Configuration

- Library: `stripe` Python SDK (server-side) + Stripe.js (client-side where needed).
- Keys as environment variables: `STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY`, `STRIPE_WEBHOOK_SECRET`.
- Supports test mode (dev/staging) and live mode (production) via separate key sets.
- Currency: configurable; default **NZD**.

#### FR-4.16.2 Package Model

| Field | Type | Description |
|-------|------|-------------|
| `name` | String | e.g. "3 Classes" |
| `class_limit` | Integer | 0 = unlimited |
| `price` | Decimal | 0.00 = free |
| `stripe_price_id` | String (optional) | Linked Stripe Price object |
| `billing_type` | String | `recurring` (monthly) |
| `trial_days` | Integer | Default: 14 |
| `is_active` | Boolean | Whether selectable at registration |

#### FR-4.16.3 Checkout Flow

1. Student selects package + optional discount code at registration.
2. If valid 100% discount code → package activated immediately, Stripe skipped, `DiscountCode.uses` incremented atomically.
3. If `Package.price == 0.00` → Stripe skipped, package activated immediately.
4. If paid package, no discount code:
   - Server creates a Stripe Checkout Session with `trial_period_days = 14`, `success_url`, `cancel_url`, metadata (`user_id`, `package_id`).
   - Student redirected to Stripe-hosted checkout. Card entry is optional during trial.
   - On successful payment: `checkout.session.completed` webhook fires → package activated, `Payment` record created.

#### FR-4.16.4 Package Upgrade / Downgrade

- **URL:** `/account/change-package/`
- **Access:** `individual_student` role.
- **Upgrade:** Existing classes kept; more slots available immediately; new Stripe Checkout for price difference.
- **Downgrade:** Student must remove excess classes first; change queued to billing period end; Stripe subscription updated via API.

#### FR-4.16.5 Stripe Webhooks

- **URL:** `/stripe/webhook/` (public; verified via `STRIPE_WEBHOOK_SECRET` signature check before any processing)
- **Idempotent:** Same event processed multiple times produces the same result.

| Stripe Event | Application Action |
|---|---|
| `checkout.session.completed` | Activate package; create `Payment` record |
| `invoice.payment_succeeded` | Renew subscription; update `Payment` record |
| `invoice.payment_failed` | Mark subscription `past_due`; downgrade access to Basic Facts only; email student |
| `customer.subscription.updated` | Sync subscription status and period dates |
| `customer.subscription.deleted` | Deactivate package; restrict access to Basic Facts only |
| `charge.refunded` | Update `Payment.status` to `refunded`; optionally downgrade package |

#### FR-4.16.6 Refunds

- **URL:** `/accounting/refund/<payment_id>/`
- **Access:** `accountant` or `admin` role.
- Initiates full or partial refund via Stripe Refunds API. Updates `Payment.status` to `refunded`. Optionally deactivates or downgrades package per refund policy.

---

## 5. Non-Functional Requirements

### NFR-5.1 Performance

- `select_related` and `prefetch_related` throughout to prevent N+1 queries.
- `TopicLevelStatistics` updated asynchronously in background threads — never blocks quiz submission responses.
- Database operations use retry logic with exponential backoff for transient errors.

### NFR-5.2 Security

- CSRF protection enabled globally via Django middleware.
- `@login_required` on all sensitive views.
- Role checks via `user.roles.filter(name='...').exists()` — never boolean flags on the user model.
- Level access control enforced on all quiz and content views.
- Password reset tokens expire after 3600 s (configurable).
- Role assignment restricted to Admin only.
- All payments via Stripe Checkout — no raw card data on application server (PCI DSS compliant).
- Webhook signature verified before processing.
- AWS S3 credentials stored as environment variables only.

### NFR-5.3 Reliability

- Atomic transactions for: bulk student registration, question creation, `StudentFinalAnswer` saving, discount code redemption.
- Retry logic with exponential backoff for transient DB errors.
- Duplicate quiz submission prevention (5-second deduplication window).
- Graceful fallback: `StudentFinalAnswer` → `StudentAnswer` for progress display.
- Stripe webhook handlers are fully idempotent.

### NFR-5.4 Scalability

- MySQL 8.0 across all environments for consistent behaviour.
- S3 for media in production — no local disk dependency at scale.

### NFR-5.5 Usability

- Responsive design (mobile-friendly CSS with media queries).
- Accordion-based year-level navigation on student dashboard.
- Dual colour-coded progress indicators (personal trend arrow + platform average background colour).
- Immediate AJAX feedback per question in topic quizzes.
- Full feedback in Practice Mode (not saved).
- Trial status, trial end date, and next billing date clearly visible in student profile.

### NFR-5.6 Timezone Handling

- All daily/weekly time resets and date comparisons use **Pacific/Auckland** local time.
- Database timestamps stored in UTC; converted to NZT in application logic.

---

## 6. Data Model

### 6.1 Entity Relationship Summary

```
Role ──────────── UserRole ──────────── CustomUser
                                             │
                          ┌──────────────────┤
                          │                  │
                     ClassTeacher       ClassStudent
                          │                  │
                       ClassRoom ◄───────────┘
                          │
                       Level (M2M assigned to class)

Subject ── Topic ── Level ── Question ── Answer
                                │
                         StudentAnswer  (topic FK → enables Mixed Quiz breakdown)
                         StudentFinalAnswer
                         BasicFactsResult

CustomUser ──── TimeLog            (1-to-1)
CustomUser ──── Package            (FK, optional — IndividualStudent only)
CustomUser ──── Subscription       (1-to-1, optional)
CustomUser ──── Payment            (1-to-many)

DiscountCode   (standalone — checked atomically at registration)
```

### 6.2 Key Models

| Model | Purpose |
|-------|---------|
| `Role` | Named role definition. Extensible via Django admin. |
| `UserRole` | M2M through table (user ↔ role) with `assigned_at`, `assigned_by` audit fields |
| `CustomUser` | Extended user with M2M roles, personal info, optional package FK |
| `DiscountCode` | Discount codes for free/reduced package activation |
| `Package` | Subscription tier: price, class_limit, stripe_price_id, trial_days, is_active |
| `Payment` | One-time or initial payment record (Stripe IDs, amount, currency, status) |
| `Subscription` | Recurring subscription synced with Stripe (status includes `trialing`, trial_end, billing period) |
| `Subject` | Curriculum subject (e.g. Mathematics) |
| `Topic` | Topic within a subject (e.g. Fractions) |
| `Level` | Year level or Basic Facts level by `level_number` |
| `ClassRoom` | Class with unique code; M2M to teachers and students; assigned levels |
| `ClassTeacher` | Teacher ↔ class M2M through table |
| `ClassStudent` | Student ↔ class M2M through table |
| `Question` | Quiz question: type, difficulty, points, optional image, topic FK, level FK |
| `Answer` | Answer option: text (comma-separated alternatives for text types), is_correct, display_order. For `drag_drop`: all `is_correct=true`; `display_order` = correct sequence. |
| `StudentAnswer` | Individual student response. Stores `topic` FK for Mixed Quiz per-topic breakdown. |
| `BasicFactsResult` | Complete Basic Facts attempt (runtime-generated questions — no Question FK) |
| `StudentFinalAnswer` | Aggregated result per quiz attempt: session_id, points, time, attempt_number |
| `TimeLog` | Daily/weekly time-on-task per student |
| `TopicLevelStatistics` | avg_points, sigma, student_count per topic-level (updated asynchronously) |

---

## 7. API Endpoints

### 7.1 Update Time Log

| Property | Value |
|----------|-------|
| **URL** | `/api/update-time-log/` |
| **Methods** | GET, POST |
| **Auth** | Login required · `student` or `individual_student` role |
| **Response** | `{ "success": true, "daily_seconds": int, "weekly_seconds": int }` |

### 7.2 Submit Topic Answer

| Property | Value |
|----------|-------|
| **URL** | `/api/submit-topic-answer/` |
| **Method** | POST (JSON body) |
| **Auth** | Login required |
| **Request** | `{ "question_id": int, "answer_id": int?, "text_answer": str?, "ordered_answer_ids": [int]?, "attempt_id": str }` |
| **Response** | `{ "success": true, "is_correct": bool, "correct_answer_id": int?, "correct_answer_text": str, "explanation": str }` |

**Field usage by question type:**
- `answer_id` → `multiple_choice`, `true_false`
- `text_answer` → `short_answer`, `fill_blank`, `calculation`
- `ordered_answer_ids` → `drag_drop` (array of answer IDs in student's submitted sequence)

---

## 8. Appendix A: Mathematics Year-Topic Mapping

| Year | Topics Available |
|------|-----------------|
| 1 | Multiplication (times tables), Division (times tables) |
| 2 | Measurements, Place Values, Multiplication (times tables), Division (times tables) |
| 3 | Measurements, Fractions, Finance, Date and Time, Multiplication (times tables), Division (times tables) |
| 4 | Fractions, Integers, Place Values, Multiplication (times tables), Division (times tables) |
| 5 | Measurements, BODMAS/PEMDAS, Multiplication (times tables), Division (times tables) |
| 6 | Measurements, BODMAS/PEMDAS, Whole Numbers, Factors, Angles |
| 7 | Measurements, BODMAS/PEMDAS, Integers, Factors, Fractions |
| 8 | Trigonometry, Integers, Factors, Fractions |

**Note:** Basic Facts (Addition, Subtraction, Multiplication drill, Division drill, Place Value Facts) are accessible to **all** students at all year levels regardless of the year-topic mapping above and regardless of payment/trial status.

---

## 9. Appendix B: JSON Upload Field Reference

| Field | Required | Type | Notes |
|-------|----------|------|-------|
| `topic` | Yes | String | Must match an existing `Topic.name` in the database |
| `year_level` | Yes | Integer | 1–8 |
| `questions[].question_text` | Yes | String | Duplicate detection key (matched with topic + level) |
| `questions[].question_type` | Yes | String | `multiple_choice` / `true_false` / `short_answer` / `fill_blank` / `calculation` / `drag_drop` |
| `questions[].difficulty` | Yes | Integer | 1 (Easy), 2 (Medium), 3 (Hard) |
| `questions[].points` | No | Integer | Default: 1 |
| `questions[].explanation` | No | String | Shown to student after answering |
| `questions[].image_path` | No | String or null | Relative path in media storage. Missing file = warning logged, field left blank. |
| `questions[].answers[].text` | Yes | String | For `fill_blank`/`short_answer`/`calculation`: comma-separated alternatives (e.g. `"0.5,1/2,half"`) |
| `questions[].answers[].is_correct` | Yes | Boolean | For `drag_drop`: always `true`. For others: exactly one `true` per question (multiple choice) or two `true` (true/false not applicable — use `true_false` type). |
| `questions[].answers[].display_order` | Yes for `drag_drop` | Integer | For `drag_drop`: correct position in sequence (1-indexed). For other types: display order of answer options. |

---

*End of Requirements Specification v2.0*
