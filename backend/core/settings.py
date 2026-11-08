import os
from pathlib import Path
import dj_database_url
from dotenv import load_dotenv

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables
load_dotenv(BASE_DIR / '.env')

# Environment detection
ENVIRONMENT = os.environ.get('ENVIRONMENT', 'development').lower()
IS_PRODUCTION = ENVIRONMENT == 'production' or bool(os.environ.get('RENDER'))

# 1. DEBUG configuration: Strictly False in production
if IS_PRODUCTION:
    DEBUG = os.environ.get('DEBUG', 'False').lower() in ('true', '1')
else:
    DEBUG = os.environ.get('DEBUG', 'True').lower() in ('true', '1')

# 2. SECRET_KEY configuration: No insecure fallback in production
if IS_PRODUCTION:
    SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY')
    if not SECRET_KEY:
        raise ValueError("CRITICAL: DJANGO_SECRET_KEY environment variable is required in production.")
else:
    SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'django-insecure-dev-arthashield-hackathon-2026-key')

# 3. ALLOWED_HOSTS: Restricted to deployment domains in production
if IS_PRODUCTION:
    custom_hosts = os.environ.get('ALLOWED_HOSTS')
    if custom_hosts:
        ALLOWED_HOSTS = [h.strip() for h in custom_hosts.split(',') if h.strip()]
    else:
        ALLOWED_HOSTS = ['.onrender.com', '.vercel.app', 'localhost', '127.0.0.1']
else:
    ALLOWED_HOSTS = ['localhost', '127.0.0.1', '0.0.0.0', '*']

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    
    # Third-party apps
    'rest_framework',
    'corsheaders',
    
    # Local apps
    'api.apps.ApiConfig',
    'sanitizer.apps.SanitizerConfig',
    'analytics.apps.AnalyticsConfig',
    'advisor.apps.AdvisorConfig',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',  # Must be at the very top
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'core.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'core.wsgi.application'

# Database: Uses PostgreSQL when DATABASE_URL is set (Render/Production), otherwise SQLite locally
DATABASE_URL = os.environ.get('DATABASE_URL')
if DATABASE_URL:
    DATABASES = {
        'default': dj_database_url.config(default=DATABASE_URL, conn_max_age=600)
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# 4. CORS configuration: Strict origin whitelist in production; permissive in local development
if IS_PRODUCTION:
    CORS_ALLOW_ALL_ORIGINS = False
    allowed_origins = [
        'https://arthashield.vercel.app',
    ]
    frontend_url = os.environ.get('FRONTEND_URL')
    if frontend_url:
        allowed_origins.append(frontend_url.strip())
    custom_origins = os.environ.get('CORS_ALLOWED_ORIGINS')
    if custom_origins:
        allowed_origins.extend([o.strip() for o in custom_origins.split(',') if o.strip()])
    CORS_ALLOWED_ORIGINS = list(set(allowed_origins))
else:
    CORS_ALLOW_ALL_ORIGINS = True

CORS_ALLOW_CREDENTIALS = True

# Cookie & Session Security Protections
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = False  # Allows standard frontend CSRF reading if needed
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SAMESITE = 'Lax'
if IS_PRODUCTION:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

import sys

IS_TESTING = 'test' in sys.argv

# Django REST Framework configuration
REST_FRAMEWORK = {
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.AllowAny',
    ],
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'api.security.SecureSessionAuthentication',
    ],
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '10000/minute' if IS_TESTING else '100/minute',
        'user': '10000/minute' if IS_TESTING else '300/minute',
    },
    'DEFAULT_RENDERER_CLASSES': (
        ['rest_framework.renderers.JSONRenderer']
        if IS_PRODUCTION else
        [
            'rest_framework.renderers.JSONRenderer',
            'rest_framework.renderers.BrowsableAPIRenderer',
        ]
    )
}
