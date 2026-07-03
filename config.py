import os
from datetime import timedelta

from dotenv import load_dotenv

basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, ".env"))


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-key-change-me-in-production")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", f"sqlite:///{os.path.join(basedir, 'eventully.db')}"
    )
    # Some hosts (e.g. Render/Heroku) hand out a postgres:// URL; SQLAlchemy needs postgresql://
    if SQLALCHEMY_DATABASE_URI.startswith("postgres://"):
        SQLALCHEMY_DATABASE_URI = SQLALCHEMY_DATABASE_URI.replace(
            "postgres://", "postgresql://", 1
        )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    PERMANENT_SESSION_LIFETIME = timedelta(days=30)

    # Cookie hardening. SECURE_COOKIES must be "true" in production (HTTPS) —
    # render.yaml sets it; leaving it off locally keeps http://127.0.0.1 working.
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("SECURE_COOKIES", "false").lower() == "true"
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_SECURE = SESSION_COOKIE_SECURE
    REMEMBER_COOKIE_DURATION = timedelta(days=30)

    # CSRF tokens shouldn't expire mid-session (they're still tied to the session)
    WTF_CSRF_TIME_LIMIT = None

    # Create tables + load the club directory automatically on boot, so a fresh
    # deploy (e.g. Render free tier, no shell access) comes up working.
    AUTO_SEED = os.environ.get("AUTO_SEED", "true").lower() == "true"

    # Seed the demo@uw.edu account. Turn OFF in production — its password is public.
    SEED_DEMO_ACCOUNT = os.environ.get("SEED_DEMO_ACCOUNT", "true").lower() == "true"

    # Comma-separated list of emails allowed to approve club-claim requests
    ADMIN_EMAILS = set(
        e.strip().lower()
        for e in os.environ.get("ADMIN_EMAILS", "demo@uw.edu").split(",")
        if e.strip()
    )

    # Require a .edu address to register. Set to "false" to allow any email (useful for testing).
    REQUIRE_EDU_EMAIL = os.environ.get("REQUIRE_EDU_EMAIL", "true").lower() == "true"
    EMAIL_VERIFICATION_REQUIRED = os.environ.get("EMAIL_VERIFICATION_REQUIRED", "false").lower() == "true"

    MAIL_SERVER = os.environ.get("MAIL_SERVER") or os.environ.get("SMTP_HOST", "")
    MAIL_PORT = int(os.environ.get("MAIL_PORT") or os.environ.get("SMTP_PORT", "587"))
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME") or os.environ.get("SMTP_USERNAME", "")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD") or os.environ.get("SMTP_PASSWORD", "")
    MAIL_USE_TLS = os.environ.get("MAIL_USE_TLS", "true").lower() == "true"
    MAIL_FROM = os.environ.get("MAIL_FROM") or os.environ.get("SMTP_FROM", "Eventully <hello@eventully.app>")

    # When set (e.g. "eventully.app"), GET requests on any other host 301 to
    # this one, so the .onrender.com URL doesn't live a parallel life.
    CANONICAL_HOST = os.environ.get("CANONICAL_HOST", "").strip().lower()

    CLUBS_PER_PAGE = 24
    MATCHES_PER_PAGE = 20
