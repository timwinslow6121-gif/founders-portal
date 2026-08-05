import pytest
from app import create_app
from app.extensions import db
from app.models import Agency, User, Plan, PlanServiceArea, Provider


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


def test_new_benefit_keys_are_saved(ctx):
    app, agency_id, uid, pid = ctx
    from app.carriers import BENEFIT_KEYS
    for k in ["otc_usage", "dental_major_innet", "hi_riders", "annual_max",
              "imaging", "therapy", "ambulance_air", "part_b_giveback"]:
        assert k in BENEFIT_KEYS


from app.models import AgentCarrierContract


def _capture_context(app, uid, pid, monkeypatch):
    from app import carriers
    captured = {}
    real = carriers.render_template

    def fake(template_name, **context):
        captured.update(context)
        return real(template_name, **context)

    monkeypatch.setattr(carriers, "render_template", fake)
    with app.test_request_context(f"/carriers/{pid}"):
        from flask_login import login_user
        from app.models import User
        # test_request_context() reuses the ALREADY-ACTIVE app context pushed by
        # the `ctx` fixture's outer `with app.app_context():` block (Flask only
        # pushes a new app context if none is active — see RequestContext.push).
        # That means this call runs on the SAME scoped session whose identity
        # map may hold a stale Plan object cached before a later test made its
        # own writes in a separate nested app_context(). Expire it so the route
        # queries fresh rows instead of returning the stale cached instance.
        db.session.expire_all()
        login_user(db.session.get(User, uid))
        carriers.plan_detail(pid)
    return captured


def test_route_passes_kpis_and_agent_context(ctx, monkeypatch):
    app, agency_id, uid, pid = ctx
    captured = _capture_context(app, uid, pid, monkeypatch)
    assert isinstance(captured.get("kpis"), list)
    assert captured.get("is_agent_context") is True
    assert captured.get("quick_info") is not None


def test_quick_info_uses_viewing_agents_own_split(ctx, monkeypatch):
    app, agency_id, uid, pid = ctx
    # Give the viewing agent a 0.525 Humana contract; plan.carrier == "Humana"
    with app.app_context():
        db.session.add(AgentCarrierContract(
            agency_id=agency_id, agent_id=uid, carrier="Humana",
            split_rate=0.525, is_active=True))
        # also set plan commission rates
        p = db.session.get(Plan, pid)
        p.comm_type = "pmpm"; p.comm_initial = 100.0; p.comm_renewal = 50.0
        p.hra_bonus = 25.0
        db.session.commit()
    captured = _capture_context(app, uid, pid, monkeypatch)
    qi = captured["quick_info"]
    assert qi["split_rate"] == 0.525
    assert round(qi["agent_take_initial"], 2) == 52.5    # 100 * 0.525
    assert round(qi["agent_take_renewal"], 2) == 26.25   # 50 * 0.525
    assert round(qi["projected_annual"], 2) == 315.0     # 26.25 * 12
    assert qi["hra_bonus"] == 25.0


def test_quick_info_falls_back_to_default_split(ctx, monkeypatch):
    app, agency_id, uid, pid = ctx
    with app.app_context():
        p = db.session.get(Plan, pid)
        p.comm_initial = 100.0; p.comm_renewal = 50.0
        db.session.commit()
    # No contract row seeded → default 0.55
    captured = _capture_context(app, uid, pid, monkeypatch)
    assert captured["quick_info"]["split_rate"] == 0.55
    assert round(captured["quick_info"]["agent_take_initial"], 2) == 55.0


def test_template_renders_toggle_and_kpi_and_views(ctx, monkeypatch):
    app, agency_id, uid, pid = ctx
    with app.app_context():
        p = db.session.get(Plan, pid)
        p.annual_oopm = 4500.0
        # seed a details_json OTC value so the gradient card appears
        import json
        p.details_json = json.dumps({"otc_allowance": "$45/quarter"})
        db.session.commit()
    from app import carriers
    with app.test_request_context(f"/carriers/{pid}"):
        from flask_login import login_user
        from app.models import User
        # See _capture_context's comment above: test_request_context() reuses the
        # already-active app context from the `ctx` fixture, so the session's
        # identity map can hold a stale Plan cached before this test's own writes
        # above (a separate nested app_context()). Expire so the route re-queries.
        db.session.expire_all()
        login_user(db.session.get(User, uid))
        resp = carriers.plan_detail(pid)
    html = resp if isinstance(resp, str) else resp.get_data(as_text=True)
    assert 'data-plan-view' in html            # the toggle
    assert 'consumer-view' in html
    assert 'pro-view' in html
    assert 'fp-plan-view' in html              # localStorage key referenced in JS
    assert 'Top extra benefits' in html or 'OTC' in html  # gradient card content


def test_quick_info_panel_renders_agents_own_numbers(ctx, monkeypatch):
    app, agency_id, uid, pid = ctx
    with app.app_context():
        db.session.add(AgentCarrierContract(
            agency_id=agency_id, agent_id=uid, carrier="Humana",
            split_rate=0.525, is_active=True))
        p = db.session.get(Plan, pid)
        p.comm_type = "pmpm"; p.comm_initial = 100.0; p.comm_renewal = 50.0
        db.session.commit()
    from app import carriers
    with app.test_request_context(f"/carriers/{pid}"):
        from flask_login import login_user
        from app.models import User
        # See _capture_context's comment above: the nested app_context() used to
        # seed the contract/plan above tears down and clears the scoped session's
        # identity map on exit, so the route's query would otherwise return a
        # stale cached Plan (comm_initial=None). Expire so it re-queries fresh.
        db.session.expire_all()
        login_user(db.session.get(User, uid))
        resp = carriers.plan_detail(pid)
    html = resp if isinstance(resp, str) else resp.get_data(as_text=True)
    assert 'quick-info' in html
    assert '52.5%' in html            # the viewing agent's own split
    assert '$52.50' in html           # agent take on initial (100 * 0.525)


def test_quick_info_panel_absent_without_agent_context(ctx, monkeypatch):
    """When is_agent_context is False, the commission panel must NOT be in the DOM."""
    app, agency_id, uid, pid = ctx
    from app import carriers
    real = carriers.render_template

    def fake(template_name, **context):
        context = dict(context)
        context["is_agent_context"] = False
        context["quick_info"] = None
        return real(template_name, **context)

    monkeypatch.setattr(carriers, "render_template", fake)
    with app.test_request_context(f"/carriers/{pid}"):
        from flask_login import login_user
        from app.models import User
        login_user(db.session.get(User, uid))
        resp = carriers.plan_detail(pid)
    html = resp if isinstance(resp, str) else resp.get_data(as_text=True)
    assert 'quick-info' not in html   # role-gated out of the DOM entirely


def test_service_area_counties_mode_when_rows_exist(ctx, monkeypatch):
    app, agency_id, uid, pid = ctx
    with app.app_context():
        for c in ("Mecklenburg", "Cabarrus", "Union"):
            db.session.add(PlanServiceArea(plan_id=pid, agency_id=agency_id,
                                           state="NC", county=c))
        db.session.commit()
    from app import carriers
    captured = {}
    real = carriers.render_template
    def fake(t, **c):
        captured.update(c); return real(t, **c)
    monkeypatch.setattr(carriers, "render_template", fake)
    with app.test_request_context(f"/carriers/{pid}"):
        from flask_login import login_user
        from app.models import User
        login_user(db.session.get(User, uid))
        carriers.plan_detail(pid)
    sa = captured["service_area"]
    assert sa["mode"] == "counties"
    assert sa["state"] == "NC"
    assert sa["count"] == 3
    assert sa["counties"] == ["Cabarrus", "Mecklenburg", "Union"]   # sorted


def test_service_area_state_mode_when_no_rows(ctx, monkeypatch):
    app, agency_id, uid, pid = ctx
    from app import carriers
    captured = {}
    real = carriers.render_template
    def fake(t, **c):
        captured.update(c); return real(t, **c)
    monkeypatch.setattr(carriers, "render_template", fake)
    with app.test_request_context(f"/carriers/{pid}"):
        from flask_login import login_user
        from app.models import User
        login_user(db.session.get(User, uid))
        carriers.plan_detail(pid)
    sa = captured["service_area"]
    assert sa["mode"] == "state"
    assert sa["label"] == "Available statewide in NC"   # plan.service_area is None


def test_state_line_label_normalizes_bare_state_and_preserves_real_area():
    from app.carriers import _state_line_label
    assert _state_line_label(None) == "Available statewide in NC"
    assert _state_line_label("") == "Available statewide in NC"
    assert _state_line_label("NC") == "Available statewide in NC"
    assert _state_line_label("nc") == "Available statewide in NC"
    assert _state_line_label("NC Statewide") == "Available statewide in NC"
    assert _state_line_label("North Carolina") == "Available statewide in NC"
    assert _state_line_label("Western NC") == "Available in Western NC"
    assert _state_line_label("National") == "Available nationally"


def test_blank_plan_shows_empty_state_note(ctx):
    app, agency_id, uid, pid = ctx
    from app import carriers
    with app.app_context():
        blank = Plan(agency_id=agency_id, carrier="BCBS", plan_name="Dental Blue PPO",
                     plan_type="dvh", year=2026, status="current")
        db.session.add(blank); db.session.commit()
        blank_id = blank.id
    with app.test_request_context(f"/carriers/{blank_id}"):
        from flask_login import login_user
        from app.models import User
        login_user(db.session.get(User, uid))
        resp = carriers.plan_detail(blank_id)
    html = resp if isinstance(resp, str) else resp.get_data(as_text=True)
    # The note's copy only appears in the rendered div (the class name also lives in
    # the always-present <style> block, so assert on the copy).
    assert "No benefit details entered yet" in html


def test_populated_plan_has_no_empty_state_note(ctx):
    app, agency_id, uid, pid = ctx  # ctx plan has pcp_copay="$0" → a real row
    from app import carriers
    with app.test_request_context(f"/carriers/{pid}"):
        from flask_login import login_user
        from app.models import User
        login_user(db.session.get(User, uid))
        resp = carriers.plan_detail(pid)
    html = resp if isinstance(resp, str) else resp.get_data(as_text=True)
    assert "No benefit details entered yet" not in html


def test_template_renders_service_area_bar(ctx):
    app, agency_id, uid, pid = ctx
    with app.app_context():
        for c in ("Mecklenburg", "Cabarrus"):
            db.session.add(PlanServiceArea(plan_id=pid, agency_id=agency_id,
                                           state="NC", county=c))
        db.session.commit()
    from app import carriers
    with app.test_request_context(f"/carriers/{pid}"):
        from flask_login import login_user
        from app.models import User
        login_user(db.session.get(User, uid))
        resp = carriers.plan_detail(pid)
    html = resp if isinstance(resp, str) else resp.get_data(as_text=True)
    assert "service-area-bar" in html
    assert "2 counties" in html                 # count line
    assert "data-service-area-toggle" in html   # View all control
    assert "Mecklenburg" in html                # county in the (collapsed) list


def test_template_service_area_state_line(ctx):
    app, agency_id, uid, pid = ctx
    from app import carriers
    with app.test_request_context(f"/carriers/{pid}"):
        from flask_login import login_user
        from app.models import User
        login_user(db.session.get(User, uid))
        resp = carriers.plan_detail(pid)
    html = resp if isinstance(resp, str) else resp.get_data(as_text=True)
    assert "service-area-bar" in html
    assert "Available statewide in NC" in html
    assert "data-service-area-toggle" not in html   # no toggle without counties


def test_providers_for_plan_splits_in_and_not_in_network(ctx):
    app, agency_id, uid, pid = ctx  # ctx plan carrier = "Humana"
    from app.carriers import providers_for_plan
    from app.models import Plan
    with app.app_context():
        innet = Provider(agency_id=agency_id, name="Kann Family", county="Cabarrus", created_by_id=uid)
        db.session.add(innet); db.session.flush(); innet.set_carriers(["Humana", "BCBS"])
        outnet = Provider(agency_id=agency_id, name="NE Digestive", county="Cabarrus", created_by_id=uid)
        db.session.add(outnet); db.session.flush(); outnet.set_carriers(["BCBS"])  # NOT Humana
        db.session.commit()
        plan = db.session.get(Plan, pid)
        res = providers_for_plan(plan, agency_id)
    innet_names = {p.name for lst in res["in_network"].values() for p in lst}
    outnet_names = {p.name for lst in res["not_in_network"].values() for p in lst}
    assert "Kann Family" in innet_names
    assert "NE Digestive" in outnet_names        # sole clinic out-of-network still surfaces
    assert "NE Digestive" not in innet_names


def test_providers_for_plan_is_ppo_flag(ctx):
    app, agency_id, uid, pid = ctx
    from app.carriers import providers_for_plan
    from app.models import Plan
    with app.app_context():
        plan = db.session.get(Plan, pid)
        plan.plan_subtype = "ppo"; db.session.commit()
        assert providers_for_plan(plan, agency_id)["is_ppo"] is True
        plan.plan_subtype = "hmo"; db.session.commit()
        assert providers_for_plan(plan, agency_id)["is_ppo"] is False


def test_providers_for_plan_agency_scoped(ctx):
    app, agency_id, uid, pid = ctx
    from app.carriers import providers_for_plan
    from app.models import Plan, Agency
    with app.app_context():
        other = Agency(name="Other"); db.session.add(other); db.session.flush()
        p = Provider(agency_id=other.id, name="Leak", county="X", created_by_id=uid)
        db.session.add(p); db.session.flush(); p.set_carriers(["Humana"])
        db.session.commit()
        plan = db.session.get(Plan, pid)
        res = providers_for_plan(plan, agency_id)
    allnames = {pr.name for grp in (res["in_network"], res["not_in_network"]) for lst in grp.values() for pr in lst}
    assert "Leak" not in allnames                # other agency's provider never returned
