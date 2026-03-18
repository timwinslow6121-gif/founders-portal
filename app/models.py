from app import db, login_manager
from flask_login import UserMixin
from datetime import datetime

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

class User(UserMixin, db.Model):
    id            = db.Column(db.Integer, primary_key=True)
    email         = db.Column(db.String(120), unique=True, nullable=False)
    name          = db.Column(db.String(120))
    google_id     = db.Column(db.String(120), unique=True)
    is_admin      = db.Column(db.Boolean, default=False)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)
    last_login    = db.Column(db.DateTime)

    def __repr__(self):
        return f'<User {self.email}>'

class Policy(db.Model):
    id             = db.Column(db.Integer, primary_key=True)
    agent_email    = db.Column(db.String(120), nullable=False)
    first_name     = db.Column(db.String(100))
    middle_initial = db.Column(db.String(10))
    last_name      = db.Column(db.String(100))
    dob            = db.Column(db.String(20))
    gender         = db.Column(db.String(10))
    mobile         = db.Column(db.String(30))
    home_phone     = db.Column(db.String(30))
    email          = db.Column(db.String(120))
    address1       = db.Column(db.String(200))
    address2       = db.Column(db.String(200))
    city           = db.Column(db.String(100))
    state          = db.Column(db.String(10))
    zip_code       = db.Column(db.String(20))
    county         = db.Column(db.String(100))
    mbi            = db.Column(db.String(30))
    carrier_member_id = db.Column(db.String(50))
    id_type        = db.Column(db.String(30))
    carrier        = db.Column(db.String(100))
    plan_name      = db.Column(db.String(200))
    cms_plan_id    = db.Column(db.String(50))
    effective_date = db.Column(db.String(20))
    term_date      = db.Column(db.String(20))
    term_reason    = db.Column(db.String(200))
    lis_status     = db.Column(db.String(50))
    medicaid_id    = db.Column(db.String(50))
    pcp            = db.Column(db.String(200))
    deceased_date  = db.Column(db.String(20))
    agent_name     = db.Column(db.String(100))
    source_carrier = db.Column(db.String(50))
    week_of        = db.Column(db.DateTime, default=datetime.utcnow)
    is_current     = db.Column(db.Boolean, default=True)

    def __repr__(self):
        return f'<Policy {self.first_name} {self.last_name} - {self.carrier}>'

class AuditLog(db.Model):
    id           = db.Column(db.Integer, primary_key=True)
    timestamp    = db.Column(db.DateTime, default=datetime.utcnow)
    file_name    = db.Column(db.String(200))
    carrier      = db.Column(db.String(100))
    rows_imported= db.Column(db.Integer)
    status       = db.Column(db.String(50))
    message      = db.Column(db.String(500))
    agent_email  = db.Column(db.String(120))
