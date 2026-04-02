"""
tests/conftest.py

Shared pytest fixtures for Founders Portal test suite.

Uses SQLite in-memory database for fast isolated tests.
No PostgreSQL connection required — tests run locally without VPS access.
"""

import os
import pytest

# Set DATABASE_URL before importing app so config picks it up
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("TESTING", "1")


@pytest.fixture(scope="session")
def app():
    """Create and configure Flask app for testing."""
    from app import create_app

    flask_app = create_app()
    flask_app.config.update(
        TESTING=True,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        WTF_CSRF_ENABLED=False,
        SECRET_KEY="test",
        SERVER_NAME=None,
    )
    return flask_app


@pytest.fixture(scope="session")
def client(app):
    """Flask test client."""
    return app.test_client()


@pytest.fixture(scope="function")
def db_session(app):
    """
    Create all tables before each test, yield the db session,
    then drop all tables after each test for full isolation.
    """
    from app.extensions import db as _db

    with app.app_context():
        _db.create_all()
        yield _db.session
        _db.session.remove()
        _db.drop_all()


@pytest.fixture(scope="function")
def agency(db_session, app):
    """Create a test Agency row."""
    from app.models import Agency
    from app.extensions import db

    with app.app_context():
        a = Agency(name="Test Agency")
        db.session.add(a)
        db.session.commit()
        db.session.refresh(a)
        return a


@pytest.fixture(scope="function")
def admin_user(db_session, app):
    """Create an admin User for testing."""
    from app.models import User
    from app.extensions import db

    with app.app_context():
        u = User(
            email="admin@test.com",
            name="Admin",
            is_admin=True,
        )
        db.session.add(u)
        db.session.commit()
        db.session.refresh(u)
        return u


@pytest.fixture(scope="function")
def agent_user(db_session, app):
    """Create a non-admin agent User for testing."""
    from app.models import User
    from app.extensions import db

    with app.app_context():
        u = User(
            email="agent@test.com",
            name="Agent",
            is_admin=False,
        )
        db.session.add(u)
        db.session.commit()
        db.session.refresh(u)
        return u


@pytest.fixture(scope="function")
def customer(db_session, app):
    """Create a test Customer record."""
    from app.models import Customer
    from app.extensions import db

    with app.app_context():
        c = Customer(
            first_name="John",
            last_name="Doe",
            full_name="John Doe",
            phone_primary="+17705551234",
            phone_secondary="+14045550001",
        )
        db.session.add(c)
        db.session.commit()
        db.session.refresh(c)
        return c
