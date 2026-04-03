from django.core.management.base import BaseCommand
from django.utils.text import slugify

from help.models import HelpCategory, HelpArticle, HelpArticleRole, FAQ


CATEGORIES = [
    {'name': 'Getting Started', 'description': 'First steps and orientation for new users.', 'order': 1},
    {'name': 'Classes & Enrolment', 'description': 'Managing classes, students, and enrolments.', 'order': 2},
    {'name': 'Quizzes & Questions', 'description': 'Creating, assigning, and completing quizzes.', 'order': 3},
    {'name': 'Attendance', 'description': 'Recording and reviewing attendance.', 'order': 4},
    {'name': 'Progress & Reports', 'description': 'Viewing and understanding progress data.', 'order': 5},
    {'name': 'Billing & Payments', 'description': 'Subscriptions, invoices, and payment history.', 'order': 6},
    {'name': 'Account & Profile', 'description': 'Managing your account settings and profile.', 'order': 7},
    {'name': 'Troubleshooting', 'description': 'Common issues and how to resolve them.', 'order': 8},
]

ARTICLES = [
    # ── Getting Started ──────────────────────────────────────────────────────
    {
        'title': 'Welcome to CWA Classroom — Head of Institute Guide',
        'category': 'Getting Started',
        'excerpt': 'An overview of the platform and your role as Head of Institute.',
        'module': 'classroom',
        'is_featured': True,
        'roles': ['hoi'],
        'body': """## Welcome, Head of Institute

As Head of Institute (HoI), you have full administrative control over your school on the CWA Classroom platform.

### What you can do

- **Set up your school** — configure departments, year levels, and curriculum strands
- **Manage staff** — invite and manage teachers, Heads of Department, and accountants
- **Oversee students** — view school-wide enrolments, progress, and attendance
- **Manage billing** — view your subscription, invoices, and upgrade your plan

### Getting started checklist

1. Complete your school profile (name, SMTP settings, logo)
2. Create departments and assign Heads of Department
3. Import or invite your teachers
4. Import or invite your students
5. Assign students to classes

Use the sidebar navigation to access each area of the platform.
""",
    },
    {
        'title': 'Welcome to CWA Classroom — Head of Department Guide',
        'category': 'Getting Started',
        'excerpt': 'An overview of your role as Head of Department.',
        'module': 'classroom',
        'is_featured': True,
        'roles': ['hod'],
        'body': """## Welcome, Head of Department

As Head of Department (HoD), you manage teachers, classes, and curriculum within your department.

### What you can do

- **Manage teachers** — add or remove teachers within your department
- **Assign classes** — assign classes and year levels to teachers
- **View department reports** — see performance across all classes in your department
- **Manage curriculum** — configure strands and topics within your department scope

### Getting started checklist

1. Log in and review your department dashboard
2. Check which teachers are assigned to your department
3. Review the classes associated with your department
4. Explore the progress reports for your department

Contact your Head of Institute if you need changes to your department structure.
""",
    },
    {
        'title': 'Welcome to CWA Classroom — Teacher Guide',
        'category': 'Getting Started',
        'excerpt': 'An overview of the platform and your daily workflow as a teacher.',
        'module': 'classroom',
        'is_featured': True,
        'roles': ['teacher'],
        'body': """## Welcome, Teacher

As a teacher on CWA Classroom, your day-to-day work centres around managing your classes, assigning activities, and tracking student progress.

### Your main areas

- **My Classes** — view students enrolled in each of your classes
- **Quizzes** — assign quiz work and review results
- **Progress** — view individual and class-level progress reports
- **Attendance** — record and approve attendance for your classes

### Getting started checklist

1. Log in and explore your dashboard
2. Review your class list under **My Classes**
3. Browse available quiz topics for your subject
4. Check pending enrolment requests

If you cannot see your classes, contact your Head of Institute or Head of Department.
""",
    },
    {
        'title': 'Getting Started as a Parent',
        'category': 'Getting Started',
        'excerpt': "How to log in, view your child's progress, and use the parent dashboard.",
        'module': 'classroom',
        'is_featured': True,
        'roles': ['parent'],
        'body': """## Welcome to CWA Classroom

This guide will help you get started as a parent on the CWA Classroom platform.

### Logging in

1. You should have received an email invitation from your child's school.
2. Click the link in the email to set your password.
3. Log in at the platform website with your email address and password.

### Your dashboard

Once logged in, your dashboard shows:
- A summary of your child's recent activity
- Upcoming homework or assignments
- Attendance overview

### Viewing your child's progress

Go to **My Children** in the sidebar, then select your child to see their detailed progress report.

### Need help?

Contact your child's school directly if you have questions about their account or class enrolment.
""",
    },
    {
        'title': 'Getting Started as a Student',
        'category': 'Getting Started',
        'excerpt': 'How to log in for the first time and navigate your student dashboard.',
        'module': 'classroom',
        'is_featured': True,
        'roles': ['student'],
        'body': """## Welcome to CWA Classroom!

Here's how to get started.

### First login

1. Your teacher or school will send you an email with a login link.
2. Click the link to set your password.
3. Log in with your email address and password.

### Your dashboard

Your dashboard shows:
- Your enrolled subjects and classes
- Recent quiz results
- Your progress across different topics

### Doing your work

- Go to **Subjects** to access your maths, coding, music, or science activities.
- Complete the activities your teacher has assigned.
- Check your **Progress** to see how you're going.

### Getting help

If you're stuck, ask your teacher. You can also browse this help centre anytime.
""",
    },

    # ── Classes & Enrolment ───────────────────────────────────────────────────
    {
        'title': 'How to View and Manage Your Classes',
        'category': 'Classes & Enrolment',
        'excerpt': 'Viewing enrolled students, managing class lists, and handling enrolment requests.',
        'module': 'classroom',
        'page_url_name': 'class_list',
        'roles': ['teacher', 'hoi', 'hod'],
        'body': """## Managing Your Classes

### Viewing your classes

Go to **My Classes** in the sidebar. You'll see all classes assigned to you (teachers) or all classes in your school (HoI/HoD).

### Viewing students in a class

Click on a class name to open the class detail page. You'll see:
- All enrolled students
- Their enrolment status
- Quick links to their progress reports

### Handling enrolment requests

Students can request to join a class. Pending requests appear under **Enrollments** in the sidebar.

To approve or decline:
1. Go to **Enrollments**
2. Review the student's request
3. Click **Approve** or **Decline**

### Removing a student from a class

From the class detail page, find the student and use the **Remove** action. The student's progress history is retained.
""",
    },
    {
        'title': 'Importing Students via CSV',
        'category': 'Classes & Enrolment',
        'excerpt': 'Step-by-step guide to bulk importing students using a CSV or Excel file.',
        'module': 'classroom',
        'page_url_name': 'student_csv_upload',
        'is_featured': True,
        'roles': ['hoi', 'hod'],
        'body': """## Importing Students via CSV

You can add many students at once by uploading a CSV or Excel (.xls/.xlsx) file. The importer supports files up to 10 MB.

### Step 1 — Go to Import Students

From the sidebar go to **Import Students** (under the school management section). You can also reach it from your admin dashboard.

### Step 2 — Choose a source preset (optional)

If you are migrating from another system (e.g. **Teachworks**), select the matching preset from the dropdown. This automatically maps your file's column headers to the correct fields, saving you time.

### Step 3 — Upload your file

Click **Choose File**, select your CSV or Excel file, then click **Upload**.

The first few rows of your file will appear as a preview so you can confirm the data looks correct.

### Step 4 — Map your columns

Match each column in your file to the correct field. Required fields are marked — you must map at least one of these:

| Required | Field |
|---|---|
| ✅ | Student First Name |
| ✅ | Student Last Name |
| ✅ (or Full Name or Children) | One of these three must be mapped |

**Optional fields you can also map:**

| Field | Notes |
|---|---|
| Student Email | Recommended. Auto-generated from parent email if left blank. |
| Student Full Name | Alternative to First + Last Name columns |
| Children (full names) | Comma-separated list, e.g. "Jane Smith, Tom Smith" — creates one row per child |
| Username | Leave blank to auto-generate |
| Date of Birth | Format: DD/MM/YYYY |
| Department | Must match an existing department name |
| Subject | Must match an existing subject |
| Class Name | Enrols the student in that class |
| Class Day / Start Time / End Time | Used to match the correct class session |
| Teacher | Assigns the student to a teacher's class |
| Parent 1 First Name, Last Name, Email | Creates a linked parent account |
| Parent 2 First Name, Last Name, Email | Optional second parent/guardian |

### Step 5 — Map school structure (if your school has departments)

If your school uses departments, an extra step will appear asking you to assign imported students to departments, subjects, and classes. Use the dropdowns to match your CSV values to the correct school structure.

### Step 6 — Review the preview

A summary shows:
- **New students** — will be created
- **Existing students** — already in the system, will be updated
- **New parent accounts** — will be created from parent columns
- **Warnings** — rows with minor issues (e.g. missing email, auto-generated values)
- **Errors** — rows that cannot be imported

Fix any errors in your CSV and re-upload if needed.

### Step 7 — Confirm the import

Click **Confirm Import**. Students are created immediately.

### Step 8 — Download credentials

After import you can download a credentials sheet with each student's login details. Share these securely with students or parents.

Students also receive an email invitation with a link to set their password.

### Tips

- **No email?** If a student email is blank, the system generates one from the parent email (or a placeholder). You can update it later from the student's profile.
- **Duplicate emails** are detected automatically — existing accounts are updated rather than duplicated.
- **Files supported:** `.csv`, `.xls`, `.xlsx` (max 10 MB)
- **Column headers** don't need to match exactly — use the mapping step to connect your file's headers to the right fields.
""",
    },
    {
        'title': 'Importing Teachers and Staff via CSV',
        'category': 'Classes & Enrolment',
        'excerpt': 'Step-by-step guide to bulk importing teachers and staff using a CSV or Excel file.',
        'module': 'classroom',
        'page_url_name': 'teacher_csv_upload',
        'is_featured': True,
        'roles': ['hoi'],
        'body': """## Importing Teachers and Staff via CSV

You can add multiple teachers and staff members at once by uploading a CSV or Excel file.

### Step 1 — Go to Import Teachers

From the sidebar go to **Import Teachers** (under the school management section).

### Step 2 — Choose a source preset (optional)

If you are migrating from **Teachworks**, select the Teachworks preset. This maps your file's column headers automatically.

### Step 3 — Upload your file

Click **Choose File**, select your CSV or Excel file, then click **Upload**.

### Step 4 — Map your columns

Match each column to the correct field. Required fields:

| Required | Field |
|---|---|
| ✅ | First Name |
| ✅ | Last Name |
| ✅ | Email |

**Optional fields:**

| Field | Notes |
|---|---|
| Mobile Phone | Teacher's contact number |
| Position / Role | Determines the staff role (see table below) |
| Subjects / Specialty | The subjects this teacher covers |
| Status | Active/Inactive — inactive staff are not imported |
| Type | Teacher or Staff |

### Role mapping from Position column

The **Position** column in your CSV determines what role the staff member receives:

| Position value (in CSV) | Role assigned |
|---|---|
| Principal Teacher / Principal | Head of Institute |
| Senior Teacher | Senior Teacher |
| Junior Teacher | Junior Teacher |
| Admin / Head Admin | Accountant |
| (anything else) | Teacher |

### Step 5 — Review the preview

The preview shows new and existing staff members. Existing accounts (matched by email) are updated rather than duplicated.

### Step 6 — Confirm the import

Click **Confirm Import**. Staff accounts are created immediately.

### Step 7 — Download credentials

After import you can download a credentials sheet with each staff member's login details.

Staff also receive an email invitation with a link to set their password.

### Tips

- **Email is required** for all staff — unlike students, there is no auto-generation.
- Inactive staff (Status = Inactive) are skipped.
- **Files supported:** `.csv`, `.xls`, `.xlsx` (max 10 MB)
""",
    },
    {
        'title': 'Importing Parents via CSV',
        'category': 'Classes & Enrolment',
        'excerpt': 'How to bulk import parent/guardian accounts and link them to students.',
        'module': 'classroom',
        'page_url_name': 'parent_csv_upload',
        'roles': ['hoi'],
        'body': """## Importing Parents via CSV

You can import parent/guardian accounts in bulk and link them to existing students.

### Step 1 — Go to Import Parents

From the sidebar go to **Import Parents** (under the school management section).

### Step 2 — Choose a source preset (optional)

Select **Teachworks** if you are migrating from Teachworks Families export.

### Step 3 — Upload your file

Click **Choose File**, select your CSV or Excel file, then click **Upload**.

### Step 4 — Map your columns

Required fields:

| Required | Field |
|---|---|
| ✅ | Parent First Name |
| ✅ | Parent Last Name |
| ✅ | Parent Email |
| ✅ (one of these) | Student Email **or** Children (names) |

**Optional fields:**

| Field | Notes |
|---|---|
| Phone | Parent contact number |
| Relationship | e.g. Mother, Father, Guardian |
| Student Email | Links this parent to an existing student account |
| Children (names) | Comma-separated list of child names — matches to existing student accounts by name |
| Address | Street address |
| City | City |
| Country | Country |

### Linking parents to students

The importer links parents to students using either:
- **Student Email** — exact match to an existing student's email address
- **Children (names)** — matches student names already in the system (e.g. "Jane Smith, Tom Smith")

If no match is found, the parent account is still created but not linked. You can link manually from the student's profile.

### Step 5 — Confirm the import

Review the preview and click **Confirm Import**. Parent accounts are created and linked to their children.

Parents receive an email invitation to set their password.

### Tips

- Existing parent accounts (matched by email) are updated, not duplicated.
- **Files supported:** `.csv`, `.xls`, `.xlsx` (max 10 MB)
""",
    },
    {
        'title': 'Importing Account Balances via CSV',
        'category': 'Billing & Payments',
        'excerpt': 'How to import opening account balances for parents when migrating from another system.',
        'module': 'billing',
        'page_url_name': 'balance_csv_upload',
        'roles': ['hoi', 'accountant'],
        'body': """## Importing Account Balances via CSV

When migrating from another system (e.g. Teachworks), you can import existing parent account balances so your financial records carry over.

### Step 1 — Go to Import Balances

From the sidebar go to **Import Balances** (under the billing or school management section).

### Step 2 — Choose a source preset (optional)

Select **Teachworks** to automatically map a Teachworks Customer Balances export.

### Step 3 — Upload your file

Click **Choose File**, select your CSV or Excel file, then click **Upload**.

### Step 4 — Map your columns

Required fields:

| Required | Field |
|---|---|
| ✅ | Parent First Name |
| ✅ | Parent Last Name |
| ✅ | Balance |

**Optional fields:**

| Field | Notes |
|---|---|
| Net Invoices | Total invoiced amount |
| Net Payments | Total payments received |
| Customer ID | External reference ID from your previous system |
| Customer Status | Active/Inactive |

### Step 5 — Review and confirm

The preview shows which parent accounts were matched and what their opening balance will be set to.

Click **Confirm Import** to apply the balances.

### Tips

- Balances are matched to existing parent accounts by name.
- Only active customers are imported (inactive are skipped).
- **Files supported:** `.csv`, `.xls`, `.xlsx` (max 10 MB)
- Run this import **after** importing parents, so all accounts exist before balances are applied.
""",
    },
    {
        'title': 'Approving and Managing Enrolment Requests',
        'category': 'Classes & Enrolment',
        'excerpt': 'How to approve, decline, and manage student enrolment requests.',
        'module': 'classroom',
        'page_url_name': 'enrollment_requests',
        'roles': ['teacher', 'hoi', 'hod'],
        'body': """## Enrolment Requests

Students can request to join your classes. You'll be notified and can approve or decline requests.

### Viewing pending requests

Go to **Enrollments** in the sidebar. You'll see all pending requests with the student name, requested class, and date.

### Approving a request

Click **Approve** next to the student's request. They'll be added to the class immediately and notified by email.

### Declining a request

Click **Decline**. The student will be notified. You can optionally add a reason.

### Bulk actions

Use the checkboxes to select multiple requests and approve or decline them together.
""",
    },

    # ── Attendance ────────────────────────────────────────────────────────────
    {
        'title': 'Recording Attendance',
        'category': 'Attendance',
        'excerpt': 'How to mark and submit attendance for your class sessions.',
        'module': 'attendance',
        'roles': ['teacher'],
        'body': """## Recording Attendance

### Starting an attendance session

1. Go to your class from **My Classes**.
2. Click **Attendance** for the relevant session.
3. Mark each student as **Present**, **Absent**, or **Late**.
4. Submit when done.

### Editing submitted attendance

If you made an error, you can edit attendance records within the session window. Contact your HoD or HoI if the window has closed.

### Absence tokens

Students who are absent can self-report an absence using an absence token sent to them by email. You'll see these reported absences on the attendance page for your review.

### Viewing attendance history

Go to **Attendance** in the sidebar to see a full history of recorded sessions.
""",
    },
    {
        'title': 'Viewing Your Child\'s Attendance',
        'category': 'Attendance',
        'excerpt': "How parents can view attendance records for their child.",
        'module': 'attendance',
        'roles': ['parent'],
        'body': """## Viewing Attendance

### Where to find attendance records

Go to **Attendance** in the sidebar. You'll see a summary of your child's attendance across all classes.

### Understanding the records

- **Present** — your child was marked present for that session
- **Absent** — your child was marked absent
- **Late** — your child arrived late
- **Pending** — the session hasn't been marked yet

### If something looks wrong

Contact your child's teacher or school directly to correct any attendance errors.
""",
    },

    # ── Progress & Reports ────────────────────────────────────────────────────
    {
        'title': 'Understanding the Progress Dashboard',
        'category': 'Progress & Reports',
        'excerpt': 'How to read progress reports and interpret student performance data.',
        'module': 'progress',
        'page_url_name': 'class_progress_list',
        'roles': ['teacher', 'hoi', 'hod', 'parent', 'student'],
        'body': """## Understanding Progress Reports

### What the progress dashboard shows

The progress dashboard gives a visual overview of performance across topics and difficulty levels.

- **Green** — strong performance (80%+)
- **Yellow** — developing (50–79%)
- **Red** — needs support (below 50%)

### For teachers

You can view:
- **Class-level reports** — how your whole class is performing on each topic
- **Individual student reports** — drill down into a specific student's results

### For parents

Your child's progress page shows their performance across all enrolled subjects, organised by topic.

### For students

Your progress page shows which topics you've mastered and which areas to keep practising.

### Tip

Progress data updates in real time as students complete activities.
""",
    },
    {
        'title': 'Generating Class and School Reports',
        'category': 'Progress & Reports',
        'excerpt': 'How to generate and export progress reports for your class or school.',
        'module': 'progress',
        'roles': ['teacher', 'hoi', 'hod'],
        'body': """## Generating Reports

### Class-level reports (Teachers)

1. Go to **Class Progress** in the sidebar.
2. Select a class.
3. You'll see a breakdown by topic and student.
4. Use the filters to narrow by strand, topic, or date range.

### School-wide reports (HoI / HoD)

Go to your admin dashboard and select **Reports**. You can view:
- School-wide performance by subject
- Department-level trends
- Year-level comparisons

### Exporting data

Use the **Export** button on any report page to download a CSV or PDF copy.
""",
    },

    # ── Billing & Payments ────────────────────────────────────────────────────
    {
        'title': 'Understanding Your Subscription and Billing',
        'category': 'Billing & Payments',
        'excerpt': 'How subscriptions work, how to view invoices, and how to upgrade your plan.',
        'module': 'billing',
        'roles': ['hoi', 'parent', 'student'],
        'body': """## Billing & Payments

### School subscriptions (HoI)

Your school subscription covers access for all staff and students in your school. You can:

- View your current plan under **Billing** in the sidebar
- Download past invoices
- Upgrade or change your plan
- Add optional modules (e.g. Attendance tracking)

### Individual subscriptions (Students & Parents)

If you're an individual student or parent managing your own subscription:

- Go to **Billing** to view your plan and payment history
- Update your payment method via the Billing portal
- Cancel or change your plan at any time

### Trial periods

New accounts start with a free trial. The number of days remaining is shown in your sidebar. Once the trial ends, you'll need to subscribe to continue accessing the platform.

### Need help with a payment?

Contact us via the **Contact** page if you have a billing issue.
""",
    },

    # ── Account & Profile ─────────────────────────────────────────────────────
    {
        'title': 'Managing Your Profile and Account Settings',
        'category': 'Account & Profile',
        'excerpt': 'How to update your name, email, password, and notification preferences.',
        'module': 'accounts',
        'page_url_name': 'profile',
        'roles': ['hoi', 'hod', 'teacher', 'parent', 'student', 'accountant'],
        'body': """## Your Profile

### Updating your details

Go to **Profile** in the sidebar to update:
- Your display name
- Your email address
- Your password

### Changing your password

1. Go to **Profile**.
2. Click **Change Password**.
3. Enter your current password, then your new password twice.
4. Click **Save**.

### Switching roles

If you have multiple roles (e.g. both Teacher and HoD), you can switch between them using the role switcher in the top navigation bar.

### Notification preferences

Notification settings are managed within your profile. You can control which email notifications you receive.
""",
    },

    # ── Troubleshooting ───────────────────────────────────────────────────────
    {
        'title': "I Can't See My Classes or Students",
        'category': 'Troubleshooting',
        'excerpt': 'Common reasons why classes or students may not appear, and how to fix them.',
        'module': 'classroom',
        'roles': ['teacher', 'hoi', 'hod', 'parent', 'student'],
        'body': """## I Can't See My Classes or Students

### For teachers

**Check your class assignments.** Your Head of Department or Head of Institute assigns classes to you. If a class is missing, contact them to be assigned.

**Check enrolment status.** Students must be enrolled in a class before they appear in it. Use the **Enrollments** section to approve pending requests.

### For students

**You may not be enrolled yet.** Ask your teacher to enrol you in the class, or request to join via the Join Class page.

**Try switching roles.** If you have multiple roles, make sure you're viewing the platform as a Student (check the top bar).

### For parents

**Your child's account may not be linked.** Contact your child's school to confirm your parent account is linked to your child's student account.

### Still stuck?

Contact your school's Head of Institute, or use the **Contact** form to reach the CWA support team.
""",
    },
    {
        'title': 'Resetting a Forgotten Password',
        'category': 'Troubleshooting',
        'excerpt': 'How to reset your password if you have forgotten it.',
        'module': 'accounts',
        'page_url_name': 'password_reset',
        'roles': ['hoi', 'hod', 'teacher', 'parent', 'student', 'accountant'],
        'body': """## Forgot Your Password?

### Resetting your password

1. Go to the login page.
2. Click **Forgot password?** below the login form.
3. Enter your email address.
4. Check your inbox for a password reset email.
5. Click the link in the email and set a new password.

### Didn't receive the email?

- Check your spam or junk folder.
- Make sure you're using the email address registered with your account.
- Contact your school's administrator if you're still unable to log in.

### For school-managed accounts

If your account was created by your school, your administrator can reset your password from the school management page.
""",
    },
    {
        'title': 'Configuring School Email (SMTP)',
        'category': 'Account & Profile',
        'excerpt': 'How to set up your school\'s email settings for branded communications.',
        'module': 'classroom',
        'roles': ['hoi'],
        'body': """## Setting Up School Email (SMTP)

Configuring SMTP lets the platform send emails on behalf of your school (e.g. student invitation emails).

### Steps

1. Go to your school settings from the admin dashboard.
2. Find the **Email / SMTP** section.
3. Enter your SMTP server details:
   - **SMTP Host** (e.g. smtp.gmail.com)
   - **SMTP Port** (usually 587 for TLS)
   - **Username** (your email address)
   - **Password** (your email password or app password)
4. Click **Test Connection** to verify the settings.
5. Save when confirmed.

### Gmail users

If using Gmail, you'll need to create an **App Password** in your Google account settings. This is required when 2-factor authentication is enabled.

### Tip

If emails aren't sending, check your firewall settings and confirm the SMTP port is not blocked.
""",
    },
]

FAQS = [
    # ── HoI FAQs (10) ────────────────────────────────────────────────────────
    {'role': 'hoi', 'category': 'Getting Started', 'order': 1,
     'question': 'How do I invite teachers to join my school?',
     'answer': 'Go to your school hierarchy page and use the **Invite Teacher** button. Teachers will receive an email with a link to set up their account.'},
    {'role': 'hoi', 'category': 'Getting Started', 'order': 2,
     'question': 'Can I import students in bulk?',
     'answer': 'Yes. Go to **Import Students** from the sidebar. Upload a CSV file with student details. The importer will walk you through mapping columns and confirming the import.'},
    {'role': 'hoi', 'category': 'Getting Started', 'order': 3,
     'question': 'How do I create a department?',
     'answer': 'Go to **School Hierarchy** in the sidebar. Click **Add Department**, enter the department name, and assign a Head of Department.'},
    {'role': 'hoi', 'category': 'Billing & Payments', 'order': 4,
     'question': 'How do I download an invoice?',
     'answer': 'Go to **Billing** in the sidebar. Your invoice history is listed there — click any invoice to download it as a PDF.'},
    {'role': 'hoi', 'category': 'Billing & Payments', 'order': 5,
     'question': 'How do I upgrade my school\'s subscription plan?',
     'answer': 'Go to **Billing** in the sidebar and click **Change Plan**. Choose your new plan and confirm. The change takes effect immediately.'},
    {'role': 'hoi', 'category': 'Classes & Enrolment', 'order': 6,
     'question': 'How do I assign a teacher to a class?',
     'answer': 'Go to the class detail page and click **Assign Teacher**. Select the teacher from the list. They will be notified by email.'},
    {'role': 'hoi', 'category': 'Account & Profile', 'order': 7,
     'question': 'How do I reset a student\'s password?',
     'answer': 'Go to the student\'s profile in the school management area and click **Reset Password**. A reset email will be sent to the student.'},
    {'role': 'hoi', 'category': 'Getting Started', 'order': 8,
     'question': 'Can I set up academic terms and holidays?',
     'answer': 'Yes. Go to the admin dashboard and select **Academic Year**. You can define term dates, holidays, and the school calendar.'},
    {'role': 'hoi', 'category': 'Troubleshooting', 'order': 9,
     'question': 'A teacher says they can\'t see their classes. What should I check?',
     'answer': 'Ensure the teacher is assigned to the correct classes. Go to the class detail page and confirm the teacher appears under **Assigned Teachers**.'},
    {'role': 'hoi', 'category': 'Account & Profile', 'order': 10,
     'question': 'How do I configure the school\'s SMTP email settings?',
     'answer': 'Go to **School Settings** in the admin dashboard. Find the **Email / SMTP** section and enter your server details. Use **Test Connection** to verify before saving.'},

    # ── HoD FAQs (10) ────────────────────────────────────────────────────────
    {'role': 'hod', 'category': 'Getting Started', 'order': 1,
     'question': 'How do I assign a teacher to a class?',
     'answer': 'From your department dashboard, select a class and use the **Assign Teacher** option to add a teacher from your department.'},
    {'role': 'hod', 'category': 'Progress & Reports', 'order': 2,
     'question': 'Can I view progress across all teachers in my department?',
     'answer': 'Yes. Go to **Progress** and select your department view to see an aggregate report across all classes in your department.'},
    {'role': 'hod', 'category': 'Classes & Enrolment', 'order': 3,
     'question': 'How do I add a teacher to my department?',
     'answer': 'Contact your Head of Institute to assign a teacher to your department. Only HoI can modify department membership.'},
    {'role': 'hod', 'category': 'Classes & Enrolment', 'order': 4,
     'question': 'Can I see which students are enrolled in each class?',
     'answer': 'Yes. Go to the class detail page for any class in your department. The enrolled students list is shown with their progress summary.'},
    {'role': 'hod', 'category': 'Progress & Reports', 'order': 5,
     'question': 'How do I export a department-level report?',
     'answer': 'Open the department progress view and click **Export**. You can download a CSV or PDF of the report.'},
    {'role': 'hod', 'category': 'Quizzes & Questions', 'order': 6,
     'question': 'Can I manage the question bank for my department?',
     'answer': 'Yes. Go to **Browse Topics** in the sidebar to view and manage questions within your department\'s subject area.'},
    {'role': 'hod', 'category': 'Attendance', 'order': 7,
     'question': 'Can I view attendance records for my department?',
     'answer': 'Yes. Go to **Attendance** and filter by department. You\'ll see a summary across all classes within your area.'},
    {'role': 'hod', 'category': 'Troubleshooting', 'order': 8,
     'question': 'A teacher in my department can\'t log in. What should I do?',
     'answer': 'Ask the teacher to use the **Forgot password?** link on the login page. If the issue persists, contact your Head of Institute to check their account status.'},
    {'role': 'hod', 'category': 'Account & Profile', 'order': 9,
     'question': 'How do I update my own profile details?',
     'answer': 'Go to **Profile** in the sidebar. You can update your name, email address, and password from there.'},
    {'role': 'hod', 'category': 'Getting Started', 'order': 10,
     'question': 'Can I coordinate with another Head of Department?',
     'answer': 'Cross-department coordination is managed through your Head of Institute. Raise any shared resource or curriculum queries with them directly.'},

    # ── Teacher FAQs (10) ─────────────────────────────────────────────────────
    {'role': 'teacher', 'category': 'Classes & Enrolment', 'order': 1,
     'question': 'How do I approve a student enrolment request?',
     'answer': "Go to **Enrollments** in the sidebar. You'll see a list of pending requests. Click **Approve** to add the student to your class."},
    {'role': 'teacher', 'category': 'Quizzes & Questions', 'order': 2,
     'question': 'How do I assign a quiz to my class?',
     'answer': 'Browse topics from the question bank, select the topic and level, then assign it to your class. Students will see it in their subject area.'},
    {'role': 'teacher', 'category': 'Progress & Reports', 'order': 3,
     'question': 'Where can I see individual student progress?',
     'answer': "Go to **Class Progress** in the sidebar, select a class, then click on a student's name to view their detailed progress report."},
    {'role': 'teacher', 'category': 'Attendance', 'order': 4,
     'question': 'How do I record attendance for a class session?',
     'answer': 'Go to your class and click **Attendance** for the session. Mark each student as Present, Absent, or Late, then submit.'},
    {'role': 'teacher', 'category': 'Quizzes & Questions', 'order': 5,
     'question': 'Can I create my own questions?',
     'answer': 'Yes. Go to **Create Questions** in the sidebar. You can create new questions and add them to the question bank for your subject.'},
    {'role': 'teacher', 'category': 'Classes & Enrolment', 'order': 6,
     'question': 'How do I remove a student from my class?',
     'answer': "Go to the class detail page, find the student, and use the **Remove** action. The student's progress history is retained."},
    {'role': 'teacher', 'category': 'Progress & Reports', 'order': 7,
     'question': 'Can I export a class progress report?',
     'answer': 'Yes. Open the class progress view and click **Export** to download a CSV or PDF.'},
    {'role': 'teacher', 'category': 'Quizzes & Questions', 'order': 8,
     'question': 'How do I upload questions in bulk?',
     'answer': 'Go to **Upload Questions** in the sidebar. Download the template, fill it in, and upload the file. You can also use **AI Import Questions** for AI-assisted import.'},
    {'role': 'teacher', 'category': 'Attendance', 'order': 9,
     'question': 'Can I edit attendance after submitting?',
     'answer': 'Yes, within the session window. Go to the attendance record and click **Edit**. Contact your HoD or HoI if the editing window has closed.'},
    {'role': 'teacher', 'category': 'Troubleshooting', 'order': 10,
     'question': 'A student says they can\'t see their work. What should I check?',
     'answer': "Confirm the student is enrolled in the correct class and subject. Also check that their account is active and not blocked."},

    # ── Parent FAQs (10) ─────────────────────────────────────────────────────
    {'role': 'parent', 'category': 'Getting Started', 'order': 1,
     'question': 'How do I link my account to my child?',
     'answer': "Your account should be automatically linked when the school sets it up. If you can't see your child, contact the school to confirm your account is linked correctly."},
    {'role': 'parent', 'category': 'Progress & Reports', 'order': 2,
     'question': 'What do the progress colours mean?',
     'answer': "Green means your child is performing well (80%+). Yellow means they're developing (50–79%). Red means the topic needs more practice (below 50%)."},
    {'role': 'parent', 'category': 'Account & Profile', 'order': 3,
     'question': 'How do I change my email address or password?',
     'answer': 'Go to **Profile** in the sidebar. You can update your email address and change your password from there.'},
    {'role': 'parent', 'category': 'Attendance', 'order': 4,
     'question': 'How do I view my child\'s attendance record?',
     'answer': "Go to **Attendance** in the sidebar. You'll see a summary of your child's attendance across all classes."},
    {'role': 'parent', 'category': 'Billing & Payments', 'order': 5,
     'question': 'How do I view or download an invoice?',
     'answer': "Go to **Invoices** in the sidebar. Click on any invoice to view or download it as a PDF."},
    {'role': 'parent', 'category': 'Progress & Reports', 'order': 6,
     'question': 'How often is the progress data updated?',
     'answer': "Progress updates in real time as your child completes activities. You'll see the most current data each time you visit the progress page."},
    {'role': 'parent', 'category': 'Getting Started', 'order': 7,
     'question': 'I didn\'t receive my invitation email. What should I do?',
     'answer': "Check your spam or junk folder first. If the email isn't there, contact your child's school and ask them to resend the invitation."},
    {'role': 'parent', 'category': 'Billing & Payments', 'order': 8,
     'question': 'How do I update my payment method?',
     'answer': 'Go to **Billing** in the sidebar and click **Manage Billing**. You can update your card details through the secure payment portal.'},
    {'role': 'parent', 'category': 'Troubleshooting', 'order': 9,
     'question': "Why can't I see my child's class?",
     'answer': "Your child may not be enrolled in a class yet, or your parent account may not be linked. Contact the school to confirm."},
    {'role': 'parent', 'category': 'Getting Started', 'order': 10,
     'question': 'Can I have more than one child linked to my account?',
     'answer': 'Yes. Contact the school to link additional children. All linked children will appear under **My Children** in the sidebar.'},

    # ── Student FAQs (10) ────────────────────────────────────────────────────
    {'role': 'student', 'category': 'Getting Started', 'order': 1,
     'question': 'How do I join a class?',
     'answer': 'Go to **Join Class** in the sidebar and enter the class code your teacher gave you. Your teacher will approve your request.'},
    {'role': 'student', 'category': 'Quizzes & Questions', 'order': 2,
     'question': 'How do I see my quiz results?',
     'answer': 'Go to your subject (e.g. Maths) and check your progress. Your recent results appear on the topic and level pages.'},
    {'role': 'student', 'category': 'Account & Profile', 'order': 3,
     'question': 'I forgot my password. How do I reset it?',
     'answer': "On the login page, click **Forgot password?** and enter your email address. You'll receive a reset link shortly."},
    {'role': 'student', 'category': 'Progress & Reports', 'order': 4,
     'question': 'How do I check my progress?',
     'answer': "Go to **My Progress** in the sidebar. You'll see a breakdown of your performance across all topics and levels."},
    {'role': 'student', 'category': 'Attendance', 'order': 5,
     'question': 'How do I report an absence?',
     'answer': "If you received an absence token email, use the link in the email to self-report your absence. Otherwise, let your teacher know directly."},
    {'role': 'student', 'category': 'Getting Started', 'order': 6,
     'question': 'I can\'t see my subject. What should I do?',
     'answer': "Ask your teacher to enrol you in the subject. You may also need to join the class first using the **Join Class** feature."},
    {'role': 'student', 'category': 'Billing & Payments', 'order': 7,
     'question': 'My trial has ended. How do I continue?',
     'answer': 'Go to **Billing** in the sidebar to view available plans and subscribe. If your school manages your subscription, contact your teacher or school.'},
    {'role': 'student', 'category': 'Quizzes & Questions', 'order': 8,
     'question': 'Can I practise maths outside of assigned work?',
     'answer': "Yes! Go to the **Maths** subject area and browse topics freely. You can practise any topic at any level, not just assigned work."},
    {'role': 'student', 'category': 'Account & Profile', 'order': 9,
     'question': 'How do I update my profile?',
     'answer': 'Go to **Profile** in the sidebar to update your name and email address.'},
    {'role': 'student', 'category': 'Troubleshooting', 'order': 10,
     'question': 'The page isn\'t loading properly. What should I try?',
     'answer': 'Try refreshing the page. If it still doesn\'t work, clear your browser cache or try a different browser. Contact your teacher if the problem continues.'},
]


class Command(BaseCommand):
    help = 'Seed initial help categories, articles, and FAQs'

    def add_arguments(self, parser):
        parser.add_argument('--clear', action='store_true', help='Clear existing help data before seeding')

    def handle(self, *args, **options):
        if options['clear']:
            HelpArticleRole.objects.all().delete()
            HelpArticle.objects.all().delete()
            FAQ.objects.all().delete()
            HelpCategory.objects.all().delete()
            self.stdout.write('Cleared existing help data.')

        # Create categories
        category_map = {}
        for cat_data in CATEGORIES:
            cat, created = HelpCategory.objects.get_or_create(
                slug=slugify(cat_data['name']),
                defaults={
                    'name': cat_data['name'],
                    'description': cat_data.get('description', ''),
                    'order': cat_data['order'],
                },
            )
            category_map[cat_data['name']] = cat
            action = 'Created' if created else 'Skipped'
            self.stdout.write(f'{action} category: {cat.name}')

        # Create articles
        for article_data in ARTICLES:
            category = category_map[article_data['category']]
            slug = slugify(article_data['title'])
            article, created = HelpArticle.objects.get_or_create(
                slug=slug,
                defaults={
                    'title': article_data['title'],
                    'category': category,
                    'body_markdown': article_data['body'].strip(),
                    'excerpt': article_data.get('excerpt', ''),
                    'module': article_data.get('module', ''),
                    'page_url_name': article_data.get('page_url_name', ''),
                    'is_featured': article_data.get('is_featured', False),
                    'is_published': True,
                },
            )
            if created:
                for role_group in article_data.get('roles', []):
                    HelpArticleRole.objects.get_or_create(article=article, role_group=role_group)
                self.stdout.write(f'Created article: {article.title}')
            else:
                self.stdout.write(f'Skipped article: {article.title}')

        # Create FAQs
        for faq_data in FAQS:
            category = category_map.get(faq_data['category'])
            faq, created = FAQ.objects.get_or_create(
                question=faq_data['question'],
                role_group=faq_data['role'],
                defaults={
                    'answer_markdown': faq_data['answer'],
                    'category': category,
                    'order': faq_data.get('order', 0),
                    'is_published': True,
                },
            )
            action = 'Created' if created else 'Skipped'
            self.stdout.write(f'{action} FAQ ({faq_data["role"]}): {faq.question[:60]}')

        self.stdout.write(self.style.SUCCESS('Help content seeded successfully.'))
