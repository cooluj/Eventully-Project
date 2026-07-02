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

    # Comma-separated list of emails allowed to approve club-claim requests
    ADMIN_EMAILS = set(
        e.strip().lower()
        for e in os.environ.get("ADMIN_EMAILS", "demo@uw.edu").split(",")
        if e.strip()
    )

    # Require a .edu address to register. Set to "false" to allow any email (useful for testing).
    REQUIRE_EDU_EMAIL = os.environ.get("REQUIRE_EDU_EMAIL", "true").lower() == "true"

    CLUBS_PER_PAGE = 24
    MATCHES_PER_PAGE = 20
