"""
Django settings for cwa_classroom project.

Single settings file for ALL environments (local dev, test, production).
Environment-specific values are read from environment variables with sensible
local-dev defaults.  On PythonAnywhere set them in the "Web" tab → "Environment
variables" section; locally use a .env file (loaded by python-dotenv).

Required env vars for production / test deploys:
    SECRET_KEY, DEBUG=False, ALLOWED_HOSTS,
    DB_NAME, DB_USER, DB_PASSWORD, DB_HOST,
    EMAIL_HOST_USER, EMAIL_HOST_PASSWORD,
    SITE_URL
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / '.env', override=True)

# ---------------------------------------------------------------------------
# App Version  (SemVer — bump manually on each release)
# ---------------------------------------------------------------------------
APP_VERSION       = '1.13.6'         # MAJOR.MINOR.PATCH
APP_VERSION_DATE  = '2026-06-25'     # ISO date of this release

SECRET_KEY = os.environ.get('SECRET_KEY', 'change-me-in-production')

DEBUG = os.environ.get('DEBUG', 'True') == 'True'

ALLOWED_HOSTS = os.environ.get('ALLOWED_HOSTS', 'localhost,127.0.0.1,test-cwa-class-avinesh.pythonanywhere.com').split(',')

CSRF_TRUSTED_ORIGINS = [
    f'https://{host}' for host in ALLOWED_HOSTS if host not in ('localhost', '127.0.0.1')
] + [
    'http://localhost:8000',
    'http://127.0.0.1:8000',
    'http://localhost',
    'http://127.0.0.1',
]


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.sitemaps',

    # Third party
    'django_htmx',
    'django_rq',
    'storages',

    # Project apps
    'accounts',
    'classroom',
    'quiz',
    'billing',
    'progress',
    'audit',
    'usage',

    # Subject apps
    'maths',
    'coding',
    'music',
    'science',

    # Live quiz
    'brainbuzz',

    # Activity apps
    'number_puzzles',
    'homework',

    # AI tools
    'ai_import',

    # Help & Documentation
    'help',

    # Worksheets
    'worksheets',

    # Lifecycle email notifications
    'notifications',

    # Background task queue
    'taskqueue',

    # User feedback & feature requests (CPP-321)
    'feedback',

    # Jira sprint burndown chart
    'sprints',

    # WhatsApp parent notifications (CPP-XXX) — inert until configured
    'whatsapp',
]

# ---------------------------------------------------------------------------
# User feedback (CPP-321)
# ---------------------------------------------------------------------------
# Email of the product owner who owns the feedback triage queue. New feedback
# is assigned to this user. Falls back to the first superuser when unset.
FEEDBACK_OWNER_EMAIL = os.environ.get('FEEDBACK_OWNER_EMAIL', '')

# Jira integration for auto-filing bug-category feedback as CPP Bug issues.
# When any of BASE_URL / USER_EMAIL / API_TOKEN is unset the integration is a
# no-op (the service logs a warning and skips), so local/dev keeps working.
JIRA_BASE_URL = os.environ.get('JIRA_BASE_URL', '')
JIRA_USER_EMAIL = os.environ.get('JIRA_USER_EMAIL', '')
JIRA_API_TOKEN = os.environ.get('JIRA_API_TOKEN', '')
JIRA_PROJECT_KEY = os.environ.get('JIRA_PROJECT_KEY', 'CPP')

# Sprint burndown (sprints app). The Agile board the active sprint is read from
# and the custom field carrying story points. Leave JIRA_BOARD_ID unset to keep
# the burndown sync a no-op. The story-points field id is Jira-instance
# specific — customfield_10016 is the common Jira Cloud default; check your
# instance (Settings → Issues → Custom fields) and override via env if needed.
JIRA_BOARD_ID = os.environ.get('JIRA_BOARD_ID', '')
JIRA_STORY_POINTS_FIELD = os.environ.get('JIRA_STORY_POINTS_FIELD', 'customfield_10016')

# Optional Discord webhook to announce newly-filed bugs. Empty = disabled.
FEEDBACK_DISCORD_WEBHOOK = os.environ.get('FEEDBACK_DISCORD_WEBHOOK', '')

# ---------------------------------------------------------------------------
# AI / Anthropic
# ---------------------------------------------------------------------------
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')

# Claude pricing (USD per 1M tokens) used to estimate per-upload AI cost in the
# usage ledger. Defaults match Claude Opus 4.8 list price — the model both AI
# pipelines actually run (AI_IMPORT_MODEL / WORKSHEET_MODEL). Override via env
# when the model or list price changes. (Was $3/$15 Sonnet 4, which understated
# true cost ~1.67x while the pipelines ran on Opus.)
CLAUDE_INPUT_COST_PER_MTOK = float(
    os.environ.get('CLAUDE_INPUT_COST_PER_MTOK', '5.0'))
CLAUDE_OUTPUT_COST_PER_MTOK = float(
    os.environ.get('CLAUDE_OUTPUT_COST_PER_MTOK', '25.0'))

# USD->NZD conversion used by the income-vs-expense dashboard to convert
# USD-billed costs (Anthropic AI grading) into the dashboard's base currency
# (NZD). Manual vendor bills are converted by the operator on entry; this only
# applies to the automatic AIGradingUsage sync.
#
# The live rate is fetched from FX_RATE_API_URL (a free, ECB-backed,
# key-less endpoint — frankfurter.app) and cached. USD_TO_NZD_RATE is the
# FALLBACK used only when the API is disabled / unreachable. Set FX_RATE_API_URL
# to '' to force the static fallback (e.g. for an air-gapped environment).
USD_TO_NZD_RATE = float(os.environ.get('USD_TO_NZD_RATE', '1.65'))
FX_RATE_API_URL = os.environ.get(
    'FX_RATE_API_URL', 'https://api.frankfurter.dev/v1/latest')

# Read-only DigitalOcean Personal Access Token. When set, sync_vendor_charges
# pulls real monthly invoices (so droplet/DB/Spaces addons are captured with no
# manual update). Inert when empty — dev/test stay no-op.
DIGITALOCEAN_API_TOKEN = os.environ.get('DIGITALOCEAN_API_TOKEN', '')

# Live AI usage dashboard — after each AI call the worker rewrites a pinned
# GitHub issue with the latest usage/cost. Best-effort: stays disabled (no-op)
# until a token + repo are configured, so dev/test/local never call out.
AI_DASHBOARD_GITHUB_TOKEN = os.environ.get('AI_DASHBOARD_GITHUB_TOKEN', '')
AI_DASHBOARD_GITHUB_REPO = os.environ.get('AI_DASHBOARD_GITHUB_REPO', '')
AI_DASHBOARD_ISSUE_LABEL = os.environ.get('AI_DASHBOARD_ISSUE_LABEL', 'ai-usage-dashboard')
AI_DASHBOARD_ISSUE_NUMBER = os.environ.get('AI_DASHBOARD_ISSUE_NUMBER', '')
AI_USAGE_WINDOW_DAYS = int(os.environ.get('AI_USAGE_WINDOW_DAYS', '30'))
# When set (e.g. "Production" / "Test"), this environment owns one named section
# of a shared dashboard issue and only rewrites its own block — so prod and test
# can publish to the same issue without clobbering each other. Empty = legacy
# whole-issue mode (the env owns the entire issue body).
AI_DASHBOARD_ENV = os.environ.get('AI_DASHBOARD_ENV', '')

# ---------------------------------------------------------------------------
# Redis / RQ  (background task processing)
# ---------------------------------------------------------------------------
REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
RQ_QUEUES = {
    'high':    {'URL': REDIS_URL},
    'default': {'URL': REDIS_URL},
    'low':     {'URL': REDIS_URL},
}

# ---------------------------------------------------------------------------
# Coding — Piston sandboxed code execution
# ---------------------------------------------------------------------------
# Self-hosted Piston instance (run via Docker — see docker-compose.piston.yml)
# Local dev default: http://localhost:2000
# Production: set PISTON_API_URL=http://piston:2000 if on the same Docker network
PISTON_API_URL = os.environ.get('PISTON_API_URL', 'http://localhost:2000')
PISTON_API_TOKEN = os.environ.get('PISTON_API_TOKEN', '')
# Piston enforces these as hard caps on the runner side. Set both env vars on
# the Piston container (PISTON_RUN_TIMEOUT, PISTON_COMPILE_TIMEOUT in ms) and
# here in lockstep — exceeding the runner's configured maximum returns HTTP 400.
# Defaults match Piston's stock config (verified against the self-hosted
# instance at piston.wizardslearninghub.co.nz): run=3s, compile=10s.
PISTON_RUN_TIMEOUT_SECONDS = int(os.environ.get('PISTON_RUN_TIMEOUT_SECONDS', '3'))
PISTON_COMPILE_TIMEOUT_SECONDS = int(os.environ.get('PISTON_COMPILE_TIMEOUT_SECONDS', '10'))

# Coding — Quality scoring
# ---------------------------------------------------------------------------
# When True, submissions are analysed for code quality (cyclomatic complexity,
# nesting depth, redundant operations) and a quality multiplier (0.70–1.00) is
# applied on top of the base accuracy+speed score.
# Set ENABLE_QUALITY_SCORING=false in the environment to revert to pure
# accuracy+speed scoring (e.g. during an initial rollout or for a specific exam).
ENABLE_QUALITY_SCORING = os.environ.get('ENABLE_QUALITY_SCORING', 'true').lower() != 'false'

# Maximum fraction of points that quality penalties can remove (0.0–1.0).
# Default: 0.30  →  the worst-quality correct solution still earns ≥ 70 pts.
QUALITY_MAX_PENALTY = float(os.environ.get('QUALITY_MAX_PENALTY', '0.30'))

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'cwa_classroom.middleware.MathsRoomRedirectMiddleware',    # mathsroom → /maths/ redirect
    'cwa_classroom.middleware.SubdomainURLRoutingMiddleware',  # subdomain → urlconf routing
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'django_htmx.middleware.HtmxMiddleware',
    'cwa_classroom.middleware.TrialExpiryMiddleware',
    'cwa_classroom.middleware.AccountBlockMiddleware',
    'cwa_classroom.middleware.ProfileCompletionMiddleware',
    'usage.middleware.UsageTrackingMiddleware',  # last: records final page-view status
]

AUTHENTICATION_BACKENDS = [
    'accounts.backends.EmailOrUsernameBackend',
]

ROOT_URLCONF = 'cwa_classroom.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'accounts.context_processors.user_role',
                'classroom.context_processors.subject_apps',
                'classroom.context_processors.subject_sidebar_context',
                'classroom.context_processors.breadcrumbs_context',
                'help.context_processors.help_context',
                'cwa_classroom.context_processors.app_version',
                'homework.context_processors.new_homework_count',
                'worksheets.context_processors.active_worksheet_count',
            ],
        },
    },
]

WSGI_APPLICATION = 'cwa_classroom.wsgi.application'


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

# DB_ENGINE env var controls the database backend.
#   - "mysql"    (default) → MySQL via env vars DB_NAME, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT
#   - "postgres"           → PostgreSQL (used in CI to avoid SQLite write-lock issues)
#   - "sqlite"             → local SQLite file (no MySQL needed)
_DB_ENGINE = os.environ.get('DB_ENGINE', 'mysql')

if _DB_ENGINE == 'sqlite':
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
            # Live-server tests (Playwright UI suite) run the dev server in a
            # thread that writes to the same SQLite file as the test, so writers
            # contend. Wait up to 30s for the lock instead of erroring at
            # SQLite's 5s default — fixes intermittent "database is locked".
            'OPTIONS': {'timeout': 30},
        },
    }

    # Put SQLite in WAL mode on every new connection so readers don't block the
    # writer (the other half of the "database is locked" fix). Scoped to the
    # sqlite vendor, so this is a no-op for MySQL/Postgres (prod is untouched).
    from django.db.backends.signals import connection_created

    def _enable_sqlite_wal(sender, connection, **kwargs):
        if connection.vendor == 'sqlite':
            cursor = connection.cursor()
            cursor.execute('PRAGMA journal_mode=WAL;')
            cursor.execute('PRAGMA synchronous=NORMAL;')
            cursor.execute('PRAGMA busy_timeout=30000;')

    connection_created.connect(_enable_sqlite_wal, dispatch_uid='sqlite_wal_pragmas')
elif _DB_ENGINE == 'postgres':
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': os.environ.get('DB_NAME', 'cwa_test'),
            'USER': os.environ.get('DB_USER', 'cwa'),
            'PASSWORD': os.environ.get('DB_PASSWORD', 'cwa'),
            'HOST': os.environ.get('DB_HOST', '127.0.0.1'),
            'PORT': os.environ.get('DB_PORT', '5432'),
        },
    }
else:
    _mysql_options = {
        'charset': 'utf8mb4',
        'init_command': (
            "SET sql_mode='STRICT_TRANS_TABLES',"
            " innodb_lock_wait_timeout=300"
        ),
    }

    # TLS for DigitalOcean Managed MySQL — set DB_SSL_CA to the CA cert path
    _db_ssl_ca = os.environ.get('DB_SSL_CA', '')
    if _db_ssl_ca:
        _mysql_options['ssl'] = {'ca': _db_ssl_ca}

    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.mysql',
            'NAME': os.environ.get('DB_NAME', 'cwa_classroom'),
            'USER': os.environ.get('DB_USER', 'root'),
            'PASSWORD': os.environ.get('DB_PASSWORD', ''),
            'HOST': os.environ.get('DB_HOST', '127.0.0.1'),
            'PORT': os.environ.get('DB_PORT', '3306'),
            'OPTIONS': _mysql_options,
            'TEST': {
                'SERIALIZE': False,
            },
        },

    }

    # Legacy CWA_SCHOOL MySQL database — used only by the
    # migrate_from_cwa_school management command.
    # Excluded during test runs to avoid test DB creation issues.
    import sys
    if 'test' not in sys.argv:
        DATABASES['cwa_school_legacy'] = {
            'ENGINE': 'django.db.backends.mysql',
            'NAME': os.environ.get('SRC_DB_NAME', 'cwa_school'),
            'USER': os.environ.get('SRC_DB_USER', os.environ.get('DB_USER', 'root')),
            'PASSWORD': os.environ.get('SRC_DB_PASSWORD', os.environ.get('DB_PASSWORD', '')),
            'HOST': os.environ.get('SRC_DB_HOST', os.environ.get('DB_HOST', '127.0.0.1')),
            'PORT': os.environ.get('SRC_DB_PORT', os.environ.get('DB_PORT', '3306')),
            'OPTIONS': {
                'charset': 'utf8mb4',
            },
        }


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

AUTH_USER_MODEL = 'accounts.CustomUser'

LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/hub/'          # Changed from '/' -- redirects to Subjects Hub after login
LOGOUT_REDIRECT_URL = '/'             # Public landing page

PASSWORD_RESET_TIMEOUT = 3600

# SHA1PasswordHasher is included so that bulk-imported accounts (which use SHA1
# for speed — see import_services.execute_import) can authenticate until the
# user changes their password on first login (must_change_password=True).
# PBKDF2 remains the default hasher for all normal account creation.
PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.PBKDF2PasswordHasher',
    'django.contrib.auth.hashers.Argon2PasswordHasher',
    'django.contrib.auth.hashers.BCryptSHA256PasswordHasher',
    'django.contrib.auth.hashers.ScryptPasswordHasher',
]

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# ---------------------------------------------------------------------------
# Login rate limiting
# ---------------------------------------------------------------------------
# Keyed primarily by *username* so a shared-IP site (e.g. a school behind one
# NAT) can't be locked out collectively by a few students' typos — one
# student's failures only lock that student. A generous per-IP cap is a
# secondary safety net against a single host enumerating many accounts; raise
# LOGIN_RATELIMIT_IP_MAX if a very large school ever trips it.
LOGIN_RATELIMIT_USER_MAX = int(os.environ.get('LOGIN_RATELIMIT_USER_MAX', '10'))
LOGIN_RATELIMIT_IP_MAX = int(os.environ.get('LOGIN_RATELIMIT_IP_MAX', '100'))
LOGIN_RATELIMIT_WINDOW = int(os.environ.get('LOGIN_RATELIMIT_WINDOW', '900'))  # 15 min


# ---------------------------------------------------------------------------
# Internationalisation
# ---------------------------------------------------------------------------

LANGUAGE_CODE = 'en-nz'
TIME_ZONE = 'Pacific/Auckland'
USE_I18N = True
USE_TZ = True


# ---------------------------------------------------------------------------
# Static files
# ---------------------------------------------------------------------------

STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'


# ---------------------------------------------------------------------------
# Media files — local dev vs S3/Spaces production
# ---------------------------------------------------------------------------
# Works with both AWS S3 and DigitalOcean Spaces (S3-compatible).
# For DO Spaces, set:
#   AWS_S3_ENDPOINT_URL=https://syd1.digitaloceanspaces.com
#   AWS_S3_CUSTOM_DOMAIN=cwa-media-prod.syd1.digitaloceanspaces.com

USE_S3 = os.environ.get('USE_S3', 'False') == 'True'

STORAGES = {
    'staticfiles': {
        'BACKEND': (
            'django.contrib.staticfiles.storage.StaticFilesStorage'
            if DEBUG
            else 'whitenoise.storage.CompressedManifestStaticFilesStorage'
        ),
    },
}

if USE_S3:
    AWS_ACCESS_KEY_ID = os.environ.get('AWS_ACCESS_KEY_ID')
    AWS_SECRET_ACCESS_KEY = os.environ.get('AWS_SECRET_ACCESS_KEY')
    AWS_STORAGE_BUCKET_NAME = os.environ.get('AWS_STORAGE_BUCKET_NAME')
    AWS_S3_REGION_NAME = os.environ.get('AWS_S3_REGION_NAME', 'ap-southeast-2')
    AWS_S3_ENDPOINT_URL = os.environ.get('AWS_S3_ENDPOINT_URL', '')
    AWS_S3_CUSTOM_DOMAIN = os.environ.get(
        'AWS_S3_CUSTOM_DOMAIN',
        f'{AWS_STORAGE_BUCKET_NAME}.s3.amazonaws.com',
    )
    AWS_DEFAULT_ACL = 'public-read'
    AWS_S3_OBJECT_PARAMETERS = {'CacheControl': 'max-age=86400'}
    AWS_S3_FILE_OVERWRITE = False
    AWS_LOCATION = 'media'  # store all files under media/ prefix in the bucket

    STORAGES['default'] = {
        'BACKEND': 'storages.backends.s3boto3.S3Boto3Storage',
    }
    MEDIA_URL = f'https://{AWS_S3_CUSTOM_DOMAIN}/media/'
else:
    STORAGES['default'] = {
        'BACKEND': 'django.core.files.storage.FileSystemStorage',
    }
    MEDIA_URL = '/media/'
    MEDIA_ROOT = BASE_DIR / 'media'


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------

DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', 'noreply@wizardslearninghub.co.nz')
# Self-imposed daily send cap. 0 (the default) disables the cap entirely —
# emails send directly via the backend with no queue throttling. Set a positive
# integer to throttle (e.g. to stay under a provider's free-tier daily limit).
DAILY_EMAIL_LIMIT = int(os.environ.get('DAILY_EMAIL_LIMIT', '0'))

# Priority: Resend API (recommended) > SMTP (legacy) > Console (dev)
RESEND_API_KEY = os.environ.get('RESEND_API_KEY', '')

# Signing secret for the Resend delivery webhook (/webhooks/resend/). Copy it
# from the webhook's page in the Resend dashboard. Without it, the endpoint
# rejects all events.
RESEND_WEBHOOK_SECRET = os.environ.get('RESEND_WEBHOOK_SECRET', '')

if RESEND_API_KEY:
    EMAIL_BACKEND = 'cwa_classroom.email_backends.ResendEmailBackend'
else:
    EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', '')
    EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')
    if EMAIL_HOST_USER and EMAIL_HOST_PASSWORD:
        EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
        EMAIL_HOST = os.environ.get('EMAIL_HOST', 'smtpout.secureserver.net')
        EMAIL_PORT = int(os.environ.get('EMAIL_PORT', '465'))
        EMAIL_USE_TLS = os.environ.get('EMAIL_USE_TLS', 'False') == 'True'
        EMAIL_USE_SSL = os.environ.get('EMAIL_USE_SSL', 'True') == 'True'
    else:
        # No credentials configured — log emails to console
        EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'


# ---------------------------------------------------------------------------
# WhatsApp parent notifications (CPP-XXX)
# ---------------------------------------------------------------------------
# Inert until these are set: with no access token / phone-number id, every send
# raises a non-retriable 'no_credentials' error and WhatsAppConfig stays
# disabled by default, so nothing leaves the system.
WHATSAPP_PROVIDER = os.environ.get('WHATSAPP_PROVIDER', 'meta_cloud')
WHATSAPP_ACCESS_TOKEN = os.environ.get('WHATSAPP_ACCESS_TOKEN', '')
WHATSAPP_PHONE_NUMBER_ID = os.environ.get('WHATSAPP_PHONE_NUMBER_ID', '')
WHATSAPP_BUSINESS_ACCOUNT_ID = os.environ.get('WHATSAPP_BUSINESS_ACCOUNT_ID', '')
WHATSAPP_WEBHOOK_VERIFY_TOKEN = os.environ.get('WHATSAPP_WEBHOOK_VERIFY_TOKEN', '')
WHATSAPP_APP_SECRET = os.environ.get('WHATSAPP_APP_SECRET', '')
# Default region for parsing local phone numbers into E.164 (NZ).
WHATSAPP_DEFAULT_REGION = os.environ.get('WHATSAPP_DEFAULT_REGION', 'NZ')
WHATSAPP_GRAPH_VERSION = os.environ.get('WHATSAPP_GRAPH_VERSION', 'v19.0')


# ---------------------------------------------------------------------------
# Stripe
# ---------------------------------------------------------------------------

STRIPE_SECRET_KEY = os.environ.get('STRIPE_SECRET_KEY', '')
STRIPE_PUBLISHABLE_KEY = os.environ.get('STRIPE_PUBLISHABLE_KEY', '')
STRIPE_WEBHOOK_SECRET = os.environ.get('STRIPE_WEBHOOK_SECRET', '')
STRIPE_CURRENCY = os.environ.get('STRIPE_CURRENCY', 'usd')

# True when running under `manage.py test` — disables rate limiting in views
TESTING = 'test' in sys.argv

# Module add-on Stripe Price IDs (module_slug → stripe_price_id)
# Populate with actual Stripe price IDs in production
MODULE_STRIPE_PRICES = {
    'teachers_attendance': os.environ.get('STRIPE_PRICE_TEACHERS_ATTENDANCE', ''),
    'students_attendance': os.environ.get('STRIPE_PRICE_STUDENTS_ATTENDANCE', ''),
    'student_progress_reports': os.environ.get('STRIPE_PRICE_PROGRESS_REPORTS', ''),
}


# ---------------------------------------------------------------------------
# Quiz settings
# ---------------------------------------------------------------------------

# Global numeric answer tolerance (±)
ANSWER_NUMERIC_TOLERANCE = 0.05

# Duplicate quiz submission prevention window (seconds)
QUIZ_DEDUP_WINDOW_SECONDS = 5

# Recent result display window (seconds) — show results again if refreshed within this window
QUIZ_RECENT_RESULT_WINDOW_SECONDS = 30


# ---------------------------------------------------------------------------
# Caching — Redis when available, LocMem fallback for dev/PA
# ---------------------------------------------------------------------------

REDIS_URL = os.environ.get('REDIS_URL', '')

if REDIS_URL:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.redis.RedisCache',
            'LOCATION': REDIS_URL,
        },
    }
    SESSION_ENGINE = 'django.contrib.sessions.backends.cached_db'
else:
    SESSION_ENGINE = 'django.contrib.sessions.backends.db'
    # No Redis: fall back to an explicit per-process in-memory cache. NOTE:
    # LocMemCache is NOT shared across gunicorn workers, so short-TTL caches
    # (e.g. the Usage dashboard's 60s reporting cache) only de-duplicate work
    # within a single worker. Set REDIS_URL for cross-process cache sharing.
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        },
    }

# ---------------------------------------------------------------------------
# Sessions — harden cookie & limit session size
# ---------------------------------------------------------------------------

SESSION_COOKIE_AGE = 60 * 60 * 24 * 7          # 1 week (default is 2 weeks)
SESSION_SAVE_EVERY_REQUEST = True               # refresh expiry on every request so active users stay logged in
SESSION_COOKIE_HTTPONLY = True                   # JS cannot read session cookie
SESSION_COOKIE_SAMESITE = 'Lax'                 # mitigate CSRF via cross-site requests
SESSION_COOKIE_SECURE = not DEBUG               # HTTPS-only in production

# ---------------------------------------------------------------------------
# Upload limits
# ---------------------------------------------------------------------------
# The homework/worksheet PDF preview form posts every question back as a block
# of individual fields (~15 per question: text, type, validation, difficulty,
# points, rubric, explanation, image_ref, an always-submitted empty file input,
# plus answer rows). A large workbook PDF can extract several hundred questions,
# so the field count climbs fast: at ~334 questions it crosses 5000 and Django's
# request parser raises TooManyFieldsSent *before the view runs* (CsrfViewMiddleware
# reads request.POST first), surfacing as a bare "Bad Request (400)" on submit with
# the URL still on the preview page. 20000 covers ~1300 questions with headroom;
# this is an authenticated teacher-only endpoint so the larger ceiling is safe.
DATA_UPLOAD_MAX_NUMBER_FIELDS = 20000

# Same form has one file input per question (image replace/upload). Django counts
# only files that are actually chosen (empty file inputs parse as fields), but a
# teacher replacing images across a big worksheet could exceed the default of 100
# and hit the identical 400 via TooManyFilesSent. Lift it in step with the fields.
DATA_UPLOAD_MAX_NUMBER_FILES = 1000


# ---------------------------------------------------------------------------
# Default primary key
# ---------------------------------------------------------------------------

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# ---------------------------------------------------------------------------
# Public landing page / Subject hub
# ---------------------------------------------------------------------------

SITE_NAME = os.environ.get('SITE_NAME', 'Classroom')
SITE_DESCRIPTION = 'A comprehensive educational platform for students ages 6-12.'
# Auto-derive from ALLOWED_HOSTS when SITE_URL env var is not set:
#   local  → http://localhost:8000
#   test   → https://test-cwa-class-avinesh.pythonanywhere.com
#   prod   → https://<prod-domain>
def _default_site_url():
    for host in ALLOWED_HOSTS:
        if host not in ('localhost', '127.0.0.1', '*'):
            return f'https://{host}'
    return 'http://localhost:8000'

SITE_URL = os.environ.get('SITE_URL', _default_site_url())

# Contact form rate limiting (uses django cache)
CONTACT_RATE_LIMIT_PER_HOUR = 5

# reCAPTCHA (production only -- leave blank for dev)
RECAPTCHA_SITE_KEY = os.environ.get('RECAPTCHA_SITE_KEY', '')
RECAPTCHA_SECRET_KEY = os.environ.get('RECAPTCHA_SECRET_KEY', '')


# ---------------------------------------------------------------------------
# Security — production only (when DEBUG is False)
# ---------------------------------------------------------------------------

if not DEBUG:
    SECURE_SSL_REDIRECT = os.environ.get('SECURE_SSL_REDIRECT', 'True') == 'True'
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True


# ---------------------------------------------------------------------------
# Logging — write errors to /var/log/cwa/ when the directory exists (server),
# fall back to console-only when it doesn't (CI, local dev without the dir).
# ---------------------------------------------------------------------------

LOG_DIR = Path(os.environ.get('LOG_DIR', '/var/log/cwa'))
_log_dir_exists = LOG_DIR.exists()

_handlers: dict = {
    'console': {
        'class': 'logging.StreamHandler',
        'formatter': 'verbose',
    },
}
if _log_dir_exists:
    _handlers['error_file'] = {
        'class': 'logging.handlers.RotatingFileHandler',
        'filename': str(LOG_DIR / 'django-error.log'),
        'maxBytes': 10 * 1024 * 1024,  # 10 MB
        'backupCount': 5,
        'formatter': 'verbose',
        'level': 'ERROR',
        'delay': True,
    }
    _handlers['app_file'] = {
        'class': 'logging.handlers.RotatingFileHandler',
        'filename': str(LOG_DIR / 'django-app.log'),
        'maxBytes': 10 * 1024 * 1024,  # 10 MB
        'backupCount': 3,
        'formatter': 'verbose',
        'level': 'WARNING',
        'delay': True,
    }

_err_handlers  = ['console'] + (['error_file'] if _log_dir_exists else [])
_app_handlers  = ['console'] + (['app_file', 'error_file'] if _log_dir_exists else [])

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '[{asctime}] {levelname} {name} {module}:{lineno} — {message}',
            'style': '{',
        },
    },
    'handlers': _handlers,
    'root': {
        'handlers': _err_handlers,
        'level': 'WARNING',
    },
    'loggers': {
        'django': {
            'handlers': _err_handlers,
            'level': 'WARNING',
            'propagate': False,
        },
        'django.request': {
            'handlers': _err_handlers,
            'level': 'ERROR',
            'propagate': False,
        },
        # App loggers — WARNING+ goes to app log, ERROR+ also to error log
        'worksheets': {'handlers': _app_handlers, 'level': 'WARNING', 'propagate': False},
        'homework':   {'handlers': _app_handlers, 'level': 'WARNING', 'propagate': False},
        'billing':    {'handlers': _app_handlers, 'level': 'WARNING', 'propagate': False},
        'classroom':  {'handlers': _app_handlers, 'level': 'WARNING', 'propagate': False},
        # INFO so successful logins (which clear the rate-limit counter) are
        # visible alongside the WARNING-level failures and lockouts.
        'accounts':   {'handlers': _app_handlers, 'level': 'INFO', 'propagate': False},
    },
}
