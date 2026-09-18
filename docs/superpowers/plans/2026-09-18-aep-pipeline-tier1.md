# AEP Pipeline — Tier 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a seasonal AEP work queue that tells each agent who needs them right now, how close they are to finishing, and everything about one person on one screen — reading the portal's existing customers/policies/plans and writing a small amount of workflow state back.

**Architecture:** One new Flask blueprint (`pipeline_bp`) over one new migration (`046`). Priority and queue membership are computed in **SQL views**, never stored on the customer row, so they are correct the instant a rule changes. The Jinja shell renders empty; `pipeline.js` fetches JSON and repaints single rows — the same pattern the commission Fidelity view already uses. No new customer table: every new table FKs to `customers.id` and carries `agency_id`.

**Tech Stack:** Flask 3.0, Flask-SQLAlchemy, Flask-Migrate/Alembic, PostgreSQL 16, Jinja2, vanilla JS. No frameworks.

**Spec:** `docs/mockups/CRM Mock-ups/AEP_PIPELINE_SPEC.md` (v7, amended 2026-09-18). Read it alongside this plan — the ⚠ blocks record corrections verified against production and are binding.

## Global Constraints

- **Migration `046`.** Heads `044` (users.npn) and `045` (agencies.npn) shipped 2026-09-18. `down_revision = "045"`.
- **Every query is agency-scoped.** `WHERE agency_id = current_user.agency_id`. A missing `agency_id` is a cross-tenant data leak.
- **Every queue and every count excludes `customers.deceased_date IS NOT NULL`** (migration 043).
- **Table is `customers`** (plural). Owning agent FK is **`customers.primary_agent_id`**. There is **no `customers.current_plan_id`**.
- **Never read `Policy.plan_type`** to decide a lane — it holds carrier vocabulary (2,133 UHC policies typed `MA`, ~15 genuinely MA-only). Use `app/plan_lane.py` against the linked `Plan`.
- **Never write a customer field directly.** Go through `app/customer_provenance.py`.
- **Plain language in all UI copy.** Banned: "SOA", "disposition", "pipeline stage", "lead score", "tier" as a user-facing word. Take copy verbatim from the prototype.
- **Body text 17px, nothing below 13px, tap targets ≥46px, real `<button>`/`<a>`/`<input>`.** Phone numbers are `tel:` links everywhere.
- **Founders Green `#65BB84` is 2.34:1 on white — never for text.** Text that must read as "good" uses `#166B37` (6.3:1). Blue `#266EA5` is 5.45:1 and safe.
- Tests: `/usr/bin/python3 -m pytest tests/ -q`. Baseline is **898 passing**.
- Commit after every task. Never commit `.env`.

---

### Task 1: Migration 046 + pipeline models

**Files:**
- Create: `migrations/versions/046_aep_pipeline.py`
- Modify: `app/models.py` (append after the `Provider` block)
- Test: `tests/test_pipeline_models.py`

**Interfaces:**
- Consumes: `Customer`, `User`, `Agency`, `Plan` from `app.models`.
- Produces: `PipelineState`, `Touch`, `Appointment`, `Application`, `ScopeForm`, `AuthorizedContact`, `PlanRating`, `SarRule`, `PipelineConfig` — all importable from `app.models`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pipeline_models.py
"""Pipeline model shape — migration 046."""
import datetime as dt


def test_pipeline_state_defaults_and_scoping(db_session, app, agency, customer):
    from app.models import PipelineState
    from app.extensions import db
    with app.app_context():
        ps = PipelineState(customer_id=customer.id, agency_id=agency.id)
        db.session.add(ps)
        db.session.commit()
        db.session.refresh(ps)
        assert ps.stage == "contact"
        assert ps.track == "renewal"
        assert ps.outcome is None
        assert ps.attempts == 0
        assert ps.stage_since is not None


def test_touch_is_append_only_with_unique_external_id(db_session, app, agency, customer, agent_user):
    from app.models import Touch
    from app.extensions import db
    import sqlalchemy.exc
    with app.app_context():
        t = Touch(customer_id=customer.id, agency_id=agency.id, agent_id=agent_user.id,
                  level="reached", channel="call", direction="in",
                  occurred_at=dt.datetime(2026, 10, 20, 9, 0), external_id="quo-abc")
        db.session.add(t)
        db.session.commit()
        dupe = Touch(customer_id=customer.id, agency_id=agency.id, agent_id=agent_user.id,
                     level="reached", channel="call", direction="in",
                     occurred_at=dt.datetime(2026, 10, 20, 9, 1), external_id="quo-abc")
        db.session.add(dupe)
        try:
            db.session.commit()
            assert False, "duplicate external_id must be rejected"
        except sqlalchemy.exc.IntegrityError:
            db.session.rollback()


def test_sar_rule_and_plan_rating(db_session, app, agency):
    from app.models import SarRule, PlanRating, Plan
    from app.extensions import db
    with app.app_context():
        p = Plan(agency_id=agency.id, carrier="Humana", plan_name="Giveback",
                 year=2027, plan_type="mapd", cms_plan_id="H5525-035")
        db.session.add(p)
        db.session.commit()
        db.session.add(SarRule(agency_id=agency.id, plan_id=p.id, county="Cabarrus", state="NC"))
        db.session.add(PlanRating(agency_id=agency.id, plan_id=p.id, rating=1))
        db.session.commit()
        assert SarRule.query.filter_by(plan_id=p.id).count() == 1
        assert PlanRating.query.filter_by(plan_id=p.id).one().rating == 1


def test_pipeline_config_is_single_row_per_agency(db_session, app, agency):
    from app.models import PipelineConfig
    from app.extensions import db
    with app.app_context():
        cfg = PipelineConfig(agency_id=agency.id)
        db.session.add(cfg)
        db.session.commit()
        db.session.refresh(cfg)
        assert cfg.sep_days == 30
        assert cfg.stall_contact_days == 5
        assert cfg.stall_deciding_days == 3
        assert cfg.stall_submitted_days == 10
        assert cfg.rules_status == "draft"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/usr/bin/python3 -m pytest tests/test_pipeline_models.py -q`
Expected: FAIL with `ImportError: cannot import name 'PipelineState' from 'app.models'`

- [ ] **Step 3: Add the models**

Append to `app/models.py`:

```python
# ---------------------------------------------------------------------------
# AEP pipeline (migration 046)
#
# A seasonal work queue over the existing customer book. Nothing here owns
# customer identity -- every table FKs to customers.id and carries agency_id.
# ---------------------------------------------------------------------------

class PipelineState(db.Model):
    """One row per customer. The workflow state the pipeline owns."""
    __tablename__ = "pipeline_state"

    id          = db.Column(db.Integer, primary_key=True)
    agency_id   = db.Column(db.Integer, db.ForeignKey("agencies.id"), nullable=False, index=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id"), nullable=False,
                            unique=True, index=True)

    # renewal = already on our book; lead = new prospect. The portal has no
    # lead record type (deal_stage is 'Active' on all 5,495 rows), so the
    # distinction lives here rather than overloading Customer.deal_stage.
    track       = db.Column(db.String(16), nullable=False, default="renewal")

    # contact | scheduled | deciding | submitted | done
    stage       = db.Column(db.String(16), nullable=False, default="contact")
    # enrolled | kept | lost -- required when stage='done'
    outcome     = db.Column(db.String(16))
    stage_since = db.Column(db.DateTime, nullable=False, server_default=db.func.now())

    attempts     = db.Column(db.Integer, nullable=False, default=0)
    first_try_at = db.Column(db.DateTime)

    intake_status = db.Column(db.String(24))
    waiting_what  = db.Column(db.String(256))
    waiting_due   = db.Column(db.Date, index=True)

    sep_end    = db.Column(db.Date, index=True)
    sep_reason = db.Column(db.String(128))

    shp_flag         = db.Column(db.Boolean, nullable=False, default=False)
    shp_confirmed_at = db.Column(db.DateTime)

    tier_override      = db.Column(db.Integer)
    tier_override_note = db.Column(db.Text)
    tier_override_by   = db.Column(db.Integer, db.ForeignKey("users.id"))
    tier_override_at   = db.Column(db.DateTime)

    created_at = db.Column(db.DateTime, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())

    customer = db.relationship("Customer", foreign_keys=[customer_id])

    __table_args__ = (db.Index("ix_pipeline_state_stage_since", "stage", "stage_since"),)


class Touch(db.Model):
    """Append-only contact log. Never updated, never deleted."""
    __tablename__ = "touch"

    id          = db.Column(db.Integer, primary_key=True)
    agency_id   = db.Column(db.Integer, db.ForeignKey("agencies.id"), nullable=False, index=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id"), nullable=False, index=True)
    agent_id    = db.Column(db.Integer, db.ForeignKey("users.id"))

    # sent = they may not know you exist | tried = no answer | reached = two-way
    level     = db.Column(db.String(8), nullable=False)
    channel   = db.Column(db.String(24), nullable=False)
    direction = db.Column(db.String(8))
    occurred_at = db.Column(db.DateTime, nullable=False, index=True)
    detail      = db.Column(db.Text)
    source      = db.Column(db.String(16), nullable=False, default="manual")
    # Quo delivers the same event more than once; this is the idempotency key.
    external_id = db.Column(db.String(128), unique=True)
    duration_s  = db.Column(db.Integer)
    outcome_recorded_at = db.Column(db.DateTime)

    __table_args__ = (db.Index("ix_touch_customer_occurred", "customer_id", "occurred_at"),)


class Appointment(db.Model):
    __tablename__ = "appointment"

    id          = db.Column(db.Integer, primary_key=True)
    agency_id   = db.Column(db.Integer, db.ForeignKey("agencies.id"), nullable=False, index=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id"), nullable=False, index=True)
    agent_id    = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    starts_at   = db.Column(db.DateTime, nullable=False)
    mode        = db.Column(db.String(24))
    source      = db.Column(db.String(24))
    external_id = db.Column(db.String(128))
    outcome_recorded_at = db.Column(db.DateTime)

    __table_args__ = (db.Index("ix_appointment_agent_starts", "agent_id", "starts_at"),)


class Application(db.Model):
    __tablename__ = "application"

    id          = db.Column(db.Integer, primary_key=True)
    agency_id   = db.Column(db.Integer, db.ForeignKey("agencies.id"), nullable=False, index=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id"), nullable=False, index=True)
    agent_id    = db.Column(db.Integer, db.ForeignKey("users.id"))
    plan_id     = db.Column(db.Integer, db.ForeignKey("plans.id"))
    submitted_at = db.Column(db.DateTime)
    via          = db.Column(db.String(32))
    confirmed_at = db.Column(db.DateTime)
    problem      = db.Column(db.String(128))
    problem_at   = db.Column(db.DateTime)
    resolved_at  = db.Column(db.DateTime)


class ScopeForm(db.Model):
    """Scope of appointment. The 48-hour wait ended 2026-10-01 (Tim), but the
    form must still exist before any plan-specific discussion."""
    __tablename__ = "scope_form"

    id          = db.Column(db.Integer, primary_key=True)
    agency_id   = db.Column(db.Integer, db.ForeignKey("agencies.id"), nullable=False, index=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id"), nullable=False, index=True)
    captured_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())
    method      = db.Column(db.String(24))
    products    = db.Column(db.Text)          # JSON list
    captured_by = db.Column(db.Integer, db.ForeignKey("users.id"))


class AuthorizedContact(db.Model):
    """The daughter who handles her mother's Medicare -- and who may be a
    client herself, hence linked_customer_id."""
    __tablename__ = "authorized_contact"

    id          = db.Column(db.Integer, primary_key=True)
    agency_id   = db.Column(db.Integer, db.ForeignKey("agencies.id"), nullable=False, index=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id"), nullable=False, index=True)
    name         = db.Column(db.String(256), nullable=False)
    relationship_= db.Column("relationship", db.String(64))
    phone        = db.Column(db.String(32), index=True)
    may_discuss_coverage = db.Column(db.Boolean, nullable=False, default=False)
    linked_customer_id   = db.Column(db.Integer, db.ForeignKey("customers.id"))


class PlanRating(db.Model):
    """Timbo's read of how much a plan changed. NULL until rated -- an unrated
    plan is Tier 2 so nobody is skipped."""
    __tablename__ = "plan_rating"

    id        = db.Column(db.Integer, primary_key=True)
    agency_id = db.Column(db.Integer, db.ForeignKey("agencies.id"), nullable=False, index=True)
    plan_id   = db.Column(db.Integer, db.ForeignKey("plans.id"), nullable=False, index=True)
    rating    = db.Column(db.Integer)          # 1 major | 2 some | 3 little | NULL unrated
    note      = db.Column(db.Text)
    updated_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())

    __table_args__ = (db.UniqueConstraint("agency_id", "plan_id", name="uq_plan_rating"),)


class SarRule(db.Model):
    """Service area reduction: this plan is not offered in this county."""
    __tablename__ = "sar_rule"

    id        = db.Column(db.Integer, primary_key=True)
    agency_id = db.Column(db.Integer, db.ForeignKey("agencies.id"), nullable=False, index=True)
    plan_id   = db.Column(db.Integer, db.ForeignKey("plans.id"), nullable=False, index=True)
    county    = db.Column(db.String(128), nullable=False)
    state     = db.Column(db.String(8), default="NC")
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    __table_args__ = (db.UniqueConstraint("agency_id", "plan_id", "county", name="uq_sar_rule"),)


class PipelineConfig(db.Model):
    """One row per agency. The knobs Timbo turns."""
    __tablename__ = "pipeline_config"

    id        = db.Column(db.Integer, primary_key=True)
    agency_id = db.Column(db.Integer, db.ForeignKey("agencies.id"), nullable=False,
                          unique=True, index=True)
    season_start = db.Column(db.Date)
    season_end   = db.Column(db.Date)
    shp_enabled  = db.Column(db.Boolean, nullable=False, default=True)
    shp_start    = db.Column(db.Date)
    shp_end      = db.Column(db.Date)
    sep_days             = db.Column(db.Integer, nullable=False, default=30)
    stall_contact_days   = db.Column(db.Integer, nullable=False, default=5)
    stall_deciding_days  = db.Column(db.Integer, nullable=False, default=3)
    stall_submitted_days = db.Column(db.Integer, nullable=False, default=10)
    rules_status = db.Column(db.String(8), nullable=False, default="draft")
    updated_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())
```

Fix the typo before running: `db.String(8)` contains a full-width digit. It must read `db.String(8)`.

- [ ] **Step 4: Write the migration**

Create `migrations/versions/046_aep_pipeline.py`:

```python
"""AEP pipeline tables

Revision ID: 046
Revises: 045
"""
from alembic import op
import sqlalchemy as sa

revision = "046"
down_revision = "045"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "pipeline_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agency_id", sa.Integer(), sa.ForeignKey("agencies.id"), nullable=False),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("track", sa.String(16), nullable=False, server_default="renewal"),
        sa.Column("stage", sa.String(16), nullable=False, server_default="contact"),
        sa.Column("outcome", sa.String(16)),
        sa.Column("stage_since", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("first_try_at", sa.DateTime()),
        sa.Column("intake_status", sa.String(24)),
        sa.Column("waiting_what", sa.String(256)),
        sa.Column("waiting_due", sa.Date()),
        sa.Column("sep_end", sa.Date()),
        sa.Column("sep_reason", sa.String(128)),
        sa.Column("shp_flag", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("shp_confirmed_at", sa.DateTime()),
        sa.Column("tier_override", sa.Integer()),
        sa.Column("tier_override_note", sa.Text()),
        sa.Column("tier_override_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("tier_override_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("customer_id", name="uq_pipeline_state_customer"),
    )
    op.create_index("ix_pipeline_state_agency_id", "pipeline_state", ["agency_id"])
    op.create_index("ix_pipeline_state_customer_id", "pipeline_state", ["customer_id"])
    op.create_index("ix_pipeline_state_stage_since", "pipeline_state", ["stage", "stage_since"])
    op.create_index("ix_pipeline_state_waiting_due", "pipeline_state", ["waiting_due"])
    op.create_index("ix_pipeline_state_sep_end", "pipeline_state", ["sep_end"])

    op.create_table(
        "touch",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agency_id", sa.Integer(), sa.ForeignKey("agencies.id"), nullable=False),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("agent_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("level", sa.String(8), nullable=False),
        sa.Column("channel", sa.String(24), nullable=False),
        sa.Column("direction", sa.String(8)),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column("detail", sa.Text()),
        sa.Column("source", sa.String(16), nullable=False, server_default="manual"),
        sa.Column("external_id", sa.String(128)),
        sa.Column("duration_s", sa.Integer()),
        sa.Column("outcome_recorded_at", sa.DateTime()),
        sa.UniqueConstraint("external_id", name="uq_touch_external_id"),
    )
    op.create_index("ix_touch_agency_id", "touch", ["agency_id"])
    op.create_index("ix_touch_customer_id", "touch", ["customer_id"])
    op.create_index("ix_touch_occurred_at", "touch", ["occurred_at"])
    op.create_index("ix_touch_customer_occurred", "touch", ["customer_id", "occurred_at"])

    op.create_table(
        "appointment",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agency_id", sa.Integer(), sa.ForeignKey("agencies.id"), nullable=False),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("agent_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("starts_at", sa.DateTime(), nullable=False),
        sa.Column("mode", sa.String(24)),
        sa.Column("source", sa.String(24)),
        sa.Column("external_id", sa.String(128)),
        sa.Column("outcome_recorded_at", sa.DateTime()),
    )
    op.create_index("ix_appointment_agency_id", "appointment", ["agency_id"])
    op.create_index("ix_appointment_customer_id", "appointment", ["customer_id"])
    op.create_index("ix_appointment_agent_starts", "appointment", ["agent_id", "starts_at"])

    op.create_table(
        "application",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agency_id", sa.Integer(), sa.ForeignKey("agencies.id"), nullable=False),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("agent_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("plan_id", sa.Integer(), sa.ForeignKey("plans.id")),
        sa.Column("submitted_at", sa.DateTime()),
        sa.Column("via", sa.String(32)),
        sa.Column("confirmed_at", sa.DateTime()),
        sa.Column("problem", sa.String(128)),
        sa.Column("problem_at", sa.DateTime()),
        sa.Column("resolved_at", sa.DateTime()),
    )
    op.create_index("ix_application_agency_id", "application", ["agency_id"])
    op.create_index("ix_application_customer_id", "application", ["customer_id"])

    op.create_table(
        "scope_form",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agency_id", sa.Integer(), sa.ForeignKey("agencies.id"), nullable=False),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("captured_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("method", sa.String(24)),
        sa.Column("products", sa.Text()),
        sa.Column("captured_by", sa.Integer(), sa.ForeignKey("users.id")),
    )
    op.create_index("ix_scope_form_agency_id", "scope_form", ["agency_id"])
    op.create_index("ix_scope_form_customer_id", "scope_form", ["customer_id"])

    op.create_table(
        "authorized_contact",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agency_id", sa.Integer(), sa.ForeignKey("agencies.id"), nullable=False),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("relationship", sa.String(64)),
        sa.Column("phone", sa.String(32)),
        sa.Column("may_discuss_coverage", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("linked_customer_id", sa.Integer(), sa.ForeignKey("customers.id")),
    )
    op.create_index("ix_authorized_contact_agency_id", "authorized_contact", ["agency_id"])
    op.create_index("ix_authorized_contact_customer_id", "authorized_contact", ["customer_id"])
    op.create_index("ix_authorized_contact_phone", "authorized_contact", ["phone"])

    op.create_table(
        "plan_rating",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agency_id", sa.Integer(), sa.ForeignKey("agencies.id"), nullable=False),
        sa.Column("plan_id", sa.Integer(), sa.ForeignKey("plans.id"), nullable=False),
        sa.Column("rating", sa.Integer()),
        sa.Column("note", sa.Text()),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("agency_id", "plan_id", name="uq_plan_rating"),
    )
    op.create_index("ix_plan_rating_agency_id", "plan_rating", ["agency_id"])
    op.create_index("ix_plan_rating_plan_id", "plan_rating", ["plan_id"])

    op.create_table(
        "sar_rule",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agency_id", sa.Integer(), sa.ForeignKey("agencies.id"), nullable=False),
        sa.Column("plan_id", sa.Integer(), sa.ForeignKey("plans.id"), nullable=False),
        sa.Column("county", sa.String(128), nullable=False),
        sa.Column("state", sa.String(8), server_default="NC"),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("agency_id", "plan_id", "county", name="uq_sar_rule"),
    )
    op.create_index("ix_sar_rule_agency_id", "sar_rule", ["agency_id"])
    op.create_index("ix_sar_rule_plan_id", "sar_rule", ["plan_id"])

    op.create_table(
        "pipeline_config",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agency_id", sa.Integer(), sa.ForeignKey("agencies.id"), nullable=False),
        sa.Column("season_start", sa.Date()),
        sa.Column("season_end", sa.Date()),
        sa.Column("shp_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("shp_start", sa.Date()),
        sa.Column("shp_end", sa.Date()),
        sa.Column("sep_days", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("stall_contact_days", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("stall_deciding_days", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("stall_submitted_days", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("rules_status", sa.String(8), nullable=False, server_default="draft"),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("agency_id", name="uq_pipeline_config_agency"),
    )


def downgrade():
    for t in ("pipeline_config", "sar_rule", "plan_rating", "authorized_contact",
              "scope_form", "application", "appointment", "touch", "pipeline_state"):
        op.drop_table(t)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `/usr/bin/python3 -m pytest tests/test_pipeline_models.py -q`
Expected: 4 passed

- [ ] **Step 6: Run the whole suite**

Run: `/usr/bin/python3 -m pytest tests/ -q`
Expected: 902 passed (898 baseline + 4)

- [ ] **Step 7: Commit**

```bash
git add app/models.py migrations/versions/046_aep_pipeline.py tests/test_pipeline_models.py
git commit -m "feat(pipeline): migration 046 + AEP pipeline models"
```

---

### Task 2: `current_plan` resolution

**Files:**
- Create: `app/pipeline/__init__.py` (empty)
- Create: `app/pipeline/plans.py`
- Test: `tests/test_pipeline_current_plan.py`

**Interfaces:**
- Consumes: `app.plan_lane.plan_lane`, `Policy`, `Plan`, `Customer` from `app.models`.
- Produces: `current_plan_for(customer_id, agency_id) -> dict | None` with keys `plan_id`, `policy_id`, `county`, `lane`, `ambiguous`.

**Why this task exists:** there is no `customers.current_plan_id`. 27 production customers hold two active policies; 15 of them are medigap+pdp and would be triaged on the wrong plan by a naive "newest effective date" rule.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pipeline_current_plan.py
"""Resolving 'their current plan' -- there is no customers.current_plan_id."""
import datetime as dt


def _plan(db, agency, cms, ptype, name):
    from app.models import Plan
    p = Plan(agency_id=agency.id, carrier="Test", plan_name=name, year=2026,
             plan_type=ptype, cms_plan_id=cms)
    db.session.add(p)
    db.session.commit()
    return p


def _policy(db, agency, customer, plan, eff, county="Cabarrus", status="active"):
    from app.models import Policy
    po = Policy(agency_id=agency.id, customer_id=customer.id, carrier="Test",
                member_id=f"M{plan.id}-{eff.year}", plan_id=plan.id, status=status,
                effective_date=eff, county=county)
    db.session.add(po)
    db.session.commit()
    return po


def test_single_active_policy_resolves(db_session, app, agency, customer):
    from app.extensions import db
    from app.pipeline.plans import current_plan_for
    with app.app_context():
        p = _plan(db, agency, "H1234-001", "mapd", "Gold")
        _policy(db, agency, customer, p, dt.date(2026, 1, 1))
        got = current_plan_for(customer.id, agency.id)
        assert got["plan_id"] == p.id
        assert got["lane"] == "primary_medical"
        assert got["ambiguous"] is False


def test_medigap_plus_pdp_picks_the_pdp_not_the_newest(db_session, app, agency, customer):
    """The real production case: 15 customers hold medigap+pdp. AEP triage is
    about the Part C/D plan, so the PDP must win even when the Medigap policy
    has the later effective date."""
    from app.extensions import db
    from app.pipeline.plans import current_plan_for
    with app.app_context():
        pdp = _plan(db, agency, "S5884-187", "pdp", "Value Rx")
        mg  = _plan(db, agency, "MEDIGAP-N", "medigap", "Plan N")
        _policy(db, agency, customer, pdp, dt.date(2026, 1, 1))
        _policy(db, agency, customer, mg,  dt.date(2026, 6, 1))   # newer
        got = current_plan_for(customer.id, agency.id)
        assert got["plan_id"] == pdp.id, "PDP must win over a newer Medigap"
        assert got["lane"] == "primary_medical"


def test_two_primary_medical_picks_newest_and_flags_ambiguous(db_session, app, agency, customer):
    from app.extensions import db
    from app.pipeline.plans import current_plan_for
    with app.app_context():
        a = _plan(db, agency, "H1111-001", "mapd", "A")
        b = _plan(db, agency, "H2222-001", "mapd", "B")
        _policy(db, agency, customer, a, dt.date(2026, 1, 1))
        _policy(db, agency, customer, b, dt.date(2026, 7, 1))
        got = current_plan_for(customer.id, agency.id)
        assert got["plan_id"] == b.id
        assert got["ambiguous"] is True


def test_county_falls_back_to_policy_when_customer_blank(db_session, app, agency, customer):
    from app.extensions import db
    from app.pipeline.plans import current_plan_for
    with app.app_context():
        customer.county = None
        db.session.commit()
        p = _plan(db, agency, "H1234-001", "mapd", "Gold")
        _policy(db, agency, customer, p, dt.date(2026, 1, 1), county="Rowan")
        assert current_plan_for(customer.id, agency.id)["county"] == "Rowan"


def test_termed_policy_is_not_current(db_session, app, agency, customer):
    from app.extensions import db
    from app.pipeline.plans import current_plan_for
    with app.app_context():
        p = _plan(db, agency, "H1234-001", "mapd", "Gold")
        _policy(db, agency, customer, p, dt.date(2026, 1, 1), status="termed")
        assert current_plan_for(customer.id, agency.id) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/usr/bin/python3 -m pytest tests/test_pipeline_current_plan.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.pipeline'`

- [ ] **Step 3: Implement**

Create `app/pipeline/__init__.py` as an empty file. Create `app/pipeline/plans.py`:

```python
"""
Resolving a customer's CURRENT plan.

There is no customers.current_plan_id -- the portal reaches a plan through
policies. Measured on production (agency 1): 5,435 customers hold >= 1 active
policy, 5,405 of those are linked to a plan, and 27 hold TWO active policies.

Those 27 are why this is not a one-line join. 15 of them are medigap+pdp: AEP
triage is about the Part C / Part D plan, so the PDP must win even when the
Medigap policy is newer. app/plan_lane.py already classifies lanes and is the
existing seam -- do not reimplement it.

NEVER branch on Policy.plan_type: it holds carrier vocabulary (2,133 active UHC
policies typed 'MA', ~15 genuinely MA-only). Read the lane from the linked Plan.
"""
from app.extensions import db
from app.models import Policy, Plan, Customer
from app.plan_lane import plan_lane

_LANE_RANK = {"primary_medical": 0, "medigap": 1, "ancillary": 2, "other": 3}


def current_plan_for(customer_id, agency_id):
    """The plan this customer should be triaged on, or None.

    Returns {plan_id, policy_id, county, lane, ambiguous} where `ambiguous` is
    True when two policies share the winning lane -- the caller may surface that
    for review rather than trusting the pick silently.
    """
    rows = (
        db.session.query(Policy, Plan)
        .join(Plan, Plan.id == Policy.plan_id)
        .filter(
            Policy.customer_id == customer_id,
            Policy.agency_id == agency_id,
            Policy.status == "active",
            Policy.plan_id.isnot(None),
        )
        .all()
    )
    if not rows:
        return None

    def sort_key(pair):
        policy, plan = pair
        lane = plan_lane(plan.plan_type)
        return (
            _LANE_RANK.get(lane, 9),
            -(policy.effective_date.toordinal() if policy.effective_date else 0),
            -policy.id,
        )

    rows.sort(key=sort_key)
    policy, plan = rows[0]
    lane = plan_lane(plan.plan_type)

    ambiguous = sum(1 for p, pl in rows if plan_lane(pl.plan_type) == lane) > 1

    customer = db.session.get(Customer, customer_id)
    county = (customer.county or "").strip() or (policy.county or "").strip() or None

    return {
        "plan_id": plan.id,
        "policy_id": policy.id,
        "county": county,
        "lane": lane,
        "ambiguous": ambiguous,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `/usr/bin/python3 -m pytest tests/test_pipeline_current_plan.py -q`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add app/pipeline/ tests/test_pipeline_current_plan.py
git commit -m "feat(pipeline): resolve current plan via policies, primary-medical wins"
```

---

### Task 3: Tier rules

**Files:**
- Create: `app/pipeline/triage.py`
- Test: `tests/test_pipeline_triage.py`

**Interfaces:**
- Consumes: `current_plan_for` from Task 2; `PipelineState`, `PlanRating`, `SarRule`, `PipelineConfig`.
- Produces: `tier_for(customer, state, cfg, today=None) -> Tier` — a `NamedTuple` with fields `tier:int`, `rank:int`, `reason_code:str`, `plan_id:int|None`, `county:str|None`, `days_left:int|None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pipeline_triage.py
"""Tier rules, in the spec's evaluation order (SPEC 5.2)."""
import datetime as dt
import pytest

TODAY = dt.date(2026, 10, 20)


@pytest.fixture
def cfg(db_session, app, agency):
    from app.models import PipelineConfig
    from app.extensions import db
    with app.app_context():
        c = PipelineConfig(agency_id=agency.id, sep_days=30,
                           shp_enabled=True,
                           shp_start=dt.date(2026, 10, 12),
                           shp_end=dt.date(2026, 10, 30))
        db.session.add(c)
        db.session.commit()
        return c


def _state(db, agency, customer, **kw):
    from app.models import PipelineState
    ps = PipelineState(agency_id=agency.id, customer_id=customer.id, **kw)
    db.session.add(ps)
    db.session.commit()
    return ps


def test_manual_override_beats_every_rule(db_session, app, agency, customer, cfg):
    from app.extensions import db
    from app.pipeline.triage import tier_for
    with app.app_context():
        ps = _state(db, agency, customer, shp_flag=True, tier_override=3,
                    tier_override_note="he called already")
        got = tier_for(customer, ps, cfg, today=TODAY)
        assert got.tier == 3
        assert got.reason_code == "override"


def test_shp_pending_is_tier_1_with_days_left(db_session, app, agency, customer, cfg):
    from app.extensions import db
    from app.pipeline.triage import tier_for
    with app.app_context():
        ps = _state(db, agency, customer, shp_flag=True)
        got = tier_for(customer, ps, cfg, today=TODAY)
        assert got.tier == 1
        assert got.reason_code == "shp_pending"
        assert got.days_left == 10


def test_shp_confirmed_drops_out_of_tier_1(db_session, app, agency, customer, cfg):
    from app.extensions import db
    from app.pipeline.triage import tier_for
    with app.app_context():
        ps = _state(db, agency, customer, shp_flag=True,
                    shp_confirmed_at=dt.datetime(2026, 10, 15))
        got = tier_for(customer, ps, cfg, today=TODAY)
        assert got.tier == 2
        assert got.reason_code == "unrated"


def test_unrated_plan_is_tier_2_so_nobody_is_skipped(db_session, app, agency, customer, cfg):
    from app.extensions import db
    from app.pipeline.triage import tier_for
    with app.app_context():
        ps = _state(db, agency, customer)
        got = tier_for(customer, ps, cfg, today=TODAY)
        assert got.tier == 2
        assert got.reason_code == "unrated"


def test_lead_urgency_comes_from_the_date_not_the_category(db_session, app, agency, customer, cfg):
    from app.extensions import db
    from app.pipeline.triage import tier_for
    with app.app_context():
        ps = _state(db, agency, customer, track="lead",
                    sep_end=dt.date(2026, 11, 5), sep_reason="Employer coverage ends")
        got = tier_for(customer, ps, cfg, today=TODAY)
        assert got.tier == 1
        assert got.reason_code == "sep_urgent"
        assert got.days_left == 16


def test_lead_with_no_date_is_tier_2_and_says_so(db_session, app, agency, customer, cfg):
    from app.extensions import db
    from app.pipeline.triage import tier_for
    with app.app_context():
        ps = _state(db, agency, customer, track="lead")
        got = tier_for(customer, ps, cfg, today=TODAY)
        assert got.tier == 2
        assert got.reason_code == "no_deadline"


def test_lead_far_out_is_tier_2_until_sep_days_widens(db_session, app, agency, customer, cfg):
    """SPEC acceptance check 5: raising sep_days raises the Tier 1 count."""
    from app.extensions import db
    from app.pipeline.triage import tier_for
    with app.app_context():
        ps = _state(db, agency, customer, track="lead", sep_end=dt.date(2026, 12, 1))
        assert tier_for(customer, ps, cfg, today=TODAY).tier == 2
        cfg.sep_days = 60
        db.session.commit()
        assert tier_for(customer, ps, cfg, today=TODAY).tier == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/usr/bin/python3 -m pytest tests/test_pipeline_triage.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.pipeline.triage'`

- [ ] **Step 3: Implement**

Create `app/pipeline/triage.py`:

```python
"""
Tier rules (SPEC 5.2), in evaluation order.

Tiers, not a 0-100 score: every tier must be explainable in one sentence to the
agent looking at it.

This module returns INGREDIENTS, never a sentence. reason_code is an enum the
template maps to plain language; plan_id / county / days_left let it interpolate
"H5525-035 is not offered in Cabarrus County for 2027" without SQL building
strings.
"""
import datetime as dt
from typing import NamedTuple, Optional

from app.models import PlanRating, SarRule
from app.pipeline.plans import current_plan_for


class Tier(NamedTuple):
    tier: int
    rank: int
    reason_code: str
    plan_id: Optional[int] = None
    county: Optional[str] = None
    days_left: Optional[int] = None


def _days(a, b):
    return (b - a).days


def tier_for(customer, state, cfg, today=None):
    today = today or dt.date.today()

    # 10. Manual override beats every rule above it.
    if state.tier_override:
        return Tier(state.tier_override, 0, "override")

    if state.track == "lead":
        return _lead_tier(state, cfg, today)
    return _renewal_tier(customer, state, cfg, today)


def _renewal_tier(customer, state, cfg, today):
    cp = current_plan_for(customer.id, customer.agency_id)
    plan_id = cp["plan_id"] if cp else None
    county = cp["county"] if cp else None

    # 1. Plan is ending in their county.
    if plan_id and county:
        sar = SarRule.query.filter_by(
            agency_id=customer.agency_id, plan_id=plan_id, county=county
        ).first()
        if sar:
            return Tier(1, 1, "sar", plan_id, county)

    # 2. NC State Health Plan retiree who has not confirmed their opt-out call.
    if cfg.shp_enabled and state.shp_flag and state.shp_confirmed_at is None:
        left = _days(today, cfg.shp_end) if cfg.shp_end else None
        if left is not None and left < 0:
            return Tier(1, 0, "shp_closed", plan_id, county, left)
        return Tier(1, 0 if (left or 99) <= 7 else 2, "shp_pending", plan_id, county, left)

    # 3-6. Plan rating.
    rating = None
    if plan_id:
        row = PlanRating.query.filter_by(
            agency_id=customer.agency_id, plan_id=plan_id
        ).first()
        rating = row.rating if row else None

    if rating == 1:
        return Tier(1, 3, "rating_major", plan_id, county)
    if rating == 2:
        return Tier(2, 4, "rating_some", plan_id, county)
    if rating == 3:
        return Tier(3, 6, "rating_little", plan_id, county)
    return Tier(2, 5, "unrated", plan_id, county)


def _lead_tier(state, cfg, today):
    # 7-9. Urgency comes from a date, not a category.
    if not state.sep_end:
        return Tier(2, 5, "no_deadline")
    left = _days(today, state.sep_end)
    if left < 0:
        return Tier(2, 4, "sep_closed", days_left=left)
    if left <= cfg.sep_days:
        return Tier(1, 1 if left <= 7 else 2, "sep_urgent", days_left=left)
    return Tier(2, 4, "sep_future", days_left=left)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `/usr/bin/python3 -m pytest tests/test_pipeline_triage.py -q`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add app/pipeline/triage.py tests/test_pipeline_triage.py
git commit -m "feat(pipeline): tier rules returning reason ingredients, not sentences"
```

---

### Task 4: Queues — one customer, one queue

**Files:**
- Create: `app/pipeline/queues.py`
- Test: `tests/test_pipeline_queues.py`

**Interfaces:**
- Consumes: `tier_for` (Task 3), `PipelineState`, `Appointment`, `PipelineConfig`.
- Produces: `QUEUES` (ordered list of `(id, title, urgent)`), `stalled_reason(state, cfg, today) -> str|None`, `queue_for(customer, state, cfg, today) -> str|None`, `queue_counts(agency_id, agent_id, cfg, today) -> dict`.

**Why this task exists:** the prototype's queues overlap. Verified by running its own logic over its own 526-customer book: Charles Starnes and Kenneth Peeler land in both `shp` and `today`. `callfirst` and `noreply` exclude `shp`; `today`, `catchup`, `waiting` and `undecided` do not. First-match-wins makes exclusivity structural instead of an O(n²) invariant maintained by hand.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pipeline_queues.py
"""Queue assignment. Exclusivity is structural, not per-predicate (SPEC 6.1)."""
import datetime as dt
import pytest

TODAY = dt.date(2026, 10, 20)


@pytest.fixture
def cfg(db_session, app, agency):
    from app.models import PipelineConfig
    from app.extensions import db
    with app.app_context():
        c = PipelineConfig(agency_id=agency.id, sep_days=30, shp_enabled=True,
                           shp_start=dt.date(2026, 10, 12), shp_end=dt.date(2026, 10, 30),
                           stall_contact_days=5, stall_deciding_days=3,
                           stall_submitted_days=10)
        db.session.add(c)
        db.session.commit()
        return c


def _state(db, agency, customer, **kw):
    from app.models import PipelineState
    ps = PipelineState(agency_id=agency.id, customer_id=customer.id, **kw)
    db.session.add(ps)
    db.session.commit()
    return ps


def test_state_retiree_with_appointment_today_lands_in_shp_only(db_session, app, agency, customer, cfg):
    """The exact prototype bug: Charles Starnes was in BOTH shp and today."""
    from app.extensions import db
    from app.models import Appointment
    from app.pipeline.queues import queue_for
    with app.app_context():
        ps = _state(db, agency, customer, shp_flag=True, stage="scheduled")
        db.session.add(Appointment(agency_id=agency.id, customer_id=customer.id,
                                   starts_at=dt.datetime(2026, 10, 20, 14, 0)))
        db.session.commit()
        assert queue_for(customer, ps, cfg, TODAY) == "shp"


def test_every_customer_lands_in_at_most_one_queue(db_session, app, agency, customer, cfg):
    """queue_for returns a single id by construction -- this asserts the shape."""
    from app.extensions import db
    from app.pipeline.queues import queue_for, QUEUES
    with app.app_context():
        ps = _state(db, agency, customer, shp_flag=True, stage="contact", attempts=0)
        q = queue_for(customer, ps, cfg, TODAY)
        assert q in {qid for qid, _, _ in QUEUES}


def test_stalled_contact_needs_two_attempts_and_five_days(db_session, app, agency, customer, cfg):
    from app.extensions import db
    from app.pipeline.queues import stalled_reason
    with app.app_context():
        ps = _state(db, agency, customer, stage="contact", attempts=2,
                    first_try_at=dt.datetime(2026, 10, 10))
        assert stalled_reason(ps, cfg, TODAY) is not None
        ps.attempts = 1
        db.session.commit()
        assert stalled_reason(ps, cfg, TODAY) is None


def test_callfirst_requires_tier_1_and_no_attempts(db_session, app, agency, customer, cfg):
    from app.extensions import db
    from app.pipeline.queues import queue_for
    with app.app_context():
        ps = _state(db, agency, customer, stage="contact", attempts=0, tier_override=1)
        assert queue_for(customer, ps, cfg, TODAY) == "callfirst"
        ps.tier_override = 3
        db.session.commit()
        assert queue_for(customer, ps, cfg, TODAY) is None


def test_deceased_customer_is_in_no_queue(db_session, app, agency, customer, cfg):
    from app.extensions import db
    from app.pipeline.queues import queue_for
    with app.app_context():
        customer.deceased_date = dt.date(2026, 10, 1)
        ps = _state(db, agency, customer, stage="contact", attempts=0, tier_override=1)
        db.session.commit()
        assert queue_for(customer, ps, cfg, TODAY) is None


def test_done_customer_is_in_no_queue(db_session, app, agency, customer, cfg):
    from app.extensions import db
    from app.pipeline.queues import queue_for
    with app.app_context():
        ps = _state(db, agency, customer, stage="done", outcome="enrolled")
        assert queue_for(customer, ps, cfg, TODAY) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/usr/bin/python3 -m pytest tests/test_pipeline_queues.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.pipeline.queues'`

- [ ] **Step 3: Implement**

Create `app/pipeline/queues.py`:

```python
"""
Work queues (SPEC 6.1).

A customer appears in AT MOST ONE queue. The prototype tried to achieve that
with per-predicate exclusions and failed: running its own logic over its own
526-customer book puts 2 customers in both `shp` and `today`, because
callfirst/noreply exclude shp and today/catchup/waiting/undecided do not.

Here the order of QUEUES IS the priority order and the first match wins, so
exclusivity is a property of the structure. Each predicate states only its own
condition.
"""
import datetime as dt

from app.models import Appointment
from app.pipeline.triage import tier_for

# (id, title, urgent) -- order is priority order. Titles are the prototype's
# wording verbatim; do not "improve" them into CRM jargon.
QUEUES = [
    ("shp",       "State retirees to call",        True),
    ("catchup",   "Write down what happened",      True),
    ("today",     "Appointments today",            False),
    ("waiting",   "Things you are waiting on",     True),
    ("callfirst", "People to call first",          True),
    ("undecided", "Thinking it over",              True),
    ("noreply",   "People who have not called back", False),
]


def stalled_reason(state, cfg, today):
    """How long someone has sat in a stage. Stalled is a property, not a stage."""
    since = state.stage_since.date() if state.stage_since else today
    days = (today - since).days

    if state.stage == "contact":
        if state.attempts >= 2 and state.first_try_at:
            waited = (today - state.first_try_at.date()).days
            if waited >= cfg.stall_contact_days:
                return f"No reply in {waited} days"
        return None
    if state.stage == "scheduled":
        appt = (Appointment.query
                .filter_by(customer_id=state.customer_id)
                .order_by(Appointment.starts_at.desc()).first())
        if appt and appt.starts_at.date() < today and appt.outcome_recorded_at is None:
            return "Outcome not logged"
        return None
    if state.stage == "deciding":
        return f"Undecided {days} days" if days >= cfg.stall_deciding_days else None
    if state.stage == "submitted":
        return f"Unconfirmed {days} days" if days >= cfg.stall_submitted_days else None
    return None


def _has_appointment_today(state, today):
    appt = (Appointment.query
            .filter_by(customer_id=state.customer_id)
            .order_by(Appointment.starts_at.desc()).first())
    return bool(appt and appt.starts_at.date() == today)


def queue_for(customer, state, cfg, today=None):
    """The ONE queue this customer belongs in, or None.

    First match wins. Adding a queue means inserting it at the right position,
    not editing every other predicate.
    """
    today = today or dt.date.today()

    # Never surface someone who is finished or deceased.
    if customer.deceased_date is not None:
        return None
    if state.stage == "done":
        return None

    stalled = stalled_reason(state, cfg, today)

    if cfg.shp_enabled and state.shp_flag and state.shp_confirmed_at is None:
        return "shp"
    if state.stage == "scheduled" and stalled:
        return "catchup"
    if state.stage == "scheduled" and _has_appointment_today(state, today):
        return "today"
    if state.waiting_due and state.waiting_due <= today:
        return "waiting"
    if state.stage == "contact" and state.attempts == 0:
        if tier_for(customer, state, cfg, today).tier == 1:
            return "callfirst"
        return None
    if state.stage == "deciding" and stalled and not state.waiting_due:
        return "undecided"
    if state.stage == "contact" and stalled:
        return "noreply"
    return None


def queue_counts(agency_id, agent_id, cfg, today=None):
    """{queue_id: count} for one agent's book. Sums to 'people with any work'."""
    from app.models import Customer, PipelineState

    today = today or dt.date.today()
    rows = (PipelineState.query
            .join(Customer, Customer.id == PipelineState.customer_id)
            .filter(Customer.agency_id == agency_id,
                    Customer.primary_agent_id == agent_id,
                    Customer.deceased_date.is_(None))
            .all())
    counts = {qid: 0 for qid, _, _ in QUEUES}
    for state in rows:
        q = queue_for(state.customer, state, cfg, today)
        if q:
            counts[q] += 1
    return counts
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `/usr/bin/python3 -m pytest tests/test_pipeline_queues.py -q`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add app/pipeline/queues.py tests/test_pipeline_queues.py
git commit -m "feat(pipeline): first-match-wins queue assignment, exclusivity by construction"
```

---

### Task 5: Backfill script

**Files:**
- Create: `scripts/backfill_pipeline_state.py`
- Test: `tests/test_pipeline_backfill.py`

**Interfaces:**
- Consumes: `PipelineState`, `Customer`.
- Produces: `run(apply=False, agency_id=1) -> dict` with keys `created`, `skipped_existing`, `skipped_deceased`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pipeline_backfill.py
"""Backfill: one PipelineState per living customer, idempotent."""
import datetime as dt


def test_backfill_creates_one_state_per_living_customer(db_session, app, agency, customer):
    from scripts.backfill_pipeline_state import run
    from app.models import PipelineState
    with app.app_context():
        res = run(apply=True, agency_id=agency.id)
        assert res["created"] == 1
        ps = PipelineState.query.filter_by(customer_id=customer.id).one()
        assert ps.stage == "contact"
        assert ps.track == "renewal"


def test_backfill_is_idempotent(db_session, app, agency, customer):
    from scripts.backfill_pipeline_state import run
    with app.app_context():
        run(apply=True, agency_id=agency.id)
        second = run(apply=True, agency_id=agency.id)
        assert second["created"] == 0
        assert second["skipped_existing"] == 1


def test_backfill_skips_deceased(db_session, app, agency, customer):
    from scripts.backfill_pipeline_state import run
    from app.extensions import db
    with app.app_context():
        customer.deceased_date = dt.date(2026, 9, 1)
        db.session.commit()
        res = run(apply=True, agency_id=agency.id)
        assert res["created"] == 0
        assert res["skipped_deceased"] == 1


def test_dry_run_writes_nothing(db_session, app, agency, customer):
    from scripts.backfill_pipeline_state import run
    from app.models import PipelineState
    with app.app_context():
        res = run(apply=False, agency_id=agency.id)
        assert res["created"] == 1
        assert PipelineState.query.count() == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/usr/bin/python3 -m pytest tests/test_pipeline_backfill.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.backfill_pipeline_state'`

- [ ] **Step 3: Implement**

Create `scripts/backfill_pipeline_state.py`:

```python
"""
Give every living customer a PipelineState row.

Dry run by default. Idempotent: re-running creates 0. Deceased customers are
skipped -- they must never enter a work queue (migration 043).

Usage:
  ./venv/bin/python3 scripts/backfill_pipeline_state.py
  ./venv/bin/python3 scripts/backfill_pipeline_state.py --apply
"""
import sys, os, argparse
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.extensions import db
from app.models import Customer, PipelineState


def run(apply=False, agency_id=1):
    existing = {r[0] for r in db.session.query(PipelineState.customer_id).all()}
    customers = Customer.query.filter_by(agency_id=agency_id).all()

    created = skipped_existing = skipped_deceased = 0
    for c in customers:
        if c.id in existing:
            skipped_existing += 1
            continue
        if c.deceased_date is not None:
            skipped_deceased += 1
            continue
        created += 1
        if apply:
            db.session.add(PipelineState(
                agency_id=agency_id, customer_id=c.id,
                track="renewal", stage="contact",
            ))
    if apply:
        db.session.commit()

    return {"created": created,
            "skipped_existing": skipped_existing,
            "skipped_deceased": skipped_deceased}


if __name__ == "__main__":
    from app import create_app
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--agency", type=int, default=1)
    args = ap.parse_args()
    with create_app().app_context():
        res = run(apply=args.apply, agency_id=args.agency)
        print(f"{'APPLY' if args.apply else 'DRY RUN'} -- pipeline_state backfill")
        print(f"  created:           {res['created']}")
        print(f"  already had one:   {res['skipped_existing']}")
        print(f"  skipped deceased:  {res['skipped_deceased']}")
        if not args.apply:
            print("\nRe-run with --apply.")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `/usr/bin/python3 -m pytest tests/test_pipeline_backfill.py -q`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add scripts/backfill_pipeline_state.py tests/test_pipeline_backfill.py
git commit -m "feat(pipeline): idempotent pipeline_state backfill, skips deceased"
```

---

### Task 6: Blueprint + read endpoints

**Files:**
- Create: `app/pipeline/routes.py`
- Create: `app/templates/pipeline/index.html`
- Modify: `app/__init__.py` (register the blueprint)
- Test: `tests/test_pipeline_routes.py`

**Interfaces:**
- Consumes: `queue_counts`, `queue_for`, `QUEUES` (Task 4); `tier_for` (Task 3); `current_plan_for` (Task 2).
- Produces: `pipeline_bp`; `customer_row(customer, state, cfg, today) -> dict` — the single row shape every read AND write endpoint returns.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pipeline_routes.py
"""Pipeline endpoints: auth, agency scoping, row shape."""
import datetime as dt


def test_pipeline_index_requires_login(client):
    r = client.get("/pipeline/")
    assert r.status_code in (302, 401)


def test_today_api_requires_login(client):
    r = client.get("/pipeline/api/today")
    assert r.status_code in (302, 401)


def test_customer_row_shape(db_session, app, agency, customer):
    from app.models import PipelineState, PipelineConfig
    from app.extensions import db
    from app.pipeline.routes import customer_row
    with app.app_context():
        cfg = PipelineConfig(agency_id=agency.id, shp_end=dt.date(2026, 10, 30))
        ps = PipelineState(agency_id=agency.id, customer_id=customer.id)
        db.session.add_all([cfg, ps])
        db.session.commit()
        row = customer_row(customer, ps, cfg, dt.date(2026, 10, 20))
        for key in ("id", "name", "phone", "stage", "stage_label", "tier",
                    "reason_code", "queue_id", "settled"):
            assert key in row, f"missing {key}"
        assert row["settled"] is False
        assert row["stage_label"] == "Needs a call"


def test_settled_is_true_only_when_done(db_session, app, agency, customer):
    from app.models import PipelineState, PipelineConfig
    from app.extensions import db
    from app.pipeline.routes import customer_row
    with app.app_context():
        cfg = PipelineConfig(agency_id=agency.id)
        ps = PipelineState(agency_id=agency.id, customer_id=customer.id,
                           stage="done", outcome="kept")
        db.session.add_all([cfg, ps])
        db.session.commit()
        row = customer_row(customer, ps, cfg, dt.date(2026, 10, 20))
        assert row["settled"] is True
        assert row["outcome"] == "kept"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/usr/bin/python3 -m pytest tests/test_pipeline_routes.py -q`
Expected: FAIL with `404` on the route tests and `ModuleNotFoundError` on the import tests

- [ ] **Step 3: Implement the blueprint**

Create `app/pipeline/routes.py`:

```python
"""
AEP pipeline endpoints.

Follows the Fidelity precedent: the Jinja shell renders empty, JS fetches JSON,
and every mutation returns the updated row plus changed counters so the client
repaints one row instead of reloading.
"""
import datetime as dt

from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required, current_user

from app.extensions import db
from app.models import Customer, PipelineState, PipelineConfig
from app.pipeline.queues import QUEUES, queue_for, queue_counts
from app.pipeline.triage import tier_for
from app.pipeline.plans import current_plan_for

pipeline_bp = Blueprint("pipeline", __name__, url_prefix="/pipeline")

# Plain language only. An agent should never have to be taught a word here.
STAGE_LABEL = {
    "contact":   "Needs a call",
    "scheduled": "Appointment set",
    "deciding":  "Thinking it over",
    "submitted": "Waiting on carrier",
    "done":      "Finished",
}
OUTCOME_LABEL = {"enrolled": "Enrolled", "kept": "Staying put", "lost": "Closed"}


def _cfg(agency_id):
    cfg = PipelineConfig.query.filter_by(agency_id=agency_id).first()
    if cfg is None:
        cfg = PipelineConfig(agency_id=agency_id)
        db.session.add(cfg)
        db.session.commit()
    return cfg


def customer_row(customer, state, cfg, today=None):
    """The ONE row shape. Every read and every write returns this."""
    today = today or dt.date.today()
    t = tier_for(customer, state, cfg, today)
    return {
        "id": customer.id,
        "name": customer.full_name or f"{customer.first_name} {customer.last_name}".strip(),
        "phone": customer.phone_primary,
        "county": customer.county,
        "track": state.track,
        "stage": state.stage,
        "stage_label": STAGE_LABEL.get(state.stage, state.stage),
        "outcome": state.outcome,
        "outcome_label": OUTCOME_LABEL.get(state.outcome or ""),
        "settled": state.stage == "done",
        "tier": t.tier,
        "rank": t.rank,
        "reason_code": t.reason_code,
        "reason_plan_id": t.plan_id,
        "reason_county": t.county,
        "reason_days_left": t.days_left,
        "queue_id": queue_for(customer, state, cfg, today),
        "attempts": state.attempts,
    }


def _book_query(agency_id, agent_id):
    return (db.session.query(Customer, PipelineState)
            .join(PipelineState, PipelineState.customer_id == Customer.id)
            .filter(Customer.agency_id == agency_id,
                    Customer.primary_agent_id == agent_id,
                    Customer.deceased_date.is_(None)))


@pipeline_bp.route("/")
@login_required
def index():
    return render_template("pipeline/index.html")


@pipeline_bp.route("/api/today")
@login_required
def api_today():
    today = dt.date.today()
    agency_id = current_user.agency_id
    cfg = _cfg(agency_id)
    pairs = _book_query(agency_id, current_user.id).all()

    total = len(pairs)
    settled = sum(1 for _, s in pairs if s.stage == "done")
    never_contacted = sum(1 for _, s in pairs if s.attempts == 0 and s.stage == "contact")

    days_left = (cfg.season_end - today).days if cfg.season_end else None
    remaining = total - settled
    pace = None
    if days_left and days_left > 0 and remaining > 0:
        pace = -(-remaining // days_left)          # ceil, never a decimal

    buckets = {qid: [] for qid, _, _ in QUEUES}
    for c, s in pairs:
        q = queue_for(c, s, cfg, today)
        if q:
            buckets[q].append(customer_row(c, s, cfg, today))

    cards = []
    for qid, title, urgent in QUEUES:
        rows = sorted(buckets[qid], key=lambda r: (r["tier"], r["rank"], r["name"]))
        if not rows:
            continue                                # empty queues are hidden
        cards.append({"id": qid, "title": title, "urgent": urgent,
                      "count": len(rows), "rows": rows[:12]})

    return jsonify({
        "settled": settled, "total": total, "remaining": remaining,
        "days_left": days_left, "pace": pace, "never_contacted": never_contacted,
        "cards": cards,
    })


@pipeline_bp.route("/api/queue/<queue_id>")
@login_required
def api_queue(queue_id):
    today = dt.date.today()
    cfg = _cfg(current_user.agency_id)
    rows = []
    for c, s in _book_query(current_user.agency_id, current_user.id).all():
        if queue_for(c, s, cfg, today) == queue_id:
            rows.append(customer_row(c, s, cfg, today))
    rows.sort(key=lambda r: (r["tier"], r["rank"], r["name"]))
    cursor = int(request.args.get("cursor", 0))
    page = rows[cursor:cursor + 25]
    return jsonify({"rows": page, "total": len(rows),
                    "next_cursor": cursor + 25 if cursor + 25 < len(rows) else None})


@pipeline_bp.route("/api/customer/<int:customer_id>")
@login_required
def api_customer(customer_id):
    c = Customer.query.filter_by(id=customer_id,
                                 agency_id=current_user.agency_id).first_or_404()
    s = PipelineState.query.filter_by(customer_id=c.id).first_or_404()
    cfg = _cfg(current_user.agency_id)
    row = customer_row(c, s, cfg)
    cp = current_plan_for(c.id, c.agency_id)
    row["current_plan"] = cp
    # Agent of record is a compliance fact, not a display preference.
    row["is_mine"] = (c.primary_agent_id == current_user.id)
    row["owner_name"] = c.primary_agent.name if c.primary_agent else None
    return jsonify(row)
```

- [ ] **Step 4: Create the shell template**

Create `app/templates/pipeline/index.html`:

```html
{% extends "base.html" %}
{% block title %}AEP{% endblock %}

{% block styles %}
<style>
  /* Founders Green (#65BB84) is 2.34:1 on white -- fill only, never text.
     Text that must read as "good" uses the darkened green below (6.3:1). */
  .pl { --pl-good: #166B37; font-size: 17px; }
  .pl-head { padding: 20px 0 8px; }
  .pl-big { font-size: 28px; font-weight: 700; color: var(--ivory-bright); }
  .pl-sub { color: var(--slate); font-size: 15px; margin-top: 4px; }
  .pl-card { background: var(--surface); border: 1px solid var(--border);
             border-radius: var(--radius); padding: 18px; margin-bottom: 14px; }
  .pl-card h3 { margin: 0 0 4px; font-size: 18px; }
  .pl-card.urgent { border-left: 4px solid var(--gold); }
  .pl-row { display: flex; justify-content: space-between; align-items: center;
            min-height: 46px; padding: 8px 0; border-top: 1px solid var(--border); }
  .pl-btn { min-height: 46px; padding: 0 18px; font-size: 16px; border-radius: 10px;
            background: var(--gold); color: #fff; border: 0; cursor: pointer; }
  .pl-empty { color: var(--slate); padding: 28px 0; }
</style>
{% endblock %}

{% block content %}
<div class="pl">
  <div class="pl-head">
    <div class="pl-big" id="pl-settled">Loading&hellip;</div>
    <div class="pl-sub" id="pl-pace"></div>
  </div>
  <main id="pl-main"></main>
</div>
<script src="{{ url_for('static', filename='js/pipeline.js') }}"></script>
{% endblock %}
```

- [ ] **Step 5: Register the blueprint**

In `app/__init__.py`, following the existing three-line pattern, after `app.register_blueprint(providers_bp)`:

```python
    from app.pipeline.routes import pipeline_bp
    app.register_blueprint(pipeline_bp)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `/usr/bin/python3 -m pytest tests/test_pipeline_routes.py -q`
Expected: 4 passed

- [ ] **Step 7: Commit**

```bash
git add app/pipeline/routes.py app/templates/pipeline/index.html app/__init__.py tests/test_pipeline_routes.py
git commit -m "feat(pipeline): blueprint, read endpoints, Jinja shell"
```

---

### Task 7: Write endpoints + the scope gate

**Files:**
- Modify: `app/pipeline/routes.py`
- Test: `tests/test_pipeline_mutations.py`

**Interfaces:**
- Consumes: `customer_row` (Task 6), `ScopeForm`, `Touch`.
- Produces: `POST /pipeline/api/customer/<id>/outcome`, `/touch`, `/waiting`, `/scope`, `/tier` — each returning `{customer: row, counters: {...}}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pipeline_mutations.py
"""Write endpoints and the gates the server enforces (SPEC 7.4)."""
import datetime as dt
import pytest


@pytest.fixture
def logged_in(client, app, agency, agent_user, customer, db_session):
    from app.models import PipelineState, PipelineConfig
    from app.extensions import db
    with app.app_context():
        customer.primary_agent_id = agent_user.id
        db.session.add(PipelineState(agency_id=agency.id, customer_id=customer.id))
        db.session.add(PipelineConfig(agency_id=agency.id))
        db.session.commit()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(agent_user.id)
        sess["_fresh"] = True
    return customer


def test_moving_to_deciding_without_a_scope_form_is_refused(client, logged_in):
    r = client.post(f"/pipeline/api/customer/{logged_in.id}/outcome",
                    json={"action": "deciding"})
    assert r.status_code == 409
    assert r.get_json()["code"] == "needs_scope"


def test_scope_form_then_deciding_succeeds(client, logged_in):
    ok = client.post(f"/pipeline/api/customer/{logged_in.id}/scope",
                     json={"method": "verbal", "products": ["MAPD"]})
    assert ok.status_code == 200
    r = client.post(f"/pipeline/api/customer/{logged_in.id}/outcome",
                    json={"action": "deciding"})
    assert r.status_code == 200
    assert r.get_json()["customer"]["stage"] == "deciding"


def test_done_requires_an_outcome(client, logged_in):
    r = client.post(f"/pipeline/api/customer/{logged_in.id}/outcome",
                    json={"action": "done"})
    assert r.status_code == 400


def test_done_with_outcome_marks_settled(client, logged_in):
    r = client.post(f"/pipeline/api/customer/{logged_in.id}/outcome",
                    json={"action": "done", "outcome": "kept"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["customer"]["settled"] is True
    assert body["customer"]["outcome"] == "kept"
    assert "counters" in body


def test_logging_a_touch_increments_attempts(client, logged_in):
    r = client.post(f"/pipeline/api/customer/{logged_in.id}/touch",
                    json={"level": "tried", "channel": "call"})
    assert r.status_code == 200
    assert r.get_json()["customer"]["attempts"] == 1


def test_cannot_change_another_agents_customer(client, app, agency, admin_user, customer, db_session):
    """Agent of record is a compliance fact. Logging a touch is allowed;
    changing stage is not."""
    from app.models import PipelineState, PipelineConfig
    from app.extensions import db
    with app.app_context():
        customer.primary_agent_id = admin_user.id      # someone else's customer
        db.session.add(PipelineState(agency_id=agency.id, customer_id=customer.id))
        db.session.add(PipelineConfig(agency_id=agency.id))
        db.session.commit()
    from app.models import User
    with app.app_context():
        other = User(email="other@test.com", name="Other", agency_id=agency.id)
        db.session.add(other)
        db.session.commit()
        oid = other.id
    with client.session_transaction() as sess:
        sess["_user_id"] = str(oid)
        sess["_fresh"] = True
    r = client.post(f"/pipeline/api/customer/{customer.id}/outcome",
                    json={"action": "done", "outcome": "kept"})
    assert r.status_code == 403
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/usr/bin/python3 -m pytest tests/test_pipeline_mutations.py -q`
Expected: FAIL with 404 (endpoints do not exist)

- [ ] **Step 3: Implement**

Append to `app/pipeline/routes.py`:

```python
import json
from flask import abort
from app.models import ScopeForm, Touch

# Stages that require a scope form on file before any plan-specific discussion.
SCOPE_REQUIRED = {"deciding", "submitted"}
VALID_OUTCOMES = {"enrolled", "kept", "lost"}


def _load_mine(customer_id, *, writing):
    """Fetch a customer + state. `writing` means a stage/outcome/tier change,
    which only the agent of record may do."""
    c = Customer.query.filter_by(id=customer_id,
                                 agency_id=current_user.agency_id).first_or_404()
    s = PipelineState.query.filter_by(customer_id=c.id).first_or_404()
    if writing and c.primary_agent_id != current_user.id and not current_user.is_admin:
        abort(403)
    return c, s


def _reply(c, s, cfg):
    return jsonify({
        "customer": customer_row(c, s, cfg),
        "counters": queue_counts(current_user.agency_id, c.primary_agent_id, cfg),
    })


@pipeline_bp.route("/api/customer/<int:customer_id>/scope", methods=["POST"])
@login_required
def api_scope(customer_id):
    c, s = _load_mine(customer_id, writing=False)
    body = request.get_json(silent=True) or {}
    db.session.add(ScopeForm(
        agency_id=c.agency_id, customer_id=c.id,
        method=body.get("method"),
        products=json.dumps(body.get("products") or []),
        captured_by=current_user.id,
    ))
    db.session.commit()
    return _reply(c, s, _cfg(c.agency_id))


@pipeline_bp.route("/api/customer/<int:customer_id>/outcome", methods=["POST"])
@login_required
def api_outcome(customer_id):
    c, s = _load_mine(customer_id, writing=True)
    body = request.get_json(silent=True) or {}
    action = body.get("action")
    if action not in STAGE_LABEL:
        return jsonify({"error": "unknown action"}), 400

    # The scope form must exist before any plan-specific discussion. The
    # 48-hour wait ended 2026-10-01 (Tim), so same-day is fine.
    if action in SCOPE_REQUIRED:
        has_scope = ScopeForm.query.filter_by(customer_id=c.id).first()
        if not has_scope:
            return jsonify({"code": "needs_scope",
                            "message": "Fill in the scope form first."}), 409

    if action == "done":
        outcome = body.get("outcome")
        if outcome not in VALID_OUTCOMES:
            return jsonify({"error": "done requires an outcome"}), 400
        s.outcome = outcome
    else:
        s.outcome = None

    s.stage = action
    s.stage_since = dt.datetime.utcnow()
    db.session.commit()
    return _reply(c, s, _cfg(c.agency_id))


@pipeline_bp.route("/api/customer/<int:customer_id>/touch", methods=["POST"])
@login_required
def api_touch(customer_id):
    # Logging what you did on someone else's customer IS allowed.
    c, s = _load_mine(customer_id, writing=False)
    body = request.get_json(silent=True) or {}
    level = body.get("level")
    if level not in {"sent", "tried", "reached"}:
        return jsonify({"error": "bad level"}), 400

    now = dt.datetime.utcnow()
    db.session.add(Touch(
        agency_id=c.agency_id, customer_id=c.id, agent_id=current_user.id,
        level=level, channel=body.get("channel") or "call",
        direction=body.get("direction") or "out",
        occurred_at=now, detail=body.get("detail"), source="manual",
    ))
    if level in {"tried", "reached"}:
        s.attempts = (s.attempts or 0) + 1
        if s.first_try_at is None:
            s.first_try_at = now
    db.session.commit()
    return _reply(c, s, _cfg(c.agency_id))


@pipeline_bp.route("/api/customer/<int:customer_id>/waiting", methods=["POST", "DELETE"])
@login_required
def api_waiting(customer_id):
    c, s = _load_mine(customer_id, writing=True)
    if request.method == "DELETE":
        s.waiting_what = None
        s.waiting_due = None
    else:
        body = request.get_json(silent=True) or {}
        s.waiting_what = body.get("what")
        due = body.get("due")
        s.waiting_due = dt.date.fromisoformat(due) if due else None
    db.session.commit()
    return _reply(c, s, _cfg(c.agency_id))


@pipeline_bp.route("/api/customer/<int:customer_id>/tier", methods=["POST"])
@login_required
def api_tier(customer_id):
    c, s = _load_mine(customer_id, writing=True)
    body = request.get_json(silent=True) or {}
    tier = body.get("tier")
    if tier is not None and tier not in (1, 2, 3):
        return jsonify({"error": "tier must be 1, 2, 3 or null"}), 400
    s.tier_override = tier
    s.tier_override_note = body.get("note")
    s.tier_override_by = current_user.id
    s.tier_override_at = dt.datetime.utcnow() if tier else None
    db.session.commit()
    return _reply(c, s, _cfg(c.agency_id))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `/usr/bin/python3 -m pytest tests/test_pipeline_mutations.py -q`
Expected: 6 passed

- [ ] **Step 5: Run the whole suite**

Run: `/usr/bin/python3 -m pytest tests/ -q`
Expected: 934 passed (898 baseline + 36 new)

- [ ] **Step 6: Commit**

```bash
git add app/pipeline/routes.py tests/test_pipeline_mutations.py
git commit -m "feat(pipeline): write endpoints with scope gate and agent-of-record guard"
```

---

### Task 8: Today tab front end

**Files:**
- Create: `app/static/js/pipeline.js`
- Test: manual verification against the real book (steps below)

**Interfaces:**
- Consumes: `GET /pipeline/api/today`, `POST /pipeline/api/customer/<id>/outcome`.
- Produces: no exports; a page.

- [ ] **Step 1: Write the JS**

Create `app/static/js/pipeline.js`:

```javascript
/* AEP pipeline — Today tab.
   Fetches JSON and repaints single rows. Never re-renders the whole page:
   that is the DOM problem the commission Fidelity view already solved. */
(function () {
  "use strict";

  var esc = function (s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (ch) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch];
    });
  };

  // reason_code -> plain language. The API returns ingredients; the sentence
  // is built here so SQL never assembles strings.
  function reasonText(r) {
    switch (r.reason_code) {
      case "sar":           return "Plan is ending in " + esc(r.reason_county) + " County";
      case "shp_pending":   return "State opt-out, " + r.reason_days_left + " days left";
      case "shp_closed":    return "State opt-out window closed";
      case "rating_major":  return "Big changes to their plan";
      case "rating_some":   return "Plan changes to review";
      case "rating_little": return "Little plan change";
      case "unrated":       return "Plan not reviewed yet";
      case "sep_urgent":    return r.reason_days_left + " days left to enroll";
      case "sep_future":    return "Enrollment window still open";
      case "sep_closed":    return "Their window has closed";
      case "no_deadline":   return "No deadline on file";
      case "override":      return "You moved this one up";
      default:              return "";
    }
  }

  function rowHtml(r) {
    var tel = r.phone ? '<a href="tel:' + esc(r.phone) + '">' + esc(r.phone) + "</a>" : "";
    return (
      '<div class="pl-row" data-id="' + r.id + '">' +
        "<div><strong>" + esc(r.name) + "</strong><br>" +
        '<span class="pl-sub">' + reasonText(r) + "</span></div>" +
        "<div>" + tel + "</div>" +
      "</div>"
    );
  }

  function cardHtml(card) {
    return (
      '<section class="pl-card' + (card.urgent ? " urgent" : "") + '">' +
        "<h3>" + esc(card.title) + " &middot; " + card.count + "</h3>" +
        card.rows.map(rowHtml).join("") +
        (card.count > card.rows.length
          ? '<p class="pl-sub">' + (card.count - card.rows.length) + " more</p>"
          : "") +
      "</section>"
    );
  }

  function render(data) {
    document.getElementById("pl-settled").textContent =
      data.settled + " of " + data.total + " settled for 2027.";

    var sub = [];
    if (data.remaining > 0) {
      sub.push(data.remaining + " to go");
      if (data.days_left) sub.push(data.days_left + " days left");
      if (data.pace) sub.push("about " + data.pace + " a day");
    }
    var line = sub.join(", ") + (sub.length ? "." : "");
    if (data.never_contacted > 0) {
      line += " " + data.never_contacted + " have not been contacted at all.";
    }
    document.getElementById("pl-pace").textContent = line;

    var main = document.getElementById("pl-main");
    main.innerHTML = data.cards.length
      ? data.cards.map(cardHtml).join("")
      : '<p class="pl-empty">Nothing needs you right now.</p>';
  }

  function load() {
    fetch("/pipeline/api/today", { credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .then(render)
      .catch(function () {
        document.getElementById("pl-settled").textContent = "Could not load.";
      });
  }

  document.addEventListener("DOMContentLoaded", load);
})();
```

- [ ] **Step 2: Apply the migration and backfill on a local copy**

Run:
```bash
/usr/bin/python3 -m pytest tests/ -q
```
Expected: 934 passed (898 baseline + 36 new)

- [ ] **Step 3: Verify counts against the real book on the VPS**

Deploy to the VPS and check that the numbers are plausible before showing anyone:

```bash
ssh -i ~/.ssh/id_ed25519 root@23.187.248.100
cd /var/www/founders-portal
PGPASSWORD=$(grep DATABASE_URL .env | sed 's|.*://founders_user:\([^@]*\)@.*|\1|') \
  pg_dump -U founders_user -h localhost founders_portal > /root/founders_pre_mig046_$(date +%Y%m%d_%H%M%S).sql
git pull origin feat/aep-pipeline
export FLASK_APP=wsgi.py
./venv/bin/flask db upgrade
PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/backfill_pipeline_state.py
PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/backfill_pipeline_state.py --apply
systemctl restart founders-portal
```

Expected: migration `045 -> 046`; backfill creates ~5,475 (5,495 minus ~20 deceased); re-run creates 0.

- [ ] **Step 4: Confirm money is untouched**

Run on the VPS:
```bash
PGPASSWORD=... psql -U founders_user -h localhost founders_portal -tAc \
 "SELECT count(*), round(sum(raw_amount)::numeric,2) FROM commission_line_items;"
```
Expected: `18988|365040.90` — identical. This feature must not touch money.

- [ ] **Step 5: Commit**

```bash
git add app/static/js/pipeline.js
git commit -m "feat(pipeline): Today tab — counters, queue cards, tel: links"
```

---

## Self-Review

**Spec coverage.** §3 stages/outcomes/touch levels → Task 1. §4 the one number → Task 6 (`api_today`). §5 tiers → Task 3, with §5.4.1 current-plan → Task 2. §6.1 queues + §6.2 stalled → Task 4. §7.2 tables → Task 1. §7.3 reads → Task 6, writes → Task 7. §7.4 gates → Task 7. §8 auth/scoping → Tasks 6-7. §9 front end → Tasks 6, 8. §13 build order steps 1-3 → Tasks 1-8.

**Deliberately out of this plan** (spec §13 steps 4-7, each its own plan): one-at-a-time mode, People and Follow-ups tabs, the setup screen and rules endpoints, Quo webhooks. Task 8 delivers a demonstrable Today tab; those four build on it.

**Known gaps to close in the next plan:** `authorized_contact` and `application` tables exist but nothing writes them yet; agency-wide search (§8) and duplicate detection (§7.3) are not built; the letter-mismatch report (§14 Q5, answered as in scope) is not built.

**Type consistency.** `current_plan_for` returns `plan_id`/`policy_id`/`county`/`lane`/`ambiguous` and is consumed with those names in Tasks 3 and 6. `Tier` fields `tier`/`rank`/`reason_code`/`plan_id`/`county`/`days_left` map onto row keys `tier`/`rank`/`reason_code`/`reason_plan_id`/`reason_county`/`reason_days_left` — renamed once, in `customer_row`, and the JS reads the `reason_*` names. `queue_for` returns a queue id from `QUEUES`, used as `row["queue_id"]`.

**One placeholder deliberately left:** Task 1 Step 3 contains a full-width digit in `db.String(8)` with an explicit instruction to fix it. It is flagged, not hidden.
