# CWA School — Classroom
# Master Project Specification

**Application Name:** Classroom  
**Hosted at:** classroom.wizardslearninghub.co.nz  
**Version:** 3.0 (Merged Master — Requirements + UI + Navigation)  
**Technology Stack:** Django 4.2+, Python 3.10, MySQL 8.0, Pillow, django-storages, stripe, HTMX, Tailwind CSS  
**Timezone:** Pacific/Auckland (New Zealand)  
**Last Revised:** 2026-02-28  

---

## Table of Contents

1. [Introduction](#1-introduction)
2. [System Overview](#2-system-overview)
3. [Design System](#3-design-system)
4. [Layout & Navigation](#4-layout--navigation)
5. [User Roles & Authentication](#5-user-roles--authentication)
   - 5.1 [Registration & Auth — Requirements](#51-registration--auth--requirements)
   - 5.2 [Registration & Auth — UI](#52-registration--auth--ui)
6. [Classroom Management](#6-classroom-management)
   - 6.1 [Requirements](#61-requirements)
   - 6.2 [UI](#62-ui)
7. [Student Dashboard](#7-student-dashboard)
   - 7.1 [Requirements](#71-requirements)
   - 7.2 [UI](#72-ui)
8. [Basic Facts Module](#8-basic-facts-module)
   - 8.1 [Requirements](#81-requirements)
   - 8.2 [UI & Templates](#82-ui--templates)
9. [Topic-Based Quizzes](#9-topic-based-quizzes)
   - 9.1 [Requirements](#91-requirements)
   - 9.2 [UI & Templates](#92-ui--templates)
10. [Mixed Quiz](#10-mixed-quiz)
    - 10.1 [Requirements](#101-requirements)
    - 10.2 [UI & Templates](#102-ui--templates)
11. [Times Tables](#11-times-tables)
    - 11.1 [Requirements](#111-requirements)
    - 11.2 [UI & Templates](#112-ui--templates)
12. [Scoring & Points System](#12-scoring--points-system)
13. [Progress Tracking & Statistics](#13-progress-tracking--statistics)
    - 13.1 [Requirements](#131-requirements)
    - 13.2 [UI](#132-ui)
14. [Time Tracking](#14-time-tracking)
15. [Teacher Dashboard & Tools](#15-teacher-dashboard--tools)
    - 15.1 [Requirements](#151-requirements)
    - 15.2 [UI](#152-ui)
16. [Question Management](#16-question-management)
    - 16.1 [Requirements](#161-requirements)
    - 16.2 [UI & Templates](#162-ui--templates)
17. [HeadOfDepartment Dashboard](#17-headofdepartment-dashboard)
    - 17.1 [Requirements](#171-requirements)
    - 17.2 [UI](#172-ui)
18. [Accountant Dashboard](#18-accountant-dashboard)
    - 18.1 [Requirements](#181-requirements)
    - 18.2 [UI](#182-ui)
19. [User Profile Management](#19-user-profile-management)
    - 19.1 [Requirements](#191-requirements)
    - 19.2 [UI](#192-ui)
20. [Payments & Subscriptions](#20-payments--subscriptions)
    - 20.1 [Requirements](#201-requirements)
    - 20.2 [UI](#202-ui)
21. [Non-Functional Requirements](#21-non-functional-requirements)
22. [Data Model](#22-data-model)
23. [API Endpoints](#23-api-endpoints)
24. [URL Structure](#24-url-structure)
25. [Template Structure](#25-template-structure)
26. [Appendix A — Mathematics Year-Topic Mapping](#26-appendix-a--mathematics-year-topic-mapping)
27. [Appendix B — JSON Upload Field Reference](#27-appendix-b--json-upload-field-reference)
28. [Appendix C — Quiz Behaviour Summary](#28-appendix-c--quiz-behaviour-summary)

---

## 1. Introduction

### 1.1 Purpose

This document is the **single source of truth** for the Classroom web application — an educational platform for primary and intermediate school students (Years 1–8) to practise curriculum content. It combines functional requirements, UI specifications, navigation structure, and template design into one interleaved reference.

**Mathematics is the first supported subject**, with the platform designed for expansion to additional subjects in the future. The system supports class-based learning managed by teachers, and self-directed individual students with subscription packages.

### 1.2 Scope

- Flexible, extensible role-based access control: Admin, Teacher, Student, IndividualStudent, Accountant, HeadOfDepartment, plus custom roles.
- Class-centric management with many-to-many teacher/student relationships.
- **`student` role:** Registered exclusively by teachers — no self-registration.
- **`individual_student` role:** Self-registers, selects a subscription package, and chooses their own classes.
- Subscription packages (1, 3, 5, or unlimited classes) with Stripe recurring billing, 14-day free trial (no card required), and 100% discount codes.
- Curriculum: Year (1–8) → Subject (Mathematics) → Topic.
- Quiz modules: Basic Facts, Times Tables (runtime-generated), Topic Quiz, Mixed Quiz.
- ~~Practice Mode~~ — **removed from scope.**
- Timed quizzes with points formula rewarding accuracy and speed.
- Dual colour-coded progress: personal trend + platform average.
- Teacher question management via JSON upload with image path support.
- Media storage: local disk (dev), AWS S3 (production).
- Frontend: Django templates + HTMX + Tailwind CSS.

### 1.3 Intended Audience

Developers building or maintaining the system, teachers and administrators evaluating it, and QA testers validating functionality.

---

## 2. System Overview

Classroom is a server-rendered Django web application organised into five Django apps:

| App | Responsibility |
|-----|---------------|
| `accounts` | Users, roles, registration, authentication |
| `classroom` | Classes, levels, subjects, topics |
| `quiz` | Questions, answers, quiz engine, Basic Facts, Times Tables |
| `billing` | Packages, subscriptions, Stripe, discount codes |
| `progress` | Student answers, statistics, time tracking |

### 2.1 High-Level Architecture

```
Browser (HTML / CSS / HTMX)
    |
Django Application
    ├── accounts app
    ├── classroom app
    ├── quiz app
    ├── billing app
    └── progress app
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
| Project root | `cwa_classroom` |
| Production host | classroom.wizardslearninghub.co.nz |
| Database | MySQL 8.0 (all environments) |
| Email | Console backend (dev) · Gmail SMTP (production) |
| Media | `USE_S3` env var switches local ↔ S3 |
| Stripe keys | `STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY`, `STRIPE_WEBHOOK_SECRET` — env vars only |

---

## 3. Design System

### 3.1 Colour Palette

| Token | Hex | Usage |
|-------|-----|-------|
| `primary` | `#16a34a` | Primary actions, active nav, buttons |
| `primary-dark` | `#15803d` | Hover on primary |
| `primary-light` | `#bbf7d0` | Backgrounds, badges, highlights |
| `accent` | `#eab308` | Stars, achievements, CTAs |
| `accent-dark` | `#ca8a04` | Hover on accent |
| `accent-light` | `#fef9c3` | Soft backgrounds |
| `surface` | `#ffffff` | Cards, panels |
| `surface-alt` | `#f0fdf4` | Page backgrounds |
| `border` | `#d1fae5` | Dividers, card borders |
| `text-primary` | `#14532d` | Headings |
| `text-body` | `#374151` | Body copy |
| `text-muted` | `#6b7280` | Secondary text, labels |
| `danger` | `#ef4444` | Errors, destructive actions |
| `warning` | `#f59e0b` | Warnings, below-average indicators |
| `info` | `#3b82f6` | Info badges, tips |

### 3.2 Typography

| Role | Font | Weight | Size |
|------|------|--------|------|
| Display / Logo | `Fredoka One` (Google Fonts) | 400 | 2xl–4xl |
| Headings | `Nunito` (Google Fonts) | 700 | lg–2xl |
| Body | `Nunito` | 400–600 | sm–base |
| Monospace (scores/code) | `JetBrains Mono` | 400 | sm |

### 3.3 Component Tokens

| Component | Tailwind Classes |
|-----------|-----------------|
| Card | `rounded-2xl bg-white border border-border shadow-sm hover:shadow-md transition p-6` |
| Button — Primary | `bg-primary text-white hover:bg-primary-dark rounded-xl px-5 py-2.5 font-semibold` |
| Button — Accent | `bg-accent text-white hover:bg-accent-dark rounded-xl px-5 py-2.5 font-semibold` |
| Button — Secondary | `bg-white border border-primary text-primary hover:bg-primary-light rounded-xl px-5 py-2.5` |
| Button — Danger | `bg-red-500 text-white hover:bg-red-600 rounded-xl px-5 py-2.5` |
| Button — Ghost | `text-primary hover:bg-primary-light rounded-xl px-5 py-2.5` |
| Input | `w-full rounded-lg border border-gray-300 px-4 py-2.5 focus:ring-2 focus:ring-primary focus:border-transparent` |
| Badge / Pill | `rounded-full px-3 py-1 text-xs font-semibold` |
| Toast | Fixed bottom-right (desktop) · top-centre (mobile) · auto-dismiss 4 s |

### 3.4 Role Badge Colours

| Role | Badge Style |
|------|------------|
| Admin | `bg-red-100 text-red-700` |
| Teacher | `bg-blue-100 text-blue-700` |
| Student | `bg-green-100 text-green-700` |
| IndividualStudent | `bg-purple-100 text-purple-700` |
| HeadOfDepartment | `bg-orange-100 text-orange-700` |
| Accountant | `bg-yellow-100 text-yellow-700` |

---

## 4. Layout & Navigation

### 4.1 Desktop Layout (≥ 768px)

```
┌─────────────────────────────────────────────────────┐
│  TOPBAR  (h-16, sticky, white, border-b)            │
│  [Logo] [Classroom]        [Role Badge] [🔔] [User▾]│
├──────────────┬──────────────────────────────────────┤
│              │                                      │
│   SIDEBAR    │         MAIN CONTENT                 │
│   (w-64,     │         (flex-1, overflow-y-auto,    │
│   fixed,     │          px-8 py-6)                  │
│   bg-primary)│                                      │
│              │                                      │
└──────────────┴──────────────────────────────────────┘
```

### 4.2 Mobile Layout (< 768px)

```
┌─────────────────────────┐
│  TOPBAR  (h-14, sticky) │
│  [☰] [Logo]    [🔔][👤] │
├─────────────────────────┤
│                         │
│     MAIN CONTENT        │
│     (pb-20 for bottom   │
│      nav clearance)     │
│                         │
├─────────────────────────┤
│  BOTTOM NAV  (h-16,     │
│  fixed, white, border-t)│
│  [🏠][⚡][✖️][📊][👤]   │
└─────────────────────────┘
```

Sidebar is hidden on mobile. Bottom nav replaces it with 5 key items. The hamburger (☰) opens a full-height slide-out drawer with complete navigation.

### 4.3 Topbar (All Roles)

**Style:** White · `border-b border-border` · sticky top · `h-16` desktop / `h-14` mobile

| Element | Detail |
|---------|--------|
| Logo | Customer-supplied image · `h-9 w-auto` |
| App name | "Classroom" · `Fredoka One` · `text-primary` · hidden on mobile |
| Role badge | Pill per §3.4 |
| Notifications | 🔔 icon · unread count dot · dropdown list |
| User menu | Avatar initials → dropdown: Profile · Change Password · (Billing for IndividualStudent) · Logout |

### 4.4 Sidebar Navigation (Desktop)

**Style:** `bg-primary text-white` · `w-64` fixed  
**Active item:** `bg-white/20 font-semibold rounded-xl`  
**Hover:** `bg-white/10 rounded-xl transition`  
**Icons:** Heroicons outline style

#### Student & IndividualStudent Sidebar

| Icon | Label | URL |
|------|-------|-----|
| HomeIcon | Home | `/` |
| BoltIcon | Basic Facts | `/basic-facts/` |
| XMarkIcon | Times Tables | `/times-tables/` |
| ChartBarIcon | My Progress | `/dashboard/` |

Bottom of sidebar (IndividualStudent only): CreditCardIcon → Billing → `/account/change-package/`  
Trial banner (IndividualStudent in trial): Yellow pill "Trial ends in X days" above billing link.

#### Teacher Sidebar

| Icon | Label | URL |
|------|-------|-----|
| BuildingLibraryIcon | My Classes | `/` |
| ChartBarSquareIcon | Class Progress | `/class/progress/` |
| BookOpenIcon | Browse Topics | `/topics/` |
| ArrowUpTrayIcon | Upload Questions | `/upload-questions/` |
| UsersIcon | Bulk Register Students | `/bulk-student-registration/` |
| AcademicCapIcon | Manage Teachers | `/class/manage-teachers/` |

#### HeadOfDepartment Sidebar

| Icon | Label | URL |
|------|-------|-----|
| BuildingOfficeIcon | Department Overview | `/department/` |
| LinkIcon | Class-Teacher Assignments | `/department/manage-classes/` |
| ScaleIcon | Teacher Workload | `/department/workload/` |
| ClipboardDocumentChartIcon | Departmental Reports | `/department/reports/` |

#### Accountant Sidebar

| Icon | Label | URL |
|------|-------|-----|
| BanknotesIcon | Dashboard | `/accounting/` |
| CubeIcon | Manage Packages | `/accounting/packages/` |
| UserGroupIcon | User Statistics | `/accounting/users/` |
| DocumentArrowDownIcon | Export Reports | `/accounting/export/` |
| ArrowPathIcon | Refunds | `/accounting/refunds/` |

### 4.5 Bottom Navigation Bar (Mobile — Student / IndividualStudent)

Fixed bottom · white · `border-t border-border` · `h-16` · 5 items max

| Icon | Label | URL |
|------|-------|-----|
| HomeIcon | Home | `/` |
| BoltIcon | Facts | `/basic-facts/` |
| XMarkIcon | Tables | `/times-tables/` |
| ChartBarIcon | Progress | `/dashboard/` |
| UserIcon | Profile | `/profile/` |

For Teacher / HoD / Accountant on mobile: Home · Role progress URL · ☰ More (slide-out drawer).

---

## 5. User Roles & Authentication

### 5.1 Registration & Auth — Requirements

#### User Model (`CustomUser` extends `AbstractUser`)

| Field | Type | Description |
|-------|------|-------------|
| `date_of_birth` | Date (optional) | Age-based Basic Facts statistics |
| `country` | String (optional) | User's country |
| `region` | String (optional) | User's region/state/province |
| `package` | FK → `Package` (optional) | Active package; null for non-IndividualStudent |
| `roles` | M2M → `Role` via `UserRole` | One or more assigned roles |

#### Role Model

Stored in a dedicated `Role` table — extensible via Django admin without code changes.

| Field | Type | Description |
|-------|------|-------------|
| `name` | String (unique) | Machine identifier e.g. `teacher`, `student` |
| `display_name` | String | Human-readable label |
| `description` | Text (optional) | Role purpose |
| `is_active` | Boolean | Whether available for assignment |
| `created_at` | DateTime | Creation timestamp |

#### Built-in Roles

| Role | Identifier | Key Capabilities |
|------|------------|-----------------|
| Admin | `admin` | Full Django admin, role management, package config |
| Teacher | `teacher` | Create classes, bulk-register students, manage questions, view class progress |
| Student | `student` | Take quizzes, view progress. Class-assigned levels only. **Registered by teachers only.** |
| IndividualStudent | `individual_student` | **Self-registers.** Selects package, accesses classes up to limit. |
| Accountant | `accountant` | Financial reports, billing, refunds |
| HeadOfDepartment | `head_of_department` | Assign classes to teachers, departmental reports |

#### Permission Resolution

- Checks: `user.roles.filter(name='...').exists()`
- Multiple roles → union of capabilities
- Dashboard redirect priority: Admin > HeadOfDepartment > Accountant > Teacher > IndividualStudent > Student
- No roles → "contact administrator" page

#### Authentication Flows

- **Login:** `/accounts/login/` → role-specific dashboard
- **Logout:** `/accounts/logout/` → `/`
- **Password Reset:** Email-based · token valid 3600 s (configurable)
- **Session:** `LOGIN_REDIRECT_URL = LOGOUT_REDIRECT_URL = '/'`

#### FR — Student Registration

`student` role has **no self-registration**. `/signup/student/` does not exist. Students registered by teachers only (bulk upload or Django admin).

#### FR — Teacher Self-Registration

- **URL:** `/signup/teacher/`
- **Fields:** Username, Email, Password, Password Confirmation
- Creates `CustomUser` with `teacher` role. Logs in → teacher dashboard.

#### FR — Teacher Center Registration

- **URL:** `/register/teacher-center/`
- **Fields:** Username, Email, Password, Password Confirmation, Center/School Name
- Creates `teacher` role user. Shows success message with center name.

#### FR — Bulk Student Registration (Teacher Only)

- **URL:** `/bulk-student-registration/`
- **Access:** `teacher` role only
- **Input:** Textarea — one student per line: `username,email,password`
- **Validation:** 3 comma-separated values · non-empty username · email contains `@` · password ≥ 8 chars
- Creates all `student` accounts atomically. Reports success count. Individual failures reported without rolling back others.
- Note: `individual_student` accounts cannot be bulk-registered — they must self-register.

#### FR — Individual Student Registration

- **URL:** `/register/individual-student/`
- **Fields:** Username, Email, Password, Password Confirmation, Package Selection, Discount Code (optional)

**Three-step flow:**

```
Step 1 — Account creation
    CustomUser created with `individual_student` role + selected package.
    User logged in immediately.

Step 2 — Class selection  (before payment)
    Redirected to /select-classes/.
    Student selects classes up to package limit immediately.

Step 3 — Payment
    If valid 100% discount code:
        → Stripe skipped. Package activated. DiscountCode.uses incremented.

    If paid package, no discount:
        → Stripe Checkout Session created (14-day trial_period_days).
        → Student redirected to Stripe checkout (card optional during trial).
        → Trial begins immediately. Full access during trial.
        → Reminder email 3 days before trial ends.
        → Notification email on trial end day.
        → After trial:
            Card provided  → monthly auto-charge from trial end date
            No card        → Basic Facts only access
            Payment fails  → Basic Facts only access
```

**Billing cycle:** From trial end date. First charge = 14 days after registration.

#### Discount Code Model

| Field | Type | Description |
|-------|------|-------------|
| `code` | String (unique) | Code entered at registration |
| `discount_percent` | Integer | 100 = fully free |
| `max_uses` | Integer (null = unlimited) | Max redemptions |
| `uses` | Integer | Current redemption count |
| `is_active` | Boolean | Usable or not |
| `expires_at` | DateTime (optional) | Expiry |

#### Package Change Rules

- **Upgrade:** Classes kept; student adds more up to new limit; Stripe handles price difference.
- **Downgrade:** Student must manually remove excess classes first. Takes effect at billing period end.

### 5.2 Registration & Auth — UI

#### Login Page (`/accounts/login/`)

- Layout: `base_auth.html` — centred card · max-w-md · `rounded-2xl shadow-lg`
- Background: soft gradient `from-green-50 to-yellow-50`
- Logo at top · "Welcome back!" in `Fredoka One`
- Fields: Username · Password · "Remember me" checkbox
- Primary green "Log In" button (full width)
- Links: "Forgot password?" · "Register as Teacher" · "Register as Individual Student"

#### Individual Student Registration (`/register/individual-student/`)

- Layout: `base_auth.html`
- Multi-step with progress dots at top (3 steps)

**Step 1 — Account Details**
- Username, Email, Password, Confirm Password fields
- "Next →" button

**Step 2 — Package Selection**
- 4 package cards in a responsive grid (1 Class / 3 Classes / 5 Classes / Unlimited)
- Each card: name · class limit · price/month · "14 days free" trial badge
- Selected package: `ring-2 ring-primary` highlight
- "← Back" · "Next →" buttons

**Step 3 — Discount Code**
- Optional discount code input
- If valid 100% code: "Activate Free" button (skips Stripe)
- Otherwise: "Continue to Payment" button → Stripe Checkout
- Small print: trial terms

#### Teacher Registration (`/signup/teacher/` and `/register/teacher-center/`)

- Layout: `base_auth.html`
- Single-step form · Username, Email, Password, Confirm Password (+ Center Name for center reg)
- "Create Account" primary button

---

## 6. Classroom Management

### 6.1 Requirements

#### FR — Create Class (Teacher Only)

- **URL:** `/create-class/`
- **Access:** `teacher` role
- **Fields:** Class Name, Levels (multi-select)
- Generates unique 8-character class code (UUID hex). Creating teacher added automatically. Redirects to teacher dashboard.

#### FR — Assign Students to Class

- **URL:** `/class/<class_id>/assign-students/`
- **Access:** `teacher` role · class member
- Adds students, preventing duplicates. Students cannot add themselves.

#### FR — Assign Teachers to Class

- **URL:** `/class/<class_id>/assign-teachers/`
- **Access:** `teacher` (class member) or `head_of_department` (any class)
- Multiple teachers can co-manage a class.

#### FR — HoD Class-Teacher Management

- **URL:** `/department/manage-classes/`
- **Access:** `head_of_department`
- Overview of all classes. Assign/remove teachers. View teacher workload (classes per teacher).

#### FR — Individual Student Class Selection

- **URL:** `/select-classes/`
- **Access:** `individual_student`
- Lists all available classes. Student selects up to package limit. Available immediately after registration before payment.

#### FR — Level Access Control

| Role / State | Access |
|--------------|--------|
| `student` | Levels assigned to their class(es) — union |
| `individual_student` — active/trial | Levels assigned to selected classes |
| `individual_student` — trial expired, no payment | Basic Facts only (level_number ≥ 100) |
| `teacher` | All levels |
| `head_of_department` | All levels |
| `accountant` | No quiz content |

Basic Facts (level_number ≥ 100) always accessible regardless of payment status.

### 6.2 UI

#### Class Selection Page (`/select-classes/`) — IndividualStudent

- Grid of available class cards
- Each card: class name · class code · level badges · "Join" button
- Joined classes show "✓ Joined" with a "Leave" option
- Package limit counter at top: "2 of 3 classes selected"
- If limit reached: other cards disabled with "Upgrade to add more" tooltip

#### Create Class Page (`/create-class/`) — Teacher

- Single card form: Class Name input · Level multi-select checkboxes
- "Create Class" primary button
- On success: toast notification + redirect to dashboard

---

## 7. Student Dashboard

### 7.1 Requirements

#### FR — Home Dashboard (`/`)

- **Access:** `student` or `individual_student`
- Info box: package + trial status + class count (IndividualStudent) or assigned classes (Student)
- Basic Facts section: 5 cards (Addition, Subtraction, Multiplication, Division, Place Value Facts)
- Year-level accordion: Years 1–8, each expands to show topic cards + "Take Quiz" (Mixed Quiz) card

#### FR — Detailed Dashboard (`/dashboard/`)

- Same layout as home plus:
  - Year-Level Progress Table: best points, time, date, attempts per topic-level
  - Basic Facts Progress Table: accordion per subtopic with level-by-level progress
  - Dual colour coding (§13.2)
- Data priority: `StudentFinalAnswer` → fallback `StudentAnswer`

### 7.2 UI

#### Student Home (`/`)

- **Hero greeting:** "Good morning, [Name]! 👋" · `Fredoka One` · large
- **Quick stats row:** 3 mini cards — Daily time · Weekly time · Best score this week
- **Basic Facts section heading** with 5 colourful cards in a grid. Each card: fun icon · subtopic name · "X levels available" · links to `/basic-facts/<subtopic>/`
- **Year accordion:** Each row: "Year [N]" chevron header. On expand: topic cards grid + yellow "Take Quiz →" card at end
- Topic card: topic name · icon · student's best score (if attempted) · "Start" button

#### Detailed Dashboard (`/dashboard/`)

- Same header section as home
- **Tab bar:** "Topic Quizzes" | "Basic Facts" | "Times Tables"
- Each tab: progress table with Topic · Level · Best Score · Time · Attempts · Date · Dual colour indicator
- Colour coding legend above table
- Clicking a row expands full attempt history inline

---

## 8. Basic Facts Module

### 8.1 Requirements

Questions are **runtime-generated — never stored in the database**. Accessible to all students regardless of payment status.

| Subtopic | Internal Levels | Display Levels | Questions/Quiz |
|----------|----------------|----------------|----------------|
| Addition | 100–106 | 1–7 | 10 |
| Subtraction | 107–113 | 1–7 | 10 |
| Multiplication | 114–120 | 1–7 | 10 |
| Division | 121–127 | 1–7 | 10 |
| Place Value Facts | 128–132 | 1–5 | 10 |

#### Question Generation

**Addition (100–106):** L100: digits 1–5 · L101: digits 0–9 · L102: 2-digit no carry · L103: 2-digit with carry · L104: 3-digit · L105: 4-digit · L106: 5-digit

**Subtraction (107–113):** L107: single-digit ≥0 · L108: 2d−1d no borrow · L109: 2d−1d with borrow · L110: 2d−2d ≥0 · L111: 2d−2d may be negative · L112: 3-digit · L113: 4-digit

**Multiplication (114–120):** L114: ×1/10 · L115: ×1/10/100 · L116: ×5/10 · L117: ×2/3/5/10 · L118: ×2–5/10 (2–3 digit) · L119: ×2–7/10 (2–3 digit) · L120: ×2–10 (3-digit)

**Division (121–127):** L121: ÷1/10 · L122: ÷1/10/100 · L123: ÷5/10 · L124: ÷2/3/5/10 · L125: ÷2–5/10 · L126: ÷2–7/10 · L127: ÷2–11

**Place Value Facts (128–132):** L128: make 10 · L129: make 100 · L130: make 1,000 · L131: make 10,000 · L132: make 100,000. Each question randomly uses one of: `a + b = ?` · `a + ? = target` · `? + b = target`

#### Quiz Flow

1. GET → 10 questions generated, stored in session, server timer starts
2. All 10 displayed at once — student fills in numeric answers
3. POST → graded, time calculated, points computed, saved to `BasicFactsResult`
4. Redirect to separate results page
5. Duplicate prevention: result saved within last 5 s → show existing result
6. Refresh within 30 s of completion → show results again

### 8.2 UI & Templates

#### Templates

| Template | Purpose |
|----------|---------|
| `quiz/basic_facts_select.html` | Subtopic landing — level selection grid |
| `quiz/basic_facts_quiz.html` | All 10 questions at once |
| `quiz/basic_facts_results.html` | Separate results page |

#### `basic_facts_select.html`

- Breadcrumb: Home > Basic Facts > [Subtopic]
- Page title: subtopic name + fun icon
- Level grid: cards for each display level (1–7 or 1–5)
- Each level card: "Level N" · difficulty stars · student's best score if attempted · "Start" button
- Uses `base_quiz_select.html` layout (full page, no sidebar during quiz)

#### `basic_facts_quiz.html`

- Layout: `base_quiz.html` (full-screen, sidebar hidden)
- **Top bar:** Subtopic name · "Level N" badge · Live timer counting up (starts on page load)
- **Question list:** 10 question cards stacked vertically. Each card:
  - Question number badge (e.g. "Q3")
  - Large equation text e.g. "247 + 138 = ?"
  - Single large number `<input>` (numeric, autofocus on first)
  - Pressing Tab or Enter advances to next input
- **Sticky bottom bar:** "Submit All Answers" accent button · questions answered counter "8 / 10"
- Timer continues until submit
- On submit: form POST → redirect to results page

#### `basic_facts_results.html`

- Layout: `base_quiz.html`
- **Hero section:** Score circle (e.g. "8/10") · Time taken · Points earned
- **Record banner** (if new record): Yellow banner "🌟 New Record!" or "Previous best: X pts"
- **Question review:** Expandable accordion or list showing each question:
  - ✅ correct: green · student's answer
  - ❌ wrong: red · student's answer · correct answer shown
- **Action buttons:** "Try Again" · "Try Next Level" · "Back to Basic Facts"

---

## 9. Topic-Based Quizzes

### 9.1 Requirements

Questions stored in DB per topic/level. Selected via stratified random sampling. Presented **one at a time** via HTMX with feedback after each answer.

**Supported topics:** Measurements · Whole Numbers · Factors · Angles · Place Values · Fractions · BODMAS/PEMDAS · Date and Time · Finance · Integers · Trigonometry *(extensible)*

#### Question Counts by Year

| Year | Questions |
|------|-----------|
| 1 | 12 |
| 2 | 10 |
| 3 | 12 |
| 4 | 15 |
| 5 | 17 |
| 6 | 20 |
| 7 | 22 |
| 8 | 25 |

#### Question Types

| Type | DB Value | Input |
|------|----------|-------|
| Multiple Choice | `multiple_choice` | Radio buttons |
| True / False | `true_false` | True / False radio |
| Short Answer | `short_answer` | Text input |
| Fill in the Blank | `fill_blank` | Text input |
| Calculation | `calculation` | Text input |
| Drag & Drop | `drag_drop` | Sort tiles into sequence |

#### Text Answer Validation

- **Multiple valid answers:** Comma-separated alternatives in `Answer.text` (e.g. `"6,six,Six"`)
- **Numeric tolerance:** Fixed global default ±0.05

#### Drag & Drop

- All `Answer` records have `is_correct=true`; `display_order` = correct sequence position
- Student submits `ordered_answer_ids` array
- Fully correct = full points. No partial credit.

#### Quiz Flow

1. All questions + shuffled answers serialised as JSON to client. Server timer starts.
2. HTMX renders one question at a time in a swap target `#question-container`
3. Student selects/enters answer → HTMX POST to `/api/submit-topic-answer/`
4. Server returns: `is_correct`, `correct_answer`, `explanation`
5. HTMX swaps in feedback partial (green/red + explanation) then "Next →" button
6. After last question → redirect to separate results page (`?completed=1`)
7. Server calculates final score, time, points, renders results

#### Results Saved To

- `StudentAnswer` (per question, with `topic` FK)
- `StudentFinalAnswer` (aggregated per attempt)

### 9.2 UI & Templates

#### Templates

| Template | Purpose |
|----------|---------|
| `quiz/topic_quiz.html` | Quiz shell — question container, progress bar, timer |
| `quiz/partials/topic_question.html` | HTMX partial — single question card |
| `quiz/partials/topic_feedback.html` | HTMX partial — correct/wrong + explanation |
| `quiz/topic_results.html` | Separate results page |

#### `topic_quiz.html`

- Layout: `base_quiz.html` (full-screen, sidebar hidden)
- **Top bar:** Topic name · Year badge · Progress bar "Question 3 of 15" · Timer counting up
- **`#question-container`:** HTMX swap target. Renders `topic_question.html` partial initially.
- No manual "next" navigation — flow driven by HTMX answer submission

#### `quiz/partials/topic_question.html` (HTMX partial)

Renders one question at a time. Content varies by question type:

**`multiple_choice` / `true_false`:**
- Question text (+ optional image)
- 2–4 large answer tile buttons (`<button hx-post="..." hx-target="#question-container" hx-swap="innerHTML">`)
- Tiles: rounded-xl · border · hover scale · full width on mobile

**`short_answer` / `fill_blank` / `calculation`:**
- Question text (+ optional image)
- Large centred text input
- "Submit Answer" button (hx-post)

**`drag_drop`:**
- Question text (+ optional image)
- Draggable tile list (using HTML5 drag-and-drop or Sortable.js)
- Numbered drop zones showing sequence positions
- "Submit Order" button (hx-post with serialised order)

#### `quiz/partials/topic_feedback.html` (HTMX partial)

Rendered after each answer submission:

- **Correct:** Green background · ✅ icon · "Correct!" · explanation text (if any) · "Next →" button
- **Wrong:** Red background · ❌ icon · "Not quite!" · "The answer was: [X]" · explanation text · "Next →" button
- "Next →" button: `hx-get` fetches next question partial OR redirects to results if last question

#### `topic_results.html`

- Layout: `base_quiz.html`
- **Hero:** Score (e.g. "12/15") · Time · Points
- **Record banner:** "🌟 New Record!" or "Previous best: X pts" or "First attempt!"
- **Per-question review:** Accordion list — ✅/❌ · question text · student answer · correct answer · explanation
- **Actions:** "Try Again" · "Try a Different Topic" · "Back to Home"

---

## 10. Mixed Quiz

### 10.1 Requirements

- **URL:** `/level/<level_number>/quiz/`
- **Access:** `student`, `individual_student` · level access control applies
- Selects random questions from **all topics** for the level (same question counts as topic quiz by year)
- Uses stratified random sampling across all topics
- Displays **all questions at once** (like Basic Facts) — student scrolls and submits together
- Each `StudentAnswer` stores `topic` FK for per-topic breakdown
- Results saved to `StudentAnswer` + `StudentFinalAnswer` (topic label = "Quiz")
- Results appear on a **separate results page**

### 10.2 UI & Templates

#### Templates

| Template | Purpose |
|----------|---------|
| `quiz/mixed_quiz.html` | All questions at once, scroll & submit |
| `quiz/mixed_results.html` | Separate results page with per-topic breakdown |

#### `mixed_quiz.html`

- Layout: `base_quiz.html`
- **Top bar:** "Year [N] Mixed Quiz" · question count · Timer counting up
- **Question list:** All questions in vertical cards (same card style as Basic Facts)
  - Each card shows question number, topic badge (e.g. "Fractions"), question text, answer input/options
  - Question types rendered same as topic quiz but statically (no HTMX per-question — submit all at end)
- **Sticky bottom bar:** "Submit All" accent button · answered counter "10 / 20"

#### `mixed_results.html`

- Layout: `base_quiz.html`
- **Hero:** Score · Time · Points · Record banner
- **Per-topic breakdown section:** Horizontal bar chart or card grid showing:
  - Each topic: "Fractions: 8/10 ✅ 80%" · progress bar coloured by percentage
  - Sorted by percentage (highest first)
- **Per-question review:** Same accordion as topic results
- **Actions:** "Try Again" · "Back to Home"

---

## 11. Times Tables

### 11.1 Requirements

**Runtime-generated — not stored in the database.** Consistent with Basic Facts.

#### Available Tables by Year

| Year | Tables |
|------|--------|
| 1 | 1× |
| 2 | 1×, 2×, 10× |
| 3 | 1×–5×, 10× |
| 4 | 1×–10× |
| 5–8 | 1×–12× |

#### Quiz Generation

- **Multiplication:** Table N → N×1 through N×12 (12 questions)
- **Division:** Table N → (N×1)÷N through (N×12)÷N (12 questions)
- Format: multiple choice · 1 correct + 3 plausible distractors
- Generated fresh each load — never cached or stored

#### Quiz Flow

Same HTMX one-at-a-time flow as topic quiz. Results on separate results page.

**URLs:**
- Selection: `/level/<level_number>/multiplication/` · `/level/<level_number>/division/`
- Quiz: `/level/<level_number>/multiplication/<table>/` · `/level/<level_number>/division/<table>/`

### 11.2 UI & Templates

#### Templates

| Template | Purpose |
|----------|---------|
| `quiz/times_tables_select.html` | Year/table selection grid |
| `quiz/times_tables_quiz.html` | One at a time via HTMX (reuses topic question/feedback partials) |
| `quiz/times_tables_results.html` | Separate results page |

#### `times_tables_select.html`

- Layout: standard (sidebar visible)
- **Year tabs** or accordion at top — select year level
- **Table grid:** Cards for each available table (e.g. "3×", "7×")
- Each card: table number · student's best score if attempted · "Multiplication" and "Division" buttons
- Locked tables (above year level) shown greyed out with lock icon

#### `times_tables_quiz.html`

- Layout: `base_quiz.html`
- **Top bar:** "X Times Table — Multiplication/Division" · "Question 4 of 12" · Timer
- Same HTMX `#question-container` swap target as topic quiz
- Questions rendered as large answer tiles (multiple choice — 4 options)
- Reuses `quiz/partials/topic_question.html` and `quiz/partials/topic_feedback.html`

#### `times_tables_results.html`

- Layout: `base_quiz.html`
- **Hero:** Score (e.g. "10/12") · Time · Points · Record banner
- **Times table review grid:** Visual N×N grid with student's answers highlighted ✅/❌
- **Actions:** "Try Again" · "Try Division" (or "Try Multiplication") · "Back to Times Tables"

---

## 12. Scoring & Points System

### 12.1 Points Formula

```
Points = (Percentage_Correct × 100 × 60) / Time_Taken_Seconds
```

- `Percentage_Correct` = Correct / Total (0–1)
- `Time_Taken_Seconds` = elapsed seconds (minimum 1)

**Basic Facts (10 questions):**
```
Basic Facts Points = ((Percentage_Correct × 100 × 60) / Time_Taken_Seconds) / 10
```

### 12.2 Record Tracking

- Each attempt: unique `session_id` (UUID)
- Compared against student's previous best for same level-topic
- Completion labels: "First attempt" · "🌟 New Record!" · "Previous best: X pts"

---

## 13. Progress Tracking & Statistics

### 13.1 Requirements

#### StudentFinalAnswer

One record per quiz attempt. `attempt_number` auto-increments per student-topic-level. Saved atomically with retry logic.

#### TopicLevelStatistics

Per topic-level: `avg_points`, `sigma`, `student_count`. Updated asynchronously after each quiz. Never blocks quiz responses.

Basic Facts stats grouped additionally by student age (`level_number = 2000 + age`).

#### Colour Coding Thresholds

Both indicators require **≥ 2 attempts**. Below threshold: no colour, raw score only.

**Indicator A — Personal Trend:**

| State | Condition |
|-------|-----------|
| ↑ Improving | Latest > previous best |
| → Steady | Latest = previous best |
| ↓ Declining | Latest < previous best |
| — | Fewer than 2 personal attempts |

**Indicator B — Platform Average:**

| Colour | Condition |
|--------|-----------|
| No colour | < 2 platform attempts |
| Dark Green | Points > avg + 2σ |
| Green | avg + σ < Points ≤ avg + 2σ |
| Light Green | avg − σ < Points ≤ avg + σ |
| Yellow | avg − 2σ < Points ≤ avg − σ |
| Orange | avg − 3σ < Points ≤ avg − 2σ |
| Red | Points ≤ avg − 3σ |

### 13.2 UI

#### Progress Table Columns

Topic · Level · Best Score · Time · Attempts · Date · **Trend Arrow (A)** · **Colour Band (B)**

#### Colour Band Tailwind Classes (Indicator B)

| Band | Class |
|------|-------|
| No data | No background |
| Exceptional | `bg-green-800 text-white` |
| Above average | `bg-green-500 text-white` |
| Average | `bg-green-200 text-green-900` |
| Below average | `bg-yellow-200 text-yellow-900` |
| Significantly below | `bg-orange-200 text-orange-900` |
| Needs improvement | `bg-red-200 text-red-900` |

#### Trend Arrow (Indicator A)

| State | Style |
|-------|-------|
| ↑ | `text-green-600` ↑ arrow |
| → | `text-gray-400` → arrow |
| ↓ | `text-orange-500` ↓ arrow |
| — | empty |

---

## 14. Time Tracking

### 14.1 Requirements

**TimeLog model** (1-to-1 with `CustomUser`):
- `daily_seconds` — resets midnight NZT
- `weekly_seconds` — resets Monday midnight NZT
- `last_updated` — last update timestamp

**API:** `GET/POST /api/update-time-log/` → `{ "success": true, "daily_seconds": int, "weekly_seconds": int }`

### 14.2 UI

Displayed on student home as two of the three quick stats cards: "Today: Xm Ys" · "This week: Xh Ym"

---

## 15. Teacher Dashboard & Tools

### 15.1 Requirements

#### Teacher Home (`/`)

- List of all classes teacher belongs to: name, code, student count, co-teacher count
- Per-class: Manage Students · Manage Teachers · View Class Progress
- Global: Create Class · Bulk Register Students · Browse Topics · Upload Questions

#### Class Progress View (`/class/<class_id>/progress/`)

- **Access:** `teacher` · class member
- Class averages panel: average best score per topic/level
- Individual student drill-down: expandable rows per student (best score, attempts, date per topic/level)
- Mixed Quiz topic breakdown: % correct per topic from `StudentAnswer.topic` (e.g. "Fractions 80% · Measurements 40%")
- Colour coding consistent with student dashboard

### 15.2 UI

#### Teacher Home (`/`)

- **Summary bar:** 3 stat cards — Total Classes · Total Students · Questions Uploaded
- **Class cards grid:** One card per class
  - Class name · class code (copy icon) · student count · teacher count
  - Action buttons: "📈 Progress" · "👥 Students" · "👨‍🏫 Teachers"
- **Quick actions bar:** "＋ New Class" · "Bulk Register" · "Upload Questions"

#### Class Progress (`/class/<id>/progress/`)

- **Breadcrumb:** My Classes > [Class Name] > Progress
- **Summary row:** Class avg score · Top performer · Most attempted topic
- **Tab bar:** "By Topic" | "By Student" | "Mixed Quiz Breakdown"
  - **By Topic:** Table — Topic · Level · Class Avg · Colour band
  - **By Student:** Expandable rows per student — name · topic · best score · attempts
  - **Mixed Quiz Breakdown:** Horizontal bar chart per topic (% correct across class)

---

## 16. Question Management

### 16.1 Requirements

#### View Level Questions (`/level/<level_number>/questions/`)

All database questions for a level: text, type, difficulty, answer count.

#### Manual Add Question (`/level/<level_number>/add-question/`)

- **Access:** `teacher`
- Fields: question text, type, difficulty (1–3), points, explanation, optional image, up to 4 answers (text, is_correct, display_order)
- For `drag_drop`: all answers `is_correct=true`; `display_order` = correct sequence
- Creates atomically. Redirects to level questions page.

#### Edit / Delete Question

- **URLs:** `/question/<id>/edit/` · `/question/<id>/delete/`
- **Access:** `teacher`
- Delete removes question + all `Answer` + `StudentAnswer` records

#### JSON Question Upload (`/upload-questions/`)

- **Access:** `teacher` (UI) · Admin (Django admin)
- One JSON file per topic/level

**JSON Format:**

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
      "explanation": "Half of 10 is 5.",
      "image_path": "images/fractions/half_of_10.png",
      "answers": [
        { "text": "5",  "is_correct": true,  "display_order": 1 },
        { "text": "2",  "is_correct": false, "display_order": 2 },
        { "text": "4",  "is_correct": false, "display_order": 3 },
        { "text": "20", "is_correct": false, "display_order": 4 }
      ]
    },
    {
      "question_text": "Order smallest to largest.",
      "question_type": "drag_drop",
      "difficulty": 2,
      "points": 2,
      "explanation": "1/4 < 1/2 < 3/4 < 1",
      "image_path": null,
      "answers": [
        { "text": "1/4", "is_correct": true, "display_order": 1 },
        { "text": "1/2", "is_correct": true, "display_order": 2 },
        { "text": "3/4", "is_correct": true, "display_order": 3 },
        { "text": "1",   "is_correct": true, "display_order": 4 }
      ]
    }
  ]
}
```

**Duplicate handling:** Matched by `question_text` + topic + level. Match → silently overwrite. No match → insert.

**Upload response:** Count of inserted · overwritten · failed (with error details per question).

**Validation errors (question skipped):** Missing `question_text` · invalid `question_type` · no answers · `drag_drop` missing `display_order`.

**Image paths:** Relative to `MEDIA_ROOT` (dev) or S3 root (production). Missing file → question imported, image blank, warning logged.

### 16.2 UI & Templates

#### `teacher/upload_questions.html`

- **Drag-and-drop file zone** (accepts `.json`) with dashed border, cloud upload icon
- Below zone: Topic dropdown + Year Level dropdown (pre-filled from filename if convention followed)
- "Upload" primary button → progress spinner → results summary card:
  - ✅ X inserted · 🔄 X overwritten · ❌ X failed
  - Expandable error list for failures
- "Download sample JSON" ghost button

#### `teacher/question_list.html`

- Table: # · Question text (truncated) · Type badge · Difficulty stars · Answers · Actions
- Row actions: Edit (pencil icon) · Delete (trash icon, confirmation modal)
- "＋ Add Question" button at top right

#### `teacher/question_form.html`

- Question text textarea
- Type dropdown (changes answer section dynamically)
- Difficulty radio (1 star / 2 stars / 3 stars)
- Points number input
- Explanation textarea
- Image upload field
- **Answer section** (dynamic per type):
  - `multiple_choice`: 4 answer rows (text input + "Correct?" radio + display order)
  - `true_false`: Two fixed rows (True / False) with "Correct?" radio
  - `short_answer` / `fill_blank` / `calculation`: Single answer input with "Comma-separate alternatives" hint
  - `drag_drop`: Up to 8 tile rows (text input + drag handle for ordering sequence)

---

## 17. HeadOfDepartment Dashboard

### 17.1 Requirements

- **URL:** `/department/`
- All classes: name, code, teachers, student count, levels
- Teacher workload: classes per teacher
- Class-teacher assignment controls
- Departmental reports: avg scores, completion rates by level/topic

### 17.2 UI

#### `hod/overview.html`

- **KPI row:** Total Classes · Total Teachers · Total Students · Avg Class Size
- **All classes table:** Name · Code · Teachers · Students · Levels · Actions (assign teacher)
- **Teacher workload panel:** Bar chart — teacher name vs number of classes

#### `hod/manage_classes.html`

- Table of all classes
- Per row: assign/remove teachers via inline dropdown + "Save" button
- Changes saved via HTMX (no full page reload)

#### `hod/reports.html`

- Filters: Year Level · Topic · Date range
- Table: Topic · Level · Avg Score · Students Attempted · Completion Rate
- Export CSV button

---

## 18. Accountant Dashboard

### 18.1 Requirements

- **URL:** `/accounting/`
- Package overview: students by package tier, counts, revenue
- Trial status: active trials, expired no-payment
- User stats: by role, active (last 30 days), new registrations
- Class stats: totals, averages
- Actions: Manage Packages, Export Reports, Refunds

### 18.2 UI

#### `accounting/dashboard.html`

- **KPI row:** Total Revenue · Active Subscriptions · In Trial · Failed Payments
- **Package breakdown table:** Package · Subscribers · MRR
- **Trial status table:** Students in trial (with days remaining) · Trial-expired unpaid
- **New subscriptions chart:** Line chart — last 30 days

#### `accounting/packages.html`

- Table of packages with edit inline (name, class limit, price, trial days, active toggle)
- "＋ New Package" button

#### `accounting/refunds.html`

- Table: User · Package · Amount · Date · Status
- "Process Refund" button → confirmation modal with full/partial option

---

## 19. User Profile Management

### 19.1 Requirements

- **URL:** `/profile/`
- View/edit: date of birth, country, region, email, first name, last name
- Change password: current, new, confirm (min 8 chars) · `update_session_auth_hash`
- IndividualStudent extras: current package, trial status, trial end date, next billing date, link to change package

### 19.2 UI

#### `accounts/profile.html`

- Two-column layout (desktop): left = personal info form, right = password change form
- IndividualStudent: subscription info card below forms
  - Current package badge · trial countdown chip (if in trial) · "Next billing: [date]" · "Change Package →" button

---

## 20. Payments & Subscriptions

### 20.1 Requirements

#### Stripe Configuration

- Library: `stripe` Python SDK + Stripe.js
- Keys: env vars only (`STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY`, `STRIPE_WEBHOOK_SECRET`)
- Currency: configurable, default NZD

#### Package Model

| Field | Type | Description |
|-------|------|-------------|
| `name` | String | e.g. "3 Classes" |
| `class_limit` | Integer | 0 = unlimited |
| `price` | Decimal | 0.00 = free |
| `stripe_price_id` | String (optional) | Stripe Price ID |
| `billing_type` | String | `recurring` |
| `trial_days` | Integer | Default: 14 |
| `is_active` | Boolean | Selectable at registration |

#### Checkout Flow

1. Paid package + no discount → Stripe Checkout Session (`trial_period_days=14`)
2. Free package or 100% code → skip Stripe, activate immediately
3. `checkout.session.completed` webhook → activate package, create `Payment` record

#### Stripe Webhooks (`/stripe/webhook/`)

Public · verified via signature · idempotent

| Event | Action |
|-------|--------|
| `checkout.session.completed` | Activate package, create `Payment` |
| `invoice.payment_succeeded` | Renew subscription, update `Payment` |
| `invoice.payment_failed` | Mark `past_due`, Basic Facts only, email student |
| `customer.subscription.updated` | Sync status + period |
| `customer.subscription.deleted` | Deactivate, Basic Facts only |
| `charge.refunded` | Update `Payment` status, optionally downgrade |

#### Payment & Subscription Models

**Payment:** user FK · package FK · stripe_payment_intent_id · stripe_checkout_session_id · amount · currency · status (`pending/succeeded/failed/refunded`) · timestamps

**Subscription:** user FK · package FK · stripe_subscription_id · stripe_customer_id · status (`active/trialing/past_due/cancelled/expired`) · trial_end · period start/end · timestamps

#### Refunds

- **URL:** `/accounting/refund/<payment_id>/`
- **Access:** `accountant` or `admin`
- Full or partial refund via Stripe Refunds API. Updates `Payment.status` to `refunded`.

### 20.2 UI

#### Package Selection (Registration Step 2)

- 4 cards in responsive grid
- Each: package name · class limit · price/month · "14 days free" badge
- Selected: `ring-2 ring-primary`

#### Change Package (`/account/change-package/`)

- Current package highlighted
- Other packages shown with "Upgrade" / "Downgrade" buttons
- Downgrade blocked with warning if student has too many classes: "Remove X classes first"

---

## 21. Non-Functional Requirements

### NFR — Performance

- `select_related` + `prefetch_related` throughout to prevent N+1 queries
- `TopicLevelStatistics` updated asynchronously in background threads
- Retry logic with exponential backoff for transient DB errors

### NFR — Security

- CSRF protection via Django middleware
- `@login_required` on all sensitive views
- Role checks via `user.roles.filter(name='...').exists()` — never boolean flags
- Level access control enforced on all quiz views
- Password reset tokens expire after 3600 s
- All payments via Stripe Checkout — no raw card data on server (PCI DSS)
- Webhook signature verified before processing
- S3 credentials as env vars only

### NFR — Reliability

- Atomic transactions: bulk registration, question creation, `StudentFinalAnswer`, discount code redemption
- Retry logic for transient DB errors
- 5-second duplicate quiz submission prevention
- `StudentFinalAnswer` → `StudentAnswer` fallback for progress display
- Stripe webhooks idempotent

### NFR — Usability

- Responsive: sidebar desktop · bottom nav mobile
- Accordion year-level navigation
- Dual colour-coded progress indicators
- Immediate HTMX feedback per question in topic/times tables quizzes
- Trial status + billing date visible in student profile
- Green & yellow bright/playful theme suitable for kids and teachers

### NFR — Timezone

- All resets + date comparisons in Pacific/Auckland
- DB timestamps stored UTC, converted to NZT in application logic

---

## 22. Data Model

### Entity Relationship Summary

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
                         StudentAnswer  (topic FK → Mixed Quiz breakdown)
                         StudentFinalAnswer
                         BasicFactsResult

CustomUser ──── TimeLog            (1-to-1)
CustomUser ──── Package            (FK, optional)
CustomUser ──── Subscription       (1-to-1, optional)
CustomUser ──── Payment            (1-to-many)

DiscountCode   (standalone)
```

### Key Models

| Model | App | Purpose |
|-------|-----|---------|
| `Role` | accounts | Named role. Extensible via admin. |
| `UserRole` | accounts | M2M through table (user ↔ role) with audit fields |
| `CustomUser` | accounts | Extended user with M2M roles, personal info, optional package |
| `DiscountCode` | billing | 100% or partial discount codes |
| `Package` | billing | Tier: price, class_limit, stripe_price_id, trial_days |
| `Payment` | billing | Payment record (Stripe IDs, amount, status) |
| `Subscription` | billing | Recurring sub synced with Stripe (includes `trialing` status) |
| `Subject` | classroom | e.g. Mathematics |
| `Topic` | classroom | e.g. Fractions |
| `Level` | classroom | Year level or Basic Facts level by `level_number` |
| `ClassRoom` | classroom | Class with code, M2M teachers/students, assigned levels |
| `ClassTeacher` | classroom | Teacher ↔ class M2M through table |
| `ClassStudent` | classroom | Student ↔ class M2M through table |
| `Question` | quiz | question_type, difficulty, points, image, topic FK, level FK |
| `Answer` | quiz | text (comma-separated for text types), is_correct, display_order |
| `StudentAnswer` | progress | Per-question response. `topic` FK for Mixed Quiz breakdown. |
| `BasicFactsResult` | progress | Basic Facts attempt (no Question FK — runtime generated) |
| `StudentFinalAnswer` | progress | Aggregated attempt: session_id, points, time, attempt_number |
| `TimeLog` | progress | Daily/weekly time-on-task (1-to-1 with CustomUser) |
| `TopicLevelStatistics` | progress | avg_points, sigma, student_count per topic-level |

---

## 23. API Endpoints

### Update Time Log

| Property | Value |
|----------|-------|
| URL | `/api/update-time-log/` |
| Methods | GET, POST |
| Auth | `student` or `individual_student` |
| Response | `{ "success": true, "daily_seconds": int, "weekly_seconds": int }` |

### Submit Topic Answer

| Property | Value |
|----------|-------|
| URL | `/api/submit-topic-answer/` |
| Method | POST (JSON) |
| Auth | Any authenticated user |
| Request | `{ "question_id": int, "answer_id": int?, "text_answer": str?, "ordered_answer_ids": [int]?, "attempt_id": str }` |
| Response | `{ "success": true, "is_correct": bool, "correct_answer_id": int?, "correct_answer_text": str, "explanation": str, "is_last_question": bool, "next_url": str? }` |

**Field usage by type:**
- `answer_id` → `multiple_choice`, `true_false`
- `text_answer` → `short_answer`, `fill_blank`, `calculation`
- `ordered_answer_ids` → `drag_drop`

---

## 24. URL Structure

### Authentication

| URL | Access |
|-----|--------|
| `/accounts/login/` | Public |
| `/accounts/logout/` | Authenticated |
| `/accounts/password-reset/` | Public |
| `/accounts/password-reset/done/` | Public |
| `/accounts/password-reset-confirm/<uidb64>/<token>/` | Public |
| `/accounts/password-reset-complete/` | Public |
| `/signup/teacher/` | Public |
| `/register/teacher-center/` | Public |
| `/register/individual-student/` | Public |

### Core / Shared

| URL | Access |
|-----|--------|
| `/` | Authenticated (role-based redirect) |
| `/profile/` | Authenticated |
| `/select-classes/` | `individual_student` |
| `/account/change-package/` | `individual_student` |

### Student / IndividualStudent

| URL | Access |
|-----|--------|
| `/dashboard/` | `student`, `individual_student` |
| `/basic-facts/` | `student`, `individual_student` |
| `/basic-facts/<subtopic>/` | `student`, `individual_student` |
| `/basic-facts/<subtopic>/<level>/` | `student`, `individual_student` |
| `/times-tables/` | `student`, `individual_student` |
| `/level/<level_number>/multiplication/` | `student`, `individual_student` |
| `/level/<level_number>/multiplication/<table>/` | `student`, `individual_student` |
| `/level/<level_number>/division/` | `student`, `individual_student` |
| `/level/<level_number>/division/<table>/` | `student`, `individual_student` |
| `/topics/` | Authenticated |
| `/topic/<topic_id>/levels/` | Authenticated |
| `/level/<level_number>/` | Authenticated |
| `/level/<level_number>/quiz/` | `student`, `individual_student` |
| `/level/<level_number>/topic/<topic_id>/quiz/` | `student`, `individual_student` |
| `/level/<level_number>/student-progress/` | `student`, `individual_student` |

### Teacher

| URL | Access |
|-----|--------|
| `/create-class/` | `teacher` |
| `/class/<class_id>/assign-students/` | `teacher` |
| `/class/<class_id>/assign-teachers/` | `teacher`, `head_of_department` |
| `/class/<class_id>/progress/` | `teacher` |
| `/class/manage-teachers/` | `teacher` |
| `/bulk-student-registration/` | `teacher` |
| `/upload-questions/` | `teacher` |
| `/level/<level_number>/questions/` | `teacher` |
| `/level/<level_number>/add-question/` | `teacher` |
| `/question/<question_id>/edit/` | `teacher` |
| `/question/<question_id>/delete/` | `teacher` |

### HeadOfDepartment

| URL | Access |
|-----|--------|
| `/department/` | `head_of_department` |
| `/department/manage-classes/` | `head_of_department` |
| `/department/workload/` | `head_of_department` |
| `/department/reports/` | `head_of_department` |

### Accountant

| URL | Access |
|-----|--------|
| `/accounting/` | `accountant` |
| `/accounting/packages/` | `accountant` |
| `/accounting/users/` | `accountant` |
| `/accounting/export/` | `accountant` |
| `/accounting/refunds/` | `accountant` |
| `/accounting/refund/<payment_id>/` | `accountant`, `admin` |

### Billing

| URL | Access |
|-----|--------|
| `/billing/checkout/<package_id>/` | `individual_student` |
| `/billing/success/` | `individual_student` |
| `/billing/cancel/` | `individual_student` |
| `/stripe/webhook/` | Public (Stripe only) |

### API

| URL | Method | Access |
|-----|--------|--------|
| `/api/submit-topic-answer/` | POST | Authenticated |
| `/api/update-time-log/` | GET, POST | `student`, `individual_student` |

---

## 25. Template Structure

```
templates/
│
├── base.html                        # Root: topbar + sidebar + content slot
├── base_quiz.html                   # Full-screen quiz (sidebar hidden, timer shown)
├── base_quiz_select.html            # Quiz landing/selection pages
├── base_auth.html                   # Centred card (login / register)
│
├── partials/
│   ├── topbar.html
│   ├── sidebar_student.html
│   ├── sidebar_teacher.html
│   ├── sidebar_hod.html
│   ├── sidebar_accountant.html
│   ├── bottom_nav.html
│   ├── notifications_dropdown.html
│   └── toast.html
│
├── accounts/
│   ├── login.html
│   ├── register_teacher.html
│   ├── register_teacher_center.html
│   ├── register_individual_student.html
│   ├── profile.html
│   ├── select_classes.html
│   ├── change_package.html
│   └── password_reset_*.html        # Django built-ins + custom templates
│
├── student/
│   ├── home.html                    # Quiz launcher + Basic Facts + year accordion
│   └── dashboard.html               # Detailed progress with dual colour coding
│
├── quiz/
│   ├── basic_facts_select.html      # Subtopic → level selection
│   ├── basic_facts_quiz.html        # All 10 questions at once
│   ├── basic_facts_results.html     # Separate results page
│   │
│   ├── topic_quiz.html              # Quiz shell + HTMX swap target
│   ├── topic_results.html           # Separate results page
│   │
│   ├── mixed_quiz.html              # All questions at once (scroll + submit)
│   ├── mixed_results.html           # Results + per-topic breakdown
│   │
│   ├── times_tables_select.html     # Year/table grid selection
│   ├── times_tables_quiz.html       # One at a time via HTMX
│   ├── times_tables_results.html    # Results + times table grid review
│   │
│   └── partials/
│       ├── topic_question.html      # HTMX partial — single question card
│       │                            # (reused by topic quiz AND times tables)
│       └── topic_feedback.html      # HTMX partial — correct/wrong + explanation
│
├── teacher/
│   ├── home.html
│   ├── class_detail.html
│   ├── class_progress.html
│   ├── assign_students.html
│   ├── assign_teachers.html
│   ├── bulk_register.html
│   ├── upload_questions.html
│   ├── question_list.html
│   ├── question_form.html
│   └── topics.html
│
├── hod/
│   ├── overview.html
│   ├── manage_classes.html
│   ├── workload.html
│   └── reports.html
│
└── accounting/
    ├── dashboard.html
    ├── packages.html
    ├── users.html
    ├── export.html
    └── refunds.html
```

---

## 26. Appendix A — Mathematics Year-Topic Mapping

| Year | Topics Available |
|------|-----------------|
| 1 | Multiplication (times tables), Division (times tables) |
| 2 | Measurements, Place Values, Multiplication, Division |
| 3 | Measurements, Fractions, Finance, Date and Time, Multiplication, Division |
| 4 | Fractions, Integers, Place Values, Multiplication, Division |
| 5 | Measurements, BODMAS/PEMDAS, Multiplication, Division |
| 6 | Measurements, BODMAS/PEMDAS, Whole Numbers, Factors, Angles |
| 7 | Measurements, BODMAS/PEMDAS, Integers, Factors, Fractions |
| 8 | Trigonometry, Integers, Factors, Fractions |

Basic Facts (Addition, Subtraction, Multiplication drill, Division drill, Place Value Facts) are accessible to **all** students at all year levels regardless of class membership or payment status.

---

## 27. Appendix B — JSON Upload Field Reference

| Field | Required | Type | Notes |
|-------|----------|------|-------|
| `topic` | Yes | String | Must match existing `Topic.name` |
| `year_level` | Yes | Integer | 1–8 |
| `questions[].question_text` | Yes | String | Duplicate detection key |
| `questions[].question_type` | Yes | String | See §9.1 Question Types |
| `questions[].difficulty` | Yes | Integer | 1 / 2 / 3 |
| `questions[].points` | No | Integer | Default: 1 |
| `questions[].explanation` | No | String | Shown after answering |
| `questions[].image_path` | No | String or null | Relative to media root |
| `questions[].answers[].text` | Yes | String | Comma-separated alternatives for text types |
| `questions[].answers[].is_correct` | Yes | Boolean | `drag_drop`: always true |
| `questions[].answers[].display_order` | Yes for `drag_drop` | Integer | Correct sequence position |

---

## 28. Appendix C — Quiz Behaviour Summary

| Quiz | Questions Displayed | Feedback | Results | Saved to DB | Timer |
|------|--------------------|---------|---------|-----------:|-------|
| **Basic Facts** | All 10 at once | After submit (on results page) | Separate results page | ✅ `BasicFactsResult` | ✅ Counts up |
| **Topic Quiz** | One at a time (HTMX) | Immediately after each answer | Separate results page | ✅ `StudentAnswer` + `StudentFinalAnswer` | ✅ Counts up |
| **Mixed Quiz** | All at once (scroll) | After submit (on results page) | Separate results page + per-topic breakdown | ✅ `StudentAnswer` + `StudentFinalAnswer` | ✅ Counts up |
| **Times Tables** | One at a time (HTMX) | Immediately after each answer | Separate results page | ✅ `StudentFinalAnswer` | ✅ Counts up |
| ~~Practice Mode~~ | ~~Removed~~ | — | — | ❌ | — |

---

*End of Master Project Specification v3.0*
