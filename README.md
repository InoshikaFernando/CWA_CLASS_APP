# Requirements Specification

## CWA School - Classroom

**Application Name:** Classroom (currently hosted at classroom.wizardslearninghub.co.nz)
**Technology Stack:** Django 4.2+, Python 3.10, MySQL 8.0, Pillow
**Timezone:** Pacific/Auckland (New Zealand)

---

## Table of Contents

1. [Introduction](#1-introduction)
2. [System Overview](#2-system-overview)
3. [User Roles and Authentication](#3-user-roles-and-authentication)
4. [Functional Requirements](#4-functional-requirements)
   - 4.1 [Registration and Authentication](#41-registration-and-authentication)
   - 4.2 [Classroom Management](#42-classroom-management)
     - 4.2.1 [Create Class](#fr-421-create-class-teacher-only)
     - 4.2.2 [Assign Students to Class](#fr-422-assign-students-to-class-teacher-only)
     - 4.2.3 [Assign Teachers to Class](#fr-423-assign-teachers-to-class-teacher-only)
     - 4.2.4 [Individual Student Class Selection](#fr-424-individual-student-class-selection)
     - 4.2.5 [Level Access Control](#fr-425-level-access-control)
   - 4.3 [Student Dashboard](#43-student-dashboard)
   - 4.4 [Teacher Dashboard](#44-teacher-dashboard)
   - 4.4a [HeadOfDepartment Dashboard](#44a-headofdepartment-dashboard)
   - 4.4b [Accountant Dashboard](#44b-accountant-dashboard)
   - 4.5 [Year-Level Subject and Topic System](#45-year-level-subject-and-topic-system)
   - 4.6 [Basic Facts Module](#46-basic-facts-module)
   - 4.7 [Topic-Based Quizzes](#47-topic-based-quizzes)
   - 4.8 [Mixed (Take Quiz) Quizzes](#48-mixed-take-quiz-quizzes)
   - 4.9 [Times Tables (Multiplication and Division)](#49-times-tables-multiplication-and-division)
   - 4.10 [Practice Mode](#410-practice-mode)
   - 4.11 [Scoring and Points System](#411-scoring-and-points-system)
   - 4.12 [Progress Tracking and Statistics](#412-progress-tracking-and-statistics)
   - 4.13 [Time Tracking](#413-time-tracking)
   - 4.14 [User Profile Management](#414-user-profile-management)
   - 4.15 [Question Management (Teacher)](#415-question-management-teacher)
5. [Non-Functional Requirements](#5-non-functional-requirements)
6. [Data Model](#6-data-model)
7. [API Endpoints](#7-api-endpoints)
8. [Appendix: Mathematics Year-Topic Mapping](#8-appendix-mathematics-year-topic-mapping)

---

## 1. Introduction

### 1.1 Purpose

This document specifies the functional and non-functional requirements for the **Classroom** web application, an educational platform designed for primary and intermediate school students (approximately Years 1-8) to practise curriculum content across multiple subjects. **Mathematics is the first supported subject**, with the platform designed to support additional subjects in the future. The system supports class-based learning managed by teachers as well as self-directed individual students.

### 1.2 Scope

The application covers:

- User registration and authentication with a flexible, extensible role-based access control system.
- Built-in roles: Admin, Teacher, Student, IndividualStudent, Accountant, HeadOfDepartment -- with the ability to add custom roles.
- Class-centric management: classes with many-to-many relationships to both teachers and students.
- HeadOfDepartment can assign classes to teachers; teachers can assign students to classes.
- Subscription packages for individual students (1, 3, 5, or unlimited classes).
- Level-based access control determined by class membership.
- A structured curriculum organised by **Year levels** (Years 1-8) and **Subjects** (e.g., Mathematics), where each subject is broken down into **Topics** (e.g., Measurements, Multiplication).
- Mathematics subject modules: **Basic Facts** drills (Addition, Subtraction, Multiplication, Division, Place Value Facts) and **Times Tables** quizzes (1x through 12x).
- Timed quizzes with an automated scoring/points system.
- Progress tracking with statistical comparison (mean and standard deviation colour-coding).
- Daily and weekly time-on-task tracking.
- Teacher tools for question management, class management, and bulk student registration.

### 1.3 Intended Audience

- Developers maintaining or extending the application.
- Teachers and school administrators evaluating the system.
- QA testers validating functionality.

---

## 2. System Overview

Classroom is a server-rendered Django web application. The core Django app is named `classroom`. The application uses a **flexible role-based access control** system where each user account can be assigned one or more roles. Built-in roles include Admin, Teacher, Student, IndividualStudent, Accountant, and HeadOfDepartment, with the ability to define additional custom roles as needed. A **Class** is the central organisational unit linking teachers and students in a many-to-many relationship. Curriculum content is organised into **Levels** (Year levels for curriculum content, numeric IDs >= 100 for Basic Facts), **Subjects** (e.g., Mathematics), and **Topics** within each subject (e.g., Measurements, Fractions, BODMAS/PEMDAS). Each role receives a role-specific dashboard and set of permissions.

### 2.1 High-Level Architecture

```
Browser (HTML/CSS/JS)
  |
Django Application (Classroom platform; current core app: `classroom`)
  |
Database (MySQL 8.0)
  |
Media Storage (uploaded question images)
```

### 2.2 Deployment

- **Production host:** classroom.wizardslearninghub.co.nz
- **Database:** MySQL 8.0 for both local development and production environments.
- **Email:** Console backend in development; Gmail SMTP in production.

---

## 3. User Roles and Authentication

### 3.1 User Model

The system uses a custom user model (`CustomUser`) extending Django's `AbstractUser` with the following additional fields:

| Field            | Type        | Description                         |
|------------------|-------------|-------------------------------------|
| `date_of_birth`  | Date (optional) | Used for age-based Basic Facts statistics |
| `country`        | String (optional) | User's country                  |
| `region`         | String (optional) | User's region/state/province    |
| `package`        | FK (optional) | The subscription package for IndividualStudent users (null for all other roles) |
| `roles`          | M2M to `Role` | One or more roles assigned to the user (via `UserRole` through table) |

### 3.2 Role Model

Roles are stored in a dedicated `Role` database table, making the system **extensible** -- new roles can be added at any time via the Django admin without code changes.

| Field            | Type        | Description                         |
|------------------|-------------|-------------------------------------|
| `name`           | String (unique) | Machine-readable role identifier (e.g., `admin`, `teacher`, `student`, `individual_student`, `accountant`, `head_of_department`) |
| `display_name`   | String      | Human-readable label (e.g., "Head of Department") |
| `description`    | Text (optional) | Description of the role's purpose |
| `is_active`      | Boolean     | Whether this role is currently available for assignment |
| `created_at`     | DateTime    | When the role was created           |

A user can hold **multiple roles simultaneously** (e.g., a user could be both a Teacher and a HeadOfDepartment).

### 3.3 Built-in Roles

| Role                    | Name Identifier         | Description | Key Capabilities |
|-------------------------|------------------------|-------------|------------------|
| **Admin**               | `admin`                | Platform administrator. Only the admin user has this role. | Full Django admin access to all models, role management, package configuration, system settings. |
| **Teacher**             | `teacher`              | Creates and manages classes. Can belong to multiple classes. | Create classes, assign students to classes, register students (individual + bulk), add questions, browse topics/levels, view class progress. |
| **Student**             | `student`              | A class-enrolled student assigned to classes by a teacher. | Take quizzes, view progress, view profile. Access is limited to levels assigned to their class(es). |
| **IndividualStudent**   | `individual_student`   | A self-registered student not managed by a teacher. Selects a subscription package during registration. | Take quizzes, view progress, view profile. Can access classes up to the limit of their selected package. |
| **Accountant**          | `accountant`           | Financial and administrative oversight role. | View financial reports, manage subscription packages and billing, view user/class statistics. |
| **HeadOfDepartment**    | `head_of_department`   | Departmental oversight role with authority over teacher-class assignments. | Assign classes to teachers, view all classes and their teacher/student assignments, view departmental progress reports, manage teacher workload. |

**Extensibility:** Additional roles can be created at any time by an Admin via the Django admin interface. New roles are defined with a name, display name, and description. Permission checks throughout the application reference role names, so custom roles can be integrated with custom permission logic as needed.

### 3.4 Permission Resolution

- Permission checks are performed by querying the user's assigned roles (e.g., `user.roles.filter(name='teacher').exists()`).
- A user with **multiple roles** receives the **union** of all capabilities from their assigned roles.
- Role-specific views redirect users to the appropriate dashboard based on their **primary role** (highest-priority role). Priority order: Admin > HeadOfDepartment > Accountant > Teacher > IndividualStudent > Student.
- If a user has no roles assigned, they are treated as having no access and are redirected to a "contact administrator" page.

### 3.5 Authentication Flows

- **Login:** Standard Django authentication (`/accounts/login/`). After login, the user is redirected to their role-specific dashboard based on primary role priority.
- **Logout:** Standard Django logout (`/accounts/logout/`), redirects to `/`.
- **Password Reset:** Full email-based password reset flow (reset form, email sent, confirmation, completion). Reset links valid for 3600 seconds (1 hour) by default (configurable via `PASSWORD_RESET_TIMEOUT`).
- **Session Management:** Django session-based authentication; `LOGIN_REDIRECT_URL` and `LOGOUT_REDIRECT_URL` both point to `/`.

---

## 4. Functional Requirements

### 4.1 Registration and Authentication

#### FR-4.1.1 Student Self-Registration

- **URL:** `/signup/student/`
- **Fields:** Username, Email, Password, Password Confirmation.
- **Behaviour:** Creates a `CustomUser` and assigns the `student` role. Automatically logs the user in and redirects to the dashboard.

#### FR-4.1.2 Teacher Self-Registration

- **URL:** `/signup/teacher/`
- **Fields:** Username, Email, Password, Password Confirmation.
- **Behaviour:** Creates a `CustomUser` and assigns the `teacher` role. Automatically logs the user in and redirects to the dashboard.

#### FR-4.1.3 Teacher Center Registration

- **URL:** `/register/teacher-center/`
- **Fields:** Username, Email, Password, Password Confirmation, Center/School Name.
- **Behaviour:** Creates a user with the `teacher` role. Displays a success message with the center name. Redirects to dashboard.

#### FR-4.1.4 Individual Student Registration

- **URL:** `/register/individual-student/`
- **Fields:** Username, Email, Password, Password Confirmation, Package Selection.
- **Package Selection:** During registration, the individual student must choose a subscription package that determines how many classes they can access:

| Package Name    | Class Limit | Description                              |
|-----------------|-------------|------------------------------------------|
| 1 Class         | 1           | Access to a single class                 |
| 3 Classes       | 3           | Access to up to 3 classes                |
| 5 Classes       | 5           | Access to up to 5 classes                |
| Unlimited       | Unlimited   | Access to any number of classes          |

- **Package configuration:** Packages (names, class limits, and availability) are customisable by administrators via the Django admin interface. The tiers listed above are the default configuration.
- **Behaviour:** Creates a user with the `individual_student` role and the selected package. Displays a success message with the chosen package details. Redirects to a class selection page where the student can browse and select available classes (up to their package limit).
- **Class Selection (post-registration):** After registration, the individual student is presented with a list of available classes and can select which class(es) to join, up to the limit defined by their package. The student can change their class selection later from their profile, subject to the same package limit.

#### FR-4.1.5 Bulk Student Registration (Teacher Only)

- **URL:** `/bulk-student-registration/`
- **Access:** Users with `teacher` role only (`@login_required`).
- **Input:** Textarea with one student per line in the format: `username,email,password`.
- **Validation:**
  - Each line must have exactly 3 comma-separated values.
  - Username must not be empty.
  - Email must contain `@`.
  - Password must be at least 8 characters.
- **Behaviour:** Creates all student accounts (with the `student` role) atomically (within a transaction). Reports success count. Individual creation failures are reported as error messages without rolling back other creations.

#### FR-4.1.6 Role Assignment (Admin Only)

- **URL:** Via Django admin interface.
- **Access:** Users with the `admin` role only.
- **Behaviour:** Admins can assign or remove any role to/from any user. This includes assigning the `accountant`, `head_of_department`, or any custom role. A user can hold multiple roles simultaneously.

---

### 4.2 Classroom Management

A **Class** is the central organisational unit. Classes have a many-to-many relationship with both teachers and students:
- A class can have **many teachers** and **many students**.
- A teacher can belong to **multiple classes**.
- A student can belong to **multiple classes**.
- **Teachers** can assign students to classes.
- **HeadOfDepartment** can assign classes to teachers (and manage teacher-class relationships).

#### FR-4.2.1 Create Class (Teacher Only)

- **URL:** `/create-class/`
- **Access:** Users with the `teacher` role.
- **Fields:** Class Name, Levels (multi-select of available levels).
- **Behaviour:**
  - Generates a unique 8-character class code (UUID hex prefix).
  - The creating teacher is automatically added as a member of the class.
  - Assigns selected levels to the class.
  - Redirects to the teacher dashboard.

#### FR-4.2.2 Assign Students to Class (Teacher Only)

- **URL:** `/class/<class_id>/assign-students/`
- **Access:** Users with the `teacher` role who are members of the class.
- **Input:** Student username(s) or email(s), or selection from a list of registered students.
- **Behaviour:**
  - Adds the selected student(s) to the class, preventing duplicates.
  - Displays a success message with the number of students added.
  - Students **cannot** add themselves to classes -- only teachers (or HeadOfDepartment) can assign them.

#### FR-4.2.3 Assign Teachers to Class (Teacher or HeadOfDepartment)

- **URL:** `/class/<class_id>/assign-teachers/`
- **Access:** Users with the `teacher` role who are members of the class, **or** users with the `head_of_department` role (who can assign teachers to any class).
- **Input:** Teacher username(s) or email(s).
- **Behaviour:**
  - Adds the selected teacher(s) as members of the class.
  - Multiple teachers can collaborate on and manage the same class.
  - HeadOfDepartment users can assign teachers to classes even if the HeadOfDepartment is not a member of that class.

#### FR-4.2.4 HeadOfDepartment Class-Teacher Management

- **URL:** `/department/manage-classes/`
- **Access:** Users with the `head_of_department` role.
- **Behaviour:**
  - Displays an overview of **all classes** with their assigned teachers and student counts.
  - HeadOfDepartment can assign or remove teachers from any class.
  - HeadOfDepartment can view teacher workload (number of classes per teacher).
  - Provides a consolidated view for managing teacher-class assignments across the department.

#### FR-4.2.5 Individual Student Class Selection

- **URL:** `/select-classes/`
- **Access:** Users with the `individual_student` role.
- **Behaviour:**
  - Displays a list of available classes the student can browse.
  - The student can select classes up to the limit defined by their subscription package (see [FR-4.1.4](#fr-414-individual-student-registration)).
  - If the student has reached their package limit, they must remove an existing class before adding a new one, or upgrade their package.
  - Selecting a class grants the student access to the levels assigned to that class.

#### FR-4.2.6 Level Access Control

- **Students** (`student` role): Can access levels assigned to the class(es) they belong to (union of all class levels).
- **Individual students** (`individual_student` role): Can access levels assigned to the class(es) they have selected (up to their package limit).
- **Teachers** (`teacher` role): No level restrictions (can browse all topics and levels).
- **HeadOfDepartment** (`head_of_department` role): No level restrictions.
- **Accountant** (`accountant` role): No direct access to quiz content (dashboard is reporting-focused).
- **Basic Facts levels** (level_number >= 100): Always accessible to **all** users with `student` or `individual_student` roles, regardless of class membership.

---

### 4.3 Student Dashboard

#### FR-4.3.1 Home Dashboard (`/`)

- **Access:** `@login_required`. Users with `student` or `individual_student` role (other roles are redirected to their respective dashboards).
- **Content:**
  - Informational box indicating whether the student is an individual student (with package details and class count) or a class-enrolled student (with list of assigned classes).
  - **Basic Facts section:** Grid cards for Addition, Subtraction, Multiplication, Division, and Place Value Facts. Each card shows the number of available levels and links to the subtopic selection page.
  - **Year-level sections:** Accordion layout grouped by Year (1-8). Each year expands to show topic cards (e.g., Measurements, Fractions, Multiplication, Division, BODMAS/PEMDAS) plus a "Take Quiz" card for random mixed questions.
  - **No progress table** is shown on the home page (progress is on `/dashboard/`).

#### FR-4.3.2 Detailed Dashboard (`/dashboard/`)

- **Access:** `@login_required`. Users with `student` or `individual_student` role.
- **Content:** Same layout as home dashboard plus:
  - **Year-Level Progress Table:** Shows the student's best points, time, date, and number of attempts for each topic-level combination they have attempted.
  - **Basic Facts Progress Table:** Accordion per subtopic showing level-by-level progress (display level, completed time, points, date, attempts).
  - **Colour coding** based on statistical comparison (see [FR-4.12.3](#fr-4123-colour-coding)).
- **Data Sources (Priority Order):**
  1. **Primary:** `StudentFinalAnswer` table (aggregated quiz results).
  2. **Fallback:** `StudentAnswer` table (individual question-level records, for older data not yet in `StudentFinalAnswer`).

---

### 4.4 Teacher Dashboard

#### FR-4.4.1 Teacher Dashboard (`/`)

- **Access:** `@login_required`, user has `teacher` role.
- **Content:**
  - List of **all classes the teacher belongs to** with names, class codes, student count, and co-teacher count.
  - Per-class actions:
    - "Manage Students" (assign/remove students).
    - "Manage Teachers" (assign/remove co-teachers).
    - "View Class Progress" (see aggregated student progress for the class).
  - Global action buttons:
    - "Create a new class" (links to `/create-class/`).
    - "Bulk Register Students" (links to `/bulk-student-registration/`).
    - "Browse topics / assign levels" (links to `/topics/`).

---

### 4.4a HeadOfDepartment Dashboard

#### FR-4.4a.1 HeadOfDepartment Dashboard (`/department/`)

- **Access:** `@login_required`, user has `head_of_department` role.
- **Content:**
  - **All classes overview:** Table of all classes with name, code, assigned teacher(s), student count, and levels.
  - **Teacher workload view:** List of all teachers with the number of classes each is assigned to.
  - **Class-teacher management:** Ability to assign/remove teachers from any class directly from the dashboard.
  - **Departmental progress reports:** Aggregated student performance across all classes (average scores, completion rates by level/topic).
  - Action buttons:
    - "Manage Class-Teacher Assignments" (links to `/department/manage-classes/`).
    - "View All Teachers" (links to teacher list with workload details).
    - "View Departmental Reports" (links to aggregated progress reports).

---

### 4.4b Accountant Dashboard

#### FR-4.4b.1 Accountant Dashboard (`/accounting/`)

- **Access:** `@login_required`, user has `accountant` role.
- **Content:**
  - **Package subscription overview:** Summary of individual students grouped by package tier (1 Class, 3 Classes, 5 Classes, Unlimited), with counts and revenue potential.
  - **User statistics:** Total registered users broken down by role, active users (logged in within last 30 days), new registrations over time.
  - **Class statistics:** Total classes, average students per class, average teachers per class.
  - **Financial reports:** Subscription-related data for billing and financial oversight.
  - Action buttons:
    - "Manage Packages" (view/edit package tiers and pricing).
    - "Export Reports" (download CSV/PDF reports).

---

### 4.5 Year-Level Subject and Topic System

The curriculum is structured as follows:

- **Levels** represent school years (Year 1 through Year 8, stored as `level_number` 1-8).
- **Subjects** represent curriculum areas (e.g., Mathematics). The system is designed to support multiple subjects over time.
- **Topics** represent sub-areas within a subject (e.g., within Mathematics: Measurements, Fractions, BODMAS/PEMDAS).
- Each year level has a defined set of available **topics per subject**. The existing mapping described in this document is for the **Mathematics** subject (see [Appendix](#8-appendix-mathematics-year-topic-mapping)).

#### FR-4.5.1 Subject and Topic Browsing

- **URL (future):** `/subjects/` - Lists all available subjects.
- **URL (future):** `/subject/<subject_id>/topics/` - Lists topics available for a given subject.
- **URL (current / legacy):** `/topics/` - Lists all topics for the Mathematics subject.
- **URL (current / legacy):** `/topic/<topic_id>/levels/` - Lists levels available for a given topic (filtered by student's allowed levels).

#### FR-4.5.2 Level Detail

- **URL:** `/level/<level_number>/`
- **Access:** `@login_required`, subject to level access control.
- **Content:** Displays the level information and its associated subjects/topics.

---

### 4.6 Basic Facts Module

#### FR-4.6.1 Overview

Basic Facts is a **Mathematics-subject** drill-based module for fundamental arithmetic operations. Questions are **dynamically generated at runtime** (not stored in the database).

**Subtopics and Level Ranges:**

| Subtopic          | Internal Level Range | Display Levels | Questions per Quiz |
|-------------------|---------------------|----------------|-------------------|
| Addition          | 100-106             | 1-7            | 10                |
| Subtraction       | 107-113             | 1-7            | 10                |
| Multiplication    | 114-120             | 1-7            | 10                |
| Division          | 121-127             | 1-7            | 10                |
| Place Value Facts | 128-132             | 1-5            | 10                |

#### FR-4.6.2 Subtopic Selection

- **URL:** `/basic-facts/<subtopic_name>/` (e.g., `/basic-facts/Addition/`)
- **Access:** `@login_required`.
- **Behaviour:** Displays a level selection page for the chosen subtopic (Addition, Subtraction, Multiplication, Division, or Place Value Facts). Selecting a level redirects to the quiz.

#### FR-4.6.3 Dynamic Question Generation

Questions are generated per quiz attempt with the following progression:

**Addition (Levels 100-106):**
- Level 100: Single digits 1-5 (e.g., `3 + 4 = ?`)
- Level 101: Single digits 0-9 (e.g., `7 + 8 = ?`)
- Level 102: Two-digit numbers, no carry-over
- Level 103: Two-digit numbers, with carry-over (units sum >= 10)
- Level 104: Three-digit + three-digit
- Level 105: Four-digit + four-digit
- Level 106: Five-digit + five-digit

**Subtraction (Levels 107-113):**
- Level 107: Single-digit subtraction (result >= 0)
- Level 108: Two-digit minus single-digit, no borrowing
- Level 109: Two-digit minus single-digit, with borrowing
- Level 110: Two-digit minus two-digit (result >= 0)
- Level 111: Two-digit minus two-digit (may be negative)
- Level 112: Three-digit subtraction
- Level 113: Four-digit subtraction

**Multiplication (Levels 114-120):**
- Level 114: Multiply by 1 or 10
- Level 115: Multiply by 1, 10, or 100
- Level 116: Multiply by 5 or 10
- Level 117: Multiply by 2, 3, 5, or 10
- Level 118: Multiply by 2, 3, 4, 5, or 10 (2-3 digit base)
- Level 119: Multiply by 2, 3, 4, 5, 6, 7, or 10 (2-3 digit base)
- Level 120: Multiply by 2-10 (3-digit base)

**Division (Levels 121-127):**
- Level 121: Divide by 1 or 10 (exact division)
- Level 122: Divide by 1, 10, or 100 (exact division)
- Level 123: Divide by 5 or 10
- Level 124: Divide by 2, 3, 5, or 10
- Level 125: Divide by 2, 3, 4, 5, or 10
- Level 126: Divide by 2, 3, 4, 5, 6, 7, or 10
- Level 127: Divide by 2-11

**Place Value Facts (Levels 128-132):**
- Level 128: Combinations that make 10 (e.g., `3 + 7 = ?`, `3 + ? = 10`, `? + 7 = 10`)
- Level 129: Combinations that make 100
- Level 130: Combinations that make 1,000
- Level 131: Combinations that make 10,000
- Level 132: Combinations that make 100,000

Each Place Value Facts question randomly chooses one of three formats:
1. `a + b = ?`
2. `a + ? = target`
3. `? + b = target`

#### FR-4.6.4 Basic Facts Quiz Flow

1. **GET request:** Generates 10 dynamic questions, stores them in the session, starts a timer.
2. **Student answers:** All 10 questions displayed at once; student fills in answers.
3. **POST submission:** Answers are graded, time is calculated, points are computed using the scoring formula (see [FR-4.11](#411-scoring-and-points-system)), and results are saved to `BasicFactsResult`.
4. **Completion screen:** Shows score, time, calculated points, whether the student beat their previous record, and a question review popup.
5. **Duplicate submission prevention:** If a result was saved within the last 5 seconds, the existing result is shown instead of saving again.
6. **Recent result display:** If a quiz was completed within the last 30 seconds and the student refreshes, the completion screen is shown again.

---

### 4.7 Topic-Based Quizzes

#### FR-4.7.1 Overview

Each **topic within a subject** at each year level has a bank of questions stored in the database. When a student starts a topic quiz, questions are selected, shuffled, and presented one at a time with AJAX-based answer submission. (Current implementation covers the Mathematics subject.)

**Supported Mathematics Topics:** Measurements, Whole Numbers, Factors, Angles, Place Values, Fractions, BODMAS/PEMDAS, Date and Time, Finance, Integers, Trigonometry (should be able to add more).

#### FR-4.7.2 Question Selection

- Questions are selected from the database for the given level and topic.
- **Question counts by year level:**

| Year | Questions per Quiz |
|------|-------------------|
| 1    | 12                |
| 2    | 10                |
| 3    | 12                |
| 4    | 15                |
| 5    | 17                |
| 6    | 20                |
| 7    | 22                |
| 8    | 25                |
| 9    | 30                |

- If more questions are available than the limit, **stratified random sampling** is used: the question pool is divided into equal-sized blocks, and one question is randomly selected from each block. This ensures coverage across the entire question set.
- Questions with no answers, no correct answer, or (for multiple choice) no wrong answers are excluded.
- Answer order is randomised for each question.

#### FR-4.7.3 Quiz Flow (Client-Side Rendering)

1. **Initial Load:** All selected questions and their shuffled answers are serialised as JSON and sent to the client. A timer starts server-side.
2. **Question Navigation:** Questions are rendered client-side one at a time (JavaScript-driven navigation).
3. **Answer Submission:** Each answer is submitted via AJAX to `/api/submit-topic-answer/` (see [FR-7.2](#72-submit-topic-answer)). The server returns correctness, the correct answer (if wrong), and an explanation.
4. **Completion:** When all questions are answered, the client redirects to `?completed=1`. The server calculates the final score, time, and points, then renders the results page.

#### FR-4.7.4 Question Types

| Type             | Input Method                         |
|------------------|--------------------------------------|
| `multiple_choice`| Radio buttons (one correct answer)   |
| `true_false`     | Radio buttons (True/False)           |
| `short_answer`   | Text input                           |
| `fill_blank`     | Text input                           |
| `calculation`    | Text input                           |

#### FR-4.7.5 Question Attributes

- **Question text** (required)
- **Question type** (default: `multiple_choice`)
- **Difficulty** (1=Easy, 2=Medium, 3=Hard)
- **Points** (default: 1)
- **Explanation** (optional; shown after answering)
- **Image** (optional; uploaded to `media/questions/`)

---

### 4.8 Mixed (Take Quiz) Quizzes

#### FR-4.8.1 Overview

- **URL:** `/level/<level_number>/quiz/`
- **Access:** `@login_required`, subject to level access control.
- **Behaviour:** Selects random questions from **all topics** for the given level. Presents all questions at once (similar to Basic Facts). On submission, grades all answers, calculates points, and saves results to both `StudentAnswer` and `StudentFinalAnswer` (with topic = "Quiz").
- Uses the same question count limits as topic-based quizzes.
- Shows a results page with question review, explanations, and record-beating status.

---

### 4.9 Times Tables (Multiplication and Division)

#### FR-4.9.1 Overview

Times Tables (Mathematics subject) provide structured multiplication and division practice. Questions (X times 1 through X times 12) are auto-generated and stored in the database on first access.

#### FR-4.9.2 Available Tables by Year

| Year | Available Tables          |
|------|--------------------------|
| 1    | 1x                       |
| 2    | 1x, 2x, 10x             |
| 3    | 1x, 2x, 3x, 4x, 5x, 10x |
| 4    | 1x through 10x           |
| 5    | 1x through 12x           |
| 6    | 1x through 12x           |
| 7    | 1x through 12x           |
| 8    | 1x through 12x           |

#### FR-4.9.3 Table Selection

- **Multiplication:** `/level/<level_number>/multiplication/` - Shows a grid of available tables.
- **Division:** `/level/<level_number>/division/` - Shows a grid of available tables.

#### FR-4.9.4 Quiz Execution

- **URL:** `/level/<level_number>/multiplication/<table_number>/` or `/level/<level_number>/division/<table_number>/`
- Each quiz contains 12 questions (X*1 through X*12 for multiplication, or the reverse for division).
- Questions are **multiple choice** with 1 correct answer and 3 plausible wrong answers (nearby numbers).
- Uses the same AJAX-based topic quiz flow as other topic quizzes.

---

### 4.10 Practice Mode

#### FR-4.10.1 Overview

- **URL:** `/level/<level_number>/practice/`
- **Access:** `@login_required`, subject to level access control.
- **Behaviour:** Selects up to 10 random questions from all topics for the given level (using stratified sampling if more than 10 are available). Shuffles and displays them. Does **not** save results or track time -- purely for practice.

---

### 4.11 Scoring and Points System

#### FR-4.11.1 Points Formula

The points system rewards both accuracy and speed:

```
Points = (Percentage_Correct * 100 * 60) / Time_Taken_Seconds
```

Where:
- `Percentage_Correct` = (Correct Answers / Total Questions), a value between 0 and 1.
- `Time_Taken_Seconds` = Elapsed time from quiz start to submission (minimum 1 second).

**Special case for Basic Facts:**
```
Basic Facts Points = ((Percentage_Correct * 100 * 60) / Time_Taken_Seconds) / 10
```
Basic Facts points are divided by 10 to account for the shorter quiz length (10 questions vs. larger sets).

#### FR-4.11.2 Record Tracking

- Each quiz attempt is tracked with a unique `session_id` (UUID).
- The system compares the current attempt's points against the student's **previous best** for the same level-topic combination.
- On the completion screen:
  - **First attempt:** Labelled as first attempt.
  - **New record:** If the current points exceed the previous best, it is highlighted as a new record.
  - **No improvement:** The previous best is displayed for comparison.

---

### 4.12 Progress Tracking and Statistics

#### FR-4.12.1 StudentFinalAnswer Table

Aggregated quiz results are stored in `StudentFinalAnswer`:
- One record per quiz attempt (identified by `session_id`).
- `attempt_number` auto-increments per student-topic-level combination.
- Helper methods: `get_best_result()`, `get_latest_attempt()`, `get_next_attempt_number()`.
- Atomic transaction with retry logic to prevent race conditions.

#### FR-4.12.2 TopicLevelStatistics

For each topic-level combination, the system calculates and stores:
- **Average points** across all students' best results.
- **Standard deviation (sigma)** of those best results.
- **Student count** (minimum 2 required for meaningful statistics).

Statistics are updated asynchronously (in a background thread) after each quiz completion.

**Basic Facts statistics** are grouped by:
- **Student's age** (calculated from `date_of_birth`).
- **Formatted topic** (e.g., `100_Addition` for Addition Level 100).
- **Age-based levels** use `level_number = 2000 + age` to avoid conflicts with regular levels.

#### FR-4.12.3 Colour Coding

Student results on the detailed dashboard are colour-coded based on their best score relative to the statistical mean and standard deviation:

| Colour      | Condition                    | Meaning                           |
|-------------|------------------------------|-----------------------------------|
| Dark Green  | Points > avg + 2 sigma              | Exceptional performance            |
| Green       | avg + sigma < Points <= avg + 2 sigma | Above average                     |
| Light Green | avg - sigma < Points <= avg + sigma  | Average (default if insufficient data) |
| Yellow      | avg - 2 sigma < Points <= avg - sigma | Below average                     |
| Orange      | avg - 3 sigma < Points <= avg - 2 sigma | Significantly below average      |
| Red         | Points <= avg - 3 sigma              | Needs significant improvement      |

If fewer than 2 students have data (`sigma = 0` or `student_count < 2`), the default colour is **Light Green**.

#### FR-4.12.4 Student Progress

- **URL:** `/level/<level_number>/student-progress/`
- **Access:** `@login_required`.
- **Behaviour:** Shows detailed progress for all topics at a specific level, including attempt history.

---

### 4.13 Time Tracking

#### FR-4.13.1 TimeLog Model

Each student has a single `TimeLog` record tracking:
- `daily_total_seconds` -- Total time spent today (resets at midnight local time).
- `weekly_total_seconds` -- Total time spent this week (resets Monday at 00:00 local time).
- `last_reset_date` and `last_reset_week` for determining when to reset.

#### FR-4.13.2 Time Calculation

Time is **not tracked via a running clock**. Instead, it is **recalculated from completed activities**:
- Sums unique session times from `StudentAnswer` records (regular quizzes).
- Sums unique session times from `BasicFactsResult` records (Basic Facts quizzes).
- Filters by local date (daily) and local week start (weekly, Monday-based).
- This ensures accurate time tracking even if the app is closed mid-activity.

#### FR-4.13.3 AJAX Time Log Endpoint

- **URL:** `/api/update-time-log/` (GET or POST)
- **Access:** Users with `student` or `individual_student` role.
- **Behaviour:** Recalculates and returns the current daily and weekly time totals as JSON.

---

### 4.14 User Profile Management

#### FR-4.14.1 Profile Page

- **URL:** `/profile/`
- **Access:** `@login_required`.
- **Features:**
  - **View/Edit profile:** Date of birth, country, region, email, first name, last name.
  - **Change password:** Current password, new password, confirm new password (minimum 8 characters).
- **Behaviour:** Separate form submission actions (`update_profile` and `change_password`). Password change keeps the session authenticated (`update_session_auth_hash`).

---

### 4.15 Question Management (Teacher)

#### FR-4.15.1 View Level Questions

- **URL:** `/level/<level_number>/questions/`
- **Access:** `@login_required`.
- **Behaviour:** Displays all questions for the specified level.

#### FR-4.15.2 Add Question

- **URL:** `/level/<level_number>/add-question/`
- **Access:** Users with `teacher` role.
- **Fields:**
  - Question text, question type, difficulty (1-3), points, explanation.
  - Up to 4 answers (answer text, is_correct flag, display order).
- **Behaviour:** Creates the question and its answers atomically. Redirects to the level questions page.

---

### 4.16 Payments and Subscriptions (Stripe)

The platform uses **Stripe** for processing payments related to individual student subscription packages. Stripe integration follows the **Stripe Checkout** (hosted payment page) pattern for secure, PCI-compliant payment collection.

#### FR-4.16.1 Stripe Configuration

- **Library:** `stripe` Python SDK (server-side) with Stripe.js on the client where needed.
- **Keys:** Stripe API keys (`STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY`) and webhook signing secret (`STRIPE_WEBHOOK_SECRET`) are stored as environment variables -- never committed to source control.
- **Mode:** Supports both **test mode** (for development/staging) and **live mode** (for production) via separate key sets.
- **Currency:** Configurable; default is NZD (New Zealand Dollar).

#### FR-4.16.2 Package Pricing

- Each `Package` record includes a `price` field (decimal) and a `stripe_price_id` field linking to the corresponding Stripe Price object.
- Pricing is managed via the Django admin. When an admin creates or updates a package price, the corresponding Stripe Price/Product is created or updated via the Stripe API.
- Packages can be configured as **one-time payments** or **recurring subscriptions** (monthly/annual), configurable per package.

#### FR-4.16.3 Checkout Flow (Individual Student Registration)

1. Student selects a package during registration ([FR-4.1.4](#fr-414-individual-student-registration)).
2. The server creates a **Stripe Checkout Session** with:
   - The selected package's Stripe Price ID.
   - A `success_url` pointing to the post-payment activation page.
   - A `cancel_url` pointing back to the registration/package selection page.
   - Metadata including the user ID and package ID for reconciliation.
3. The student is redirected to the **Stripe-hosted checkout page** to enter payment details.
4. On successful payment, Stripe redirects the student to the `success_url`.
5. The application verifies payment status (via the Checkout Session ID) and activates the user's package.

#### FR-4.16.4 Package Upgrade / Downgrade

- **URL:** `/account/change-package/`
- **Access:** Users with the `individual_student` role.
- **Behaviour:**
  - Displays available packages with pricing.
  - **Upgrade:** Student selects a higher-tier package and is redirected to Stripe Checkout for the price difference or new subscription.
  - **Downgrade:** Student selects a lower-tier package. If the student currently exceeds the new package's class limit, they must remove classes before the downgrade is applied. Refund/proration policy is configurable.
  - Changes take effect immediately upon successful payment (upgrades) or at the end of the current billing period (downgrades, if subscription-based).

#### FR-4.16.5 Stripe Webhooks

- **URL:** `/stripe/webhook/`
- **Access:** Public endpoint (authenticated via Stripe webhook signature verification).
- **Handled Events:**

| Stripe Event                         | Application Action                                                    |
|--------------------------------------|-----------------------------------------------------------------------|
| `checkout.session.completed`         | Activate user's package, record payment in `Payment` model.          |
| `invoice.payment_succeeded`          | Renew subscription, update payment record.                           |
| `invoice.payment_failed`             | Mark subscription as past-due, notify user via email.                |
| `customer.subscription.updated`      | Sync subscription status (e.g., upgrade/downgrade applied).          |
| `customer.subscription.deleted`      | Deactivate package, restrict class access.                           |
| `charge.refunded`                    | Update payment record, optionally downgrade/deactivate package.      |

- **Idempotency:** Webhook handlers are idempotent -- processing the same event multiple times produces the same result.
- **Signature Verification:** All incoming webhooks are verified using the `STRIPE_WEBHOOK_SECRET` before processing.

#### FR-4.16.6 Payment Records

All payment activity is recorded locally for auditing and reporting:

- **`Payment` model** stores: user (FK), package (FK), Stripe Payment Intent ID, Stripe Checkout Session ID, amount, currency, status (`pending`, `succeeded`, `failed`, `refunded`), and timestamps.
- **`Subscription` model** (for recurring packages) stores: user (FK), package (FK), Stripe Subscription ID, Stripe Customer ID, status (`active`, `past_due`, `cancelled`, `expired`), current period start/end, and timestamps.

#### FR-4.16.7 Refunds

- **Access:** Users with the `accountant` or `admin` role.
- **URL:** `/accounting/refund/<payment_id>/`
- **Behaviour:** Initiates a full or partial refund via the Stripe Refunds API. Updates the local `Payment` record status to `refunded`. Optionally deactivates or downgrades the student's package depending on refund policy.

#### FR-4.16.8 Free Packages

- If a package has a price of $0.00 (or is marked as free), the Stripe Checkout step is skipped entirely. The package is activated immediately upon selection.

---

## 5. Non-Functional Requirements

### NFR-5.1 Performance

- Database queries use `select_related` and `prefetch_related` to minimise N+1 query issues.
- Topic statistics are updated **asynchronously** in background threads to avoid blocking quiz responses.
- Database operations include retry logic for transient errors.

### NFR-5.2 Security

- CSRF protection is enabled via Django middleware.
- `@login_required` decorator protects all sensitive views.
- **Role-based permission checks** query the user's assigned roles (via the `UserRole` M2M relationship) rather than boolean flags. Example: `user.roles.filter(name='teacher').exists()`.
- Level access control prevents unauthorised access to restricted content based on class membership and role.
- Password reset tokens expire after a configurable timeout (default: 1 hour).
- Role assignment is restricted to Admin users only.
- **Stripe security:** All payment processing is handled via Stripe Checkout (hosted by Stripe), so no raw credit card data ever touches the application server (PCI DSS compliance). Stripe API keys are stored as environment variables. Webhook endpoints verify Stripe signatures before processing.


### NFR-5.3 Reliability

- Database operations use atomic transactions where needed (bulk registration, question creation, final answer saving).
- Retry logic with exponential backoff for transient database errors.
- Duplicate quiz submission prevention (5-second window).
- Graceful fallback: if `StudentFinalAnswer` records don't exist, the system falls back to `StudentAnswer` records.

### NFR-5.4 Scalability

- MySQL 8.0 used across all environments for consistent behaviour and strong concurrency support.
- Persistent storage for database, static files, and media.

### NFR-5.5 Usability

- Responsive design (mobile-friendly CSS with media queries).
- Accordion-based navigation for year levels.
- Colour-coded progress indicators for quick visual feedback.
- Immediate feedback on answers (AJAX-based for topic quizzes).

### NFR-5.6 Timezone Handling

- All time-based calculations (daily/weekly resets, date comparisons) use **New Zealand local time** (`Pacific/Auckland`).
- Database timestamps are stored in UTC; local time conversion is performed in application logic.

---

## 6. Data Model

### 6.1 Entity Relationship Summary

```
Role
  |-- name (unique identifier, e.g., "teacher", "student", "head_of_department")
  |-- display_name, description, is_active, created_at

UserRole
  |-- user_id (FK to CustomUser)
  |-- role_id (FK to Role)
  |-- assigned_at (DateTime)
  |-- assigned_by (FK to CustomUser, optional)

CustomUser (extends AbstractUser)
  |
  |-- roles (M2M to Role via UserRole)  <-- Extensible role assignments
  |-- date_of_birth, country, region
  |-- package (FK, optional)            <-- Subscription package for IndividualStudent users
  |
  +-- ClassRoom (M2M via ClassTeacher)  <-- Teachers belong to classes
  +-- ClassRoom (M2M via ClassStudent)  <-- Students belong to classes
  |
  +-- StudentAnswer                     <-- Individual question responses
  +-- StudentFinalAnswer                <-- Aggregated quiz attempt results
  +-- BasicFactsResult                  <-- Basic Facts quiz results
  +-- TimeLog (1-to-1)                 <-- Time tracking

Package
  |-- name (e.g., "1 Class", "3 Classes", "Unlimited")
  |-- class_limit (integer, 0 = unlimited)
  |-- price (Decimal)                   <-- Package price (0.00 for free)
  |-- stripe_price_id (String, optional) <-- Linked Stripe Price object
  |-- billing_type (String)             <-- "one_time" or "recurring"
  |-- billing_interval (String, optional) <-- "month" or "year" (if recurring)
  |-- is_active (boolean)

Payment
  |-- user (FK to CustomUser)
  |-- package (FK to Package)
  |-- stripe_payment_intent_id (String)
  |-- stripe_checkout_session_id (String)
  |-- amount (Decimal)
  |-- currency (String, e.g., "nzd")
  |-- status (String: pending/succeeded/failed/refunded)
  |-- created_at, updated_at (DateTime)

Subscription
  |-- user (FK to CustomUser)
  |-- package (FK to Package)
  |-- stripe_subscription_id (String)
  |-- stripe_customer_id (String)
  |-- status (String: active/past_due/cancelled/expired)
  |-- current_period_start, current_period_end (DateTime)
  |-- created_at, updated_at (DateTime)

ClassRoom
  +-- teachers (M2M via ClassTeacher)   <-- Many teachers per class
  +-- students (M2M via ClassStudent)   <-- Many students per class
  +-- Level (M2M)                      <-- Levels assigned to classes
  +-- created_by (FK to CustomUser)    <-- Teacher who originally created the class

Subject
  +-- Topic (FK)                       <-- Topics grouped under a subject (e.g., Mathematics)

Topic (belongs to Subject)
  +-- Level (M2M)                      <-- Topics belong to levels
  +-- Question (FK)                    <-- Questions belong to topics
  +-- TopicLevelStatistics (FK)        <-- Statistics per topic-level

Level
  +-- Question (FK)                    <-- Questions belong to levels

Question
  +-- Answer (FK)                      <-- Multiple answers per question
```

### 6.2 Key Models

| Model                  | Purpose                                                    |
|------------------------|------------------------------------------------------------|
| `Role`                 | Defines a named role (e.g., teacher, student, accountant). Extensible via admin. |
| `UserRole`             | M2M through table linking users to roles (supports auditing via assigned_at / assigned_by) |
| `CustomUser`           | Extended user with M2M role assignments, personal info, and optional package |
| `Package`              | Subscription tier with pricing, class limit, and Stripe Price linkage |
| `Payment`              | Record of a one-time or initial payment via Stripe (amount, status, Stripe IDs) |
| `Subscription`         | Recurring subscription record synced with Stripe (status, billing period, Stripe IDs) |
| `Subject`              | Curriculum subject (e.g., Mathematics). Designed to support multiple subjects over time. |
| `Topic`                | Topic within a subject (e.g., within Mathematics: Measurements, Fractions) |
| `Level`                | Year level or Basic Facts level (by `level_number`)        |
| `ClassRoom`            | Class with unique code, assigned levels, and M2M relationships to teachers and students |
| `ClassTeacher`         | Teacher-to-class membership (M2M through table)            |
| `ClassStudent`         | Student-to-class membership (M2M through table)            |
| `Question`             | Quiz question with type, difficulty, points, optional image |
| `Answer`               | Answer option for a question (with correctness flag)       |
| `StudentAnswer`        | Individual student response to a specific question         |
| `BasicFactsResult`     | Complete Basic Facts quiz attempt result                   |
| `StudentFinalAnswer`   | Aggregated result per quiz attempt (session)               |
| `TimeLog`              | Daily/weekly time tracking per student                     |
| `TopicLevelStatistics` | Statistical averages and sigma per topic-level             |

---

## 7. API Endpoints

### 7.1 Update Time Log

| Property    | Value                          |
|-------------|--------------------------------|
| **URL**     | `/api/update-time-log/`        |
| **Methods** | GET, POST                      |
| **Auth**    | Login required, `student` or `individual_student` roles |
| **Response**| `{ "success": true, "daily_seconds": int, "weekly_seconds": int }` |

### 7.2 Submit Topic Answer

| Property    | Value                               |
|-------------|-------------------------------------|
| **URL**     | `/api/submit-topic-answer/`         |
| **Methods** | POST (JSON body)                    |
| **Auth**    | Login required                      |
| **Request** | `{ "question_id": int, "answer_id": int?, "text_answer": str?, "attempt_id": str }` |
| **Response**| `{ "success": true, "is_correct": bool, "correct_answer_id": int?, "correct_answer_text": str, "explanation": str }` |

---

## 8. Appendix: Mathematics Year-Topic Mapping

The following table defines which **Mathematics** topics are available at each year level:

| Year | Mathematics Topics Available |
|------|-----------------|
| 1    | Multiplication (times tables), Division (times tables) |
| 2    | Measurements, Place Values, Multiplication (times tables), Division (times tables) |
| 3    | Measurements, Fractions, Finance, Date and Time, Multiplication (times tables), Division (times tables) |
| 4    | Fractions, Integers, Place Values, Multiplication (times tables), Division (times tables) |
| 5    | Measurements, BODMAS/PEMDAS, Multiplication (times tables), Division (times tables) |
| 6    | Measurements, BODMAS/PEMDAS, Whole Numbers, Factors, Angles |
| 7    | Measurements, BODMAS/PEMDAS, Integers, Factors, Fractions |
| 8    | Trigonometry, Integers, Factors, Fractions |

**Note:** Basic Facts (Addition, Subtraction, Multiplication drill, Division drill, Place Value Facts) are accessible to **all** students at all year levels, independent of the year-topic mapping above.

---

*End of Requirements Specification*
