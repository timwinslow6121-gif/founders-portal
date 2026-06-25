def test_registry_registers_and_runs(app, db_session):
    from app.integrity import invariant, run_all, REGISTRY, Violation

    with app.app_context():
        @invariant("test_dummy", severity="high", domain="data",
                   description="dummy for testing")
        def _dummy():
            return 3, [{"id": 1}, {"id": 2}, {"id": 3}]

        assert "test_dummy" in REGISTRY
        results = run_all()
        v = next(r for r in results if r.key == "test_dummy")
        assert isinstance(v, Violation)
        assert v.count == 3
        assert v.severity == "high"
        assert v.domain == "data"
        assert len(v.sample) == 3
        # cleanup so the dummy doesn't leak into other tests
        REGISTRY.pop("test_dummy", None)


def test_run_all_sorts_high_severity_first(app, db_session):
    from app.integrity import invariant, run_all, REGISTRY

    with app.app_context():
        @invariant("z_low", severity="low", domain="data", description="x")
        def _a(): return 0, []

        @invariant("a_high", severity="high", domain="data", description="x")
        def _b(): return 0, []

        results = [r for r in run_all() if r.key in ("z_low", "a_high")]
        assert results[0].key == "a_high"   # high before low despite name order
        REGISTRY.pop("z_low", None); REGISTRY.pop("a_high", None)
