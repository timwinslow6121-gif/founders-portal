import os
import json
from flask import Blueprint, redirect, url_for, session, request, render_template
from flask_login import login_user, logout_user, login_required
from google.oauth2 import id_token
from google_auth_oauthlib.flow import Flow
from google.auth.transport import requests as google_requests
from app.models import User
from app.extensions import db, login_manager
from datetime import datetime
@login_manager.user_loader
def load_user(user_id):
	return User.query.get(int(user_id))

auth = Blueprint('auth', __name__, url_prefix='/auth')

os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '0'

ALLOWED_DOMAIN  = os.environ.get('ALLOWED_DOMAIN', 'foundersinsuranceagency.com')
ADMIN_EMAILS    = [e.strip() for e in os.environ.get('ADMIN_EMAILS', '').split(',')]
APP_URL         = os.environ.get('APP_URL', 'https://portal.foundersinsuranceagency.com')
CLIENT_ID       = os.environ.get('GOOGLE_CLIENT_ID')
CLIENT_SECRET   = os.environ.get('GOOGLE_CLIENT_SECRET')

CLIENT_CONFIG = {
    "web": {
        "client_id":                   CLIENT_ID,
        "client_secret":               CLIENT_SECRET,
        "auth_uri":                    "https://accounts.google.com/o/oauth2/auth",
        "token_uri":                   "https://oauth2.googleapis.com/token",
        "redirect_uris":               [f"{APP_URL}/auth/callback"],
        "javascript_origins":          [APP_URL]
    }
}

def make_flow():
    flow = Flow.from_client_config(
        CLIENT_CONFIG,
        scopes=[
            'openid',
            'https://www.googleapis.com/auth/userinfo.email',
            'https://www.googleapis.com/auth/userinfo.profile'
        ]
    )
    flow.redirect_uri = f"{APP_URL}/auth/callback"
    return flow

@auth.route('/login')
def login():
    return render_template('login.html')

@auth.route('/google')
def google_login():
    flow = make_flow()
    authorization_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        hd=ALLOWED_DOMAIN
    )
    session['oauth_state'] = state
    return redirect(authorization_url)

@auth.route('/callback')
def callback():
    if 'oauth_state' not in session:
        return redirect(url_for('auth.login'))

    flow = make_flow()
    flow.fetch_token(authorization_response=request.url)

    credentials = flow.credentials
    request_session = google_requests.Request()

    id_info = id_token.verify_oauth2_token(
        credentials.id_token,
        request_session,
        CLIENT_ID
    )

    email  = id_info.get('email', '')
    domain = email.split('@')[-1] if '@' in email else ''

    if domain != ALLOWED_DOMAIN:
        return render_template('login.html',
            error='Access restricted to @foundersinsuranceagency.com accounts.')

    user = User.query.filter_by(email=email).first()
    if not user:
        user = User(
            email     = email,
            name      = id_info.get('name', ''),
            is_admin  = email in ADMIN_EMAILS
        )
        db.session.add(user)
    else:
        user.last_login = datetime.utcnow()
        user.is_admin   = email in ADMIN_EMAILS

    db.session.commit()
    login_user(user, remember=True)

    return redirect(url_for('main.dashboard'))

@auth.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('auth.login'))
