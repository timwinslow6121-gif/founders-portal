from flask import Blueprint

commission_bp = Blueprint("commission", __name__)

from app.commission import routes  # noqa
