import pytest
from app import create_app
from app.extensions import db
from app.models import Agency, User, Plan


@pytest.fixture
def ctx():
    app = create_app()
    app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
                      RATELIMIT_ENABLED=False, WTF_CSRF_ENABLED=False,
                      LOGIN_DISABLED=True)
    with app.app_context():
        db.create_all()
        ag = Agency(name="T"); db.session.add(ag); db.session.flush()
        u = User(email="a@foundersinsuranceagency.com", name="A", is_admin=True,
                 agency_id=ag.id, role="admin")
        db.session.add(u); db.session.flush()
        p = Plan(agency_id=ag.id, carrier="Humana", cms_plan_id="H1036-335",
                 year=2026, plan_name="Gold Plus HMO", plan_type="mapd",
                 status="current", monthly_premium=0.0, pcp_copay="$0")
        db.session.add(p); db.session.commit()
        yield app, ag.id, u.id, p.id
        db.session.remove(); db.drop_all()


def test_plan_detail_passes_sections(ctx):
    app, agency_id, uid, pid = ctx
    from app import carriers
    with app.test_request_context(f"/carriers/{pid}"):
        from flask_login import login_user
        from app.models import User
        login_user(db.session.get(User, uid))
        resp = carriers.plan_detail(pid)
    html = resp if isinstance(resp, str) else resp.get_data(as_text=True)
    assert "H1036-335" in html


def test_plan_detail_route_builds_sections_context(ctx, monkeypatch):
    """Exercise the actual context passed to render_template — proves the route
    computes sections/category/oop_cap/medigap_rows via app.plan_sections rather
    than relying on the (not-yet-built) template to surface them."""
    app, agency_id, uid, pid = ctx
    from app import carriers

    captured = {}
    real_render_template = carriers.render_template

    def fake_render_template(template_name, **context):
        captured.update(context)
        return real_render_template(template_name, **context)

    monkeypatch.setattr(carriers, "render_template", fake_render_template)

    with app.test_request_context(f"/carriers/{pid}"):
        from flask_login import login_user
        from app.models import User
        login_user(db.session.get(User, uid))
        carriers.plan_detail(pid)

    assert captured.get("category") == "part_c"
    assert captured.get("oop_cap") == "$2,100"
    sections = captured.get("sections")
    assert sections is not None
    titles = [s["title"] for s in sections]
    assert "Costs" in titles
    assert "Drugs" in titles  # mapd plan_type includes the Drugs group
    assert captured.get("medigap_rows") == []  # mapd plan has no plan_letter
    # Plan columns surfaced into details under the keys the section config expects
    assert captured["details"]["monthly_premium"] == "$0.00"
    assert captured["details"]["pcp_copay"] == "$0"
