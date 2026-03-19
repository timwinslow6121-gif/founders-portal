"""
app/models.py

SQLAlchemy models for the Founders Portal.
All database operations go through these models — never raw SQL.
"""

from datetime import date
from flask_login import UserMixin
from app.extensions import db



class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    name = db.Column(db.String(255))
    picture = db.Column(db.String(512))
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    last_login = db.Column(db.DateTime)

    policies = db.relationship("Policy", back_populates="agent", lazy="dynamic")

    def __repr__(self):
        return f"<User {self.email}>"

    @property
    def initials(self):
        parts = (self.name or self.email).split()
        if len(parts) >= 2:
            return f"{parts[0][0]}{parts[-1][0]}".upper()
        return (self.name or self.email)[:2].upper()

    @property
    def display_name(self):
        return self.name or self.email.split("@")[0].title()


class Policy(db.Model):
    """
    Normalized policy record sourced from carrier BOB exports.
    One row per active policy per carrier per agent.
    Upserted on each carrier file import (keyed on carrier + member_id).
    """
    __tablename__ = "policies"

    id = db.Column(db.Integer, primary_key=True)

    # Carrier identity
    carrier = db.Column(db.String(64), nullable=False, index=True)
    member_id = db.Column(db.String(128), nullable=False, index=True)  # carrier's own ID
    mbi = db.Column(db.String(20), index=True)                          # Medicare Beneficiary ID

    # Member info
    first_name = db.Column(db.String(128))
    last_name = db.Column(db.String(128))
    full_name = db.Column(db.String(256))
    dob = db.Column(db.Date)
    phone = db.Column(db.String(32))
    address1 = db.Column(db.String(256))
    city = db.Column(db.String(128))
    state = db.Column(db.String(32))
    zip_code = db.Column(db.String(16))
    county = db.Column(db.String(128))

    # Plan info
    plan_name = db.Column(db.String(256))
    plan_type = db.Column(db.String(64))
    effective_date = db.Column(db.Date)
    term_date = db.Column(db.Date)
    renewal_date = db.Column(db.Date)
    status = db.Column(db.String(32), default="active")

    # Agent linkage
    agent_id_carrier = db.Column(db.String(64))   # agent ID as reported by carrier
    agent_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    agent = db.relationship("User", back_populates="policies")

    # Audit fields
    last_seen_date = db.Column(db.Date)            # date of most recent BOB import where record appeared
    import_batch_id = db.Column(db.Integer, db.ForeignKey("import_batches.id"))
    import_batch = db.relationship("ImportBatch", back_populates="policies")
    zoho_matched = db.Column(db.Boolean, default=None)  # None = unchecked, True = matched, False = unmatched
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())

    __table_args__ = (
        db.UniqueConstraint("carrier", "member_id", name="uq_carrier_member"),
    )

    def __repr__(self):
        return f"<Policy {self.carrier} {self.member_id} {self.full_name}>"

    @property
    def days_until_term(self):
        if not self.term_date:
            return None
        return (self.term_date - date.today()).days

    @property
    def urgency_class(self):
        """Returns badge class name based on days until term."""
        days = self.days_until_term
        if days is None:
            return "gray"
        if days < 0:
            return "gray"   # already termed — should be filtered out
        if days <= 30:
            return "red"
        if days <= 60:
            return "amber"
        if days <= 90:
            return "yellow"
        return "green"


class ImportBatch(db.Model):
    """
    Records each carrier file upload. One row per file processed.
    Links to all Policy records created or updated from that upload.
    """
    __tablename__ = "import_batches"

    id = db.Column(db.Integer, primary_key=True)
    carrier = db.Column(db.String(64), nullable=False)
    filename = db.Column(db.String(512), nullable=False)
    uploaded_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    uploaded_by = db.relationship("User")
    upload_date = db.Column(db.DateTime, server_default=db.func.now())
    record_count = db.Column(db.Integer, default=0)
    new_count = db.Column(db.Integer, default=0)
    updated_count = db.Column(db.Integer, default=0)
    error_message = db.Column(db.Text)
    status = db.Column(db.String(32), default="pending")  # pending / success / error

    policies = db.relationship("Policy", back_populates="import_batch", lazy="dynamic")

    def __repr__(self):
        return f"<ImportBatch {self.carrier} {self.upload_date} ({self.status})>"


class AuditLog(db.Model):
    """
    Immutable log of all actions taken by users in the portal.
    """
    __tablename__ = "audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    user = db.relationship("User")
    action = db.Column(db.String(128), nullable=False)
    detail = db.Column(db.Text)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    def __repr__(self):
        return f"<AuditLog {self.action} by user {self.user_id}>"


class CommissionStatement(db.Model):
    """
    Parsed commission statement uploaded by AJ.
    One row per carrier per agent per statement period.
    """
    __tablename__ = "commission_statements"

    id             = db.Column(db.Integer, primary_key=True)
    carrier        = db.Column(db.String(64), nullable=False, index=True)
    statement_date = db.Column(db.Date, nullable=False)
    period_label   = db.Column(db.String(32))                # e.g. "February 2026"

    # Agent linkage
    agent_id       = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    agent          = db.relationship("User", foreign_keys=[agent_id])

    # Commission amounts
    gross_amount   = db.Column(db.Float, default=0.0)        # sum of all line item commissions
    bonus_amount   = db.Column(db.Float, default=0.0)        # HA/HRA bonuses (separate)
    split_rate     = db.Column(db.Float, default=0.55)
    expected_amount = db.Column(db.Float, default=0.0)       # gross × split_rate
    paid_amount    = db.Column(db.Float, default=0.0)        # what AJ's summary row shows
    difference     = db.Column(db.Float, default=0.0)        # expected - paid (0 = verified)

    # Status
    status         = db.Column(db.String(32), default="pending")  # pending / verified / discrepancy

    # Raw line items stored as JSON
    line_items     = db.Column(db.Text)                      # JSON array of member rows

    # Upload tracking
    upload_date    = db.Column(db.DateTime, server_default=db.func.now())
    uploaded_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    uploaded_by    = db.relationship("User", foreign_keys=[uploaded_by_id])
    filename       = db.Column(db.String(512))

    __table_args__ = (
        db.UniqueConstraint("carrier", "agent_id", "period_label", name="uq_commission_period"),
    )

    def __repr__(self):
        return f"<CommissionStatement {self.carrier} {self.period_label} agent={self.agent_id}>"
