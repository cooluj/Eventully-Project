import hashlib
import os
import secrets

from flask import Flask, flash, g, redirect, render_template, request, url_for
from flask_compress import Compress
from flask_wtf.csrf import CSRFError
from werkzeug.middleware.proxy_fix import ProxyFix

from config import Config
from extensions import csrf, db, login_manager


def _static_versions(static_folder):
    """filename -> short content hash, computed once at boot. Versioned
    static URLs can be cached for a year and still update on deploy."""
    versions = {}
    for root, _dirs, files in os.walk(static_folder):
        for name in files:
            path = os.path.join(root, name)
            rel = os.path.relpath(path, static_folder).replace(os.sep, "/")
            with open(path, "rb") as fh:
                versions[rel] = hashlib.md5(fh.read()).hexdigest()[:10]
    return versions


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Render/Heroku terminate TLS at a proxy one hop away. Without this,
    # request.remote_addr is the proxy IP (breaking per-IP rate limits) and
    # _external=True links in emails come out http://.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)

    # Registered before Compress so it runs after it: a view that must not
    # be compressed (reflected input next to a CSRF token — the BREACH
    # setup) marks itself "identity"; Flask-Compress then skips it and this
    # drops the marker so clients never see a non-standard encoding.
    @app.after_request
    def strip_identity_marker(response):
        if response.headers.get("Content-Encoding") == "identity":
            del response.headers["Content-Encoding"]
        return response

    Compress(app)

    versions = _static_versions(app.static_folder)

    @app.template_global()
    def static_url(filename, **kwargs):
        version = versions.get(filename)
        if version:
            kwargs["v"] = version
        return url_for("static", filename=filename, **kwargs)

    @app.template_global()
    def csp_nonce():
        if "csp_nonce" not in g:
            g.csp_nonce = secrets.token_urlsafe(16)
        return g.csp_nonce

    from models import User

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    from blueprints.auth import bp as auth_bp
    from blueprints.main import bp as main_bp
    from blueprints.clubs import bp as clubs_bp
    from blueprints.events import bp as events_bp
    from blueprints.messages import bp as messages_bp
    from blueprints.officer import bp as officer_bp
    from blueprints.admin import bp as admin_bp
    from blueprints.tasks import bp as tasks_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(clubs_bp)
    app.register_blueprint(events_bp)
    app.register_blueprint(messages_bp)
    app.register_blueprint(officer_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(tasks_bp)

    @app.template_filter("days_ago")
    def days_ago(dt):
        if not dt:
            return ""
        from datetime import datetime
        days = (datetime.utcnow() - dt).days
        if days <= 0:
            return "today"
        if days == 1:
            return "yesterday"
        if days < 30:
            return f"{days} days ago"
        months = days // 30
        return f"{months} month{'s' if months > 1 else ''} ago"

    @app.template_filter("commas")
    def commas(value):
        try:
            return f"{int(value):,}"
        except (TypeError, ValueError):
            return value

    @app.template_filter("short_datetime")
    def short_datetime(dt):
        # DB timestamps are naive UTC; students read Pacific wall time.
        from utils import utc_to_campus
        if not dt:
            return ""
        text = utc_to_campus(dt).strftime("%b %d, %I:%M %p")
        return text.replace(" 0", " ").replace(", 0", ", ")

    @app.template_filter("clock_time")
    def clock_time(dt):
        from utils import utc_to_campus
        if not dt:
            return ""
        return utc_to_campus(dt).strftime("%I:%M %p").lstrip("0")

    @app.context_processor
    def inject_admin_flag():
        from flask_login import current_user
        is_admin = (
            current_user.is_authenticated
            and current_user.is_admin(app.config["ADMIN_EMAILS"])
        )
        return {"is_site_admin": is_admin}

    @app.context_processor
    def inject_demo_flag():
        return {"show_demo_login": app.config["SEED_DEMO_ACCOUNT"]}

    @app.context_processor
    def inject_nav_badges():
        """Unread counts for the nav bell and Messages link."""
        from flask_login import current_user
        if not current_user.is_authenticated:
            return {"unread_notifications": 0, "unread_threads": 0}
        from sqlalchemy import and_, func, or_
        from models import ClubMessage, Notification, ThreadRead
        unread_notifications = Notification.query.filter_by(
            user_id=current_user.id, read_at=None
        ).count()
        club_ids = current_user.joined_club_ids | current_user.managed_club_ids
        unread_threads = 0
        if club_ids:
            # One statement: newest foreign message per club, outer-joined to
            # this user's read marker, kept only where it's newer.
            newest = func.max(ClubMessage.created_at)
            unread_threads = (
                db.session.query(func.count())
                .select_from(
                    db.session.query(ClubMessage.club_id)
                    .outerjoin(ThreadRead, and_(ThreadRead.club_id == ClubMessage.club_id,
                                                ThreadRead.user_id == current_user.id))
                    .filter(ClubMessage.club_id.in_(club_ids),
                            ClubMessage.sender_id != current_user.id)
                    .group_by(ClubMessage.club_id, ThreadRead.last_read_at)
                    .having(or_(ThreadRead.last_read_at.is_(None), newest > ThreadRead.last_read_at))
                    .subquery()
                )
                .scalar()
            ) or 0
        return {
            "unread_notifications": unread_notifications,
            "unread_threads": unread_threads,
        }

    @app.errorhandler(404)
    def not_found(e):
        return render_template("404.html"), 404

    @app.errorhandler(403)
    def forbidden(e):
        return render_template("403.html"), 403

    @app.errorhandler(500)
    def server_error(e):
        return render_template("500.html"), 500

    @app.errorhandler(CSRFError)
    def csrf_error(e):
        flash("Your session expired — please try that again.", "error")
        return redirect(request.referrer or url_for("main.index"))

    @app.before_request
    def enforce_canonical_host():
        canonical = app.config["CANONICAL_HOST"]
        if not canonical or request.host.lower() == canonical:
            return None
        # /healthz stays reachable on the host the platform probes;
        # only redirect safe methods so in-flight form posts aren't dropped.
        if request.path == "/healthz" or request.method not in ("GET", "HEAD"):
            return None
        return redirect(
            f"https://{canonical}{request.full_path.rstrip('?')}", code=301
        )

    @app.after_request
    def security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()"
        )
        if response.mimetype == "text/html":
            # Scripts run only with this request's nonce; images may come
            # from anywhere (officers paste event photo URLs); everything
            # else stays same-origin. Inline style attributes are part of
            # the design system (hue tokens), hence 'unsafe-inline' there.
            nonce = g.get("csp_nonce") or csp_nonce()
            response.headers.setdefault("Content-Security-Policy", (
                "default-src 'self'; "
                f"script-src 'self' 'nonce-{nonce}'; "
                "style-src 'self' 'unsafe-inline'; "
                "img-src * data:; "
                "font-src 'self'; "
                "connect-src 'self'; "
                "object-src 'none'; base-uri 'self'; form-action 'self'; "
                "frame-ancestors 'none'; upgrade-insecure-requests"
            ))
        return response

    @app.after_request
    def cache_headers(response):
        if request.path.startswith("/static/"):
            if request.args.get("v"):
                # Content-hashed URL: safe to keep forever, a deploy changes the URL.
                response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            else:
                response.headers["Cache-Control"] = "public, max-age=3600"
        elif "Cache-Control" not in response.headers and response.mimetype == "text/html":
            # Pages are personal (nav badges, CSRF tokens): always revalidate,
            # but no-store would break the back/forward cache.
            response.headers["Cache-Control"] = "private, no-cache"
        return response

    @app.cli.command("seed-db")
    def seed_db_command():
        """Load clubs_categorized.csv into the database (skips clubs that already exist)."""
        from seed import seed_clubs
        with app.app_context():
            count = seed_clubs()
            print(f"Seeded {count} new clubs.")

    if app.config["AUTO_SEED"]:
        bootstrap_database(app)

    return app


def bootstrap_database(app):
    """Create tables and load the club directory if the database is empty.

    Runs at import time so gunicorn deploys (no shell, no __main__ block)
    come up working. Both steps are idempotent; races between workers are
    harmless because seeding skips existing rows.
    """
    if (
        app.config["SESSION_COOKIE_SECURE"]
        and app.config["SQLALCHEMY_DATABASE_URI"].startswith("sqlite")
    ):
        app.logger.warning(
            "Running in production mode on SQLite. On hosts with ephemeral disks "
            "(Render, Heroku) ALL DATA IS LOST on every deploy/restart — set "
            "DATABASE_URL to a Postgres instance before inviting real users."
        )
    with app.app_context():
        db.create_all()
        try:
            add_missing_columns(app)
        except Exception:
            app.logger.exception("Column migration failed; continuing.")
        try:
            add_missing_indexes(app)
        except Exception:
            app.logger.exception("Index migration failed; continuing.")
        from seed import seed_clubs
        try:
            seed_clubs()
        except Exception:
            app.logger.exception("Database seeding failed; continuing with what exists.")


def add_missing_columns(app):
    """Minimal forward-only migration: ALTER TABLE ADD COLUMN for any model
    column that doesn't exist yet. Handles simple additive schema changes on
    live SQLite/Postgres databases without a full migration tool.
    """
    inspector = db.inspect(db.engine)
    for table in db.metadata.sorted_tables:
        if not inspector.has_table(table.name):
            continue
        existing = {c["name"] for c in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in existing:
                continue
            ddl = f'ALTER TABLE "{table.name}" ADD COLUMN {column.name} {column.type.compile(db.engine.dialect)}'
            if column.default is not None and getattr(column.default, "arg", None) is not None \
                    and not callable(column.default.arg):
                default = column.default.arg
                default = f"'{default}'" if isinstance(default, str) else default
                ddl += f" DEFAULT {default}"
            with db.engine.begin() as conn:
                conn.execute(db.text(ddl))
            app.logger.info("Added column %s.%s", table.name, column.name)


def add_missing_indexes(app):
    """Create model-declared indexes that don't exist yet (create_all only
    builds indexes for brand-new tables, never for existing ones)."""
    inspector = db.inspect(db.engine)
    for table in db.metadata.sorted_tables:
        if not inspector.has_table(table.name):
            continue
        existing = {ix["name"] for ix in inspector.get_indexes(table.name)}
        for index in table.indexes:
            if index.name in existing:
                continue
            index.create(db.engine)
            app.logger.info("Created index %s on %s", index.name, table.name)


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    debug = os.environ.get("FLASK_DEBUG", "true").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug)
