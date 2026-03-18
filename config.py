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
