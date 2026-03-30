# CWA Classroom - Public Landing Page & Subject Hub
# Specification Document

**Application:** CWA Classroom (CWA_CLASS_APP)
**Repository:** https://github.com/InoshikaFernando/CWA_CLASS_APP
**Reference Site:** https://www.wizardslearninghub.co.nz/
**Reference Repo:** https://github.com/InoshikaFernando/CWA_SCHOOL
**Version:** 1.1 (QA-reviewed)
**Date:** 2026-03-06
**Revised:** 2026-03-06

---

## Table of Contents

1. [Overview](#1-overview)
2. [Goals & Constraints](#2-goals--constraints)
3. [Public Landing Page](#3-public-landing-page)
4. [Navigation Structure](#4-navigation-structure)
5. [Authentication Integration](#5-authentication-integration)
6. [Subjects Hub (Post-Login)](#6-subjects-hub-post-login)
7. [Subject Routing](#7-subject-routing)
8. [Contact Us Page](#8-contact-us-page)
9. [Join Class Page](#9-join-class-page)
10. [Design System](#10-design-system)
11. [URL Structure](#11-url-structure)
12. [Template Structure](#12-template-structure)
13. [Data Model Changes](#13-data-model-changes)
14. [Implementation Notes](#14-implementation-notes)
15. [Accessibility](#15-accessibility)
16. [Error Handling](#16-error-handling)
17. [Acceptance Criteria & Test Cases](#17-acceptance-criteria--test-cases)
18. [Future Extensibility](#18-future-extensibility)

---

## 1. Overview

### 1.1 Purpose

This specification defines the addition of a **public-facing landing page** and **subject hub** to the CWA Classroom application. Currently, CWA_CLASS_APP serves only authenticated users with a role-based dashboard. This change introduces:

- A public home page (unauthenticated visitors)
- A unified navigation with Home, Contact Us, and Join Class tabs
- A Sign In button linking to the existing CWA_CLASS_APP login
- A post-login **Subjects** tab that acts as a hub for multiple subject applications
- Maths as the first active subject, linking to the existing Maths Room at `mathsroom.wizardslearninghub.co.nz`
- Other subjects (Science, Coding, Music, etc.) shown as "Coming Soon" placeholders

### 1.2 Background

The existing ecosystem consists of:

| Project | Repository | Purpose | URL |
|---------|-----------|---------|-----|
| CWA_SCHOOL | `CWA_SCHOOL` | Original Maths Room (monolith) | wizardslearninghub.co.nz |
| CWA_CLASS_APP | `CWA_CLASS_APP` | Classroom v2 (multi-app Django) | classroom.wizardslearninghub.co.nz |

The public landing page at `wizardslearninghub.co.nz` currently shows subject-specific tabs (Maths, Coding, Music). This spec replaces that with a **generic educational platform landing page** that routes authenticated users to subject-specific applications.

### 1.3 Scope

- New public landing page (no authentication required)
- New public navigation bar (replaces the existing authenticated-only layout for public pages)
- Contact Us page
- Join Class page (merged from CWA_SCHOOL's `/join-class/` pattern)
- Post-login Subjects hub page with expandable subject cards
- Routing to external subject apps (Maths Room first)
- All existing CWA_CLASS_APP authenticated functionality remains unchanged

### 1.4 Branding

| Context | Name |
|---------|------|
| Organisation / Company | Code Wizard Aotearoa |
| Product / Application | Classroom |
| Navigation bar (logo text) | "Classroom" |
| Footer / legal / copyright | "Code Wizard Aotearoa" |
| Page `<title>` prefix | "Classroom" |

### 1.5 Out of Scope

- Changes to the Maths Room application itself
- Building Science, Coding, or Music subject applications (placeholder only)
- Changes to teacher/student/individual_student role logic
- Changes to billing, quiz engine, or progress tracking

---

## 2. Goals & Constraints

### 2.1 Goals

1. **Unified entry point** -- One landing page for the entire CWA educational platform
2. **Subject-agnostic** -- The landing page should NOT mention specific subjects (Maths, Coding, Music) in its default navigation
3. **Post-login discovery** -- Subjects are revealed after authentication via a Subjects tab
4. **Expandable** -- Adding a new subject requires only a database entry and (optionally) a new external URL
5. **Design consistency** -- Merge the visual style from `wizardslearninghub.co.nz` into CWA_CLASS_APP's Tailwind-based design system

### 2.2 Constraints

- Must work within Django 4.2+ / Python 3.10 / MySQL 8.0
- Must use Tailwind CSS (CDN or compiled) consistent with CWA_CLASS_APP
- Must not break existing authenticated routes (`/dashboard/`, `/basic-facts/`, etc.)
- The existing `base.html` (sidebar + topbar layout) remains for authenticated app pages
- Public pages use a new `base_public.html` layout

---

## 3. Public Landing Page

### 3.1 Route

| URL | View | Template | Auth |
|-----|------|----------|------|
| `/` | `PublicHomeView` | `public/home.html` | Public (unauthenticated) |

**Behaviour:** If the user is already authenticated, `/` redirects to `/hub/` (the Subjects hub). If unauthenticated, `/` renders the public landing page.

### 3.2 Page Sections

#### 3.2.1 Hero Section

```
+---------------------------------------------------------------+
|                                                                 |
|   Discover the magic of learning                               |
|   A comprehensive educational platform for students             |
|   ages 6-12. Explore subjects, practise skills, and track       |
|   your progress.                                                |
|                                                                 |
|   [ Get Started ]    [ Learn More ]                             |
|                                                                 |
|   [Hero Image / Illustration]                                   |
|                                                                 |
+---------------------------------------------------------------+
```

- **Headline:** "Discover the magic of learning" (Fredoka One, large)
- **Subtext:** Brief platform description (Nunito, body)
- **CTA buttons:**
  - "Get Started" -- links to `/join/` (Join Class page)
  - "Learn More" -- smooth scrolls to `#features` anchor (the Features section below)
- **Hero image:** Use existing imagery from wizardslearninghub.co.nz if available. Fallback: a generic SVG illustration from [undraw.co](https://undraw.co/) (education theme, green primary colour). Image stored in `static/images/hero.svg` (or `.png`).
- **Background:** Soft gradient matching CWA_CLASS_APP design (`from-green-50 to-yellow-50`)

#### 3.2.2 Features Section

**Anchor:** `id="features"` (scroll target for "Learn More" button)

Six feature cards in a responsive grid (3 columns desktop, 2 tablet, 1 mobile):

| Icon | Title | Description |
|------|-------|-------------|
| Brain icon | Problem Solving | Develop analytical thinking through interactive challenges |
| Lightbulb icon | Creativity | Explore creative approaches across multiple subjects |
| Monitor icon | Technology Skills | Early exposure to digital learning tools |
| Target icon | Critical Thinking | Build reasoning skills with curriculum-aligned content |
| Rocket icon | Career Ready | Foundation skills for future success |
| Star icon | Confidence | Build confidence through guided practice and achievement |

Cards use the CWA_CLASS_APP card token: `rounded-2xl bg-white border border-border shadow-sm hover:shadow-md transition p-6`

#### 3.2.3 How It Works Section

Three-step visual flow:

```
[ 1. Create Account ]  -->  [ 2. Choose Subjects ]  -->  [ 3. Start Learning ]
```

- Step 1: Register as a teacher or individual student
- Step 2: Browse available subjects and select your classes
- Step 3: Take quizzes, practise skills, and track progress

#### 3.2.4 Testimonials Section (Optional)

Pulled from the existing wizardslearninghub.co.nz testimonials data. 3 cards with parent/teacher quotes.

#### 3.2.5 Footer

```
+---------------------------------------------------------------+
| [Logo] Code Wizard Aotearoa                                    |
|                                                                 |
| Quick Links        Contact                 Follow Us            |
| - Home             - 123 Example Street,   - Facebook (fb.com/  |
| - Contact Us         Auckland, NZ            codewizardaotearoa) |
| - Join Class       - contact@wizards       - LinkedIn (linkedin |
| - Sign In            learninghub.co.nz       .com/company/cwa)  |
|                    - +64 XX XXX XXXX                            |
|                                                                 |
| (c) 2026 Code Wizard Aotearoa. All rights reserved.            |
+---------------------------------------------------------------+
```

**Note:** Actual contact details (address, phone, social URLs) must be supplied by the client before deployment. Use placeholder values during development.

---

## 4. Navigation Structure

### 4.1 Public Navigation Bar (Unauthenticated)

A horizontal top navigation bar. Replaces the CWA_CLASS_APP sidebar/topbar for public pages.

**Style:** White background, sticky top, `border-b border-gray-200`, `h-16`

```
+---------------------------------------------------------------+
| [Logo] Classroom       Home | Contact Us | Join Class | Sign In|
+---------------------------------------------------------------+
```

| Position | Element | Link | Notes |
|----------|---------|------|-------|
| Left | Logo + "Classroom" | `/` | Fredoka One, `text-primary` |
| Right | Home | `/` | Active highlight: `text-primary font-semibold border-b-2 border-primary` |
| Right | Contact Us | `/contact/` | |
| Right | Join Class | `/join/` | |
| Right | Sign In | `/accounts/login/` | Button style: `bg-primary text-white rounded-xl px-5 py-2.5` |

**Mobile (< 768px):** Hamburger menu with slide-out drawer:
- Drawer slides in from the **left** (`transform translateX`, 300ms ease transition)
- Semi-transparent dark overlay behind the drawer (`bg-black/50`); clicking overlay closes drawer
- Drawer width: `w-72` (288px), full height, `bg-white`
- Close button (`XMarkIcon`) in top-right corner of the drawer
- Contains: Home, Contact Us, Join Class links (vertical stack), and "Sign In" primary button at bottom
- Sign In button is **also always visible** in the topbar (right side) independent of the drawer
- Focus trap: keyboard focus stays within drawer while open; `Escape` key closes it

### 4.2 Authenticated Navigation Bar (Post-Login)

After login, the navigation bar gains one additional tab: **Subjects**. The existing sidebar + topbar layout from `base.html` is used for subject-specific app pages (e.g., Maths dashboard). The public nav transforms into:

```
+---------------------------------------------------------------+
| [Logo] Classroom    Home | Subjects | Contact Us | [User Menu] |
+---------------------------------------------------------------+
```

| Position | Element | Link | Notes |
|----------|---------|------|-------|
| Left | Logo + "Classroom" | `/hub/` | |
| Right | Home | `/hub/` | Authenticated home = Subjects hub |
| Right | Subjects | `/subjects/` | Dropdown or page with subject links |
| Right | Contact Us | `/contact/` | |
| Right | User Menu | dropdown | Profile, Change Password, Billing (IndividualStudent), Logout |

**Note:** The "Join Class" tab is removed post-login (class management is handled within subject apps). The "Sign In" button is replaced by the user menu dropdown.

### 4.3 Subjects Dropdown (Authenticated)

When the user clicks/hovers "Subjects", a dropdown appears:

```
+-----------------------+
| Subjects              |
|-----------------------|
| Maths        [Active] |
| Science   [Coming Soon]|
| Coding    [Coming Soon]|
| Music     [Coming Soon]|
+-----------------------+
```

- **Active subjects:** Clickable, links to external app URL
- **Coming Soon subjects:** Greyed out with "Coming Soon" badge, not clickable

---

## 5. Authentication Integration

### 5.1 Sign In Flow

```
Public Home (/)
    |
    v
Sign In button --> /accounts/login/ (existing CWA_CLASS_APP login page)
    |
    v
Login success --> /hub/ (Subjects Hub - new authenticated home)
    |
    v
User clicks "Maths" --> redirect to mathsroom.wizardslearninghub.co.nz
```

### 5.2 Login Page Changes

The existing `registration/login.html` template requires minimal changes:

- **Footer links remain:** "Register as Teacher" and "Register as Individual Student"
- **Add:** "Back to Home" link pointing to `/` (public landing page)
- **`LOGIN_REDIRECT_URL`** changes from `'/'` to `'/hub/'`

### 5.2.1 Registration View Redirect Audit

All registration views currently redirect to `/` after success. These must be updated to redirect to `/hub/`:

| View | Current Redirect | New Redirect |
|------|-----------------|--------------|
| `TeacherSignupView` | `/` | `/hub/` |
| `TeacherCenterRegisterView` | `/` | `/hub/` |
| `IndividualStudentRegisterView` | `/select-classes/` | `/select-classes/` (unchanged -- class selection is still needed) |

Use `reverse('subjects_hub')` instead of hardcoded `'/hub/'` in all redirect calls.

### 5.3 Account Types

All existing account types are supported. Authentication is shared across the platform.

| Account Type | Registration URL | Can Access Subjects? | Notes |
|--------------|-----------------|---------------------|-------|
| Teacher | `/accounts/signup/teacher/` | Yes (all subjects) | Manages classes within subject apps |
| Student | N/A (registered by teacher) | Yes (assigned subjects) | Access controlled by class assignment |
| Individual Student | `/accounts/register/individual-student/` | Yes (per package) | Subscription-based access |
| Accountant | Admin-assigned | No subject access | Financial dashboard only |
| Head of Department | Admin-assigned | No subject access | Departmental oversight only |

### 5.4 Session & Auth Settings

```python
LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/hub/'          # Changed from '/'
LOGOUT_REDIRECT_URL = '/'             # Stays the same (public home)
```

---

## 6. Subjects Hub (Post-Login)

### 6.1 Route

| URL | View | Template | Auth | Purpose |
|-----|------|----------|------|---------|
| `/hub/` | `SubjectsHubView` | `hub/home.html` | `@login_required` | Authenticated home -- greeting + subject cards + quick stats |
| `/subjects/` | Redirect to `/hub/` | N/A | `@login_required` | Convenience alias. The Subjects nav link and dropdown both point here; it redirects to `/hub/` to avoid duplicate pages. |

**Rationale:** In v1 there is no need for a separate subjects-only page. `/subjects/` exists as a named URL for the nav link and redirects to `/hub/`. If a dedicated subjects page is needed later (e.g., with filtering or search), it can be implemented at that URL.

### 6.2 Hub Home Page (`/hub/`)

The authenticated user's home page after login. Replaces the current role-based `/` redirect.

```
+---------------------------------------------------------------+
|  Welcome back, [Name]!                                         |
|                                                                 |
|  Your Subjects                                                  |
|                                                                 |
|  +---------------+  +---------------+  +---------------+       |
|  |   [Maths      |  |   [Science    |  |   [Coding     |       |
|  |    Icon]      |  |    Icon]      |  |    Icon]      |       |
|  |               |  |               |  |               |       |
|  |  Mathematics  |  |   Science     |  |   Coding      |       |
|  |               |  |  Coming Soon  |  |  Coming Soon  |       |
|  |  [Go to       |  |               |  |               |       |
|  |   Maths Room] |  |  [Notify Me]  |  |  [Notify Me]  |       |
|  +---------------+  +---------------+  +---------------+       |
|                                                                 |
|  +---------------+                                              |
|  |   [Music      |                                              |
|  |    Icon]      |                                              |
|  |               |                                              |
|  |   Music       |                                              |
|  |  Coming Soon  |                                              |
|  |               |                                              |
|  |  [Notify Me]  |                                              |
|  +---------------+                                              |
|                                                                 |
+---------------------------------------------------------------+
```

### 6.3 Subject Card Design

Each subject is rendered as a card:

**Active Subject Card (e.g., Maths):**
```
+---------------------------+
|  [Subject Icon]            |
|                            |
|  Mathematics               |
|  "Practise maths skills    |
|   with quizzes and         |
|   times tables"            |
|                            |
|  [Go to Maths Room -->]    |
+---------------------------+
```

- Card style: `rounded-2xl bg-white border border-border shadow-sm hover:shadow-md transition p-6`
- Icon: Large (48px), subject-specific colour
- Title: `Nunito 700`, `text-primary`
- Description: Short blurb
- CTA button: Primary button style, links to external subject URL
- Hover: Card lifts with shadow, button brightens

**Coming Soon Subject Card:**
```
+---------------------------+
|  [Subject Icon] (greyed)   |
|                            |
|  Science                   |
|  +------------------+      |
|  | Coming Soon       |      |
|  +------------------+      |
|                            |
|  "Stay tuned! Science is   |
|   on its way."             |
|                            |
+---------------------------+
```

- Card style: Same card but `opacity-75` with `bg-gray-50`
- Badge: `bg-accent-light text-accent-dark rounded-full px-3 py-1 text-xs font-semibold` "Coming Soon"
- Icon: Grey-toned
- **No CTA button** on Coming Soon cards in v1. The card is not clickable and has no action.
- **Future (v2):** Add a "Notify Me" button that stores user interest in a `SubjectInterest` model (user FK + subject FK + timestamp). This is out of scope for v1.

### 6.4 Role-Specific Behaviour

| Role | Hub Behaviour |
|------|--------------|
| Admin | Sees all subjects (active + coming soon). No redirect. Admin can also access Django admin via `/admin/`. |
| Teacher | Sees all subjects. Active subjects link to their teacher dashboard within that subject app. |
| Student | Sees all active subjects (v1 simplification -- all active subjects are visible to all students). Subject-level access control is deferred to the subject app itself. |
| Individual Student | Sees all subjects. Active subjects link to student home. Coming Soon subjects shown. |
| HoD | Redirected to `/department/` (existing HoD dashboard). |
| Accountant | Redirected to `/accounting/` (existing Accountant dashboard). |

**Note on Student subject visibility (v1):** In v1, all students see all active subjects on the hub. The subject app (e.g., Maths Room) enforces its own access control based on class membership and package. A future version may filter hub cards based on class-subject assignments.

**Redirect logic in `SubjectsHubView`:**
```python
if user has role 'admin': render hub (all subjects, no redirect)
if user has role 'head_of_department': redirect to /department/
if user has role 'accountant': redirect to /accounting/
otherwise (teacher, student, individual_student): render hub/home.html
```

---

## 7. Subject Routing

### 7.1 Subject Model

A new `Subject` entry structure (extending or using the existing `classroom.Subject` model):

| Field | Type | Description |
|-------|------|-------------|
| `name` | String | Display name (e.g., "Mathematics") |
| `slug` | String | URL-safe identifier (e.g., "maths") |
| `description` | Text | Short description for the card |
| `icon` | String | Icon identifier (Heroicons name or emoji) |
| `external_url` | URL (nullable) | Full URL to the subject's application |
| `is_active` | Boolean | Whether the subject is launchable |
| `is_coming_soon` | Boolean | Show "Coming Soon" badge |
| `order` | Integer | Display order on the hub |
| `color` | String | Accent colour for the subject card (hex) |

### 7.2 Initial Subject Data

| Subject | Slug | External URL | Active | Coming Soon |
|---------|------|-------------|--------|-------------|
| Mathematics | `maths` | `https://mathsroom.wizardslearninghub.co.nz` | Yes | No |
| Science | `science` | `null` | No | Yes |
| Coding | `coding` | `null` | No | Yes |
| Music | `music` | `null` | No | Yes |

### 7.3 Clicking an Active Subject

When a user clicks "Go to Maths Room":

1. Browser navigates to `https://mathsroom.wizardslearninghub.co.nz`
2. The Maths Room app handles its own authentication
3. The user lands on the Maths Room home page (or its login page if not authenticated there)

#### Known Limitation: Separate Authentication (v1)

**Accepted for v1:** CWA Classroom and Maths Room are separate Django applications on different domains. They do **not** share sessions. Users will need to log in separately on each subject app.

**UX mitigation (required for v1):**
- The "Go to Maths Room" button label must include a hint: **"Go to Maths Room (separate sign-in)"**
- A small info text below the button: *"You may need to sign in again on Maths Room."*
- The button opens the link in the **same tab** (not a new tab), so the user can use browser back to return to the hub.

**Future (v2):** Implement SSO via shared session cookies (same parent domain `*.wizardslearninghub.co.nz`) or OAuth2. See [Section 18.2](#182-sso--shared-authentication).

### 7.4 Adding a New Subject

To add a new subject (e.g., Science):

1. Create a `Subject` record via Django admin:
   - `name = "Science"`, `slug = "science"`, `is_active = True`, `is_coming_soon = False`
   - `external_url = "https://science.wizardslearninghub.co.nz"`
2. No code changes required -- the hub renders dynamically from the database.

---

## 8. Contact Us Page

### 8.1 Route

| URL | View | Template | Auth |
|-----|------|----------|------|
| `/contact/` | `ContactView` | `public/contact.html` | Public |

### 8.2 Layout

```
+---------------------------------------------------------------+
|  Get in Touch                                                   |
|                                                                 |
|  +---------------------------+  +---------------------------+   |
|  |  Contact Form             |  |  Contact Information      |   |
|  |                           |  |                           |   |
|  |  Name: [____________]     |  |  Address:                 |   |
|  |  Email: [____________]    |  |  [street address]         |   |
|  |  Subject: [__________]    |  |                           |   |
|  |  Message:                 |  |  Email:                   |   |
|  |  [                   ]    |  |  contact@wizards...       |   |
|  |  [                   ]    |  |                           |   |
|  |  [                   ]    |  |  Phone:                   |   |
|  |                           |  |  [phone number]           |   |
|  |  [Send Message]           |  |                           |   |
|  +---------------------------+  |  Social:                  |   |
|                                 |  [FB] [LinkedIn]          |   |
|                                 +---------------------------+   |
|                                                                 |
+---------------------------------------------------------------+
```

### 8.3 Contact Form Fields

| Field | Type | Required | Validation |
|-------|------|----------|------------|
| Name | Text | Yes | Non-empty |
| Email | Email | Yes | Valid email format |
| Subject | Dropdown | Yes | Predefined options: General Inquiry, Technical Support, Billing, Partnership, Other |
| Message | Textarea | Yes | Non-empty, max 2000 chars |

### 8.4 Form Submission

- POST to `/contact/` with CSRF token (`{% csrf_token %}` inside the `<form>` tag)
- **CSRF on public pages:** Django's `CsrfViewMiddleware` is already in the middleware stack and works for all views (authenticated and anonymous). The `{% csrf_token %}` template tag is sufficient. No special HTMX CSRF setup is needed for standard form POSTs.
- **Spam protection:** Integrate a honeypot field (hidden input `name="website"`, CSS `display:none`). If submitted with a value, silently discard the submission. For production, add Google reCAPTCHA v3 (invisible) -- site key/secret key via env vars `RECAPTCHA_SITE_KEY`, `RECAPTCHA_SECRET_KEY`.
- Server-side: Validates form, saves to `ContactMessage` model, sends email to configured admin address (console in dev, SMTP in production)
- **Rate limiting:** Max 5 contact form submissions per IP per hour. Use Django's cache framework with a simple counter keyed on `contact_ratelimit_{ip}`.
- Success: Redirect to `/contact/?sent=1` with toast notification "Message sent successfully!"
- Error: Re-render form with inline validation errors (field-level)

---

## 9. Join Class Page

### 9.1 Route

| URL | View | Template | Auth |
|-----|------|----------|------|
| `/join/` | `JoinClassView` | `public/join_class.html` | Public |

### 9.2 Layout

Merged from CWA_SCHOOL's `/join-class/` page, restyled with CWA_CLASS_APP's Tailwind design system.

```
+---------------------------------------------------------------+
|  Join Classroom                                                |
|                                                                 |
|  Choose how you'd like to get started:                         |
|                                                                 |
|  +---------------------------+  +---------------------------+   |
|  |  Register as              |  |  Register as              |   |
|  |  Center / Teacher         |  |  Individual Student       |   |
|  |                           |  |                           |   |
|  |  Create a center or       |  |  Create a personal        |   |
|  |  school account to        |  |  account to access all    |   |
|  |  manage multiple classes  |  |  available subjects.      |   |
|  |  and students.            |  |                           |   |
|  |                           |  |  - Self-paced learning    |   |
|  |  - Create & manage        |  |  - Personal progress      |   |
|  |    multiple classes       |  |    tracking               |   |
|  |  - Bulk register students |  |  - Join classes with      |   |
|  |  - Track student progress |  |    class codes            |   |
|  |  - Assign levels          |  |  - Subscription packages  |   |
|  |                           |  |                           |   |
|  |  [Register as Teacher]    |  |  [Register as Student]    |   |
|  +---------------------------+  +---------------------------+   |
|                                                                 |
|  +-------------------------------------------------------+     |
|  |  Already have an account?                               |     |
|  |                                                         |     |
|  |  Sign in to access your classes and subjects.           |     |
|  |                                                         |     |
|  |  [Sign In]                                              |     |
|  +-------------------------------------------------------+     |
|                                                                 |
+---------------------------------------------------------------+
```

### 9.3 Registration Links

| Card | CTA Button | Link |
|------|-----------|------|
| Center / Teacher | "Register as Teacher" (Primary button) | `/accounts/register/teacher-center/` |
| Individual Student | "Register as Student" (Secondary button) | `/accounts/register/individual-student/` |
| Already have an account | "Sign In" (Ghost button) | `/accounts/login/` |

### 9.4 Design Notes

- Cards use CWA_CLASS_APP card token with hover shadow
- Feature lists use checkmark icons (Heroicons `CheckIcon`)
- Two-column grid on desktop, stacked on mobile
- "Already have an account?" section: Full-width card below the grid

---

## 10. Design System

### 10.1 Colour Palette

Inherits from CWA_CLASS_APP's existing design system (Section 3.1 of the README):

| Token | Hex | Usage |
|-------|-----|-------|
| `primary` | `#16a34a` | Primary actions, active nav, buttons |
| `primary-dark` | `#15803d` | Hover on primary |
| `primary-light` | `#bbf7d0` | Backgrounds, badges, highlights |
| `accent` | `#eab308` | Stars, achievements, CTAs |
| `surface` | `#ffffff` | Cards, panels |
| `surface-alt` | `#f0fdf4` | Page backgrounds |
| `border` | `#d1fae5` | Dividers, card borders |

### 10.2 Typography

| Role | Font | Weight | Size |
|------|------|--------|------|
| Display / Logo | Fredoka One | 400 | 2xl-4xl |
| Headings | Nunito | 700 | lg-2xl |
| Body | Nunito | 400-600 | sm-base |

### 10.3 Public Page Specific Tokens

| Component | Tailwind Classes |
|-----------|-----------------|
| Public nav | `bg-white border-b border-gray-200 sticky top-0 z-50 h-16` |
| Nav link | `text-gray-600 hover:text-primary font-medium px-4 py-2 transition` |
| Nav link (active) | `text-primary font-semibold border-b-2 border-primary` |
| Sign In button | `bg-primary text-white hover:bg-primary-dark rounded-xl px-5 py-2.5 font-semibold` |
| Hero section | `bg-gradient-to-br from-green-50 to-yellow-50 py-20` |
| Feature card | `rounded-2xl bg-white border border-border shadow-sm hover:shadow-md transition p-6 text-center` |
| Subject card (active) | `rounded-2xl bg-white border border-border shadow-sm hover:shadow-lg transition p-8 cursor-pointer` |
| Subject card (coming soon) | `rounded-2xl bg-gray-50 border border-gray-200 shadow-sm p-8 opacity-75` |
| Footer | `bg-gray-800 text-gray-300 py-12` |

---

## 11. URL Structure

### 11.1 New Public URLs

| URL | View | Auth | Purpose |
|-----|------|------|---------|
| `/` | `PublicHomeView` | Public | Landing page (redirects to `/hub/` if authenticated) |
| `/contact/` | `ContactView` | Public | Contact form |
| `/join/` | `JoinClassView` | Public | Registration options |

### 11.2 New Authenticated URLs

| URL | View | Auth | Purpose |
|-----|------|------|---------|
| `/hub/` | `SubjectsHubView` | `@login_required` | Subjects hub (authenticated home) |
| `/subjects/` | Redirect to `/hub/` | `@login_required` | Convenience alias for nav links |

### 11.3 Existing URLs (Unchanged)

All existing CWA_CLASS_APP URLs remain unchanged:

- `/accounts/login/` -- Login
- `/accounts/logout/` -- Logout
- `/accounts/signup/teacher/` -- Teacher registration
- `/accounts/register/individual-student/` -- Individual student registration
- `/accounts/register/teacher-center/` -- Teacher center registration
- `/dashboard/` -- Student dashboard
- `/basic-facts/` -- Basic facts
- `/times-tables/` -- Times tables
- `/department/` -- HoD dashboard
- `/accounting/` -- Accountant dashboard
- All quiz, progress, billing URLs

### 11.4 Changed URLs

| URL | Current Behaviour | New Behaviour |
|-----|------------------|---------------|
| `/` | `HomeView` (role-based redirect) | `PublicHomeView` (public) or redirect to `/hub/` (authenticated) |

The existing `HomeView` role-based redirect logic moves to `/hub/` via `SubjectsHubView`.

---

## 12. Template Structure

### 12.1 New Templates

```
templates/
|
+-- base_public.html              # NEW: Public page layout (nav + footer, no sidebar)
|
+-- public/
|   +-- home.html                 # NEW: Public landing page
|   +-- contact.html              # NEW: Contact us page
|   +-- join_class.html           # NEW: Join class / registration options
|
+-- hub/
|   +-- home.html                 # NEW: Subjects hub (post-login home)
|
+-- partials/
|   +-- public_nav.html           # NEW: Public navigation bar
|   +-- public_footer.html        # NEW: Public footer
|   +-- auth_nav.html             # NEW: Authenticated navigation bar (with Subjects dropdown)
|   +-- subject_card.html         # NEW: Reusable subject card partial (active vs coming soon)
|
+-- 404.html                      # NEW: Custom 404 page (extends base_public.html)
+-- 500.html                      # NEW: Custom 500 page (extends base_public.html)
```

### 12.2 base_public.html Structure

```html
{% load static %}
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{% block title %}Classroom{% endblock %} — Code Wizard Aotearoa</title>
  <meta name="description" content="{% block meta_description %}A comprehensive educational platform for students ages 6-12.{% endblock %}" />

  <!-- Open Graph -->
  <meta property="og:title" content="{% block og_title %}Classroom{% endblock %}" />
  <meta property="og:description" content="{% block og_description %}Explore subjects, practise skills, and track your progress.{% endblock %}" />
  <meta property="og:type" content="website" />
  <meta property="og:image" content="{% static 'images/og-image.png' %}" />

  <!-- Google Fonts (Fredoka One, Nunito) -->
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=Fredoka+One&family=Nunito:wght@400;600;700&display=swap" rel="stylesheet" />

  <!-- Tailwind CSS -->
  <script src="https://cdn.tailwindcss.com"></script>
  <script>
    tailwind.config = {
      theme: {
        extend: {
          fontFamily: {
            display: ['Fredoka One', 'cursive'],
            body: ['Nunito', 'sans-serif'],
          },
          colors: {
            primary: { DEFAULT: '#16a34a', dark: '#15803d', light: '#bbf7d0' },
            accent:  { DEFAULT: '#eab308', dark: '#ca8a04', light: '#fef9c3' },
            border:  '#d1fae5',
          },
        },
      },
    }
  </script>

  {% block extra_head %}{% endblock %}
</head>
<body class="bg-white font-body text-gray-700 antialiased">

  <!-- Skip to content (accessibility) -->
  <a href="#main-content" class="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-[100] focus:bg-primary focus:text-white focus:px-4 focus:py-2 focus:rounded-lg">
    Skip to main content
  </a>

  {% include "partials/public_nav.html" %}

  <main id="main-content">
    {% block content %}{% endblock %}
  </main>

  {% include "partials/public_footer.html" %}

</body>
</html>
```

### 12.3 Existing Templates (Unchanged)

- `base.html` -- Authenticated app layout (sidebar + topbar) -- unchanged
- `base_auth.html` -- Auth pages (login, register) -- unchanged
- `base_quiz.html` -- Quiz layout -- unchanged
- All existing student, teacher, quiz, billing templates -- unchanged

---

## 13. Data Model Changes

### 13.1 SubjectApp Model (New)

A new `SubjectApp` model in the **`classroom`** app (no new Django app needed for v1). This is separate from the existing `classroom.Subject` model, which represents internal curriculum subjects. `SubjectApp` represents top-level subject applications (external or internal) shown on the hub.

**Model: `classroom.SubjectApp`**

| Field | Type | Constraints | Description |
|-------|------|------------|-------------|
| `name` | CharField(max_length=100) | `unique=True` | Display name, e.g. "Mathematics" |
| `slug` | SlugField(max_length=50) | `unique=True` | URL-safe identifier, e.g. "maths" |
| `description` | TextField | `blank=True` | Card description text |
| `icon_name` | CharField(max_length=50) | `blank=True` | Heroicon name (e.g. "calculator") or emoji |
| `external_url` | URLField | `blank=True, null=True` | Full URL to external subject app. `null` = internal or not yet available. |
| `is_active` | BooleanField | `default=False` | Whether the subject is launchable (card is clickable) |
| `is_coming_soon` | BooleanField | `default=True` | Show "Coming Soon" badge on card |
| `order` | PositiveIntegerField | `default=0` | Display order on the hub (ascending) |
| `color` | CharField(max_length=7) | `default='#16a34a'` | Accent colour hex for the subject card |
| `subject` | ForeignKey(`Subject`) | `null=True, blank=True, on_delete=SET_NULL` | Optional link to internal `classroom.Subject` for future use |
| `created_at` | DateTimeField | `auto_now_add=True` | Creation timestamp |
| `updated_at` | DateTimeField | `auto_now=True` | Last update timestamp |

**State validation (enforced in `clean()`):**

| `is_active` | `is_coming_soon` | Result |
|-------------|-----------------|--------|
| `True` | `False` | Active subject -- card is clickable, CTA links to `external_url` |
| `False` | `True` | Coming soon -- card is greyed, no link |
| `False` | `False` | Hidden -- not displayed on the hub |
| `True` | `True` | **Invalid** -- `clean()` raises `ValidationError` |

```python
def clean(self):
    if self.is_active and self.is_coming_soon:
        raise ValidationError("A subject cannot be both active and coming soon.")
    if self.is_active and not self.external_url:
        raise ValidationError("Active subjects must have an external_url.")
```

**Registered in Django Admin** with list display: name, is_active, is_coming_soon, order.

### 13.2 ContactMessage Model

Stores contact form submissions in the database (in the `classroom` app).

**Model: `classroom.ContactMessage`**

| Field | Type | Constraints | Description |
|-------|------|------------|-------------|
| `name` | CharField(max_length=100) | | Sender's name |
| `email` | EmailField | | Sender's email address |
| `subject` | CharField(max_length=50) | `choices=SUBJECT_CHOICES` | Message category |
| `message` | TextField | `max_length=2000` | Message body |
| `created_at` | DateTimeField | `auto_now_add=True` | Submission timestamp |
| `is_read` | BooleanField | `default=False` | Admin has read this message |
| `ip_address` | GenericIPAddressField | `null=True` | For rate limiting |

**SUBJECT_CHOICES:**
```python
SUBJECT_CHOICES = [
    ('general', 'General Inquiry'),
    ('support', 'Technical Support'),
    ('billing', 'Billing'),
    ('partnership', 'Partnership'),
    ('other', 'Other'),
]
```

**Registered in Django Admin** with list display: name, email, subject, is_read, created_at. Filterable by is_read and subject.

### 13.3 Migration Plan

1. Add `SubjectApp` and `ContactMessage` models to `classroom/models.py`
2. Run `python manage.py makemigrations classroom`
3. Run `python manage.py migrate`
4. Create data fixture `classroom/fixtures/initial_subjects.json` with 4 subjects:
   - Mathematics (`is_active=True`, `is_coming_soon=False`, `external_url=https://mathsroom.wizardslearninghub.co.nz`, `order=1`)
   - Science (`is_active=False`, `is_coming_soon=True`, `order=2`)
   - Coding (`is_active=False`, `is_coming_soon=True`, `order=3`)
   - Music (`is_active=False`, `is_coming_soon=True`, `order=4`)
5. Load fixture: `python manage.py loaddata initial_subjects`
6. Register both models in `classroom/admin.py`
7. No changes to existing models (Subject, Level, ClassRoom, etc.)

---

## 14. Implementation Notes

### 14.1 App Ownership

All new views and models live in the **existing `classroom` app**. No new Django app is created for v1.

| View | App | File |
|------|-----|------|
| `PublicHomeView` | `classroom` | `classroom/views.py` |
| `SubjectsHubView` | `classroom` | `classroom/views.py` |
| `SubjectsListView` | `classroom` | `classroom/views.py` |
| `ContactView` | `classroom` | `classroom/views.py` |
| `JoinClassView` | `classroom` | `classroom/views.py` |
| `SubjectApp` (model) | `classroom` | `classroom/models.py` |
| `ContactMessage` (model) | `classroom` | `classroom/models.py` |

### 14.2 View Logic

**`PublicHomeView`:**
```python
class PublicHomeView(View):
    def get(self, request):
        if request.user.is_authenticated:
            return redirect(reverse('subjects_hub'))
        return render(request, 'public/home.html')
```

**`SubjectsHubView`:**
```python
class SubjectsHubView(LoginRequiredMixin, View):
    def get(self, request):
        user = request.user

        # Redirect HoD and Accountant to their existing dashboards
        if user.roles.filter(name='head_of_department').exists():
            return redirect(reverse('hod_overview'))
        if user.roles.filter(name='accountant').exists():
            return redirect(reverse('accounting_dashboard'))

        # Show all visible subjects (active or coming soon)
        subjects = SubjectApp.objects.exclude(
            is_active=False, is_coming_soon=False
        ).order_by('order')

        return render(request, 'hub/home.html', {
            'subjects': subjects,
        })
```

**`ContactView`:**
```python
class ContactView(View):
    def get(self, request):
        sent = request.GET.get('sent') == '1'
        return render(request, 'public/contact.html', {'sent': sent})

    def post(self, request):
        # Rate limiting check (5 per IP per hour)
        # Honeypot check (if 'website' field has value, discard)
        # Validate form
        # Save ContactMessage
        # Send email
        return redirect('/contact/?sent=1')
```

### 14.3 URL Configuration

**Critical migration step:** The existing `classroom/urls.py` registers a `HomeView` at `path('', HomeView.as_view(), name='home')`. This must be changed:

1. **Remove** the existing `path('', ...)` from `classroom/urls.py`
2. **Rename** the existing `HomeView` to `AppHomeView` and move it to `path('app-home/', ...)` (this is a fallback; the hub replaces it)
3. **Update all template references** to `{% url 'home' %}` -- replace with `{% url 'subjects_hub' %}` for authenticated contexts or `{% url 'public_home' %}` for public contexts
4. **Add new URLs** in the project-level `cwa_classroom/urls.py` BEFORE the classroom app include

```python
# cwa_classroom/urls.py (updated)
from classroom.views import PublicHomeView, SubjectsHubView, SubjectsListView, ContactView, JoinClassView

urlpatterns = [
    # New public/hub routes (MUST be before classroom app include)
    path('', PublicHomeView.as_view(), name='public_home'),
    path('hub/', SubjectsHubView.as_view(), name='subjects_hub'),
    path('subjects/', SubjectsListView.as_view(), name='subjects_list'),
    path('contact/', ContactView.as_view(), name='contact'),
    path('join/', JoinClassView.as_view(), name='join_class'),

    # Existing routes
    path('admin/', admin.site.urls),
    path('accounts/', include('django.contrib.auth.urls')),
    path('accounts/', include('accounts.urls')),
    path('', include('classroom.urls')),       # Existing (but with '/' removed from classroom/urls.py)
    path('', include('quiz.urls')),
    path('', include('progress.urls')),
    path('api/', include('quiz.api_urls')),
    path('api/', include('progress.api_urls')),
    path('', include('billing.urls')),
]
```

**Template reference migration checklist:**

| Old Reference | New Reference | Files Affected |
|--------------|--------------|----------------|
| `{% url 'home' %}` | `{% url 'subjects_hub' %}` | `base.html`, `partials/sidebar_*.html`, `partials/topbar.html`, `partials/bottom_nav.html` |
| Hardcoded `/` in links | `{% url 'public_home' %}` | `registration/login.html` (new "Back to Home" link) |
| `LOGIN_REDIRECT_URL = '/'` | `LOGIN_REDIRECT_URL = '/hub/'` | `settings.py` |

### 14.4 Settings Changes

```python
LOGIN_REDIRECT_URL = '/hub/'    # Changed from '/'
LOGOUT_REDIRECT_URL = '/'       # Unchanged (public landing page)

# SEO Meta (new settings for public pages)
SITE_NAME = 'Classroom'
SITE_DESCRIPTION = 'A comprehensive educational platform for students ages 6-12.'
SITE_URL = 'https://classroom.wizardslearninghub.co.nz'

# Contact form rate limiting (optional, can use django cache)
CONTACT_RATE_LIMIT_PER_HOUR = 5

# reCAPTCHA (production only)
RECAPTCHA_SITE_KEY = os.environ.get('RECAPTCHA_SITE_KEY', '')
RECAPTCHA_SECRET_KEY = os.environ.get('RECAPTCHA_SECRET_KEY', '')
```

### 14.5 SEO & Meta Tags

Each public page must include the following in `<head>`:

```html
<title>{% block title %}Classroom{% endblock %} — Code Wizard Aotearoa</title>
<meta name="description" content="{% block meta_description %}A comprehensive educational platform for students ages 6-12.{% endblock %}" />
<meta property="og:title" content="{% block og_title %}Classroom{% endblock %}" />
<meta property="og:description" content="{% block og_description %}Explore subjects, practise skills, and track your progress.{% endblock %}" />
<meta property="og:type" content="website" />
<meta property="og:url" content="{{ request.build_absolute_uri }}" />
<meta property="og:image" content="{% static 'images/og-image.png' %}" />
<meta name="robots" content="index, follow" />
```

**Per-page meta:**

| Page | `<title>` | `meta description` |
|------|----------|-------------------|
| `/` (Home) | "Classroom -- Code Wizard Aotearoa" | "A comprehensive educational platform for students ages 6-12." |
| `/contact/` | "Contact Us -- Classroom" | "Get in touch with the Classroom team." |
| `/join/` | "Join Classroom -- Classroom" | "Register as a teacher or student to start learning." |

### 14.6 Branch Strategy

- Create branch: `feature/public-landing-and-subject-hub`
- Base: `main` (or current default branch of CWA_CLASS_APP)
- All changes committed to this branch for review before merge

---

## 15. Accessibility

### 15.1 General Requirements

All public and hub pages must meet **WCAG 2.1 Level AA** compliance:

| Requirement | Implementation |
|------------|----------------|
| Keyboard navigation | All interactive elements reachable via Tab. Visible focus ring (`focus:ring-2 focus:ring-primary`). |
| Focus management | Mobile drawer traps focus when open. `Escape` key closes drawer. Focus returns to hamburger button on close. |
| ARIA labels | Nav: `<nav aria-label="Main navigation">`. Drawer: `aria-expanded`, `aria-controls`. Subject cards: `role="link"` for active, `aria-disabled="true"` for coming soon. |
| Alt text | All images have descriptive `alt` attributes. Decorative icons use `aria-hidden="true"`. |
| Colour contrast | All text/background combinations meet 4.5:1 ratio minimum. Verified against the design system palette. |
| Screen reader | Coming Soon badge announced as "Coming Soon" text (not just visual). Form errors announced via `aria-live="polite"`. |
| Skip link | `<a href="#main-content" class="sr-only focus:not-sr-only">Skip to main content</a>` as first element in `base_public.html`. |
| Responsive text | No text smaller than 14px. Body text uses `rem` units. |

### 15.2 Contact Form Accessibility

- All form fields have associated `<label>` elements
- Required fields marked with `aria-required="true"` and visible asterisk
- Validation errors linked to fields via `aria-describedby`
- Success message uses `role="status"` with `aria-live="polite"`

---

## 16. Error Handling

### 16.1 Custom Error Pages

| Page | Template | Layout | Content |
|------|----------|--------|---------|
| 404 Not Found | `404.html` | `base_public.html` | Friendly message: "Page not found". Link back to Home. Illustration. |
| 500 Server Error | `500.html` | `base_public.html` (static -- no template context) | "Something went wrong". Contact support link. |

**Django config:**
```python
# settings.py (production)
DEBUG = False
# Django auto-serves 404.html and 500.html from the templates root
```

**Note:** `500.html` must be fully static (no `{% url %}` tags, no context variables) since it renders when Django itself has errored. Use hardcoded URLs.

### 16.2 Contact Form Errors

| Error | Handling |
|-------|----------|
| Validation failure | Re-render form with field-level error messages (red text below field) |
| Rate limit exceeded | Flash message: "Too many submissions. Please try again later." HTTP 429. |
| Email send failure | Save `ContactMessage` to DB anyway. Log error. Show success to user (message is saved). |
| Honeypot triggered | Return HTTP 200 with success message (do not reveal detection). Do not save to DB. |

---

## 17. Acceptance Criteria & Test Cases

### 17.1 Public Landing Page (`/`)

| # | Criteria | Expected Result |
|---|---------|----------------|
| AC-1 | Unauthenticated user visits `/` | Public landing page renders with hero, features, how-it-works, footer |
| AC-2 | Authenticated user visits `/` | Redirected to `/hub/` |
| AC-3 | "Get Started" button clicked | Navigates to `/join/` |
| AC-4 | "Learn More" button clicked | Smooth scrolls to `#features` section |
| AC-5 | Page renders on mobile (375px) | Hamburger menu visible, nav links hidden, content stacks vertically |
| AC-6 | Hamburger menu opened on mobile | Slide-out drawer with Home, Contact Us, Join Class, Sign In links |
| AC-7 | Sign In button clicked | Navigates to `/accounts/login/` |
| AC-8 | Page has correct `<title>` and meta tags | "Classroom -- Code Wizard Aotearoa" title, OG tags present |

### 17.2 Navigation

| # | Criteria | Expected Result |
|---|---------|----------------|
| AC-9 | Public nav shows correct tabs (unauthenticated) | Home, Contact Us, Join Class, Sign In button |
| AC-10 | Authenticated nav shows correct tabs | Home, Subjects (dropdown), Contact Us, User Menu |
| AC-11 | "Join Class" tab not visible when authenticated | Tab is removed from nav |
| AC-12 | Subjects dropdown lists all visible subjects | Maths (active), Science/Coding/Music (coming soon, greyed) |
| AC-13 | Active subject in dropdown is clickable | Links to external URL |
| AC-14 | Coming Soon subject in dropdown is not clickable | Greyed out, shows "Coming Soon" badge, no link |
| AC-15 | Active nav tab is highlighted | Current page tab has `border-b-2 border-primary text-primary` |

### 17.3 Authentication & Redirects

| # | Criteria | Expected Result |
|---|---------|----------------|
| AC-16 | User logs in with valid credentials | Redirected to `/hub/` |
| AC-17 | User logs out | Redirected to `/` (public landing page) |
| AC-18 | Teacher registers via `/accounts/signup/teacher/` | Redirected to `/hub/` after registration |
| AC-19 | Individual student registers | Redirected to `/select-classes/` (then `/hub/` after class selection) |
| AC-20 | HoD user logs in | Redirected from `/hub/` to `/department/` |
| AC-21 | Accountant user logs in | Redirected from `/hub/` to `/accounting/` |
| AC-22 | Admin user logs in | Sees `/hub/` with all subjects (no redirect) |
| AC-23 | User with no roles logs in | Sees "contact administrator" page (existing behaviour) |
| AC-24 | Login page has "Back to Home" link | Link to `/` visible and functional |

### 17.4 Subjects Hub (`/hub/`)

| # | Criteria | Expected Result |
|---|---------|----------------|
| AC-25 | Hub shows greeting with user's name | "Welcome back, [first_name or username]!" |
| AC-26 | Active subject card (Maths) shows CTA button | "Go to Maths Room (separate sign-in)" button, links to external URL |
| AC-27 | Active subject card shows info about separate login | Small text: "You may need to sign in again on Maths Room." |
| AC-28 | Coming Soon subject cards show badge | "Coming Soon" badge visible, no CTA button |
| AC-29 | Subjects ordered by `order` field | Cards display in `order` ascending |
| AC-30 | Hidden subject (`is_active=False, is_coming_soon=False`) not shown | Not rendered on the page |
| AC-31 | Hub page is responsive (mobile) | Cards stack vertically in a single column |

### 17.5 Contact Us Page (`/contact/`)

| # | Criteria | Expected Result |
|---|---------|----------------|
| AC-32 | Page renders with form and contact info | Name, Email, Subject, Message fields visible. Contact details on right. |
| AC-33 | Valid form submission | `ContactMessage` saved, email sent, redirect to `/contact/?sent=1` with toast |
| AC-34 | Invalid form submission (empty fields) | Form re-rendered with inline errors, no data saved |
| AC-35 | Invalid email format | Field-level error: "Enter a valid email address." |
| AC-36 | Message exceeds 2000 chars | Field-level error: "Message must be 2000 characters or fewer." |
| AC-37 | Rate limit exceeded (6th submission in 1 hour) | HTTP 429 or flash: "Too many submissions." |
| AC-38 | Honeypot field filled | HTTP 200, success message shown, no data saved |
| AC-39 | Contact form accessible via keyboard | All fields reachable via Tab, submit via Enter |

### 17.6 Join Class Page (`/join/`)

| # | Criteria | Expected Result |
|---|---------|----------------|
| AC-40 | Page renders with two registration cards | "Center / Teacher" and "Individual Student" cards visible |
| AC-41 | "Register as Teacher" button | Links to `/accounts/register/teacher-center/` |
| AC-42 | "Register as Student" button | Links to `/accounts/register/individual-student/` |
| AC-43 | "Already have an account?" section visible | "Sign In" button links to `/accounts/login/` |
| AC-44 | Cards responsive on mobile | Stacks to single column |

### 17.7 Data Model

| # | Criteria | Expected Result |
|---|---------|----------------|
| AC-45 | `SubjectApp` with `is_active=True` and `is_coming_soon=True` | `ValidationError` raised on `clean()` |
| AC-46 | `SubjectApp` with `is_active=True` and no `external_url` | `ValidationError` raised on `clean()` |
| AC-47 | `SubjectApp` visible in Django admin | List display: name, is_active, is_coming_soon, order |
| AC-48 | `ContactMessage` visible in Django admin | List display: name, email, subject, is_read, created_at |
| AC-49 | Data fixture loads 4 subjects | Maths (active), Science/Coding/Music (coming soon) |

### 17.8 Backward Compatibility

| # | Criteria | Expected Result |
|---|---------|----------------|
| AC-50 | `/dashboard/` still works for authenticated students | Existing student dashboard renders correctly |
| AC-51 | `/basic-facts/` still works | Basic facts page renders |
| AC-52 | `/department/` still works for HoD | HoD dashboard renders |
| AC-53 | `/accounting/` still works for Accountant | Accountant dashboard renders |
| AC-54 | All existing quiz URLs still work | No 404s on existing quiz routes |
| AC-55 | Existing `base.html` sidebar layout unchanged | Authenticated app pages still use sidebar + topbar |

---

## 18. Future Extensibility

### 18.1 Adding a New Subject

**Database only (no code changes):**
1. Create `SubjectApp` record in Django admin
2. Set `is_active = True`, `is_coming_soon = False`
3. Set `external_url` to the subject app's URL
4. Subject automatically appears on the hub

### 18.2 SSO / Shared Authentication

When multiple subject apps are deployed, implement shared authentication:
- **Option A:** Shared session cookies (same domain, e.g., `*.wizardslearninghub.co.nz`)
- **Option B:** OAuth2 / OpenID Connect with CWA_CLASS_APP as the identity provider
- **Option C:** JWT tokens passed as URL parameters during redirect

### 18.3 Internal Subject Apps

For subjects built within CWA_CLASS_APP (not external):
- `SubjectApp.external_url` is left null
- `SubjectApp.internal_url_name` references a Django named URL
- Hub renders internal links instead of external redirects

### 18.4 Subject-Specific Roles

Future subjects may need role variations:
- A teacher for Maths may not be a teacher for Coding
- Role assignment could be extended with a subject dimension: `UserRole` + `subject` FK

---

## Appendix A: Page Flow Diagram

```
                    +-------------------+
                    |  Public Home (/)  |
                    |  (Unauthenticated)|
                    +--------+----------+
                             |
              +--------------+--------------+
              |              |              |
              v              v              v
      +-------+----+  +-----+------+  +----+-------+
      | Contact Us |  | Join Class |  |  Sign In   |
      | /contact/  |  |  /join/    |  | /accounts/ |
      +------------+  +-----+------+  |  login/    |
                             |         +----+-------+
                  +----------+              |
                  |          |              v
                  v          v        +-----+------+
          +-------+--+  +---+------+  | Login Form |
          | Register |  | Register |  +-----+------+
          | Teacher  |  | Student  |        |
          +-------+--+  +---+------+        |
                  |          |              |
                  +----------+--------------+
                             |
                             v
                    +--------+----------+
                    |  Subjects Hub     |
                    |  /hub/            |
                    |  (Authenticated)  |
                    +--------+----------+
                             |
              +--------------+--------------+
              |              |              |
              v              v              v
      +-------+----+  +-----+------+  +----+--------+
      | Maths Room |  | Science    |  | Coding      |
      | (External) |  | (Coming    |  | (Coming     |
      | mathsroom. |  |  Soon)     |  |  Soon)      |
      | wizards..  |  +------------+  +-------------+
      +------------+
```

---

## Appendix B: Mobile Layout

### Public Pages (Mobile)

```
+-------------------------+
| [hamburger] [Logo] [Sign In] |
+-------------------------+
|                         |
|     MAIN CONTENT        |
|                         |
+-------------------------+
|     FOOTER              |
+-------------------------+
```

Hamburger opens a slide-out drawer with: Home, Contact Us, Join Class, Sign In.

### Subjects Hub (Mobile, Authenticated)

```
+-------------------------+
| [hamburger] [Logo] [Avatar] |
+-------------------------+
|                         |
|  Welcome back, [Name]!  |
|                         |
|  +-------------------+  |
|  | Maths     [Go ->] |  |
|  +-------------------+  |
|  +-------------------+  |
|  | Science [Soon]    |  |
|  +-------------------+  |
|  +-------------------+  |
|  | Coding  [Soon]    |  |
|  +-------------------+  |
|                         |
+-------------------------+
```

Subject cards stack vertically (single column) on mobile.

---

*End of Specification v1.1 (QA-reviewed)*
