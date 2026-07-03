from datetime import datetime

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from extensions import db


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    university = db.Column(db.String(120), default="University of Washington")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    preferences = db.relationship(
        "UserPreference", backref="user", uselist=False, cascade="all, delete-orphan"
    )
    memberships = db.relationship(
        "Membership", backref="user", cascade="all, delete-orphan"
    )
    officer_of = db.relationship("Club", backref="officer", foreign_keys="Club.officer_id")
    rsvps = db.relationship("RSVP", backref="user", cascade="all, delete-orphan")

    def set_password(self, raw_password):
        # pbkdf2 instead of Werkzeug's scrypt default: some Python builds
        # (e.g. macOS CLT 3.9) ship a hashlib without scrypt support.
        self.password_hash = generate_password_hash(raw_password, method="pbkdf2:sha256")

    def check_password(self, raw_password):
        return check_password_hash(self.password_hash, raw_password)

    def is_officer(self):
        return len(self.officer_of) > 0

    def is_admin(self, admin_emails):
        return self.email.lower() in admin_emails

    @property
    def joined_club_ids(self):
        return {m.club_id for m in self.memberships}

    @property
    def saved_club_ids(self):
        return {s.club_id for s in self.saved_clubs if s.kind == "saved"}

    @property
    def hidden_club_ids(self):
        return {s.club_id for s in self.saved_clubs if s.kind == "hidden"}


class Club(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), unique=True, nullable=False, index=True)
    description = db.Column(db.Text, default="")
    category = db.Column(db.String(80), index=True)

    # Officer-editable listing details
    website = db.Column(db.String(300), default="")
    instagram = db.Column(db.String(100), default="")
    contact_email = db.Column(db.String(255), default="")
    meeting_info = db.Column(db.String(200), default="")  # e.g. "Tuesdays 6pm, HUB 145"
    dues = db.Column(db.String(60), default="")            # e.g. "No dues" / "$15/quarter"
    hours_per_week = db.Column(db.String(40), default="")  # e.g. "2 hours/week"
    updated_at = db.Column(db.DateTime, nullable=True)     # last officer edit

    officer_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    claimed_at = db.Column(db.DateTime, nullable=True)

    memberships = db.relationship(
        "Membership", backref="club", cascade="all, delete-orphan"
    )
    events = db.relationship("Event", backref="club", cascade="all, delete-orphan")
    claims = db.relationship("ClubClaim", backref="club", cascade="all, delete-orphan")

    @property
    def is_claimed(self):
        return self.officer_id is not None

    @property
    def member_count(self):
        return len(self.memberships)

    @property
    def directory_number(self):
        # A stable, catalog-style ID used in the UI (e.g. "No. 0842")
        return f"{self.id:04d}"

    @property
    def avatar_letter(self):
        return (self.name or "?")[0].upper()


class Membership(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    club_id = db.Column(db.Integer, db.ForeignKey("club.id"), nullable=False)
    joined_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint("user_id", "club_id", name="uq_membership"),)


class ClubClaim(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    club_id = db.Column(db.Integer, db.ForeignKey("club.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    message = db.Column(db.Text, default="")
    status = db.Column(db.String(20), default="pending")  # pending / approved / rejected
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    decided_at = db.Column(db.DateTime, nullable=True)

    requester = db.relationship("User", foreign_keys=[user_id])


class Event(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    club_id = db.Column(db.Integer, db.ForeignKey("club.id"), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, default="")
    weekday = db.Column(db.String(20), default="Monday")
    time = db.Column(db.String(20), default="18:00")
    location = db.Column(db.String(200), default="TBD")
    image_url = db.Column(db.String(500), default="")
    capacity = db.Column(db.Integer, default=50)
    is_public = db.Column(db.Boolean, default=True)
    created_by = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    rsvps = db.relationship("RSVP", backref="event", cascade="all, delete-orphan")

    @property
    def attendee_count(self):
        return len(self.rsvps)


class RSVP(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("event.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint("user_id", "event_id", name="uq_rsvp"),)


class SavedClub(db.Model):
    """A user's bookmark on a club: kind='saved' (heart) or kind='hidden'
    (dismissed from recommendations)."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    club_id = db.Column(db.Integer, db.ForeignKey("club.id"), nullable=False)
    kind = db.Column(db.String(10), default="saved", nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    club = db.relationship("Club")
    user = db.relationship(
        "User", backref=db.backref("saved_clubs", cascade="all, delete-orphan")
    )

    __table_args__ = (db.UniqueConstraint("user_id", "club_id", "kind", name="uq_saved_club"),)


class UserPreference(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), unique=True, nullable=False)
    categories = db.Column(db.Text, default="")  # comma-separated
    major = db.Column(db.String(80), default="")
    time_commitment = db.Column(db.String(20), default="")

    def category_list(self):
        return [c for c in self.categories.split(",") if c]
