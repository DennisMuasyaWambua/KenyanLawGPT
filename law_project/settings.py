import os
from pathlib import Path

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Load .env before any os.environ reads below so secrets/config (e.g.
# GMI_CLOUD_API_KEY) resolve at settings-import time. Real environment variables
# (platform-provided in production) take precedence — load_dotenv won't override
# them — and a missing python-dotenv or .env file is a safe no-op.
try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / '.env')
except ImportError:
    pass

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'django-insecure-1234567890')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.environ.get('DJANGO_DEBUG', 'true').lower() == 'true'

ALLOWED_HOSTS = os.environ.get('DJANGO_ALLOWED_HOSTS', '*').split(',')

# We terminate TLS at nginx and proxy to gunicorn over HTTP; trust the
# forwarded scheme so request.is_secure() and CSRF checks behave correctly.
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# Trust the real https origins for CSRF (derived from ALLOWED_HOSTS).
CSRF_TRUSTED_ORIGINS = [
    f'https://{h.strip()}'
    for h in ALLOWED_HOSTS
    if h.strip() not in ('*', 'localhost', '127.0.0.1')
]

# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'rest_framework.authtoken',
    'corsheaders',
    'law_app',
    'gateway',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'law_project.urls'

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

WSGI_APPLICATION = 'law_project.wsgi.application'

# Database
# https://docs.djangoproject.com/en/5.2/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

# Password validation
# https://docs.djangoproject.com/en/5.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Internationalization
# https://docs.djangoproject.com/en/5.2/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True

# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.2/howto/static-files/

STATIC_URL = 'static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
STATICFILES_DIRS = [
    os.path.join(BASE_DIR, 'static'),
]

# Default primary key field type
# https://docs.djangoproject.com/en/5.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# CORS settings
CORS_ALLOW_ALL_ORIGINS = True

# DRF settings
REST_FRAMEWORK = {
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.AllowAny',
    ],
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.TokenAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
    ],
}

# Environment variables
VECTOR_DB_PATH = os.environ.get('VECTOR_DB_PATH', './vector_db')
CONCURRENT_REQUESTS = int(os.environ.get('CONCURRENT_REQUESTS', '4'))
REQUEST_DELAY = float(os.environ.get('REQUEST_DELAY', '1.0'))

# --- Gateway (multi-tenant SaaS) configuration --------------------------------
# Public origin of this backend, used to build local presigned upload URLs.
PUBLIC_BASE_URL = os.environ.get('PUBLIC_BASE_URL', '')

# Where uploaded objects live on the local (dev) storage backend.
MEDIA_ROOT = os.environ.get('MEDIA_ROOT', os.path.join(BASE_DIR, 'media'))

# Google Sign-In: the OAuth 2.0 Web client ID. When set, Google credentials
# must be issued for this audience; leave blank in development.
GOOGLE_OAUTH_CLIENT_ID = os.environ.get('GOOGLE_OAUTH_CLIENT_ID', '')

# Object storage. Set AWS_STORAGE_BUCKET_NAME (+ credentials) to switch the
# presign backend from local disk to S3-compatible storage (S3, R2, MinIO...).
AWS_STORAGE_BUCKET_NAME = os.environ.get('AWS_STORAGE_BUCKET_NAME', '')
AWS_S3_ENDPOINT_URL = os.environ.get('AWS_S3_ENDPOINT_URL', '')
AWS_S3_REGION_NAME = os.environ.get('AWS_S3_REGION_NAME', '')
AWS_ACCESS_KEY_ID = os.environ.get('AWS_ACCESS_KEY_ID', '')
AWS_SECRET_ACCESS_KEY = os.environ.get('AWS_SECRET_ACCESS_KEY', '')

# IE multilingual speech-to-text. IE_API_KEY is the bearer JWT — provide it via
# the environment / server .env, never commit it.
IE_TRANSCRIPTION_URL = os.environ.get('IE_TRANSCRIPTION_URL', '')
IE_API_KEY = os.environ.get('IE_API_KEY', '')
IE_TRANSCRIPTION_TIMEOUT = int(os.environ.get('IE_TRANSCRIPTION_TIMEOUT', '300'))

# --- GMI Cloud generation (OpenAI-compatible) --------------------------------
# Text generation via GMI Cloud-hosted models.
# GMICloudProvider(model=...) picks a model at instantiation; the model strings
# are exposed as separate env vars so each role is easy to reference.
# The API key lives ONLY in the server environment — never commit it.
#
# NOTE: pick models that are CURRENTLY served on GMI. The original defaults
# (DeepSeek-R1-Distill-Llama-70B, Qwen3-235B-...-FP8) were retired and returned
# HTTP 429 "No available endpoints", which silently forced every request onto
# the slow local Ollama fallback. Prefer fast, non-reasoning models: reasoning
# (R1/distill/reasoner) models emit long <think> scratchpads that are stripped
# and discarded, so you pay their full latency for tokens the user never sees.
GMI_CLOUD_BASE_URL = os.environ.get('GMI_CLOUD_BASE_URL', 'https://api.gmi-serving.com/v1')
GMI_CLOUD_API_KEY = os.environ.get('GMI_CLOUD_API_KEY', '')
# The ONLY genuinely free model on GMI (prompt=$0, completion=$0), so it runs on
# a zero-balance account. It is a reasoning model: it "thinks" for a few seconds
# (a separate `reasoning` field, not <think> tags) before the answer, so give it
# a generous output budget below or `content` comes back null (all tokens spent
# thinking). Still dramatically faster than local Ollama.
GMI_CLOUD_FREE_MODEL = os.environ.get(
    'GMI_CLOUD_FREE_MODEL', 'nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-BF16')
# Near-free PAID upgrades (non-reasoning, instant streaming) if you fund the
# account and want no think-gap: DeepSeek-V4-Flash ~$0.14/$0.28 per 1M,
# gpt-oss-120b ~$0.05/$0.25 per 1M. Referenced for spend pricing only.
GMI_CLOUD_DEEPSEEK_MODEL = os.environ.get('GMI_CLOUD_DEEPSEEK_MODEL', 'deepseek-ai/DeepSeek-V4-Flash-0731')
GMI_CLOUD_QWEN_MODEL = os.environ.get('GMI_CLOUD_QWEN_MODEL', 'Qwen/Qwen3.7-Max')
# Role-based aliases used by the app. Default both to the free model; override
# per role via env once the account is funded.
GMI_CLOUD_DRAFT_MODEL = os.environ.get('GMI_CLOUD_DRAFT_MODEL', GMI_CLOUD_FREE_MODEL)
GMI_CLOUD_RESEARCH_MODEL = os.environ.get('GMI_CLOUD_RESEARCH_MODEL', GMI_CLOUD_FREE_MODEL)
# Primary model for the live assistant / research path (falls back to Ollama).
GMI_CLOUD_MODEL = os.environ.get('GMI_CLOUD_MODEL', GMI_CLOUD_RESEARCH_MODEL)
GMI_CLOUD_TIMEOUT = int(os.environ.get('GMI_CLOUD_TIMEOUT', '120'))

# Data-sensitivity gate: real client/case-document prompts are refused unless
# this is explicitly enabled. Synthetic / public-corpus prompts always flow.
GMI_CLOUD_ALLOW_REAL_DATA = os.environ.get('GMI_CLOUD_ALLOW_REAL_DATA', 'false').lower() == 'true'

# Cost controls. The daily USD cap fails closed (-> Ollama fallback); the
# per-request output cap bounds worst-case single-call cost.
GMI_CLOUD_DAILY_USD_CAP = float(os.environ.get('GMI_CLOUD_DAILY_USD_CAP', '10'))
# Generous by default: the free reasoning model spends part of this budget on its
# (free) chain-of-thought, so a small cap truncates the actual answer to null.
GMI_CLOUD_MAX_OUTPUT_TOKENS = int(os.environ.get('GMI_CLOUD_MAX_OUTPUT_TOKENS', '4096'))

# Per-model pricing (USD per 1M tokens) for spend accounting. The DeepSeek
# distill endpoint is free by default; set Qwen3 to GMI's real published rates.
GMI_CLOUD_QWEN_PRICE_INPUT_PER_1M = float(os.environ.get('GMI_CLOUD_QWEN_PRICE_INPUT_PER_1M', '0'))
GMI_CLOUD_QWEN_PRICE_OUTPUT_PER_1M = float(os.environ.get('GMI_CLOUD_QWEN_PRICE_OUTPUT_PER_1M', '0'))
GMI_CLOUD_DEEPSEEK_PRICE_INPUT_PER_1M = float(os.environ.get('GMI_CLOUD_DEEPSEEK_PRICE_INPUT_PER_1M', '0'))
GMI_CLOUD_DEEPSEEK_PRICE_OUTPUT_PER_1M = float(os.environ.get('GMI_CLOUD_DEEPSEEK_PRICE_OUTPUT_PER_1M', '0'))
