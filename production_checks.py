def run_launch_checks(app):
    """Return admin-facing production readiness checks."""
    config = app.config
    database_url = config.get("SQLALCHEMY_DATABASE_URI", "")
    admin_emails = {email.lower() for email in config.get("ADMIN_EMAILS", set())}
    mail_from = config.get("MAIL_FROM", "")
    mail_configured = bool(
        config.get("MAIL_SERVER")
        and mail_from
        and mail_from != "Eventully <hello@eventully.app>"
        and (not config.get("MAIL_USERNAME") or config.get("MAIL_PASSWORD"))
    )

    checks = [
        {
            "key": "database",
            "title": "Production database",
            "status": "pass" if database_url.startswith("postgresql://") else "fail",
            "detail": "Using Postgres for persistent production data."
            if database_url.startswith("postgresql://")
            else "DATABASE_URL is not pointing at Postgres. Do not launch real users on local SQLite.",
            "action": "Set DATABASE_URL to a managed Postgres connection string.",
        },
        {
            "key": "secret-key",
            "title": "Secret key",
            "status": "pass"
            if config.get("SECRET_KEY") and config.get("SECRET_KEY") != "dev-key-change-me-in-production"
            else "fail",
            "detail": "SECRET_KEY is set."
            if config.get("SECRET_KEY") and config.get("SECRET_KEY") != "dev-key-change-me-in-production"
            else "SECRET_KEY is still the development fallback.",
            "action": "Use Render's generated SECRET_KEY or another long random value.",
        },
        {
            "key": "admin",
            "title": "Admin access",
            "status": "pass" if admin_emails and admin_emails != {"demo@uw.edu"} else "fail",
            "detail": "Admin claims are restricted to configured real admin email(s)."
            if admin_emails and admin_emails != {"demo@uw.edu"}
            else "ADMIN_EMAILS is empty or still points only at demo@uw.edu.",
            "action": "Set ADMIN_EMAILS to the real account that should review club claims.",
        },
        {
            "key": "demo-account",
            "title": "Demo account disabled",
            "status": "pass" if not config.get("SEED_DEMO_ACCOUNT") else "fail",
            "detail": "The public demo account is disabled."
            if not config.get("SEED_DEMO_ACCOUNT")
            else "The public demo account can still be seeded.",
            "action": "Set SEED_DEMO_ACCOUNT=false in production.",
        },
        {
            "key": "secure-cookies",
            "title": "Secure cookies",
            "status": "pass" if config.get("SESSION_COOKIE_SECURE") else "fail",
            "detail": "Session and remember cookies require HTTPS."
            if config.get("SESSION_COOKIE_SECURE")
            else "Secure cookies are off. This is okay locally, but not for HTTPS production.",
            "action": "Set SECURE_COOKIES=true on Render.",
        },
        {
            "key": "edu-email",
            "title": "Campus email gate",
            "status": "pass" if config.get("REQUIRE_EDU_EMAIL") else "warning",
            "detail": ".edu signup restriction is enabled."
            if config.get("REQUIRE_EDU_EMAIL")
            else "Anyone can register, including non-campus emails.",
            "action": "Keep REQUIRE_EDU_EMAIL=true for the UW launch.",
        },
        {
            "key": "mail",
            "title": "Email delivery",
            "status": "pass" if mail_configured else "fail",
            "detail": "SMTP is configured for verification, reset, claim, team, and message emails."
            if mail_configured
            else "SMTP is incomplete. Verification and password reset emails will not reach inboxes.",
            "action": "Set MAIL_SERVER, MAIL_PORT, MAIL_USERNAME, MAIL_PASSWORD, MAIL_FROM, and MAIL_USE_TLS with a verified sender.",
        },
        {
            "key": "verification-required",
            "title": "Email verification enforcement",
            "status": "pass" if config.get("EMAIL_VERIFICATION_REQUIRED") and mail_configured else "warning",
            "detail": "Unverified users are blocked from officer-sensitive workflows."
            if config.get("EMAIL_VERIFICATION_REQUIRED") and mail_configured
            else "Verification is not fully enforced. Turn it on only after SMTP test email succeeds.",
            "action": "After email works, set EMAIL_VERIFICATION_REQUIRED=true.",
        },
    ]

    blockers = sum(1 for check in checks if check["status"] == "fail")
    warnings = sum(1 for check in checks if check["status"] == "warning")
    return {
        "checks": checks,
        "blockers": blockers,
        "warnings": warnings,
        "ready": blockers == 0,
    }
