"""
Seed help centre with starter categories, articles, FAQs, and role assignments.
"""
from django.db import migrations


CATEGORIES = [
    {
        'name': 'Getting Started',
        'slug': 'getting-started',
        'description': 'Everything you need to know to get up and running.',
        'order': 1,
        'icon_svg': '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M12 18v-5.25m0 0a6.01 6.01 0 001.5-.189m-1.5.189a6.01 6.01 0 01-1.5-.189m3.75 7.478a12.06 12.06 0 01-4.5 0m3.75 2.383a14.406 14.406 0 01-3 0M14.25 18v-.192c0-.983.658-1.823 1.508-2.316a7.5 7.5 0 10-7.517 0c.85.493 1.509 1.333 1.509 2.316V18" /></svg>',
    },
    {
        'name': 'For Teachers',
        'slug': 'for-teachers',
        'description': 'Guides for managing classes, sessions, and students.',
        'order': 2,
        'icon_svg': '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M4.26 10.147a60.436 60.436 0 00-.491 6.347A48.627 48.627 0 0112 20.904a48.627 48.627 0 018.232-4.41 60.46 60.46 0 00-.491-6.347m-15.482 0a50.57 50.57 0 00-2.658-.813A59.905 59.905 0 0112 3.493a59.902 59.902 0 0110.399 5.84c-.896.248-1.783.52-2.658.814m-15.482 0A50.697 50.697 0 0112 13.489a50.702 50.702 0 017.74-3.342M6.75 15a.75.75 0 100-1.5.75.75 0 000 1.5zm0 0v-3.675A55.378 55.378 0 0112 8.443m-7.007 11.55A5.981 5.981 0 006.75 15.75v-1.5" /></svg>',
    },
    {
        'name': 'For Students',
        'slug': 'for-students',
        'description': 'How to join classes, take quizzes, and track your learning.',
        'order': 3,
        'icon_svg': '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M17.982 18.725A7.488 7.488 0 0012 15.75a7.488 7.488 0 00-5.982 2.975m11.963 0a9 9 0 10-11.963 0m11.963 0A8.966 8.966 0 0112 21a8.966 8.966 0 01-5.982-2.275M15 9.75a3 3 0 11-6 0 3 3 0 016 0z" /></svg>',
    },
    {
        'name': 'For Parents',
        'slug': 'for-parents',
        'description': 'Monitor your child\'s progress, attendance, and invoices.',
        'order': 4,
        'icon_svg': '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M18 18.72a9.094 9.094 0 003.741-.479 3 3 0 00-4.682-2.72m.94 3.198l.001.031c0 .225-.012.447-.037.666A11.944 11.944 0 0112 21c-2.17 0-4.207-.576-5.963-1.584A6.062 6.062 0 016 18.719m12 0a5.971 5.971 0 00-.941-3.197m0 0A5.995 5.995 0 0012 12.75a5.995 5.995 0 00-5.058 2.772m0 0a3 3 0 00-4.681 2.72 8.986 8.986 0 003.74.477m.94-3.197a5.971 5.971 0 00-.94 3.197M15 6.75a3 3 0 11-6 0 3 3 0 016 0zm6 3a2.25 2.25 0 11-4.5 0 2.25 2.25 0 014.5 0zm-13.5 0a2.25 2.25 0 11-4.5 0 2.25 2.25 0 014.5 0z" /></svg>',
    },
    {
        'name': 'School Administration',
        'slug': 'school-administration',
        'description': 'Setting up and managing your school, departments, and staff.',
        'order': 5,
        'icon_svg': '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M3.75 21h16.5M4.5 3h15M5.25 3v18m13.5-18v18M9 6.75h1.5m-1.5 3h1.5m-1.5 3h1.5m3-6H15m-1.5 3H15m-1.5 3H15M9 21v-3.375c0-.621.504-1.125 1.125-1.125h3.75c.621 0 1.125.504 1.125 1.125V21" /></svg>',
    },
    {
        'name': 'Billing & Payments',
        'slug': 'billing-payments',
        'description': 'Invoices, fees, salary slips, and payment records.',
        'order': 6,
        'icon_svg': '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M2.25 18.75a60.07 60.07 0 0115.797 2.101c.727.198 1.453-.342 1.453-1.096V18.75M3.75 4.5v.75A.75.75 0 013 6h-.75m0 0v-.375c0-.621.504-1.125 1.125-1.125H20.25M2.25 6v9m18-10.5v.75c0 .414.336.75.75.75h.75m-1.5-1.5h.375c.621 0 1.125.504 1.125 1.125v9.75c0 .621-.504 1.125-1.125 1.125h-.375m1.5-1.5H21a.75.75 0 00-.75.75v.75m0 0H3.75m0 0h-.375a1.125 1.125 0 01-1.125-1.125V15m1.5 1.5v-.75A.75.75 0 003 15h-.75M15 10.5a3 3 0 11-6 0 3 3 0 016 0zm3 0h.008v.008H18V10.5zm-12 0h.008v.008H6V10.5z" /></svg>',
    },
]

ARTICLES = [
    # ── Getting Started ──────────────────────────────────────────────────────
    {
        'category_slug': 'getting-started',
        'title': 'Welcome to Classroom',
        'slug': 'welcome-to-classroom',
        'excerpt': 'An overview of the Classroom platform and what you can do with it.',
        'module': 'accounts',
        'order': 1,
        'is_featured': True,
        'roles': ['hoi', 'hod', 'teacher', 'accountant', 'parent', 'student', 'admin'],
        'body_markdown': """\
# Welcome to Classroom

Classroom is a comprehensive school management platform by Code Wizard Aotearoa.
It brings together everything your school needs in one place.

## What can you do?

- **Teachers** can manage classes, run sessions, record attendance, and set quizzes.
- **Students** can join classes, practise subjects, and track their own progress.
- **Parents** can monitor their child\'s attendance, results, and invoices.
- **School owners and heads of department** can manage staff, departments, and billing.

## Navigating the platform

After signing in you will land on the **Hub** — your personal starting point.
From there use the top navigation bar or the subject cards to move around.

If you ever need help, visit this Help Centre or use the **Contact Us** page to reach our team.
""",
    },
    {
        'category_slug': 'getting-started',
        'title': 'How to sign in',
        'slug': 'how-to-sign-in',
        'excerpt': 'Step-by-step instructions for signing in to your Classroom account.',
        'module': 'accounts',
        'order': 2,
        'is_featured': False,
        'roles': ['hoi', 'hod', 'teacher', 'accountant', 'parent', 'student', 'admin'],
        'body_markdown': """\
# How to sign in

1. Go to the Classroom website and click **Sign In** in the top-right corner.
2. Enter your **username** (or email address) and **password**.
3. Click **Sign In**.

## Forgot your password?

Click **Forgot password?** on the sign-in page. Enter the email address linked to your
account and you will receive a reset link within a few minutes.

## First-time login

If your school administrator created your account, you may be asked to **change your
password** and complete your profile on first login. Follow the prompts — this only
takes a minute.

## Still can\'t sign in?

Contact your school administrator or reach us through the **Contact Us** page.
""",
    },
    {
        'category_slug': 'getting-started',
        'title': 'Updating your profile',
        'slug': 'updating-your-profile',
        'excerpt': 'How to update your name, email address, and password.',
        'module': 'accounts',
        'page_url_name': 'profile',
        'order': 3,
        'is_featured': False,
        'roles': ['hoi', 'hod', 'teacher', 'accountant', 'parent', 'student', 'admin'],
        'body_markdown': """\
# Updating your profile

To update your profile information:

1. Click your **avatar / initials** in the top-right corner of any page.
2. Select **My Profile** from the drop-down menu.
3. Edit your details and click **Save**.

## What can you update?

- First and last name
- Email address
- Password

## Why keep your details up to date?

Your email address is used for important notifications such as invoice reminders,
session updates, and password resets. Make sure it is always current.
""",
    },

    # ── For Teachers ─────────────────────────────────────────────────────────
    {
        'category_slug': 'for-teachers',
        'title': 'Creating and managing your classes',
        'slug': 'creating-managing-classes',
        'excerpt': 'How to create a class, add students, and set it up ready for teaching.',
        'module': 'classroom',
        'page_url_name': 'create_class',
        'order': 1,
        'is_featured': True,
        'roles': ['teacher', 'hod', 'hoi'],
        'body_markdown': """\
# Creating and managing your classes

## Create a new class

1. From your **Teacher Dashboard**, click **Create Class**.
2. Give the class a name and assign it to the correct subject and level.
3. Click **Save**.

## Adding students

1. Open the class from your dashboard.
2. Click **Assign Students**.
3. Search for students by name or username and add them to the class.

## Sharing the class code

Each class has a unique join code. Share it with students so they can self-enrol
from their student dashboard using **Join a Class**.

## Editing or archiving a class

Open the class, click the **Edit** button to change details, or use the archive
option to hide it from your active list without deleting it.
""",
    },
    {
        'category_slug': 'for-teachers',
        'title': 'Running a session',
        'slug': 'running-a-session',
        'excerpt': 'Start a class session, mark attendance, and complete it when done.',
        'module': 'attendance',
        'page_url_name': 'teacher_dashboard',
        'order': 2,
        'is_featured': False,
        'roles': ['teacher', 'hod'],
        'body_markdown': """\
# Running a session

A **session** represents one live class meeting. Recording sessions lets you
track attendance and hours taught.

## Starting a session

1. Go to your **Teacher Dashboard**.
2. Find your class and click **Start Session**.
3. Confirm the date and time, then click **Begin**.

## Marking attendance

During or after the session, open it and mark each student as:

- **Present** — attended the session
- **Absent** — did not attend
- **Late** — arrived after the session started

## Completing a session

When the class is finished, click **Complete Session**. This locks the
attendance record and adds the hours to your teaching log.

## Scheduling a future session

Use **Create Session** to schedule a session in advance. Students and parents
will be able to see it on their dashboards.
""",
    },
    {
        'category_slug': 'for-teachers',
        'title': 'Importing students via CSV',
        'slug': 'importing-students-csv',
        'excerpt': 'Bulk-enrol students into your school by uploading a CSV file.',
        'module': 'classroom',
        'page_url_name': 'student_csv_upload',
        'order': 3,
        'is_featured': False,
        'roles': ['teacher', 'hod', 'hoi'],
        'body_markdown': """\
# Importing students via CSV

You can add many students at once by uploading a CSV file instead of
creating accounts one by one.

## Prepare your CSV

Your file should include columns for:

- **First name** and **Last name**
- **Email address** (used as login)
- **Year level** or class name (optional)

Download our **CSV template** from the import page for the exact format.

## Upload and map columns

1. Go to **Import Students** from the admin or teacher menu.
2. Upload your file.
3. On the next screen, map your CSV columns to the correct fields.
4. Click **Preview** to review the data before importing.

## Confirm and send credentials

After previewing, click **Confirm Import**. Student accounts will be created
and a credentials sheet will be available to download and hand out.

## Tips

- Remove any header rows before uploading if they cause mapping issues.
- Duplicate email addresses are skipped automatically.
- You can re-run the import with a corrected file — existing accounts will not be duplicated.
""",
    },
    {
        'category_slug': 'for-teachers',
        'title': 'Tracking student progress',
        'slug': 'tracking-student-progress',
        'excerpt': 'View quiz results, time spent, and subject performance for your students.',
        'module': 'progress',
        'page_url_name': 'class_progress_list',
        'order': 4,
        'is_featured': False,
        'roles': ['teacher', 'hod'],
        'body_markdown': """\
# Tracking student progress

Classroom automatically records quiz scores, time spent on subjects,
and session attendance so you can see how each student is doing.

## Class progress overview

From your **Teacher Dashboard**, click **Class Progress** to see a summary
for all students in a class — quiz accuracy, sessions attended, and recent activity.

## Individual student view

Click on a student\'s name to open their detailed progress report, including:

- Quiz results by topic
- Time spent on each subject
- Attendance history

## Progress criteria

You can set custom progress milestones for students. Go to **Progress → Criteria**
to create criteria, then approve or reject student submissions when they claim
to have met them.

## Exporting reports

Use the **Export** button on any progress page to download a CSV for your records
or to share with parents.
""",
    },

    # ── For Students ─────────────────────────────────────────────────────────
    {
        'category_slug': 'for-students',
        'title': 'How to join a class',
        'slug': 'how-to-join-a-class',
        'excerpt': 'Join a class using a code from your teacher or a direct invitation.',
        'module': 'classroom',
        'page_url_name': 'student_join_class',
        'order': 1,
        'is_featured': True,
        'roles': ['student'],
        'body_markdown': """\
# How to join a class

## Join with a class code

Your teacher will give you a **class code** — a short string of letters and numbers.

1. Sign in and go to **My Classes** from your dashboard.
2. Click **Join a Class**.
3. Enter the class code and click **Join**.

## Join via invitation

If your teacher has enrolled you directly, the class will already appear under
**My Classes** — no code needed.

## Can\'t find the class?

- Double-check the code with your teacher (codes are case-sensitive).
- Make sure you are signed in to the correct account.
- Contact your teacher if the class does not appear after joining.
""",
    },
    {
        'category_slug': 'for-students',
        'title': 'Taking a quiz',
        'slug': 'taking-a-quiz',
        'excerpt': 'How to start a quiz, answer questions, and review your results.',
        'module': 'quiz',
        'order': 2,
        'is_featured': False,
        'roles': ['student'],
        'body_markdown': """\
# Taking a quiz

## Starting a quiz

1. From the **Hub**, select a subject (e.g. Maths).
2. Choose a topic and click **Start Quiz** or **Practise**.
3. Read each question and select your answer.
4. Click **Submit** when you are ready to move on.

## Tips for a good score

- Read the question carefully before selecting an answer.
- If you are unsure, try to eliminate the answers you know are wrong.
- There is no time penalty for thinking — take your time.

## Reviewing your results

After the quiz your score and correct answers are shown immediately.
You can also find your quiz history under **My Progress**.

## Basic facts (speed drills)

Some quizzes are timed speed drills — answer as many as you can before the clock runs out.
Your best score is saved and you can try to beat it next time.
""",
    },
    {
        'category_slug': 'for-students',
        'title': 'Practising Maths',
        'slug': 'practising-maths',
        'excerpt': 'How to use the Maths module to practise topics and track your time.',
        'module': 'maths',
        'order': 3,
        'is_featured': False,
        'roles': ['student'],
        'body_markdown': """\
# Practising Maths

The Maths module lets you work through questions at your own pace and track
how much time you spend practising each week.

## Choosing a topic

1. Go to **Maths** from the Hub or subject menu.
2. Browse topics such as Addition, Multiplication, Fractions, or Algebra.
3. Select a level that matches your year group.
4. Click **Start Practising**.

## Weekly time tracker

Your time is tracked automatically while you practise. You can see your
**daily** and **weekly** totals on your Maths dashboard. The weekly total
resets every Monday.

## Number Puzzles

Number Puzzles are a fun way to sharpen mental maths. Find them under
**Number Puzzles** in the subject menu — try to beat your personal best score.

## Stuck on a question?

If a question seems very hard, skip it and come back later, or ask your teacher
to go over the topic with you.
""",
    },
    {
        'category_slug': 'for-students',
        'title': 'Viewing your progress',
        'slug': 'viewing-your-progress',
        'excerpt': 'How to see your quiz scores, attendance, and subject history.',
        'module': 'progress',
        'order': 4,
        'is_featured': False,
        'roles': ['student'],
        'body_markdown': """\
# Viewing your progress

## Your progress page

From the Hub, click **Progress** (or your subject\'s progress link) to see:

- Quiz scores broken down by topic
- Time spent on each subject this week
- Sessions attended and missed

## Attendance history

Go to **My Attendance** to see a full list of sessions, whether you were marked
present, absent, or late, and any makeup sessions you have been granted.

## Progress criteria

Your teacher may set milestones for you to achieve. When you believe you have
met one, click **Submit** on that criterion. Your teacher will review and
approve or give feedback.
""",
    },

    # ── For Parents ──────────────────────────────────────────────────────────
    {
        'category_slug': 'for-parents',
        'title': 'Linking your child\'s account',
        'slug': 'linking-childs-account',
        'excerpt': 'How to connect your parent account to your child so you can monitor their activity.',
        'module': 'accounts',
        'order': 1,
        'is_featured': True,
        'roles': ['parent'],
        'body_markdown': """\
# Linking your child\'s account

## Receiving an invitation

Your child\'s school will send you an email invitation with a link to create
your parent account and link it to your child automatically.

1. Click the link in the invitation email.
2. Create your password and complete your profile.
3. You will be taken directly to your parent dashboard showing your child\'s activity.

## Multiple children

If you have more than one child at the school, each will have their own invitation.
Once both are linked, you can switch between children using the **Switch Child**
option at the top of your parent dashboard.

## Can\'t find the invitation email?

- Check your spam or junk folder.
- Contact the school and ask them to resend the invitation.
""",
    },
    {
        'category_slug': 'for-parents',
        'title': 'Monitoring your child\'s progress',
        'slug': 'monitoring-child-progress',
        'excerpt': 'View quiz scores, subject activity, and time spent learning.',
        'module': 'progress',
        'page_url_name': 'parent_progress',
        'order': 2,
        'is_featured': False,
        'roles': ['parent'],
        'body_markdown': """\
# Monitoring your child\'s progress

## Progress dashboard

From your **Parent Dashboard**, click **Progress** to see:

- Quiz scores and accuracy by subject and topic
- Time spent on each subject this week and cumulatively
- Recent activity

## Understanding the scores

Each quiz shows a **percentage score**. A score above 80% is excellent.
If your child is consistently below 50% on a topic, it may be worth
discussing extra practice with their teacher.

## Switching between children

If you have more than one child linked to your account, use the
**Switch Child** button at the top of the page to view each child\'s report.
""",
    },
    {
        'category_slug': 'for-parents',
        'title': 'Checking attendance',
        'slug': 'checking-attendance',
        'excerpt': 'See which sessions your child attended, missed, or was late to.',
        'module': 'attendance',
        'page_url_name': 'parent_attendance',
        'order': 3,
        'is_featured': False,
        'roles': ['parent'],
        'body_markdown': """\
# Checking attendance

## Attendance page

From your **Parent Dashboard**, click **Attendance** to see a list of all
sessions for your child\'s enrolled classes, with a status for each:

- **Present** — attended
- **Absent** — did not attend
- **Late** — arrived after the session started

## Makeup sessions (absence tokens)

If your child missed a session and the school offers makeups, an
**absence token** may be issued. Your child can use this token to attend
a different session as a makeup. You can see any tokens and their status
from the attendance page.

## Concerned about an absence?

If you believe an attendance record is incorrect, contact your child\'s
teacher directly or use the **Contact Us** page.
""",
    },
    {
        'category_slug': 'for-parents',
        'title': 'Understanding your invoices',
        'slug': 'understanding-invoices',
        'excerpt': 'How to view, download, and understand your fee invoices.',
        'module': 'billing',
        'page_url_name': 'parent_invoices',
        'order': 4,
        'is_featured': False,
        'roles': ['parent'],
        'body_markdown': """\
# Understanding your invoices

## Viewing invoices

From your **Parent Dashboard**, click **Invoices** to see all issued invoices
for your child\'s classes.

Each invoice shows:

- The billing period it covers
- The classes or subjects included
- The total amount due
- The payment status (unpaid, paid, or cancelled)

## Making a payment

Payments are recorded by the school. Contact your school directly if you have
questions about how to pay (bank transfer, cash, etc.).

## Invoice history

All past invoices — including paid ones — are listed in your invoice history
so you always have a record.

## Questions about a charge?

Contact the school or use the **Contact Us** page and include the invoice
number from the invoice page.
""",
    },

    # ── School Administration ─────────────────────────────────────────────────
    {
        'category_slug': 'school-administration',
        'title': 'Setting up your school',
        'slug': 'setting-up-your-school',
        'excerpt': 'A step-by-step guide for new school owners getting started on Classroom.',
        'module': 'hierarchy',
        'order': 1,
        'is_featured': True,
        'roles': ['hoi', 'admin'],
        'body_markdown': """\
# Setting up your school

Welcome! Follow these steps to get your school ready on Classroom.

## Step 1 — Complete your school profile

Go to **Admin Dashboard → Schools → Your School → Edit** and fill in:

- School name and contact email
- Invoice terms and address
- Outgoing email settings

## Step 2 — Create departments

Departments group your classes by subject area or year level.

1. Go to **Admin Dashboard → Schools → Your School → Departments**.
2. Click **Create Department** and give it a name (e.g. "Maths Department").
3. Assign a **Head of Department** if applicable.

## Step 3 — Add teachers

Go to **Admin Dashboard → Schools → Your School → Teachers → Add Teacher**.
Enter their details — they will receive a welcome email with login credentials.

## Step 4 — Set up an academic year and terms

Go to **Admin Dashboard → Schools → Academic Year → Create** to define the
current year, its start/end dates, and the term structure.

## Step 5 — Publish your school

Once everything is set up, click **Publish School**. This activates teacher
accounts and makes the school fully operational.
""",
    },
    {
        'category_slug': 'school-administration',
        'title': 'Managing departments and subject levels',
        'slug': 'managing-departments',
        'excerpt': 'How to create departments, assign heads, and configure subject levels.',
        'module': 'hierarchy',
        'order': 2,
        'is_featured': False,
        'roles': ['hoi', 'hod', 'admin'],
        'body_markdown': """\
# Managing departments and subject levels

## What is a department?

A department is a group of classes, teachers, and students organised around a
subject or curriculum area (e.g. "Junior Maths", "Coding Club").

## Creating a department

1. Go to **Admin Dashboard → Schools → Your School → Departments → Create Department**.
2. Enter a name and assign a fee if applicable.
3. Click **Save**.

## Assigning a Head of Department

Open the department and click **Assign HoD**. The HoD will gain access to
department-level management tools such as workload reports and class creation.

## Configuring subject levels

Use **Subject Levels** within a department to control which quiz levels and
topics are available for classes in that department. Only enabled levels will
appear when teachers set up quizzes.

## Deactivating a department

If a department is no longer needed, use the **Toggle Active** button. Inactive
departments are hidden from teachers and students but their data is preserved.
""",
    },
    {
        'category_slug': 'school-administration',
        'title': 'Adding and managing teachers',
        'slug': 'adding-managing-teachers',
        'excerpt': 'How to add new teachers, assign them to departments, and manage their access.',
        'module': 'classroom',
        'order': 3,
        'is_featured': False,
        'roles': ['hoi', 'hod', 'admin'],
        'body_markdown': """\
# Adding and managing teachers

## Adding a single teacher

1. Go to **Admin Dashboard → Schools → Your School → Teachers → Add Teacher**.
2. Enter their full name and email address.
3. Click **Save** — a welcome email is sent automatically with their login details.

## Bulk-adding teachers via CSV

For multiple teachers at once, use **Import Teachers**:

1. Download the CSV template.
2. Fill in name and email for each teacher.
3. Upload the file and follow the mapping and confirmation steps.

## Assigning teachers to departments

Open a department and go to **Manage Teachers** to add or remove teachers.
Teachers must be in a department to create classes within it.

## Editing or removing a teacher

Open the teacher from the school's teacher list. Use **Edit** to update their
details, or **Remove** to revoke access. Removed teachers can be restored later.
""",
    },

    # ── Billing & Payments ───────────────────────────────────────────────────
    {
        'category_slug': 'billing-payments',
        'title': 'Generating and issuing invoices',
        'slug': 'generating-issuing-invoices',
        'excerpt': 'How to generate fee invoices for students and issue them for payment.',
        'module': 'invoicing',
        'page_url_name': 'generate_invoices',
        'order': 1,
        'is_featured': True,
        'roles': ['hoi', 'hod', 'accountant'],
        'body_markdown': """\
# Generating and issuing invoices

## Before you begin

Make sure fee rates are configured under **Invoicing → Fees** before
generating invoices. Fees can be set at the department, subject, class,
or individual student level.

## Generate invoices

1. Go to **Invoicing → Generate**.
2. Select the billing period (term or date range).
3. Choose the classes or departments to invoice.
4. Click **Generate** to create draft invoices.

## Review and issue

1. Go to **Invoicing → Preview** to review all draft invoices before sending.
2. Make any corrections.
3. Click **Issue** to send invoices. Students and parents will be notified.

## Recording a payment

Open an invoice and click **Record Payment**. Enter the amount, date, and
payment method (bank transfer, cash, etc.).

## Cancelling an invoice

Open the invoice and click **Cancel**. Cancelled invoices are kept in the
system for your records but removed from the student\'s outstanding balance.
""",
    },
    {
        'category_slug': 'billing-payments',
        'title': 'Managing teacher salary slips',
        'slug': 'managing-salary-slips',
        'excerpt': 'How to generate, issue, and record payments for teacher salary slips.',
        'module': 'salaries',
        'page_url_name': 'salary_slip_list',
        'order': 2,
        'is_featured': False,
        'roles': ['hoi', 'accountant'],
        'body_markdown': """\
# Managing teacher salary slips

## Setting hourly rates

Before generating slips, configure rates under **Salaries → Rates**:

- Set a **school-wide default rate**.
- Override the rate for individual teachers using **Teacher Rate Overrides**.

## Generating salary slips

1. Go to **Salaries → Generate**.
2. Select the pay period.
3. Click **Generate** — draft slips are created based on sessions taught.

## Review and issue

1. Go to **Salaries → Preview** to review draft slips.
2. Once correct, click **Issue** to finalise them.

## Recording a payment

Open a salary slip and click **Record Payment**. Enter the amount paid,
date, and payment method.

## Correcting a slip

If a slip is wrong, cancel it and regenerate for the corrected period.
""",
    },
    {
        'category_slug': 'billing-payments',
        'title': 'Importing payments from a bank CSV',
        'slug': 'importing-payments-csv',
        'excerpt': 'Match and record bulk payments by uploading your bank\'s transaction export.',
        'module': 'invoicing',
        'page_url_name': 'csv_upload',
        'order': 3,
        'is_featured': False,
        'roles': ['hoi', 'accountant'],
        'body_markdown': """\
# Importing payments from a bank CSV

Instead of recording each payment manually, you can upload a CSV export from
your bank and let Classroom match transactions to invoices automatically.

## Export from your bank

Download a CSV or Excel export of transactions from your bank\'s online portal.
Most banks include date, reference, and amount columns.

## Upload and map columns

1. Go to **Invoicing → CSV Upload**.
2. Upload the file.
3. Map the columns (date, amount, reference/description) to the correct fields.

## Review matches

Classroom will attempt to match each transaction to a student\'s invoice by
payment reference. Review the matches on the next screen:

- **Matched** — a confident match was found.
- **Unmatched** — no match found; you can manually select the invoice.

## Confirm

Click **Confirm** to apply the matches and mark the invoices as paid.
Unmatched transactions are skipped and can be handled manually later.
""",
    },
]

FAQS = [
    {
        'category_slug': 'getting-started',
        'role_group': 'student',
        'question': 'I forgot my password. How do I reset it?',
        'answer_markdown': 'Go to the sign-in page and click **Forgot password?**. Enter your email and follow the link in the reset email.',
        'order': 1,
    },
    {
        'category_slug': 'getting-started',
        'role_group': 'teacher',
        'question': 'How do I switch between schools?',
        'answer_markdown': 'From your **Teacher Dashboard**, click **Switch School** in the top menu. Select the school you want to manage.',
        'order': 1,
    },
    {
        'category_slug': 'for-students',
        'role_group': 'student',
        'question': 'My class code isn\'t working. What do I do?',
        'answer_markdown': 'Double-check the code with your teacher — codes are case-sensitive. Make sure you\'re signed in to the correct account.',
        'order': 2,
    },
    {
        'category_slug': 'for-students',
        'role_group': 'student',
        'question': 'Can I redo a quiz I\'ve already completed?',
        'answer_markdown': 'Yes! Open the topic from the Hub and click **Practise Again**. Your previous best score is saved separately.',
        'order': 3,
    },
    {
        'category_slug': 'for-teachers',
        'role_group': 'teacher',
        'question': 'A student says they can\'t see the class I assigned them to.',
        'answer_markdown': 'Check that the student is enrolled in the class under **Class → Assign Students**. Also confirm their account is active.',
        'order': 2,
    },
    {
        'category_slug': 'for-parents',
        'role_group': 'parent',
        'question': 'I didn\'t receive the invitation email.',
        'answer_markdown': 'Check your spam or junk folder. If it\'s not there, ask the school to resend the invitation.',
        'order': 1,
    },
    {
        'category_slug': 'for-parents',
        'role_group': 'parent',
        'question': 'How do I pay an invoice?',
        'answer_markdown': 'Payments are made directly to the school. Contact them for their preferred payment method (bank transfer, cash, etc.). The school will then mark the invoice as paid.',
        'order': 2,
    },
    {
        'category_slug': 'billing-payments',
        'role_group': 'accountant',
        'question': 'Can I regenerate an invoice after cancelling it?',
        'answer_markdown': 'Yes. Go to **Invoicing → Generate**, select the same billing period, and regenerate. The cancelled invoice is kept as a record.',
        'order': 1,
    },
]


def seed_help_content(apps, schema_editor):
    HelpCategory = apps.get_model('help', 'HelpCategory')
    HelpArticle = apps.get_model('help', 'HelpArticle')
    HelpArticleRole = apps.get_model('help', 'HelpArticleRole')
    FAQ = apps.get_model('help', 'FAQ')

    # Create categories
    cat_map = {}
    for cat_data in CATEGORIES:
        cat, _ = HelpCategory.objects.get_or_create(
            slug=cat_data['slug'],
            defaults={
                'name': cat_data['name'],
                'description': cat_data['description'],
                'icon_svg': cat_data.get('icon_svg', ''),
                'order': cat_data['order'],
                'is_active': True,
            },
        )
        cat_map[cat_data['slug']] = cat

    # Create articles and role assignments
    for art_data in ARTICLES:
        cat = cat_map[art_data['category_slug']]
        article, created = HelpArticle.objects.get_or_create(
            slug=art_data['slug'],
            defaults={
                'category': cat,
                'title': art_data['title'],
                'body_markdown': art_data['body_markdown'],
                'excerpt': art_data.get('excerpt', ''),
                'module': art_data.get('module', ''),
                'page_url_name': art_data.get('page_url_name', ''),
                'order': art_data.get('order', 0),
                'is_published': True,
                'is_featured': art_data.get('is_featured', False),
            },
        )
        if created:
            for role in art_data.get('roles', []):
                HelpArticleRole.objects.get_or_create(article=article, role_group=role)

    # Create FAQs
    for faq_data in FAQS:
        cat = cat_map.get(faq_data['category_slug'])
        FAQ.objects.get_or_create(
            question=faq_data['question'],
            role_group=faq_data['role_group'],
            defaults={
                'answer_markdown': faq_data['answer_markdown'],
                'category': cat,
                'order': faq_data.get('order', 0),
                'is_published': True,
            },
        )


def remove_help_content(apps, schema_editor):
    HelpArticle = apps.get_model('help', 'HelpArticle')
    HelpCategory = apps.get_model('help', 'HelpCategory')
    FAQ = apps.get_model('help', 'FAQ')

    slugs = [a['slug'] for a in ARTICLES]
    HelpArticle.objects.filter(slug__in=slugs).delete()

    cat_slugs = [c['slug'] for c in CATEGORIES]
    HelpCategory.objects.filter(slug__in=cat_slugs).delete()

    questions = [f['question'] for f in FAQS]
    FAQ.objects.filter(question__in=questions).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('help', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed_help_content, remove_help_content),
    ]
