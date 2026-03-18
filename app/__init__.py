from flask import Flask
from flask_login import LoginManager
from app.extensions import db, login_manager
from config import Config

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'

    from app.models import User  # noqa
    from app.routes import main
    from app.auth import auth
    from app.upload import upload_bp
    app.register_blueprint(main)
    app.register_blueprint(auth)
    app.register_blueprint(upload_bp)

    with app.app_context():
        db.create_all()

    return app
