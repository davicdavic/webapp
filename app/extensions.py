"""
Flask Extensions
Initialize all Flask extensions for the application
"""
from datetime import timedelta
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from flask_wtf import CSRFProtect
from flask_bcrypt import Bcrypt
from flask_caching import Cache
from flask_compress import Compress
try:
    import redis
except Exception:  # pragma: no cover - optional in local setups
    redis = None
try:
    from flask_session import Session
except Exception:  # pragma: no cover - optional dependency during local dev
    Session = None

# Initialize extensions
db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
csrf = CSRFProtect()
bcrypt = Bcrypt()
cache = Cache()
compress = Compress()
session_ext = Session() if Session else None


def init_extensions(app):
    """Initialize all Flask extensions with the app"""
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    bcrypt.init_app(app)
    try:
        cache.init_app(app)
    except Exception as exc:
        # Local fallback: keep app booting even if redis backend isn't available.
        app.logger.warning(f'Cache backend init failed, falling back to simple cache: {exc}')
        app.config['CACHE_TYPE'] = 'simple'
        cache.init_app(app)
    compress.init_app(app)

    # Shared Redis client (cache/session/game-state helpers can reuse this).
    redis_url = app.config.get('REDIS_URL') or app.config.get('CACHE_REDIS_URL')
    if redis_url and redis is not None:
        try:
            client = redis.Redis.from_url(redis_url, decode_responses=True)
            client.ping()
            app.extensions['redis_client'] = client
        except Exception as exc:
            app.logger.warning(f'Redis unavailable at {redis_url}; disabling redis_client fallback: {exc}')
            app.extensions['redis_client'] = None
    else:
        app.extensions['redis_client'] = None
    
    # Enable CSRF protection (always on unless explicitly disabled)
    if app.config.get('CSRF_ENABLED', True):
        csrf.init_app(app)
    
    # Configure login manager - PRO APP STYLE
    # User stays logged in like Facebook/X.com
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Please log in to continue'
    # Use basic protection to avoid forced re-logins when IP/User-Agent fingerprints drift.
    login_manager.session_protection = 'basic'  # Security level: basic, strong, or None
    
    # Session configuration for persistent login (like pro apps)
    # Use defaults only; do not override environment-specific config values.
    app.config.setdefault('SESSION_COOKIE_HTTPONLY', True)  # Prevent XSS attacks
    app.config.setdefault('SESSION_COOKIE_SAMESITE', 'Lax')  # CSRF protection while allowing navigation
    app.config.setdefault('PERMANENT_SESSION_LIFETIME', timedelta(days=30))
    app.config.setdefault('SESSION_REFRESH_EACH_REQUEST', True)
    app.config.setdefault('REMEMBER_COOKIE_DURATION', timedelta(days=30))
    app.config.setdefault('REMEMBER_COOKIE_REFRESH_EACH_REQUEST', True)

    if app.config.get('ENABLE_SERVER_SIDE_SESSIONS'):
        if session_ext is None:
            app.logger.warning('ENABLE_SERVER_SIDE_SESSIONS is set but Flask-Session is not installed')
        else:
            if app.config.get('SESSION_TYPE') == 'redis' and redis is None:
                app.logger.warning('Server-side sessions require redis package; disabling server-side sessions')
                return
            session_redis = app.config.get('SESSION_REDIS_URL')
            if session_redis and redis is not None:
                app.config['SESSION_REDIS'] = redis.Redis.from_url(session_redis, decode_responses=True)
            session_ext.init_app(app)
