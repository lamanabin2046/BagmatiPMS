"""
Settings for the Palika Project Management SaaS.

Multi-tenant (django-tenants): every palika gets its own PostgreSQL schema,
created automatically when the palika is added in the SaaS manager.
All secrets come from the .env file (see .env.example).
"""
from pathlib import Path
import os

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env_bool(name, default=False):
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def env_list(name, default=""):
    return [x.strip() for x in os.environ.get(name, default).split(",") if x.strip()]


# ==================================================
# SECURITY
# ==================================================
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    raise RuntimeError("DJANGO_SECRET_KEY is not set. Copy .env.example to .env and fill it in.")

DEBUG = env_bool("DJANGO_DEBUG", False)

# The SaaS manager runs on BASE_DOMAIN; each palika on <subdomain>.BASE_DOMAIN.
# Locally: BASE_DOMAIN=localhost -> manager at localhost:8000, palika at bagmati.localhost:8000
BASE_DOMAIN = os.environ.get("BASE_DOMAIN", "localhost")
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", f"{BASE_DOMAIN},.{BASE_DOMAIN},127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS", "")
CSRF_FAILURE_VIEW = "accounts.views.csrf_failure"   # 403 को सट्टा: फेरि प्रयास गर्न भन्ने (दुई पटक थिच्दा / पुरानो पेज)


# ==================================================
# APPLICATIONS (django-tenants)
# ==================================================
# Apps in the public schema (SaaS manager, palika list, domains, SaaS staff logins).
SHARED_APPS = [
    "django_tenants",
    "tenants",

    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.admin",
    "django.contrib.staticfiles",

    "accounts",  # users exist in both: SaaS staff (public) and palika staff (each palika)
    "nepali_datetime_field",
    "django_nepali",
]

# Apps whose tables are created inside every palika's own schema.
TENANT_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.admin",

    "accounts",
    "projects",
    "usercommittee",
    "biddings",
    "quatation",
    "letters",
]

INSTALLED_APPS = list(SHARED_APPS) + [a for a in TENANT_APPS if a not in SHARED_APPS]

TENANT_MODEL = "tenants.Palika"
TENANT_DOMAIN_MODEL = "tenants.Domain"
PUBLIC_SCHEMA_NAME = "public"


# ==================================================
# MIDDLEWARE
# ==================================================
MIDDLEWARE = [
    "django_tenants.middleware.main.TenantMainMiddleware",  # must be first: picks the palika from the host
    "tenants.middleware.InactivePalikaMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",  # /static/ (production मा पनि; cPanel/Passenger)
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "tenants.middleware.PalikaLoginRequiredMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "usercommittee.middleware.ReturnToNextMiddleware",
    "projects.fiscal.OldFiscalYearLockMiddleware",   # अघिल्लो आ.व. का योजनामा काम रोक्ने
    "accounts.mywork.MyWorkInvalidateMiddleware",   # फारम सुरक्षित भएपछि "मेरो काम" ताजा
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]


# ==================================================
# URLS & WSGI
# ==================================================
ROOT_URLCONF = "ProjectManagement.urls"            # palika sites
PUBLIC_SCHEMA_URLCONF = "ProjectManagement.urls_public"  # SaaS manager (BASE_DOMAIN)
WSGI_APPLICATION = "ProjectManagement.wsgi.application"


# ==================================================
# TEMPLATES
# ==================================================
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "tenants.context_processors.palika",
                "tenants.context_processors.me",
            ],
        },
    },
]


# ==================================================
# DATABASE (PostgreSQL, one schema per palika)
# ==================================================
DATABASES = {
    "default": {
        "ENGINE": "django_tenants.postgresql_backend",
        "NAME": os.environ.get("DB_NAME", "bpm"),
        "USER": os.environ.get("DB_USER", "bpm"),
        "PASSWORD": os.environ.get("DB_PASSWORD", ""),
        "HOST": os.environ.get("DB_HOST", "127.0.0.1"),
        "PORT": os.environ.get("DB_PORT", "5432"),
    }
}
DATABASE_ROUTERS = ("django_tenants.routers.TenantSyncRouter",)


# ==================================================
# PASSWORD VALIDATION
# ==================================================
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


# ==================================================
# INTERNATIONALIZATION
# ==================================================
LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kathmandu"
USE_I18N = True
USE_TZ = True


# ==================================================
# STATIC & MEDIA
# ==================================================
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles_collected"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
# Each palika's uploads go to media/<schema_name>/... so palikas never see each other's files.
MULTITENANT_RELATIVE_MEDIA_ROOT = "%s"
STORAGES = {
    "default": {"BACKEND": "django_tenants.files.storage.TenantFileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}


# ==================================================
# USERS
# ==================================================
AUTH_USER_MODEL = "accounts.CustomUser"
LOGIN_URL = "login"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# ==================================================
# राष्ट्रिय परिचयपत्र (NID) — उपभोक्ता समिति सदस्य खोज
# ==================================================
# खाली: यही पालिकाका पुराना सदस्यमा मात्र खोजिन्छ।  demo: डेमो data (server बिना)।
# डेमो server: NID_API_URL=http://127.0.0.1:8765/api/person/{nid}/  (manage.py nid_demo_server)
NID_API_URL = os.environ.get("NID_API_URL", "")
NID_API_KEY = os.environ.get("NID_API_KEY", "")
NID_API_TIMEOUT = int(os.environ.get("NID_API_TIMEOUT", "8"))


# ==================================================
# PRODUCTION (DJANGO_DEBUG=False) — cPanel / Passenger
# ==================================================
if not DEBUG:
    SESSION_COOKIE_SECURE = env_bool("SECURE_COOKIES", True)
    CSRF_COOKIE_SECURE = env_bool("SECURE_COOKIES", True)
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", False)
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = "same-origin"

# त्रुटिहरू logs/django.log मा (cPanel मा हेर्न सजिलो)
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"}},
    "handlers": {
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": LOG_DIR / "django.log",
            "maxBytes": 5 * 1024 * 1024,
            "backupCount": 5,
            "formatter": "plain",
            "level": "WARNING",
        },
        "console": {"class": "logging.StreamHandler", "level": "INFO"},
    },
    "loggers": {
        "django": {"handlers": ["file", "console"], "level": "INFO"},
        "django.request": {"handlers": ["file"], "level": "ERROR", "propagate": False},
    },
}
