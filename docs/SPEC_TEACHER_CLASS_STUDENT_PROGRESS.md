# CWA Classroom — Teacher, Class, Student & Progress System
# Specification Document

**Application:** CWA Classroom (CWA_CLASS_APP)
**Repository:** https://github.com/InoshikaFernando/CWA_CLASS_APP
**Version:** 1.0 (Draft)
**Date:** 2026-03-07

---

## Table of Contents

1. [Overview](#1-overview)
2. [Roles & Permissions](#2-roles--permissions)
3. [Entity Definitions & Scoping](#3-entity-definitions)
4. [Entity Relationships](#4-entity-relationships)
5. [School System](#5-school-system)
6. [Subject & Curriculum Hierarchy (Global)](#6-subject--curriculum-hierarchy-global)
7. [Class System](#7-class-system)
8. [Teacher System](#8-teacher-system)
9. [Student System](#9-student-system)
10. [Enrollment & Join Flow](#10-enrollment--join-flow)
11. [Attendance System](#11-attendance-system)
12. [Progress Criteria & Tracking](#12-progress-criteria--tracking)
13. [Packages & Billing (Global)](#13-packages--billing-global)
14. [Data Model (Django)](#14-data-model-django)
15. [Business Rules Summary](#15-business-rules-summary)
16. [Open Items](#16-open-items)

---

## 1. Overview

### 1.1 Purpose

This specification defines the core domain model and business logic for the school, teacher, class, student, progress, and attendance systems within CWA Classroom. It covers:

- **School multi-tenancy** — Admin can manage multiple schools; all operational data is scoped to a school
- **Curriculum hierarchy** (Subject → Level → Topic → SubTopic) — global, shared across all schools
- Class management and scheduling — per school
- Teacher roles (Senior Teacher, Teacher, Junior Teacher) and capabilities
- Student enrollment and class join requests
- Attendance tracking for both students and teachers
- Progress criteria definition, approval, and daily tracking
- Package tiers that limit class enrollment

### 1.2 Scope

- Data model definitions for all entities
- Relationships and constraints between entities
- Business rules and workflows
- Package tier definitions (billing details deferred)

### 1.3 Out of Scope

- Billing implementation (pricing, payment processing, invoicing) — to be specified separately
- UI/UX design for these features
- API endpoint definitions
- Quiz engine integration

---

## 2. Roles & Permissions

### 2.1 Roles

CWA_CLASS_APP uses `accounts.Role` for role management. This spec **adds 2 new roles** (`senior_teacher`, `junior_teacher`) and replaces the generic `teacher` role with a 3-tier teacher hierarchy.

| # | Role | Slug | Description | Created By |
|---|------|------|-------------|------------|
| 1 | **Admin** | `admin` | Full system access. Creates schools, approves teacher attendance. | System/manual |
| 2 | **Senior Teacher** | `senior_teacher` | **NEW.** Approves progress criteria. All standard teacher capabilities. | Promoted by Admin |
| 3 | **Teacher** | `teacher` | Manages classes, marks attendance, creates progress criteria (draft). | Self-registers via `/accounts/register/teacher-center/` |
| 4 | **Junior Teacher** | `junior_teacher` | **NEW.** Same as Teacher minus criteria creation. | Created by Admin or assigned at registration |
| 5 | **Student** | `student` | Enrolled via a teacher/center. Takes quizzes, views progress. | Registered **by teacher** (no self-signup) |
| 6 | **Individual Student** | `individual_student` | Self-enrolled with subscription package. Can join classes later. | Self-registers via `/accounts/register/individual-student/` |
| 7 | **Accountant** | `accountant` | Billing and finance access. | Created by Admin |
| 8 | **Head of Department** | `head_of_department` | Department-level reporting. Assigns classes to teachers. | Created by Admin |

### 2.2 Teacher Role Hierarchy

The teacher role is split into 3 tiers stored as **separate roles** in `accounts.Role`:

```
Senior Teacher
  ├── All Teacher capabilities
  └── Can APPROVE progress criteria (gets notifications for pending criteria)

Teacher
  ├── All Junior Teacher capabilities
  └── Can CREATE progress criteria (draft → pending approval by Senior Teacher)

Junior Teacher
  ├── View assigned classes
  ├── Mark student attendance
  ├── Mark own attendance
  ├── Update student progress (record achievements + comments)
  ├── Approve/reject student join requests
  └── Revoke student enrollment
```

**Key difference:** Only the **criteria workflow** varies between tiers. All three tiers can manage attendance, progress records, and enrollments identically.

### 2.3 Role Capabilities in This Spec

| Capability | Admin | Sr. Teacher | Teacher | Jr. Teacher | Student | Indiv. Student | Accountant | HoD |
|-----------|-------|-------------|---------|-------------|---------|----------------|------------|-----|
| Create & manage schools | Yes | — | — | — | — | — | — | — |
| Select active school context | Yes | — | — | — | — | — | — | — |
| Define academic year & generate sessions | Yes | — | — | — | — | — | — | — |
| Cancel/modify class sessions | Yes | Own classes | Own classes | Own classes | — | — | — | — |
| Create progress criteria (draft) | — | Yes | Yes | — | — | — | — | — |
| Approve progress criteria | — | Yes | — | — | — | — | — | — |
| Mark student attendance | — | Own classes | Own classes | Own classes | — | — | — | — |
| Mark own (teacher) attendance | — | Yes | Yes | Yes | — | — | — | — |
| Approve teacher attendance | Yes | — | — | — | — | — | — | — |
| Update student progress | — | Own classes | Own classes | Own classes | — | — | — | — |
| Approve student join requests | — | Own classes | Own classes | Own classes | — | — | — | — |
| Revoke student enrollment | — | Own classes | Own classes | Own classes | — | — | — | — |
| Request to join a class | — | — | — | — | Yes | Yes | — | — |
| View own progress dashboard | — | — | — | — | Yes | Yes (if in class) | — | — |
| View own attendance | — | — | — | — | Yes | Yes (if in class) | — | — |
| Manage packages & billing | Yes | — | — | — | — | — | Yes | — |

### 2.4 Dashboard Redirect Priority

When a user with multiple roles logs in, they are redirected based on this priority:

1. Admin → Admin dashboard (with school selector)
2. Head of Department → `/department/`
3. Accountant → `/accounting/`
4. Senior Teacher → Teacher dashboard
5. Teacher → Teacher dashboard
6. Junior Teacher → Teacher dashboard
7. Individual Student → Student dashboard
8. Student → Student dashboard

### 2.5 Future Consideration

If a dedicated **Head Master** role is needed in the future (separate from Admin), it can be added to the `accounts.Role` model with specific permissions for:
- Approving teacher attendance (currently Admin)
- Overseeing curriculum structure
- School-level administration

---

## 3. Entity Definitions

### 3.1 Global vs Per-School Scoping

| Scope | Entities | Rationale |
|-------|----------|-----------|
| **Global** (platform-wide) | Subject, Level, Topic, TopicLevel, SubTopic, Package | Curriculum is shared across all schools. Packages are platform-wide tiers. |
| **Per-School** | School, Class, Enrollment, ClassSession, StudentAttendance, TeacherAttendance, ProgressCriteria, ProgressRecord, AcademicYear | Operational data is scoped to a school. |
| **Multi-School** (M2M) | Teacher ↔ School | Teachers can work at multiple schools. |
| **Derived** | Student ↔ School | Students are associated with schools through their class enrollments. |

### 3.2 Entity Table

| Entity | Scope | Description |
|--------|-------|-------------|
| **School** | — | An institute/center managed by an Admin. All operational data is scoped under a school. |
| **Subject** | Global | A discipline offered by the platform (e.g., Maths, Coding) |
| **Level** | Global | A year/grade tier within a subject (e.g., Year 7, Year 8, Python Level 1) |
| **Topic** | Global | A curriculum area within a subject (e.g., Algebra, Loops). Spans multiple levels. |
| **TopicLevel** | Global | The intersection of a Topic and a Level. Scopes subtopics to a specific level. |
| **SubTopic** | Global | A specific learning item within a Topic at a specific Level (e.g., "Quadratic Equations" under Algebra × Year 8) |
| **Class** | Per-School | A scheduled teaching group. Has exactly 1 subject, 1 level, a fixed schedule, and a unique class code. |
| **Teacher** | Multi-School | A user (Senior/Standard/Junior) who teaches classes, marks attendance, and tracks student progress. |
| **Student** | Derived | A user enrolled in classes. Associated with schools through enrollments. |
| **Enrollment** | Per-School | The relationship between a student and a class, with approval status. |
| **ClassSession** | Per-School | A single occurrence of a class (derived from the class schedule for a given date). |
| **StudentAttendance** | Per-School | A student's attendance record for a specific class session. |
| **TeacherAttendance** | Per-School | A teacher's attendance record for a specific class session, requiring Admin approval. |
| **ProgressCriteria** | Per-School | A defined learning milestone for a School + Subject + Level combination. Teacher/Senior Teacher-created, Senior Teacher-approved. |
| **ProgressRecord** | Per-School | A student's achievement against a specific criterion, recorded by a teacher within a class context. |
| **AcademicYear** | Per-School | Defines the year's date range for bulk session generation. Only one can be current per school. See §7.3. |
| **Package** | Global | A subscription tier that limits how many classes a student can join. |

---

## 4. Entity Relationships

### 4.1 ER Diagram (Text)

```
School (per-school tenant)
  │
  ├── M2M ── Admin (user can manage multiple schools)
  ├── M2M ── Teacher (teacher can work at multiple schools)
  ├── 1:many ── AcademicYear
  │
  ├── 1:many ── Class
  │     │ belongs to 1 Subject + 1 Level (global curriculum)
  │     │
  │     ├── M2M ── Teacher
  │     ├── M2M ── Student (through Enrollment)
  │     │
  │     ├── 1:many ── ClassSession
  │     │                │
  │     │                ├── StudentAttendance
  │     │                └── TeacherAttendance
  │     │
  │     └── ProgressRecord (Student × Class × Criteria)
  │
  └── 1:many ── ProgressCriteria (per School + Subject + Level)

Subject (global) ─────────────────────────────────────────────┐
  │ 1:many                                                    │
  ├── Level                                                   │
  │     │                                                     │
  │     ├── (M2M via TopicLevel) ── Topic ──┐                 │
  │     │                            │ 1:many to Subject ─────┘
  │     │                            │
  │     │                     TopicLevel (through)
  │     │                            │ 1:many
  │     │                        SubTopic
  │     │
  │     └── (ProgressCriteria is per School + Subject + Level)
```

### 4.2 Relationship Table

| From | To | Cardinality | Notes |
|------|----|-------------|-------|
| Admin | School | many:many | Admin can manage multiple schools |
| Teacher | School | many:many | Teacher can work at multiple schools |
| School | Class | 1:many | Class belongs to exactly 1 school |
| School | AcademicYear | 1:many | Each school defines its own academic years |
| School + Subject + Level | ProgressCriteria | 1:many | Criteria are per-school (different schools can have different criteria for same Subject+Level) |
| Subject | Level | 1:many | Level belongs to exactly 1 subject (global) |
| Subject | Topic | 1:many | Topic belongs to exactly 1 subject (global) |
| Topic | Level | many:many | Via TopicLevel (same subject enforced, global) |
| TopicLevel | SubTopic | 1:many | SubTopic scoped to Topic × Level (global) |
| Subject | Class | 1:many | Class has exactly 1 subject |
| Level | Class | 1:many | Class has exactly 1 level |
| Class | Teacher | many:many | Class can have multiple teachers |
| Class | Student | many:many | Via Enrollment (with approval status) |
| Class | ClassSession | 1:many | Sessions derived from schedule |
| ClassSession | StudentAttendance | 1:many | One record per student per session |
| ClassSession | TeacherAttendance | 1:many | One record per teacher per session |
| Student + Class + Criteria | ProgressRecord | unique | Each teacher records separately per class |

---

## 5. School System

### 5.1 School

A school (or institute/center) is the primary tenant in the system. All operational data (classes, enrollments, attendance, progress) is scoped to a school. One Admin can manage multiple schools and must select a school context before operating.

**Fields:**
- `name` — School display name (e.g., "Wizards Learning Hub — Auckland")
- `slug` — URL-safe identifier (unique)
- `address` — Physical address (optional)
- `contact_email` — School contact email (optional)
- `contact_phone` — School contact phone (optional)
- `admins` — M2M to Admin users
- `is_active` — Whether the school is currently operational
- `created_at`, `updated_at` — Timestamps

**Admin School Context:**
- Admin must select a school before accessing school-scoped features
- Selected school is stored in session (e.g., `request.session['active_school_id']`)
- All school-scoped queries filter by the active school
- Admin dashboard shows a school selector/switcher

### 5.2 Teacher ↔ School Membership

Teachers can work at multiple schools. Their school association is managed through a membership model.

**SchoolTeacher (through table):**
- `school` — FK to School
- `teacher` — FK to Teacher user
- `role` — Teacher's role at this school: `senior_teacher` | `teacher` | `junior_teacher`
- `joined_at` — Timestamp

**Constraint:** `unique_together: (school, teacher)`

**Notes:**
- A teacher can have **different seniority levels at different schools** (e.g., Senior Teacher at School A, regular Teacher at School B)
- The teacher's role in `accounts.Role` determines their **base capabilities** — the SchoolTeacher role refines their capabilities within a specific school
- When a teacher logs in, they see classes from all their schools (grouped by school)

---

## 6. Subject & Curriculum Hierarchy (Global)

All curriculum entities are **global** — shared across all schools. This ensures a consistent curriculum structure platform-wide.

### 6.1 Subject

A top-level discipline. All other curriculum entities are scoped under a subject.

**Examples:** Maths, Coding, Science, Music

**Fields:**
- `name` — Display name (unique)
- `slug` — URL-safe identifier (unique)
- `description` — Short description
- `is_active` — Whether the subject is currently offered

### 6.2 Level

A year or grade tier within a subject. Levels are subject-specific — "Year 7" in Maths is a different record from "Year 7" in Coding (if it exists).

**Examples:**
- Maths: Year 7, Year 8, Year 9
- Coding: Python Level 1, Python Level 2, Web Dev Level 1

**Fields:**
- `subject` — FK to Subject
- `name` — Display name (unique within subject)
- `order` — Display/sorting order within the subject
- `description` — Optional description

**Constraint:** `unique_together: (subject, name)`

### 6.3 Topic

A curriculum area within a subject. Topics are **not** scoped to a single level — they span multiple levels via the TopicLevel through table.

**Examples:**
- Maths: Algebra, Numbers, Statistics, Geometry
- Coding: Loops, Arrays, Functions, OOP

**Fields:**
- `subject` — FK to Subject
- `name` — Display name (unique within subject)
- `description` — Optional description

**Constraint:** `unique_together: (subject, name)`

### 6.4 TopicLevel (Through Table)

The many-to-many join between Topic and Level. Both must belong to the same Subject (enforced by validation). This is the anchor point for SubTopics — subtopics are specific to a Topic at a particular Level.

**Fields:**
- `topic` — FK to Topic
- `level` — FK to Level

**Constraints:**
- `unique_together: (topic, level)`
- Validation: `topic.subject == level.subject` (same subject enforced)

**Example:**
| Topic | Level | SubTopics |
|-------|-------|-----------|
| Algebra | Year 7 | Basic Equations, Number Patterns |
| Algebra | Year 8 | Quadratic Equations, Simultaneous Equations |
| Numbers | Year 7 | Fractions, Decimals |
| Numbers | Year 8 | Surds, Indices |

### 6.5 SubTopic

A specific learning item scoped to a Topic at a specific Level.

**Fields:**
- `topic_level` — FK to TopicLevel
- `name` — Display name (unique within topic_level)
- `order` — Display/sorting order
- `description` — Optional description

**Constraint:** `unique_together: (topic_level, name)`

---

## 7. Class System

### 7.1 Class

A scheduled teaching group tied to exactly one School, one Subject, and one Level. Identified by a unique class code that students use to request enrollment.

**Fields:**
- `school` — FK to School **(per-school scoping)**
- `subject` — FK to Subject
- `level` — FK to Level
- `name` — Display name (e.g., "Maths Year 8 — Monday Group")
- `class_code` — Unique alphanumeric code (auto-generated or teacher-set)
- `schedule_day` — Day of week (Monday–Sunday)
- `schedule_time` — Start time
- `schedule_duration` — Duration in minutes (optional)
- `teachers` — M2M to Teacher
- `is_active` — Whether the class is currently running
- `created_at`, `updated_at` — Timestamps

**Constraints:**
- `level.subject == subject` (enforced by validation)
- `class_code` is unique across all classes
- Teachers assigned to a class must be members of the class's school

**Notes:**
- A class can have multiple teachers (e.g., main teacher + assistant)
- Multiple classes can exist for the same Subject + Level (different schedules/teachers)
- This enables the "catchup" scenario: a student attends Maths Year 7 on Monday (Class A, Teacher X) AND Wednesday (Class B, Teacher Y)

### 7.2 ClassSession

A single occurrence of a class on a specific date. Used as the anchor for attendance records.

**Fields:**
- `class_ref` — FK to Class
- `date` — Date of the session
- `status` — `scheduled` | `completed` | `cancelled`
- `notes` — Optional session notes by teacher

**Constraint:** `unique_together: (class_ref, date)`

**Generation:** See §7.3.

### 7.3 Session Generation & Holidays

Sessions are **bulk-generated at the start of the year** for each class based on its fixed schedule.

**Generation Process:**
```
1. Admin defines the academic year date range (e.g., 2026-02-02 to 2026-12-18)
2. System generates ClassSession records for each class:
   - For a class scheduled on Mondays, create a session for every Monday in the date range
   - All generated sessions start with status = "scheduled"
3. Admin/Teacher can then modify the generated sessions:
   - Cancel sessions for known holidays → status = "cancelled"
   - Add extra sessions if needed (e.g., makeup classes)
   - Reschedule is done by cancelling + creating a new session on a different date
```

**Holiday Handling:**
- There is no separate holiday calendar model (for now)
- Holidays are handled by **cancelling individual sessions** after generation
- Cancelled sessions remain in the database (status = `cancelled`) for audit purposes
- Attendance is not recorded for cancelled sessions

**Modification Rules:**
- Admin can cancel/modify any session
- Teachers can cancel/modify sessions for their own classes
- Sessions with existing attendance records should warn before cancellation

**AcademicYear Model (supporting session generation):**

**Fields:**
- `name` — Display name (e.g., "2026")
- `start_date` — First day of the academic year
- `end_date` — Last day of the academic year
- `is_current` — Boolean (only one can be current)

**Constraint:** Only one `is_current = True` at a time

---

## 8. Teacher System

### 8.1 Teacher Roles

Teachers are users with one of three roles: `senior_teacher`, `teacher`, or `junior_teacher`. A teacher's seniority **can vary per school** via the SchoolTeacher membership (see §5.2).

### 8.2 Teacher Capabilities by Tier

| Capability | Senior Teacher | Teacher | Junior Teacher |
|-----------|---------------|---------|----------------|
| View assigned classes | Own classes | Own classes | Own classes |
| Mark student attendance | Per class session | Per class session | Per class session |
| Mark own attendance | Per class session | Per class session | Per class session |
| Update student progress | Per student, per class, per criteria, daily | Same | Same |
| Create progress criteria (draft) | Yes (per School + Subject + Level) | Yes (per School + Subject + Level) | **No** |
| Approve progress criteria | **Yes** (gets notifications) | No | No |
| Approve student join requests | Per class | Per class | Per class |
| Revoke student access | Per class | Per class | Per class |

### 8.3 Teacher ↔ School/Class Relationship

- A teacher can belong to **multiple schools** (via SchoolTeacher M2M)
- A teacher's seniority can differ per school (e.g., Senior at School A, Teacher at School B)
- A teacher's subjects are **derived** from their assigned classes (no direct Teacher ↔ Subject M2M needed)
- A teacher can teach multiple classes across different subjects, levels, and schools
- When logged in, a teacher sees classes from all their schools (grouped by school)

---

## 9. Student System

### 9.1 Student Types

There are two categories of students:

| Type | Has Classes | Has Attendance | Has Teacher | Has Progress |
|------|-------------|----------------|-------------|--------------|
| **Class Student** | Yes (1+) | Yes | Yes (via class) | Yes (per class) |
| **Individual Student** | Optional (0+) | Only if in a class | Only if in a class | Can have progress if in a class |

### 9.2 Individual Student Specifics

- Signs up independently (not through a class/center)
- Initially has **no classes, no teacher, no attendance**
- Can request to join a class at any time after signup (not during signup)
- Once enrolled in a class, behaves like a class student for that class
- Limited by their package tier (1 / 5 / unlimited classes)

### 9.3 Student Capabilities

| Capability | Scope | Details |
|-----------|-------|---------|
| View enrolled classes | Own enrollments | See classes they are part of |
| View progress dashboard | Per class | See teacher comments and criteria achievements |
| Request to join a class | Using class code | Submit join request for teacher approval |
| View suggested next criteria | Per class | System suggests next unachieved criterion in order |

### 9.4 Catchup Scenario (Same Student, 2 Classes)

A student needing extra support can be enrolled in **two separate classes** at the same Subject + Level.

**Example:**
- Alice is enrolled in "Maths Year 7 — Monday" (Teacher X) AND "Maths Year 7 — Wednesday" (Teacher Y)
- Both classes share the same ProgressCriteria (defined at Subject + Level)
- But each teacher records ProgressRecords **independently** within their own class context
- Alice's dashboard shows progress from **both** classes separately
- Attendance is tracked separately per class session

---

## 10. Enrollment & Join Flow

### 10.1 Enrollment Model

The enrollment represents a student's membership in a class.

**Fields:**
- `student` — FK to Student
- `class_ref` — FK to Class
- `status` — `pending` | `approved` | `revoked`
- `requested_at` — When the student submitted the join request
- `approved_at` — When the teacher approved (nullable)
- `approved_by` — FK to Teacher who approved (nullable)
- `revoked_at` — When access was revoked (nullable)
- `revoked_by` — FK to Teacher who revoked (nullable)

**Constraint:** `unique_together: (student, class_ref)`

### 10.2 Join Flow

```
1. Student obtains class code (from teacher, website, etc.)
2. Student enters class code in "Join Class" form
3. System validates:
   a. Class code exists and class is active
   b. Student is not already enrolled in this class
   c. Student's package allows another class enrollment
4. Enrollment created with status = "pending"
5. Teacher(s) of that class see the pending request
6. Teacher approves or rejects:
   - Approve → status = "approved", student gains access
   - Reject → enrollment deleted or status = "rejected"
7. Student is notified of the outcome
```

### 10.3 Revoke Access

- Any teacher of the class can revoke a student's enrollment
- Status changes to `revoked`, student loses access
- `revoked_at` and `revoked_by` are recorded
- Student can re-request enrollment (teacher can approve again)

### 10.4 Package Limit Enforcement

Before creating an enrollment, the system checks:
```
active_enrollments = Enrollment.filter(student=student, status="approved").count()
if active_enrollments >= student.package.class_limit:
    raise ValidationError("Package limit reached")
```
- `class_limit = null` means unlimited

---

## 11. Attendance System

### 11.1 Student Attendance

Tracked per student per class session. Marked by the teacher.

**Fields:**
- `student` — FK to Student
- `session` — FK to ClassSession
- `status` — `present` | `absent` | `late`
- `marked_by` — FK to Teacher
- `marked_at` — Timestamp
- `notes` — Optional notes

**Constraint:** `unique_together: (student, session)`

**Rules:**
- Only teachers assigned to the class can mark attendance
- Attendance can be updated (e.g., correcting a mistake)
- Individual students without classes have no attendance records

### 11.2 Teacher Attendance

Teachers self-report their attendance per class session. Requires Admin approval.

**Fields:**
- `teacher` — FK to Teacher
- `session` — FK to ClassSession
- `status` — `present` | `absent`
- `approval_status` — `pending` | `approved` | `rejected`
- `approved_by` — FK to Admin user (nullable)
- `approved_at` — Timestamp (nullable)
- `notes` — Optional notes

**Constraint:** `unique_together: (teacher, session)`

**Workflow:**
```
1. Teacher marks themselves as present/absent for a class session
2. Record created with approval_status = "pending"
3. Admin sees pending teacher attendance records
4. Admin approves or rejects
5. Approved records may feed into payroll/billing (TBD)
```

---

## 12. Progress Criteria & Tracking

### 12.1 Progress Criteria

Criteria are learning milestones defined at the **School + Subject + Level** scope. They are shared across all classes of that School + Subject + Level combination. Different schools can define different criteria for the same Subject + Level.

**Fields:**
- `school` — FK to School **(per-school scoping)**
- `subject` — FK to Subject
- `level` — FK to Level
- `name` — Criterion description (e.g., "Can solve linear equations")
- `description` — Detailed description (optional)
- `order` — Suggested sequence order
- `status` — `draft` | `pending_approval` | `approved`
- `created_by` — FK to Teacher (Senior Teacher or Teacher role; not Junior Teacher)
- `approved_by` — FK to Senior Teacher user (nullable)
- `created_at`, `updated_at` — Timestamps

**Constraints:**
- `unique_together: (school, subject, level, name)`
- `level.subject == subject` (enforced by validation)
- Only `approved` criteria are visible for progress tracking
- Only users with `senior_teacher` or `teacher` role (at the relevant school) can create criteria
- Only users with `senior_teacher` role (at the relevant school) can approve criteria

### 12.2 Criteria Approval Workflow

```
1. Teacher or Senior Teacher creates a criterion → status = "draft"
2. Teacher submits for approval → status = "pending_approval"
3. Senior Teacher(s) at the same school are NOTIFIED of pending criteria
4. Senior Teacher reviews:
   - Approve → status = "approved", criterion becomes active
   - Reject → status = "draft" (with feedback)
5. Only approved criteria appear in progress tracking
6. Admin can also approve as an override (full system access)
```

**Notification:** When a criterion moves to `pending_approval`, all Senior Teachers at that school should receive a notification (in-app and/or email — implementation TBD in OI-5).

### 12.3 Criteria Ordering

- Each criterion has an `order` field defining the suggested learning sequence
- Example for Maths Year 8:
  1. "Can identify quadratic expressions"
  2. "Can factor simple quadratics"
  3. "Can solve quadratic equations"
  4. "Can plot quadratic graphs"
- **Order is suggested, not enforced** — students can achieve criteria in any order
- The system highlights the **next unachieved criterion** in sequence as the suggested next step

### 12.4 Progress Record

A record of a student's achievement against a specific criterion, within a specific class context.

**Fields:**
- `student` — FK to Student
- `class_ref` — FK to Class
- `criteria` — FK to ProgressCriteria
- `teacher` — FK to Teacher (who recorded this entry)
- `date` — Date of the progress entry
- `achieved` — Boolean (has the student met this criterion?)
- `comment` — Teacher's comment (displayed in dashboard)
- `created_at`, `updated_at` — Timestamps

**Constraint:** `unique_together: (student, class_ref, criteria, date)`

**This allows:**
- Multiple entries per criterion over time (daily updates)
- Same criterion tracked independently by different teachers in different classes (catchup scenario)
- Teacher comments displayed in the student's dashboard tab

### 12.5 Progress Dashboard Display

The student dashboard shows:
- List of all approved criteria for their Subject + Level (ordered)
- For each criterion: achieved status, teacher comments (most recent)
- Suggested next step: first unachieved criterion in order sequence
- If enrolled in multiple classes at same level: progress shown **per class** with teacher name

**Example Dashboard View for Alice (Maths Year 7, enrolled in 2 classes):**

```
Maths Year 7 — Progress

Monday Class (Teacher X):
  ✅ Can identify linear expressions — "Great work, Alice!" (Mar 3)
  ✅ Can solve simple linear equations — "Solid understanding" (Mar 5)
  ⬜ Can plot linear graphs ← Suggested next step
  ⬜ Can interpret graph data

Wednesday Class (Teacher Y):
  ✅ Can identify linear expressions — "Good start" (Mar 4)
  ⬜ Can solve simple linear equations ← Suggested next step
  ⬜ Can plot linear graphs
  ⬜ Can interpret graph data
```

---

## 13. Packages & Billing (Global)

### 13.1 Package Tiers

Three tiers control how many classes a student can join:

| Package | Class Limit | Description |
|---------|-------------|-------------|
| **Basic** | 1 | Single class enrollment |
| **Standard** | 5 | Up to 5 class enrollments |
| **Unlimited** | No limit | Unlimited class enrollments |

### 13.2 Package Model

**Fields:**
- `name` — Package name
- `slug` — URL-safe identifier
- `class_limit` — Integer (null = unlimited)
- `description` — Package description
- `is_active` — Whether this package is currently offered
- `order` — Display order

### 13.3 Student ↔ Package

- Each student has one active package
- Package is checked during enrollment (see §10.4)
- Default package for new students: TBD (likely Basic)

### 13.4 Billing (Deferred)

The following billing details are **out of scope** for this spec and will be defined separately:

- Pricing per package tier
- Billing frequency (monthly, termly, annually)
- Payment processing integration
- Invoice generation
- Who pays (student, parent, center)
- Whether billing is tied to attendance
- Differences between individual and class student billing
- Package upgrade/downgrade flows
- Trial periods or free tiers

---

## 14. Data Model (Django)

### 14.1 School Models

```python
class School(models.Model):
    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    address = models.TextField(blank=True)
    contact_email = models.EmailField(blank=True)
    contact_phone = models.CharField(max_length=20, blank=True)
    admins = models.ManyToManyField('accounts.CustomUser', related_name='managed_schools', blank=True,
                                    limit_choices_to={'roles__name': 'admin'})
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']


class SchoolTeacher(models.Model):
    """M2M through table: links a Teacher to a School with a school-specific seniority role."""
    ROLE_CHOICES = [
        ('senior_teacher', 'Senior Teacher'),
        ('teacher', 'Teacher'),
        ('junior_teacher', 'Junior Teacher'),
    ]

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='school_teachers')
    teacher = models.ForeignKey('accounts.CustomUser', on_delete=models.CASCADE, related_name='school_memberships',
                                 limit_choices_to={'roles__name__in': ['senior_teacher', 'teacher', 'junior_teacher']})
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='teacher')
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('school', 'teacher')
```

### 14.2 Curriculum Models (Global)

```python
class Subject(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(unique=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']


class Level(models.Model):
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name='levels')
    name = models.CharField(max_length=100)
    order = models.PositiveIntegerField(default=0)
    description = models.TextField(blank=True)

    class Meta:
        unique_together = ('subject', 'name')
        ordering = ['subject', 'order']


class Topic(models.Model):
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name='topics')
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)

    class Meta:
        unique_together = ('subject', 'name')
        ordering = ['name']


class TopicLevel(models.Model):
    """Through table: links a Topic to a Level within the same Subject.
    SubTopics are scoped to this intersection."""
    topic = models.ForeignKey(Topic, on_delete=models.CASCADE, related_name='topic_levels')
    level = models.ForeignKey(Level, on_delete=models.CASCADE, related_name='topic_levels')

    class Meta:
        unique_together = ('topic', 'level')

    def clean(self):
        if self.topic.subject != self.level.subject:
            raise ValidationError('Topic and Level must belong to the same Subject.')


class SubTopic(models.Model):
    topic_level = models.ForeignKey(TopicLevel, on_delete=models.CASCADE, related_name='subtopics')
    name = models.CharField(max_length=200)
    order = models.PositiveIntegerField(default=0)
    description = models.TextField(blank=True)

    class Meta:
        unique_together = ('topic_level', 'name')
        ordering = ['order']
```

### 14.3 Academic Year Model (Per-School)

```python
class AcademicYear(models.Model):
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='academic_years')
    name = models.CharField(max_length=50)  # e.g., "2026"
    start_date = models.DateField()
    end_date = models.DateField()
    is_current = models.BooleanField(default=False)

    class Meta:
        unique_together = ('school', 'name')
        ordering = ['-start_date']

    def clean(self):
        if self.start_date >= self.end_date:
            raise ValidationError('Start date must be before end date.')

    def save(self, *args, **kwargs):
        if self.is_current:
            # Ensure only one academic year is current PER SCHOOL
            AcademicYear.objects.filter(school=self.school, is_current=True).exclude(pk=self.pk).update(is_current=False)
        super().save(*args, **kwargs)
```

### 14.4 Class Models (Per-School)

```python
class Class(models.Model):
    DAYS_OF_WEEK = [
        ('MON', 'Monday'), ('TUE', 'Tuesday'), ('WED', 'Wednesday'),
        ('THU', 'Thursday'), ('FRI', 'Friday'), ('SAT', 'Saturday'), ('SUN', 'Sunday'),
    ]

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='classes')
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name='classes')
    level = models.ForeignKey(Level, on_delete=models.CASCADE, related_name='classes')
    name = models.CharField(max_length=200)
    class_code = models.CharField(max_length=20, unique=True)
    schedule_day = models.CharField(max_length=3, choices=DAYS_OF_WEEK)
    schedule_time = models.TimeField()
    schedule_duration = models.PositiveIntegerField(help_text='Duration in minutes', null=True, blank=True)
    teachers = models.ManyToManyField('accounts.CustomUser', related_name='teaching_classes', blank=True,
                                      limit_choices_to={'roles__name__in': ['senior_teacher', 'teacher', 'junior_teacher']})
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = 'classes'

    def clean(self):
        if self.level.subject != self.subject:
            raise ValidationError('Level must belong to the selected Subject.')


class ClassSession(models.Model):
    STATUS_CHOICES = [
        ('scheduled', 'Scheduled'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ]

    class_ref = models.ForeignKey(Class, on_delete=models.CASCADE, related_name='sessions')
    date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='scheduled')
    notes = models.TextField(blank=True)

    class Meta:
        unique_together = ('class_ref', 'date')
        ordering = ['-date']
```

### 14.5 Enrollment Model

```python
class Enrollment(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('revoked', 'Revoked'),
    ]

    student = models.ForeignKey('accounts.Student', on_delete=models.CASCADE, related_name='enrollments')
    class_ref = models.ForeignKey(Class, on_delete=models.CASCADE, related_name='enrollments')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    requested_at = models.DateTimeField(auto_now_add=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey('accounts.Teacher', on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_enrollments')
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey('accounts.Teacher', on_delete=models.SET_NULL, null=True, blank=True, related_name='revoked_enrollments')

    class Meta:
        unique_together = ('student', 'class_ref')
```

### 14.6 Attendance Models

```python
class StudentAttendance(models.Model):
    STATUS_CHOICES = [
        ('present', 'Present'),
        ('absent', 'Absent'),
        ('late', 'Late'),
    ]

    student = models.ForeignKey('accounts.Student', on_delete=models.CASCADE, related_name='attendance_records')
    session = models.ForeignKey(ClassSession, on_delete=models.CASCADE, related_name='student_attendance')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES)
    marked_by = models.ForeignKey('accounts.Teacher', on_delete=models.SET_NULL, null=True, related_name='marked_student_attendance')
    marked_at = models.DateTimeField(auto_now=True)
    notes = models.TextField(blank=True)

    class Meta:
        unique_together = ('student', 'session')


class TeacherAttendance(models.Model):
    STATUS_CHOICES = [
        ('present', 'Present'),
        ('absent', 'Absent'),
    ]
    APPROVAL_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]

    teacher = models.ForeignKey('accounts.Teacher', on_delete=models.CASCADE, related_name='attendance_records')
    session = models.ForeignKey(ClassSession, on_delete=models.CASCADE, related_name='teacher_attendance')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES)
    approval_status = models.CharField(max_length=20, choices=APPROVAL_CHOICES, default='pending')
    approved_by = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_teacher_attendance')
    approved_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        unique_together = ('teacher', 'session')
```

### 14.7 Progress Models (Per-School)

```python
class ProgressCriteria(models.Model):
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('pending_approval', 'Pending Approval'),
        ('approved', 'Approved'),
    ]

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='progress_criteria')
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name='progress_criteria')
    level = models.ForeignKey(Level, on_delete=models.CASCADE, related_name='progress_criteria')
    name = models.CharField(max_length=300)
    description = models.TextField(blank=True)
    order = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    created_by = models.ForeignKey('accounts.CustomUser', on_delete=models.SET_NULL, null=True,
                                    related_name='created_criteria',
                                    limit_choices_to={'roles__name__in': ['senior_teacher', 'teacher']})
    approved_by = models.ForeignKey('accounts.CustomUser', on_delete=models.SET_NULL, null=True, blank=True,
                                     related_name='approved_criteria',
                                     limit_choices_to={'roles__name__in': ['senior_teacher', 'admin']})
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('school', 'subject', 'level', 'name')
        ordering = ['school', 'subject', 'level', 'order']
        verbose_name_plural = 'progress criteria'

    def clean(self):
        if self.level.subject != self.subject:
            raise ValidationError('Level must belong to the selected Subject.')


class ProgressRecord(models.Model):
    student = models.ForeignKey('accounts.Student', on_delete=models.CASCADE, related_name='progress_records')
    class_ref = models.ForeignKey(Class, on_delete=models.CASCADE, related_name='progress_records')
    criteria = models.ForeignKey(ProgressCriteria, on_delete=models.CASCADE, related_name='records')
    teacher = models.ForeignKey('accounts.Teacher', on_delete=models.SET_NULL, null=True, related_name='recorded_progress')
    date = models.DateField()
    achieved = models.BooleanField(default=False)
    comment = models.TextField(blank=True, help_text='Displayed in student dashboard as teacher comment')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('student', 'class_ref', 'criteria', 'date')
        ordering = ['-date']
```

### 14.8 Package Model (Global)

```python
class Package(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(unique=True)
    class_limit = models.PositiveIntegerField(
        null=True, blank=True,
        help_text='Max classes a student can join. Null = unlimited.'
    )
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order']
```

---

## 15. Business Rules Summary

### 15.1 School Rules

| # | Rule |
|---|------|
| SC-1 | An Admin can manage multiple schools |
| SC-2 | Admin must select an active school context before accessing school-scoped features |
| SC-3 | A teacher can belong to multiple schools (via SchoolTeacher) |
| SC-4 | A teacher's seniority role can differ per school |
| SC-5 | Teachers assigned to a class must be members of that class's school |
| SC-6 | All school-scoped queries must filter by the active school |

### 15.2 Curriculum Rules (Global)

| # | Rule |
|---|------|
| CR-1 | A Level belongs to exactly one Subject |
| CR-2 | A Topic belongs to exactly one Subject |
| CR-3 | TopicLevel links Topic and Level; both must share the same Subject |
| CR-4 | SubTopics are scoped to a TopicLevel (Topic × Level), not to Topic alone |
| CR-5 | Deleting a Subject cascades to its Levels, Topics, TopicLevels, and SubTopics |
| CR-6 | Curriculum is global — shared across all schools |

### 15.3 Class Rules (Per-School)

| # | Rule |
|---|------|
| CL-1 | A Class belongs to exactly one School, one Subject, and one Level; the Level must belong to the Subject |
| CL-2 | A Class has a unique class code |
| CL-3 | A Class has a fixed schedule (day + time) |
| CL-4 | A Class can have multiple teachers (all must be members of the class's school) |
| CL-5 | Multiple classes can exist for the same School + Subject + Level (different schedules) |
| CL-6 | ClassSessions are unique per Class + Date |

### 15.4 Role Rules

| # | Rule |
|---|------|
| RL-1 | Teacher roles are: `senior_teacher`, `teacher`, `junior_teacher` (3 separate roles in `accounts.Role`) |
| RL-2 | SchoolTeacher membership defines a teacher's seniority at a specific school |
| RL-3 | Only Senior Teachers and Teachers can create progress criteria (not Junior Teachers) |
| RL-4 | Only Senior Teachers can approve progress criteria (Admin can override) |
| RL-5 | Senior Teachers receive notifications when criteria are pending approval |
| RL-6 | All three teacher tiers can: mark attendance, update progress, manage enrollments |

### 15.5 Enrollment Rules

| # | Rule |
|---|------|
| EN-1 | A student joins a class by submitting the class code |
| EN-2 | Enrollment starts as `pending`; teacher must approve |
| EN-3 | A student cannot be enrolled in the same class twice |
| EN-4 | A student CAN be enrolled in multiple classes at the same Subject + Level (catchup) |
| EN-5 | Enrollment is checked against the student's package class_limit (count of `approved` enrollments) |
| EN-6 | Teachers can revoke enrollment; student can re-request |
| EN-7 | Individual students can join classes after signup (not during) |

### 15.6 Attendance Rules

| # | Rule |
|---|------|
| AT-1 | Student attendance is per session, marked by a teacher of the class |
| AT-2 | Teacher attendance is per session, self-reported |
| AT-3 | Teacher attendance requires Admin approval |
| AT-4 | Only teachers assigned to the class can mark student attendance |
| AT-5 | Individual students without classes have no attendance records |
| AT-6 | Attendance can be updated (corrections allowed) |

### 15.7 Progress Rules

| # | Rule |
|---|------|
| PR-1 | Progress criteria are defined per **School + Subject + Level** (not per class) |
| PR-2 | Criteria are created by Teachers/Senior Teachers, approved by **Senior Teachers** |
| PR-3 | Only approved criteria are used for progress tracking |
| PR-4 | Criteria have a suggested order; achievement order is not enforced |
| PR-5 | Progress records are per Student + Class + Criteria + Date |
| PR-6 | Each teacher records progress independently within their class context |
| PR-7 | The dashboard suggests the next unachieved criterion in order |
| PR-8 | Progress comments are displayed in the student dashboard |
| PR-9 | Different schools can define different criteria for the same Subject + Level |

### 15.8 Package Rules (Global)

| # | Rule |
|---|------|
| PK-1 | Each student has one active package |
| PK-2 | Basic = 1 class, Standard = 5 classes, Unlimited = no limit |
| PK-3 | Package limit is enforced at enrollment time |
| PK-4 | `class_limit = null` means unlimited |
| PK-5 | Packages are global — not scoped to a school |

---

## 16. Open Items

These items require further definition in future spec iterations:

| # | Item | Notes |
|---|------|-------|
| OI-1 | **Billing details** | Pricing, payment processing, billing frequency, who pays |
| ~~OI-2~~ | ~~**Head master role**~~ | **RESOLVED:** Admin handles teacher attendance approval. Progress criteria approval moved to **Senior Teacher** role. 3 teacher tiers added: `senior_teacher`, `teacher`, `junior_teacher`. Head Master can be added in future if needed. |
| ~~OI-3~~ | ~~**Class session auto-generation**~~ | **RESOLVED:** Sessions are bulk-generated at the start of the year for each class based on its schedule. Admin/teacher can modify after generation (cancel, add, reschedule). See §7.3. |
| ~~OI-4~~ | ~~**Holiday handling**~~ | **RESOLVED:** After bulk generation, holidays are handled by cancelling individual sessions (status = `cancelled`). Teachers/Admin can cancel sessions manually. See §7.3. |
| OI-5 | **Notifications** | How are teachers notified of join requests? How are students notified of approval? |
| OI-6 | **Package assignment** | When and how is a package assigned to a student? At signup? By admin? |
| OI-7 | **Package upgrade/downgrade** | What happens to enrollments if a student downgrades and exceeds the new limit? |
| OI-8 | **Progress criteria editing** | Can approved criteria be edited? Re-ordered? Archived? |
| OI-9 | **Individual student progress without class** | Can individual students (no class) have progress tracked? By whom? |
| ~~OI-10~~ | ~~**Multi-day class schedules**~~ | **RESOLVED:** For now, each class has a single schedule day. A class meeting Mon + Wed = 2 separate Class records. Future: may add M2M schedule support if needed. |
| OI-11 | **School creation flow** | How does an Admin create a new school? Through Django admin, or a dedicated UI? |
| OI-12 | **School context switching UX** | How does the Admin school selector work? Dropdown in nav bar? Separate page? |
| OI-13 | **Teacher school assignment** | How are teachers added to a school? Admin invites them? Teacher requests? Auto-assigned at registration? |
| OI-14 | **Student cross-school enrollment** | Can an individual student join classes at multiple schools, or must they stay within one school? |
| OI-15 | **Senior Teacher promotion flow** | How is a teacher promoted to Senior Teacher at a school? Admin action? Request workflow? |

---

*End of specification.*
