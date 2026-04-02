import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-key-change-in-production'
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or 'sqlite:///founders_portal.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID')
    GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET')
    ALLOWED_DOMAIN = os.environ.get('ALLOWED_DOMAIN') or 'foundersinsuranceagency.com'
    ADMIN_EMAILS = os.environ.get('ADMIN_EMAILS') or 'tim@foundersinsuranceagency.com,aj@foundersinsuranceagency.com'
    APP_URL = os.environ.get('APP_URL') or 'http://localhost:5000'

    # Phase 3 — Quo (formerly OpenPhone) webhook secrets
    QUO_WEBHOOK_SIGNING_KEY = os.environ.get("QUO_WEBHOOK_SIGNING_KEY", "")
    # ^ Base64-encoded key from Quo dashboard — decoded to binary before HMAC use
    QUO_API_KEY = os.environ.get("QUO_API_KEY", "")
    # ^ Used in Authorization header (no Bearer prefix) for REST API calls to api.openphone.com
    RETELL_WEBHOOK_SECRET = os.environ.get("RETELL_WEBHOOK_SECRET", "")
    CALENDLY_WEBHOOK_SECRET = os.environ.get("CALENDLY_WEBHOOK_SECRET", "")
    HEALTHSHERPA_WEBHOOK_SECRET = os.environ.get("HEALTHSHERPA_WEBHOOK_SECRET", "")
    GOOGLE_MEET_PUBSUB_SUBSCRIPTION = os.environ.get("GOOGLE_MEET_PUBSUB_SUBSCRIPTION", "")
    TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID", "")
    TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "")
    TWILIO_FROM_NUMBER = os.environ.get("TWILIO_FROM_NUMBER", "")
    # Agency ID for single-tenant webhook fallback (used when agent lookup fails)
    DEFAULT_AGENCY_ID = int(os.environ.get("DEFAULT_AGENCY_ID", "1"))
