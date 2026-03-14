"""
Django settings for cwa_classroom project.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / '.env')

SECRET_KEY = os.environ.get('SECRET_KEY', 'change-me-in-production')

DEBUG = os.environ.get('DEBUG', 'True') == 'True'

ALLOWED_HOSTS = os.environ.get('ALLOWED_HOSTS', 'localhost,127.0.0.1,test-cwa-class-avinesh.pythonanywhere.com').split(',')

CSRF_TRUSTED_ORIGINS = [
    f'https://{host}' for host in ALLOWED_HOSTS if host not in ('localhost', '127.0.0.1')
] + ['http://localhost', 'http://127.0.0.1']


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

    # Third party
    'django_htmx',
    'storages',

    # Project apps
    'accounts',
    'classroom',
    'quiz',
    'billing',
    'progress',

    # Subject apps
    'maths',
    'coding',
    'music',
    'science',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'cwa_classroom.middleware.MathsRoomRedirectMiddleware',    # mathsroom → /maths/ redirect
    'cwa_classroom.middleware.SubdomainURLRoutingMiddleware',  # subdomain → urlconf routing
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'django_htmx.middleware.HtmxMiddleware',
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
            ],
        },
    },
]

WSGI_APPLICATION = 'cwa_classroom.wsgi.application'


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

# DB_ENGINE env var controls the database backend.
#   - "mysql" (default) → MySQL via env vars DB_NAME, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT
#   - "sqlite"          → local SQLite file (no MySQL needed)
_DB_ENGINE = os.environ.get('DB_ENGINE', 'mysql')

if _DB_ENGINE == 'sqlite':
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        },
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.mysql',
            'NAME': os.environ.get('DB_NAME', 'cwa_classroom'),
            'USER': os.environ.get('DB_USER', 'root'),
            'PASSWORD': os.environ.get('DB_PASSWORD', ''),
            'HOST': os.environ.get('DB_HOST', '127.0.0.1'),
            'PORT': os.environ.get('DB_PORT', '3306'),
            'OPTIONS': {
                'charset': 'utf8mb4',
                'init_command': "SET sql_mode='STRICT_TRANS_TABLES'",
            },
        },

        # Legacy CWA_SCHOOL MySQL database — used only by the
        # migrate_from_cwa_school management command.
        'cwa_school_legacy': {
            'ENGINE': 'django.db.backends.mysql',
            'NAME': os.environ.get('SRC_DB_NAME', 'cwa_school'),
            'USER': os.environ.get('SRC_DB_USER', os.environ.get('DB_USER', 'root')),
            'PASSWORD': os.environ.get('SRC_DB_PASSWORD', os.environ.get('DB_PASSWORD', '')),
            'HOST': os.environ.get('SRC_DB_HOST', os.environ.get('DB_HOST', '127.0.0.1')),
            'PORT': os.environ.get('SRC_DB_PORT', os.environ.get('DB_PORT', '3306')),
            'OPTIONS': {
                'charset': 'utf8mb4',
            },
            'TEST': {
                'NAME': None,
            },
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

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]


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
# Media files — local dev vs S3 production
# ---------------------------------------------------------------------------

USE_S3 = os.environ.get('USE_S3', 'False') == 'True'

if USE_S3:
    # AWS settings
    AWS_ACCESS_KEY_ID = os.environ.get('AWS_ACCESS_KEY_ID')
    AWS_SECRET_ACCESS_KEY = os.environ.get('AWS_SECRET_ACCESS_KEY')
    AWS_STORAGE_BUCKET_NAME = os.environ.get('AWS_STORAGE_BUCKET_NAME')
    AWS_S3_REGION_NAME = os.environ.get('AWS_S3_REGION_NAME', 'ap-southeast-2')
    AWS_S3_CUSTOM_DOMAIN = f'{AWS_STORAGE_BUCKET_NAME}.s3.amazonaws.com'
    AWS_DEFAULT_ACL = 'public-read'
    AWS_S3_OBJECT_PARAMETERS = {'CacheControl': 'max-age=86400'}
    AWS_S3_FILE_OVERWRITE = False

    DEFAULT_FILE_STORAGE = 'storages.backends.s3boto3.S3Boto3Storage'
    MEDIA_URL = f'https://{AWS_S3_CUSTOM_DOMAIN}/media/'
else:
    MEDIA_URL = '/media/'
    MEDIA_ROOT = BASE_DIR / 'media'


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------

if DEBUG:
    EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
else:
    EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
    EMAIL_HOST = 'smtp.gmail.com'
    EMAIL_PORT = 587
    EMAIL_USE_TLS = True
    EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER')
    EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD')
    DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', 'noreply@wizardslearninghub.co.nz')


# ---------------------------------------------------------------------------
# Stripe
# ---------------------------------------------------------------------------

STRIPE_SECRET_KEY = os.environ.get('STRIPE_SECRET_KEY', '')
STRIPE_PUBLISHABLE_KEY = os.environ.get('STRIPE_PUBLISHABLE_KEY', '')
STRIPE_WEBHOOK_SECRET = os.environ.get('STRIPE_WEBHOOK_SECRET', '')
STRIPE_CURRENCY = os.environ.get('STRIPE_CURRENCY', 'nzd')


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
# Default primary key
# ---------------------------------------------------------------------------

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# ---------------------------------------------------------------------------
# Public landing page / Subject hub
# ---------------------------------------------------------------------------

SITE_NAME = 'Classroom'
SITE_DESCRIPTION = 'A comprehensive educational platform for students ages 6-12.'
SITE_URL = 'https://classroom.wizardslearninghub.co.nz'

# Contact form rate limiting (uses django cache)
CONTACT_RATE_LIMIT_PER_HOUR = 5

# reCAPTCHA (production only -- leave blank for dev)
RECAPTCHA_SITE_KEY = os.environ.get('RECAPTCHA_SITE_KEY', '')
RECAPTCHA_SECRET_KEY = os.environ.get('RECAPTCHA_SECRET_KEY', '')
