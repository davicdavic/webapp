"""
Flask Application Factory
Create and configure the Flask application with all blueprints and extensions
"""
import os
from flask import Flask, make_response, jsonify, flash, request, redirect, url_for
from sqlalchemy import text
from app.config import config
from app.extensions import init_extensions, db, login_manager
from app.game_state import init_game_state


def create_app(config_name=None):
    """Application factory function"""

    # Determine config to use
    if config_name is None:
        config_name = os.environ.get('FLASK_ENV', 'development')

    # Create Flask app
    app = Flask(__name__,
                template_folder='templates',
                static_folder='static')

    # Load configuration
    app.config.from_object(config.get(config_name, config['development']))

    if config_name == 'production':
        missing_env = [
            name for name in (
                'SECRET_KEY',
                'DATABASE_URL',
                'NOWPAYMENTS_API_KEY',
                'NOWPAYMENTS_IPN_SECRET',
            )
            if not os.environ.get(name)
        ]
        if missing_env:
            raise RuntimeError(
                'Missing required production environment variables: ' + ', '.join(missing_env)
            )

    # Initialize extensions
    init_extensions(app)
    init_game_state(app)

    # Rate limiting (per-IP + per-user)
    from app.security import enforce_rate_limit

    @app.before_request
    def _enforce_rate_limit():
        enforce_rate_limit()

    @app.get('/healthz')
    def healthz():
        return jsonify({'status': 'ok'}), 200

    # Add aggressive caching headers for maximum speed
    @app.after_request
    def add_cache_headers(response):
        """Add caching headers for maximum browser caching"""
        # Cache static assets for 1 week
        if request := response.headers.get('Content-Type', ''):
            if 'javascript' in request or 'css' in request or 'image' in request:
                response.headers['Cache-Control'] = 'public, max-age=604800, immutable'
            elif 'html' in request:
                # Don't cache HTML in production for dynamic content
                if app.config.get('ENV') != 'production':
                    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
                else:
                    response.headers['Cache-Control'] = 'public, max-age=60'
        
        # Add compression header
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        
        return response

    # Create upload folder with absolute path
    upload_folder = app.config.get('UPLOAD_FOLDER')
    if not os.path.isabs(upload_folder):
        upload_folder = os.path.join(os.path.dirname(__file__), '..', upload_folder)
    os.makedirs(upload_folder, exist_ok=True)

    # Setup login manager user loader
    @login_manager.user_loader
    def load_user(user_id):
        from app.models import User
        return User.query.get(int(user_id))

    # Register blueprints
    register_blueprints(app)

    # Register error handlers
    register_error_handlers(app)

    # Register context processors
    register_context_processors(app)

    # Register custom filters
    register_filters(app)

    # Create/ensure schema in development-style environments.
    if app.config.get('AUTO_CREATE_SCHEMA_ON_START', True):
        # Ensure database directory exists for SQLite
        if 'sqlite' in app.config['SQLALCHEMY_DATABASE_URI']:
            db_path = app.config['SQLALCHEMY_DATABASE_URI'].replace('sqlite:///', '')
            if db_path and db_path != ':memory:':
                db_dir = os.path.dirname(db_path)
                if db_dir:
                    os.makedirs(db_dir, exist_ok=True)
        with app.app_context():
            def safe_schema_step(step_name, func):
                try:
                    func()
                except Exception as exc:
                    db.session.rollback()
                    db.session.remove()
                    print(f"Warning: {step_name} failed during startup: {exc}")

            safe_schema_step('db.create_all', lambda: db.create_all())
            safe_schema_step('DepositService.ensure_deposit_schema', lambda: __import__('app.services.deposit_service', fromlist=['DepositService']).DepositService.ensure_deposit_schema())
            safe_schema_step('SellerService.ensure_seller_schema', lambda: __import__('app.services.seller_service', fromlist=['SellerService']).SellerService.ensure_seller_schema())
            safe_schema_step('NotificationService.ensure_notification_schema', lambda: __import__('app.services.notification_service', fromlist=['NotificationService']).NotificationService.ensure_notification_schema())
            safe_schema_step('MerchService.ensure_merch_schema', lambda: __import__('app.services.merch_service', fromlist=['MerchService']).MerchService.ensure_merch_schema())
            safe_schema_step('HistoryService.ensure_history_schema', lambda: __import__('app.services.history_service', fromlist=['HistoryService']).HistoryService.ensure_history_schema())
            safe_schema_step('ensure_runtime_indexes', ensure_runtime_indexes)
            safe_schema_step('optimize_database', optimize_database)

            # Create admin user if not exists
            from app.models import User
            admin_username = app.config.get('ADMIN_USER', 'admin')
            admin_pass = app.config.get('ADMIN_PASS', 'Ab112211@$')
            def create_admin_user():
                if not User.query.filter_by(username=admin_username).first():
                    admin_user = User(username=admin_username, role='admin')
                    admin_user.set_password(admin_pass)
                    db.session.add(admin_user)
                    db.session.commit()
            safe_schema_step('create_admin_user', create_admin_user)

    # Start background tasks
    register_background_tasks(app)

    return app


def register_blueprints(app):
    """Register all Flask blueprints"""
    from app.routes.auth import auth_bp
    from app.routes.missions import missions_bp
    from app.routes.deposit import nowpayments_bp, deposit_bp
    from app.routes.feed import feed_bp
    from app.routes.admin import admin_bp
    from app.routes.profile import profile_bp
    from app.routes.work import work_bp
    from app.routes.api import api_bp
    from app.routes.game import game_bp
    from app.routes.merch import merch_bp
    from app.routes.history import history_bp

    # Register blueprints with URL prefixes
    app.register_blueprint(auth_bp)
    app.register_blueprint(missions_bp, url_prefix='/missions')
    app.register_blueprint(deposit_bp, url_prefix='/deposit')
    app.register_blueprint(nowpayments_bp)
    app.register_blueprint(feed_bp, url_prefix='/feed')
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(profile_bp, url_prefix='/profile')
    app.register_blueprint(work_bp, url_prefix='/work')
    app.register_blueprint(api_bp, url_prefix='/api')
    app.register_blueprint(game_bp, url_prefix='/game')
    app.register_blueprint(merch_bp, url_prefix='/store')
    app.register_blueprint(history_bp)


def register_error_handlers(app):
    """Register error handlers"""
    from flask import render_template

    @app.errorhandler(404)
    def not_found_error(error):
        return render_template('errors/404.html'), 404

    @app.errorhandler(500)
    def internal_error(error):
        db.session.rollback()
        return render_template('errors/500.html'), 500

    @app.errorhandler(403)
    def forbidden_error(error):
        return render_template('errors/403.html'), 403

    @app.errorhandler(400)
    def bad_request_error(error):
        return render_template('errors/400.html'), 400

    @app.errorhandler(413)
    def request_entity_too_large(error):
        return render_template('errors/400.html'), 413

    @app.errorhandler(429)
    def rate_limited_error(error):
        return render_template('errors/429.html'), 429


def register_context_processors(app):
    """Register template context processors"""
    from flask import g
    from flask_login import current_user
    from datetime import datetime, timedelta
    import math
    from app.utils import count_words

    @app.before_request
    def before_request():
        """Make current user available in templates"""
        g.current_user = current_user

    @app.before_request
    def seller_expiry_reminder():
        """Auto-remind sellers before plan expiry (once per day)."""
        if not current_user.is_authenticated:
            return
        if current_user.is_admin():
            return
        if not current_user.is_seller:
            return
        expires_at = current_user.seller_expires_at
        if not expires_at:
            return
        if request.method != 'GET':
            return
        if request.blueprint in {'api'}:
            return
        if request.endpoint in {'static', 'healthz'}:
            return

        now = datetime.utcnow()
        if expires_at <= now:
            return

        seconds_left = (expires_at - now).total_seconds()
        days_left = int(math.ceil(seconds_left / 86400))
        if days_left > 7:
            return

        last = current_user.seller_reminder_sent_at
        if last and (now - last) < timedelta(hours=24):
            return

        if days_left == 1:
            message = 'Your seller plan expires in 1 day. Renew to keep products visible.'
        else:
            message = f'Your seller plan expires in {days_left} days. Renew to keep products visible.'

        flash(message, 'warning')
        current_user.seller_reminder_sent_at = now
        db.session.commit()

    @app.before_request
    def enforce_word_limit():
        """Enforce max word count on submitted text fields."""
        if not app.config.get('WORD_LIMIT_ENABLED', True):
            return
        if request.method not in {'POST', 'PUT', 'PATCH'}:
            return
        if not request.form:
            return

        max_words = int(app.config.get('MAX_WORDS_PER_FIELD', 100))
        for _, value in request.form.items():
            if not isinstance(value, str):
                continue
            if count_words(value) > max_words:
                message = f'Maximum {max_words} words allowed.'
                if request.blueprint == 'api':
                    return jsonify({'error': message}), 400
                flash(message, 'error')
                return redirect(request.referrer or url_for('missions.index'))

    @app.context_processor
    def inject_global_badges():
        """Inject lightweight notification counts for global UI badges."""
        if not current_user.is_authenticated:
            return {}
        from app.models import UserNotification
        notif_count = UserNotification.query.filter_by(user_id=current_user.id, read_at=None).count()
        return {
            'global_notif_count': notif_count
        }


def register_filters(app):
    """Register custom Jinja2 filters"""
    import hashlib
    import os
    from flask import url_for

    @app.template_filter('format_number')
    def format_number(value):
        """Format number with thousands separator, supports up to 99,999,999"""
        if value is None:
            return '0'
        try:
            val = int(value)
            # Format with M (million) for values >= 1,000,000
            if val >= 10000000:
                return f'{val/1000000:.1f}M'
            elif val >= 1000000:
                return f'{val/1000000:.0f}M'
            elif val >= 100000:
                return f'{val/1000:.0f}K'
            else:
                return f"{val:,}"
        except (ValueError, TypeError):
            return str(value)

    @app.template_filter('lazy_img')
    def lazy_img(path, alt='', css_class=''):
        """Generate an optimized img tag with lazy loading"""
        if not path:
            return ''
        
        # Ensure path starts with uploads/
        if not path.startswith('uploads/'):
            path = f'uploads/{path}'
        
        # Get the static URL
        img_url = url_for('static', filename=path)
        
        # Generate unique placeholder based on path for consistent loading
        placeholder = f'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 300"%3E%3Crect fill="%23f0f0f0" width="400" height="300"/%3E%3C/svg%3E'
        
        class_attr = f'class="{css_class}"' if css_class else ''
        alt_attr = f'alt="{alt}"' if alt else 'alt=""'
        
        # Use data-src for lazy loading, src for placeholder
        return f'<img src="{placeholder}" data-src="{img_url}" {class_attr} {alt_attr} loading="lazy" width="400" height="300">'

    @app.template_filter('static_path')
    def static_path(value):
        """Normalize a stored file path for use with `url_for('static', filename=...)`.
        The database may contain values like 'missions/file.png' or 'uploads/missions/file.png'.
        This filter ensures the returned path always begins with 'uploads/'.
        """
        if not value:
            return ''
        # strip any leading slashes
        v = value.lstrip('/')
        if v.startswith('uploads/'):
            return v
        return f"uploads/{v}"

    @app.template_filter('static_exists')
    def static_exists(value):
        """Return True if the normalized static file exists on disk."""
        if not value:
            return False
        path = static_path(value)
        full = os.path.join(app.static_folder, path)
        return os.path.exists(full)

    @app.template_filter('static_version')
    def static_version(filename):
        """Add cache-busting version hash to static file URL."""
        try:
            filepath = os.path.join(app.static_folder, filename)
            if os.path.exists(filepath):
                with open(filepath, 'rb') as f:
                    file_hash = hashlib.md5(f.read()).hexdigest()[:8]
                return f"{filename}?v={file_hash}"
        except Exception:
            pass
        return filename

    @app.template_global('asset_url')
    def asset_url(filename):
        """Build static URL with stable file hash for cache-busting."""
        try:
            filepath = os.path.join(app.static_folder, filename)
            if os.path.exists(filepath):
                with open(filepath, 'rb') as f:
                    file_hash = hashlib.md5(f.read()).hexdigest()[:8]
                return url_for('static', filename=filename, v=file_hash)
        except Exception:
            pass
        return url_for('static', filename=filename)

    @app.template_filter('process_post_content')
    def process_post_content(content):
        """Process post content for 4chan-style formatting:
        - Greentext (>text)
        - Reply links (>>123456)
        """
        if not content:
            return ''

        import re

        # First escape HTML to prevent XSS
        content = content.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

        # Process greentext (>text) - lines starting with >
        content = re.sub(r'^(&gt;.*)$', r'<span class="greentext">\1</span>', content, flags=re.MULTILINE)

        # Process reply links (>>123456) - capture >> and number separately
        content = re.sub(r'(&gt;&gt;)(\d+)', r'<span class="reply-link" onclick="scrollToPost(\2)">\1\2</span>', content)

        # Convert newlines to <br>
        content = content.replace('\n', '<br>')

        return content


def register_background_tasks(app):
    """Register background tasks"""
    from app.services.blockchain_service import BlockchainChecker

    if not app.config.get('START_BLOCKCHAIN_CHECKER', True):
        app.logger.info('Blockchain checker disabled by config')
        return

    # Initialize blockchain checker
    checker = BlockchainChecker(app)
    checker.start()


def ensure_runtime_indexes():
    """Create missing runtime indexes for high-traffic pages."""
    from sqlalchemy import text
    db.session.execute(text('CREATE INDEX IF NOT EXISTS ix_users_coins ON users (coins)'))
    db.session.execute(text('CREATE INDEX IF NOT EXISTS ix_posts_parent_created ON posts (parent_id, created_at)'))
    db.session.execute(text('CREATE INDEX IF NOT EXISTS ix_user_missions_arch_created ON user_missions (is_archived, created_at)'))
    db.session.execute(text('CREATE INDEX IF NOT EXISTS ix_work_requests_arch_created ON work_requests (is_archived, created_at)'))
    db.session.execute(text('CREATE INDEX IF NOT EXISTS ix_service_orders_arch_created ON service_orders (is_archived, created_at)'))
    db.session.execute(text('CREATE INDEX IF NOT EXISTS ix_withdraw_requests_arch_created ON withdraw_requests (is_archived, created_at)'))
    db.session.execute(text('CREATE INDEX IF NOT EXISTS ix_deposits_arch_created ON deposits (is_archived, created_at)'))
    db.session.execute(text('CREATE INDEX IF NOT EXISTS ix_merch_orders_arch_created ON merch_orders (is_archived, created_at)'))
    db.session.commit()


def optimize_database():
    """Optimize database for better performance - enable WAL mode and pragmas."""
    from sqlalchemy import text

    engine_url = str(db.engine.url).lower()
    if 'sqlite' not in engine_url:
        return

    # Enable WAL mode for better concurrent read/write performance
    try:
        db.session.execute(text('PRAGMA journal_mode=WAL'))
        db.session.execute(text('PRAGMA synchronous=NORMAL'))
        db.session.execute(text('PRAGMA cache_size=-64000'))  # 64MB cache
        db.session.execute(text('PRAGMA temp_store=MEMORY'))
        db.session.commit()
    except Exception:
        # WAL mode may not be available on all SQLite versions
        pass
