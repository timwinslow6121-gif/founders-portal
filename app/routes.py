from flask import Blueprint, render_template, jsonify
from flask_login import login_required, current_user

main = Blueprint('main', __name__)

@main.route('/')
@login_required
def dashboard():
    return render_template('dashboard.html', user=current_user)

@main.route('/health')
def health():
    return jsonify({'status': 'ok', 'message': 'Founders Portal is running'})
