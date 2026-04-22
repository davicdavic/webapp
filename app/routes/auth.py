"""
Auth Routes
User authentication (signup, login, logout)
"""
from flask import Blueprint, render_template, redirect, url_for, flash, request, session, current_app, jsonify
from flask_login import login_user, logout_user, login_required, current_user
from app.extensions import db
from app.models import User
from app.services import UserService
from app.validators import ValidationError, validate_password, validate_username

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/')
def index():
    """Home page - redirect to dashboard or login"""
    if current_user.is_authenticated:
        return redirect(url_for('missions.index'))
    return redirect(url_for('auth.login'))


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """User login page - PRO APP STYLE with remember me"""
    if current_user.is_authenticated:
        return redirect(url_for('missions.index'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        # Default to persistent login unless explicitly disabled.
        remember_raw = request.form.get('remember', 'true')
        remember = str(remember_raw).lower() in ('1', 'true', 'on', 'yes')

        if not username or not password:
            flash('Please enter username and password', 'error')
            return render_template('auth/login.html')

        user, message = UserService.authenticate_user(username, password)
        
        if user:
            # Login with remember me (persistent session like Facebook/X.com)
            # If remember is checked, stay logged in for 30 days
            login_user(user, remember=remember)
            session.permanent = True
            flash('Login successful!', 'success')
            next_page = request.args.get('next')
            return redirect(next_page or url_for('missions.index'))
        else:
            flash(message, 'error')

    return render_template('auth/login.html')


@auth_bp.route('/signup', methods=['GET', 'POST'])
def signup():
    """User registration page"""
    if current_user.is_authenticated:
        return redirect(url_for('missions.index'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')
        email = request.form.get('email', '').strip()

        try:
            validate_username(username)
            validate_password(password)
        except ValidationError as exc:
            flash(str(exc), 'error')
            return render_template('auth/signup.html')

        if password != confirm_password:
            flash('Passwords do not match', 'error')
            return render_template('auth/signup.html')

        # Create user
        user, message = UserService.create_user(username, password, email if email else None)

        if user:
            flash('Registration successful! Please login.', 'success')
            return redirect(url_for('auth.login'))
        else:
            flash(message, 'error')

    return render_template('auth/signup.html')


@auth_bp.route('/about-app')
def about_app():
    """About app page with feature guide and rules."""
    return render_template('auth/about_app.html')


@auth_bp.route('/logout', methods=['POST'])
@login_required
def logout():
    """User logout"""
    logout_user()
    flash('You have been logged out', 'info')
    return redirect(url_for('auth.login'))


@auth_bp.route('/logout', methods=['GET'])
def logout_get():
    """Prevent accidental logout via prefetch/crawlers; require POST for sign-out."""
    if current_user.is_authenticated:
        flash('Use the Logout button to sign out.', 'info')
        return redirect(url_for('missions.index'))
    return redirect(url_for('auth.login'))


@auth_bp.route('/check_username', methods=['POST'])
def check_username():
    """Check if username is available"""
    username = request.form.get('username', '').strip()
    try:
        username = validate_username(username)
    except ValidationError as exc:
        return jsonify({'available': False, 'message': str(exc)})

    admin_username = current_app.config.get('ADMIN_USER', 'admin')
    if username.lower() in {admin_username.lower(), 'admin'}:
        return jsonify({'available': False, 'message': 'This username is reserved'})
    
    existing = UserService.get_user_by_username(username)
    if existing:
        return jsonify({'available': False, 'message': 'Your username is already taken'})
    else:
        return jsonify({'available': True, 'message': 'Username is available'})
