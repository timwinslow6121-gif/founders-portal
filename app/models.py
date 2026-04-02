"""
app/models.py

SQLAlchemy models for the Founders Portal.
All database operations go through these models — never raw SQL.
"""

from datetime import date
from flask_login import UserMixin
from app.extensions import db


class Agency(db.Model):
    """
    Top-level tenant. Every row in every table belongs to one Agency.
    Phase 2.5 seeds one row: "Founders Insurance Agency".
    Phase 7 adds multi-agency provisioning.
    """
    __tablename__ = "agencies"

    id         = db.Column(db.Integer, primary_key=True)
    name       = db.Column(db.String(256), nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    def __repr__(self):
        return f"<Agency {self.name}>"


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    name = db.Column(db.String(255))
    picture = db.Column(db.String(512))
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    last_login = db.Column(db.DateTime)
    quo_user_id = db.Column(db.String(64))
    # Quo userId (pattern "US...") — maps webhook data.object.userId to portal User
    # Set by admin in agent settings; NULL for unmapped agents

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


class Pharmacy(db.Model):
    """
    Partner pharmacy that refers customers to Founders agents.
    Founders pays rent to the pharmacy in exchange for warm leads.
    """
    __tablename__ = "pharmacies"

    id             = db.Column(db.Integer, primary_key=True)
    name           = db.Column(db.String(256), nullable=False)
    address1       = db.Column(db.String(256))
    city           = db.Column(db.String(128))
    state          = db.Column(db.String(32))
    zip_code       = db.Column(db.String(16))
    phone          = db.Column(db.String(32))
    is_partner     = db.Column(db.Boolean, default=True, nullable=False)
    rent_amount    = db.Column(db.Float, default=0.0)
    rent_frequency = db.Column(db.String(16), default="monthly")   # monthly/quarterly/annual
    contact_name   = db.Column(db.String(256))
    contact_phone  = db.Column(db.String(32))
    contact_email  = db.Column(db.String(256))
    notes          = db.Column(db.Text)
    created_at     = db.Column(db.DateTime, server_default=db.func.now())

    customers      = db.relationship("Customer", back_populates="pharmacy", lazy="dynamic")

    def __repr__(self):
        return f"<Pharmacy {self.name}>"


class Customer(db.Model):
    """
    Master customer record, keyed on MBI (Medicare Beneficiary Identifier).
    One record per beneficiary, linked to policies across all carriers.
    Created/updated automatically on every BOB import; editable by agents.
    """
    __tablename__ = "customers"

    id                = db.Column(db.Integer, primary_key=True)

    # Primary identifier — NULL allowed for Humana-only customers until MBI is resolved
    mbi               = db.Column(db.String(20), unique=True, index=True)
    # Humana fallback — Humana masks MBI, so we store their member_id here
    humana_id         = db.Column(db.String(64), index=True)

    # Name
    first_name        = db.Column(db.String(128), nullable=False)
    last_name         = db.Column(db.String(128), nullable=False)
    full_name         = db.Column(db.String(256), index=True)      # denormalized for fast search

    # Demographics
    dob               = db.Column(db.Date, index=True)
    gender            = db.Column(db.String(16))

    # Contact — agent-editable; protected from import overwrites when manually_edited=True
    phone_primary     = db.Column(db.String(32), index=True)
    phone_secondary   = db.Column(db.String(32))
    email             = db.Column(db.String(256))
    address1          = db.Column(db.String(256))
    city              = db.Column(db.String(128))
    state             = db.Column(db.String(32))
    zip_code          = db.Column(db.String(16))
    county            = db.Column(db.String(128))

    # Raw carrier address — always updated on import, never shown as primary
    carrier_address   = db.Column(db.String(512))

    # Medicare / Medicaid
    medicaid_level    = db.Column(db.String(32))   # Full / QMB / SLMB / QI / None
    medicaid_id       = db.Column(db.String(64))

    # Pipeline
    deal_stage        = db.Column(db.String(32), default="Active")
    # Lead / SOA_Sent / Appointed / Enrolled / Active / Termed
    lead_source       = db.Column(db.String(64))
    # pharmacy_referral / self_generated / referral / transfer

    # Relationships
    primary_agent_id  = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    primary_agent     = db.relationship("User", foreign_keys=[primary_agent_id])
    pharmacy_id       = db.Column(db.Integer, db.ForeignKey("pharmacies.id"))
    pharmacy          = db.relationship("Pharmacy", back_populates="customers")

    # Import guard — True = agent-edited fields won't be overwritten by BOB imports
    manually_edited   = db.Column(db.Boolean, default=False, nullable=False)
    last_carrier_sync = db.Column(db.DateTime)

    # SMS consent — NULL = no consent; datetime = consent given at this timestamp
    sms_consent_at    = db.Column(db.DateTime)

    # Audit
    created_by_id     = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_by        = db.relationship("User", foreign_keys=[created_by_id])
    created_at        = db.Column(db.DateTime, server_default=db.func.now())
    updated_at        = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())

    notes             = db.relationship("CustomerNote", back_populates="customer",
                                        order_by="CustomerNote.created_at.desc()", lazy="dynamic")
    contacts          = db.relationship("CustomerContact", back_populates="customer", lazy="dynamic")
    aor_history       = db.relationship("CustomerAorHistory", back_populates="customer",
                                        order_by="CustomerAorHistory.effective_date.desc()", lazy="dynamic")

    def __repr__(self):
        return f"<Customer {self.full_name} MBI={self.mbi}>"

    @property
    def display_name(self):
        return self.full_name or f"{self.first_name} {self.last_name}"


class CustomerContact(db.Model):
    """
    Point of contact for a customer — often a family member or case manager.
    The POC is NOT the patient; they may be the one answering the phone.
    """
    __tablename__ = "customer_contacts"

    id           = db.Column(db.Integer, primary_key=True)
    customer_id  = db.Column(db.Integer, db.ForeignKey("customers.id", ondelete="CASCADE"),
                             nullable=False, index=True)
    customer     = db.relationship("Customer", back_populates="contacts")
    contact_name = db.Column(db.String(256), nullable=False)
    relationship = db.Column(db.String(64))   # daughter/son/spouse/nurse_case_manager/other
    phone        = db.Column(db.String(32))
    email        = db.Column(db.String(256))
    is_primary   = db.Column(db.Boolean, default=False)
    notes        = db.Column(db.Text)
    created_at   = db.Column(db.DateTime, server_default=db.func.now())

    def __repr__(self):
        return f"<CustomerContact {self.contact_name} for customer {self.customer_id}>"


class CustomerNote(db.Model):
    """
    Interaction log entry for a customer. Created manually by agents or automatically
    by webhooks from OpenPhone (calls/SMS), Calendly (appointments), and Fireflies (meetings).
    """
    __tablename__ = "customer_notes"

    id                   = db.Column(db.Integer, primary_key=True)
    customer_id          = db.Column(db.Integer, db.ForeignKey("customers.id", ondelete="CASCADE"),
                                     nullable=False, index=True)
    customer             = db.relationship("Customer", back_populates="notes")
    agent_id             = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    agent                = db.relationship("User")

    note_text            = db.Column(db.Text)
    note_type            = db.Column(db.String(32), default="general", index=True)
    # call / meeting / email / sms / general / missed_call / appointment_scheduled / meeting_summary
    # voicemail / healthsherpa_enrollment / task
    contact_method       = db.Column(db.String(32))   # phone / sms / email / in_person / video
    duration_minutes     = db.Column(db.Integer)
    source_url           = db.Column(db.String(512))  # Fireflies transcript, call recording URL

    # Integration keys — set when note is auto-created by a webhook
    openphone_call_id    = db.Column(db.String(128))
    calendly_event_id    = db.Column(db.String(128))
    fireflies_meeting_id = db.Column(db.String(128))   # superseded by source_url — keep for backward compat

    # Phase 3 integration keys — Quo (formerly OpenPhone) replaces Dialpad
    quo_call_id          = db.Column(db.String(128))
    twilio_msg_sid       = db.Column(db.String(128))
    retell_call_id       = db.Column(db.String(128))
    resolved             = db.Column(db.Boolean, default=False, nullable=False)
    # resolved: used when note_type='task' — True = task is complete

    created_at           = db.Column(db.DateTime, server_default=db.func.now(), index=True)

    def __repr__(self):
        return f"<CustomerNote {self.note_type} for customer {self.customer_id}>"


class CustomerAorHistory(db.Model):
    """
    Records each Agent of Record enrollment for a customer per carrier.
    Tracks ownership over time and enables AOR change / cannibalization detection.
    """
    __tablename__ = "customer_aor_history"

    id              = db.Column(db.Integer, primary_key=True)
    customer_id     = db.Column(db.Integer, db.ForeignKey("customers.id", ondelete="CASCADE"),
                                nullable=False, index=True)
    customer        = db.relationship("Customer", back_populates="aor_history")
    agent_id        = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    agent           = db.relationship("User")

    carrier         = db.Column(db.String(64))
    plan_name       = db.Column(db.String(256))
    effective_date  = db.Column(db.Date)
    end_date        = db.Column(db.Date)   # NULL = currently active

    source          = db.Column(db.String(32), default="carrier_import")
    # carrier_import / manual / medicarecenter_pdf
    import_batch_id = db.Column(db.Integer, db.ForeignKey("import_batches.id"))
    import_batch    = db.relationship("ImportBatch")

    created_at      = db.Column(db.DateTime, server_default=db.func.now())

    __table_args__ = (
        db.UniqueConstraint("customer_id", "carrier", "effective_date",
                            name="uq_aor_customer_carrier_date"),
    )

    def __repr__(self):
        return f"<CustomerAorHistory customer={self.customer_id} carrier={self.carrier}>"


class AgentCarrierContract(db.Model):
    """
    Tracks which carriers each agent is contracted with,
    their commission split rate, and their agent ID per carrier.
    One row per agent per carrier.
    """
    __tablename__ = "agent_carrier_contracts"

    id         = db.Column(db.Integer, primary_key=True)
    agent_id   = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    agent      = db.relationship("User", foreign_keys=[agent_id])

    carrier    = db.Column(db.String(64), nullable=False)
    is_active  = db.Column(db.Boolean, default=True, nullable=False)

    # Commission split — overrides the agency default if set
    split_rate = db.Column(db.Float, default=0.55, nullable=False)

    # Agent identifier for this carrier
    id_type    = db.Column(db.String(32), default="NPN")   # NPN / writing_number / agent_code
    id_value   = db.Column(db.String(64))                  # actual ID string

    notes      = db.Column(db.Text)

    created_at = db.Column(db.DateTime, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())

    __table_args__ = (
        db.UniqueConstraint("agent_id", "carrier", name="uq_agent_carrier"),
    )

    def __repr__(self):
        return f"<AgentCarrierContract {self.agent_id} {self.carrier} active={self.is_active}>"


class UnmatchedCall(db.Model):
    """
    Stores inbound calls/voicemails from phone numbers that could not be matched
    to a Customer record. Agents can review and resolve by linking to a customer.

    provider default is "quo" — Quo (formerly OpenPhone) is the primary VoIP provider.
    direction values: inbound / outbound
    """
    __tablename__ = "unmatched_calls"

    id               = db.Column(db.Integer, primary_key=True)
    agency_id        = db.Column(db.Integer, db.ForeignKey("agencies.id"), nullable=False, index=True)
    agency           = db.relationship("Agency", foreign_keys=[agency_id])
    agent_id         = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    agent            = db.relationship("User", foreign_keys=[agent_id])

    provider         = db.Column(db.String(32), default="quo")   # quo / twilio / retell
    call_sid         = db.Column(db.String(128))                 # provider's call/message ID
    from_number      = db.Column(db.String(32))                  # E.164, e.g. +17705551234
    to_number        = db.Column(db.String(32))                  # E.164, agency number called
    direction        = db.Column(db.String(16))                  # inbound / outbound
    duration_seconds = db.Column(db.Integer)
    occurred_at      = db.Column(db.DateTime, nullable=False)

    # Resolution tracking — agent links this record to a Customer and optionally a Note
    resolved         = db.Column(db.Boolean, default=False, nullable=False)
    resolved_at      = db.Column(db.DateTime)
    resolved_by_id   = db.Column(db.Integer, db.ForeignKey("users.id"))
    resolved_by      = db.relationship("User", foreign_keys=[resolved_by_id])
    resolved_note_id = db.Column(db.Integer, db.ForeignKey("customer_notes.id"))
    resolved_note    = db.relationship("CustomerNote", foreign_keys=[resolved_note_id])

    created_at       = db.Column(db.DateTime, server_default=db.func.now())

    def __repr__(self):
        return f"<UnmatchedCall from={self.from_number} provider={self.provider} resolved={self.resolved}>"


class SmsTemplate(db.Model):
    """
    Pre-approved SMS message templates for agent use in SC-5 SMS blast/send flows.

    status workflow: pending → approved (admin review) or rejected
    Agents may only use templates with status='approved'.
    Admin creates or approves; created_by_id tracks authorship.
    """
    __tablename__ = "sms_templates"

    id              = db.Column(db.Integer, primary_key=True)
    agency_id       = db.Column(db.Integer, db.ForeignKey("agencies.id"), nullable=False, index=True)
    agency          = db.relationship("Agency", foreign_keys=[agency_id])

    name            = db.Column(db.String(256), nullable=False)
    body            = db.Column(db.Text, nullable=False)
    status          = db.Column(db.String(32), default="pending")
    # status: pending / approved / rejected

    created_by_id   = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_by      = db.relationship("User", foreign_keys=[created_by_id])
    reviewed_by_id  = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    reviewed_by     = db.relationship("User", foreign_keys=[reviewed_by_id])
    reviewed_at     = db.Column(db.DateTime)

    created_at      = db.Column(db.DateTime, server_default=db.func.now())

    def __repr__(self):
        return f"<SmsTemplate {self.name!r} status={self.status}>"
