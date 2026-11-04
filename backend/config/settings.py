"""Django settings. Everything environment-specific is read from environment variables."""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def load_dotenv(path: Path) -> None:
    """Read KEY=VALUE lines from a local .env file without overriding real environment variables."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))


load_dotenv(BASE_DIR / ".env")


def env_list(name: str, default: str = "") -> list[str]:
    return [v.strip() for v in os.environ.get(name, default).split(",") if v.strip()]


def env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).lower() in {"1", "true", "yes"}


SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-insecure-key")
DEBUG = env_bool("DJANGO_DEBUG", False)

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
if render_host := os.environ.get("RENDER_EXTERNAL_HOSTNAME"):
    ALLOWED_HOSTS.append(render_host)

INSTALLED_APPS = [
    "corsheaders",
    "rest_framework",
    "routing",
]

MIDDLEWARE = [
    "routing.middleware.RequestLogMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.gzip.GZipMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

# The API is stateless; no database is needed.
DATABASES: dict = {}

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "truck-route-weather",
    }
}

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = False
USE_TZ = True

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": [],
    "UNAUTHENTICATED_USER": None,
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.ScopedRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {
        "places": "120/min",
        "plan": "20/min",
        "heatmap": "20/min",
    },
    "EXCEPTION_HANDLER": "routing.views.exception_handler",
}

CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS", "http://localhost:5173")
CORS_ALLOWED_ORIGIN_REGEXES = env_list("CORS_ALLOWED_ORIGIN_REGEXES")

# Security headers. TLS terminates at the hosting proxy, which forwards the original scheme.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
X_FRAME_OPTIONS = "DENY"
if not DEBUG:
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 365
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True

# Application settings
TOMTOM_API_KEY = os.environ.get("TOMTOM_API_KEY", "")
TOMTOM_COUNTRY_SET = os.environ.get("TOMTOM_COUNTRY_SET", "")  # e.g. "US,CA" to limit place search
OPEN_METEO_API_KEY = os.environ.get("OPEN_METEO_API_KEY", "")  # optional commercial key
# Open-Meteo's free tier allows 600 location lookups a minute. Without a commercial key, a plan that
# would need more than this many lookups skips 10-mile spacing. 0 means no limit.
WEATHER_LOOKUP_BUDGET = int(os.environ.get("WEATHER_LOOKUP_BUDGET", "0" if OPEN_METEO_API_KEY else "450"))
APP_VERSION = (os.environ.get("RENDER_GIT_COMMIT") or os.environ.get("APP_VERSION") or "dev")[:12]
TRUCK_TARE_LB = int(os.environ.get("TRUCK_TARE_LB", "35000"))  # empty tractor + trailer
MAX_LOAD_LB = int(os.environ.get("MAX_LOAD_LB", "80000"))
MAX_DEPARTURE_DAYS = int(os.environ.get("MAX_DEPARTURE_DAYS", "7"))

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}},
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "plain"},
        "null": {"class": "logging.NullHandler"},
    },
    "root": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")},
    # Request lines come from RequestLogMiddleware; Django's own would duplicate them.
    "loggers": {
        "django.request": {"level": "ERROR"},
        # Bots probing with forged Host headers get a 400; their stack traces are noise.
        "django.security.DisallowedHost": {"handlers": ["null"], "propagate": False},
    },
}
