from flask import Flask
from flask_login import LoginManager
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
    app.register_blueprint(main)
    app.register_blueprint(auth)
    app.register_blueprint(upload_bp)
    app.register_blueprint(labels_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(commission_bp)
    app.register_blueprint(customers_bp)
    app.register_blueprint(pharmacies_bp)

    with app.app_context():

    return app
