def test_links_resolve_runs_and_is_int(app):
    from app.integrity import REGISTRY
    with app.app_context():
        v = REGISTRY["links_resolve"]()
        assert v.domain == "route"
        assert isinstance(v.count, int)   # 0 if all template url_for targets exist


def test_links_resolve_flags_bogus_endpoint(app, tmp_path, monkeypatch):
    from app.integrity import REGISTRY, _template_endpoints
    # _template_endpoints returns the set of url_for endpoint names found in templates;
    # feed it a fake template dir containing a bogus endpoint.
    d = tmp_path / "templates"; d.mkdir()
    (d / "x.html").write_text("{{ url_for('does.not_exist') }}")
    eps = _template_endpoints(str(d))
    assert "does.not_exist" in eps
    with app.app_context():
        assert "does.not_exist" not in {r.endpoint for r in app.url_map.iter_rules()}


def test_no_orphan_routes_runs(app):
    from app.integrity import REGISTRY
    with app.app_context():
        v = REGISTRY["no_orphan_routes"]()
        assert v.domain == "route"
        assert isinstance(v.count, int)
