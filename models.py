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
    email_verified_at = db.Column(db.DateTime, nullable=True)

    preferences = db.relationship(
        "UserPreference", backref="user", uselist=False, cascade="all, delete-orphan"
    )
    memberships = db.relationship(
        "Membership", backref="user", cascade="all, delete-orphan"
    )
    officer_of = db.relationship("Club", backref="officer", foreign_keys="Club.officer_id")
    club_roles = db.relationship(
        "ClubRole",
        backref="user",
        cascade="all, delete-orphan",
        foreign_keys="ClubRole.user_id",
    )
    rsvps = db.relationship("RSVP", backref="user", cascade="all, delete-orphan")

    def set_password(self, raw_password):
        # pbkdf2 instead of Werkzeug's scrypt default: some Python builds
        # (e.g. macOS CLT 3.9) ship a hashlib without scrypt support.
        self.password_hash = generate_password_hash(raw_password, method="pbkdf2:sha256")

    def check_password(self, raw_password):
        return check_password_hash(self.password_hash, raw_password)

    def is_officer(self):
        return len(self.officer_of) > 0 or len(self.club_roles) > 0

    def is_admin(self, admin_emails):
        return self.email.lower() in admin_emails

    @property
    def is_email_verified(self):
        return self.email_verified_at is not None

    @property
    def managed_club_ids(self):
        return {c.id for c in self.officer_of} | {r.club_id for r in self.club_roles}

    @property
    def managed_clubs(self):
        seen = set()
        clubs = []
        for club in list(self.officer_of) + [role.club for role in self.club_roles]:
            if club.id in seen:
                continue
            seen.add(club.id)
            clubs.append(club)
        return clubs

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
    roles = db.relationship(
        "ClubRole", backref="club", cascade="all, delete-orphan", foreign_keys="ClubRole.club_id"
    )
    messages = db.relationship(
        "ClubMessage", backref="club", cascade="all, delete-orphan", order_by="ClubMessage.created_at"
    )
    claims = db.relationship("ClubClaim", backref="club", cascade="all, delete-orphan")

    @property
    def is_claimed(self):
        return self.officer_id is not None

    def can_manage(self, user):
        if not getattr(user, "is_authenticated", False):
            return False
        return self.officer_id == user.id or self.id in user.managed_club_ids

    def role_for(self, user):
        if not getattr(user, "is_authenticated", False):
            return None
        if self.officer_id == user.id:
            return "owner"
        for role in self.roles:
            if role.user_id == user.id:
                return role.role
        return None

    @property
    def officer_users(self):
        users = []
        seen = set()
        if self.officer:
            users.append(("owner", self.officer))
            seen.add(self.officer.id)
        for role in self.roles:
            if role.user_id not in seen:
                users.append((role.role, role.user))
                seen.add(role.user_id)
        return users

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
    decision_note = db.Column(db.Text, default="")
    decided_by = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    decided_at = db.Column(db.DateTime, nullable=True)

    requester = db.relationship("User", foreign_keys=[user_id])
    reviewer = db.relationship("User", foreign_keys=[decided_by])


class ClubRole(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    club_id = db.Column(db.Integer, db.ForeignKey("club.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    role = db.Column(db.String(24), default="officer", nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    invited_by_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)

    invited_by = db.relationship("User", foreign_keys=[invited_by_id])

    __table_args__ = (db.UniqueConstraint("club_id", "user_id", name="uq_club_role"),)


class ClubMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    club_id = db.Column(db.Integer, db.ForeignKey("club.id"), nullable=False, index=True)
    sender_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    deleted_at = db.Column(db.DateTime, nullable=True)
    deleted_by_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)

    sender = db.relationship("User", foreign_keys=[sender_id])
    deleted_by = db.relationship("User", foreign_keys=[deleted_by_id])

    @property
    def is_deleted(self):
        return self.deleted_at is not None

    @property
    def is_from_officer(self):
        return self.club.officer_id == self.sender_id or self.sender_id in {
            role.user_id for role in self.club.roles
        }


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

    # attendee_count is a SQL column_property (defined at the bottom of this
    # module); these two derive from it.
    @property
    def remaining_spots(self):
        return max((self.capacity or 0) - self.attendee_count, 0)

    @property
    def capacity_percent(self):
        if not self.capacity:
            return 0
        return min(round((self.attendee_count / self.capacity) * 100), 100)



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


# SQL-side counts, loaded with the row itself — avoids N+1 lazy loads when
# rendering card grids. Defined after the classes so both sides exist.
from sqlalchemy import func, select  # noqa: E402

Club.member_count = db.column_property(
    select(func.count(Membership.id))
    .where(Membership.club_id == Club.id)
    .correlate_except(Membership)
    .scalar_subquery()
)

Event.attendee_count = db.column_property(
    select(func.count(RSVP.id))
    .where(RSVP.event_id == Event.id)
    .correlate_except(RSVP)
    .scalar_subquery()
)
