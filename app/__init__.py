from flask import Flask
from flask_login import LoginManager, current_user
from flask_migrate import Migrate
from app.extensions import db, login_manager
from config import Config

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    Migrate(app, db)

    from app.models import User  # noqa
    from app.routes import main
    from app.auth import auth
    from app.upload import upload_bp
    from app.labels import labels_bp
    from app.agent_settings import settings_bp
    from app.commission import commission_bp
    from app.customers import customers_bp
    from app.pharmacies import pharmacies_bp
    from app.carriers import carriers_bp
    from app.comms import comms_bp
    app.register_blueprint(main)
    app.register_blueprint(auth)
    app.register_blueprint(upload_bp)
    app.register_blueprint(labels_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(commission_bp)
    app.register_blueprint(customers_bp)
    app.register_blueprint(pharmacies_bp)
    app.register_blueprint(carriers_bp)
    app.register_blueprint(comms_bp)

    @app.context_processor
    def inject_duplicate_count():
        if not current_user.is_authenticated:
            return {}
        from app.customers import get_duplicate_mbi_count
        try:
            count = get_duplicate_mbi_count(
                current_user.agency_id,
                agent_id=current_user.id,
                is_admin=current_user.is_admin,
            )
        except Exception:
            count = 0
        return {'duplicate_mbi_count': count}

    with app.app_context():
        pass

    return app
