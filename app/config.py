"""
RetroQuest Platform Configuration
Production-ready Flask configuration with environment variable support
Optimized for 100K+ users
"""
import os
from datetime import timedelta


def _bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ('1', 'true', 'yes', 'on')


class Config:
    """Base configuration class"""

    # Secret Key
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'
    AUTO_CREATE_SCHEMA_ON_START = _bool_env('AUTO_CREATE_SCHEMA_ON_START', True)

    # Database Configuration
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))
    PROJECT_ROOT = os.path.abspath(os.path.join(BASE_DIR, '..'))
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        f'sqlite:///{os.path.join(BASE_DIR, "..", "instance", "database.db")}'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True,
        'pool_recycle': int(os.environ.get('DB_POOL_RECYCLE') or '300'),
        'pool_size': int(os.environ.get('DB_POOL_SIZE') or '20'),
        'max_overflow': int(os.environ.get('DB_MAX_OVERFLOW') or '30'),
        'pool_timeout': int(os.environ.get('DB_POOL_TIMEOUT') or '30'),
    }

    # Cache Configuration - Optimized for high traffic
    # For production with 100K+ users, use Redis: CACHE_TYPE = 'redis'
    CACHE_TYPE = os.environ.get('CACHE_TYPE') or 'simple'
    REDIS_URL = os.environ.get('REDIS_URL') or 'redis://localhost:6379/0'
    CACHE_REDIS_URL = os.environ.get('CACHE_REDIS_URL') or REDIS_URL
    CACHE_DEFAULT_TIMEOUT = int(os.environ.get('CACHE_TIMEOUT') or '60')  # 1 minute default
    CACHE_KEY_PREFIX = 'retroquest:'
    
    # Aggressive caching settings for maximum speed
    CACHE_THRESHOLD = 500  # Cache at least 500 items
    CACHE_NULL_NONE = True  # Cache None results
    
    # Static file caching (for production) - aggressive
    SEND_FILE_MAX_AGE_DEFAULT = 86400  # 24 hours for static files
    SESSION_COOKIE_SECURE = False

    # Compression Configuration - Maximum compression for fastest transfer
    COMPRESS_MIMETYPES = ['text/html', 'text/css', 'text/javascript',
                         'application/javascript', 'application/json',
                         'image/svg+xml', 'application/xml', 'text/plain',
                         'application/vnd.ms-fontobject', 'application/x-font-ttf']
    COMPRESS_LEVEL = 9  # Maximum compression
    COMPRESS_MIN_SIZE = 200  # Compress even small files

    # Upload Configuration
    UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER') or os.path.join(BASE_DIR, 'static', 'uploads')
    MAX_CONTENT_LENGTH = 10 * 1024 * 1024  # 10 MB max file size
    MAX_WORDS_PER_FIELD = int(os.environ.get('MAX_WORDS_PER_FIELD') or '100')
    WORD_LIMIT_ENABLED = _bool_env('WORD_LIMIT_ENABLED', True)
    NOTIFICATION_ALLOWED_EXTENSIONS = {
        'png', 'jpg', 'jpeg', 'gif', 'webp',
        'pdf', 'zip', 'rar', 'txt', 'doc', 'docx'
    }
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp'}

    # Session Configuration
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)
    SESSION_COOKIE_NAME = os.environ.get('SESSION_COOKIE_NAME') or 'retroquest_session'
    SESSION_REFRESH_EACH_REQUEST = True
    REMEMBER_COOKIE_DURATION = timedelta(days=30)
    REMEMBER_COOKIE_REFRESH_EACH_REQUEST = True
    REMEMBER_COOKIE_SECURE = False

    # CSRF Protection (enabled by default)
    CSRF_ENABLED = _bool_env('CSRF_ENABLED', True)

    # Rate Limiting (per-IP + per-user)
    RATE_LIMIT_ENABLED = _bool_env('RATE_LIMIT_ENABLED', True)
    RATE_LIMIT_WINDOW_SECONDS = int(os.environ.get('RATE_LIMIT_WINDOW_SECONDS') or '60')
    RATE_LIMIT_PER_IP = int(os.environ.get('RATE_LIMIT_PER_IP') or '600')
    RATE_LIMIT_PER_USER = int(os.environ.get('RATE_LIMIT_PER_USER') or '300')
    RATE_LIMIT_TRUST_PROXY_HEADERS = _bool_env('RATE_LIMIT_TRUST_PROXY_HEADERS', False)
    RATE_LIMIT_EXEMPT_ENDPOINTS = ('static', 'healthz')

    # Optional server-side session storage (recommended for large clusters)
    ENABLE_SERVER_SIDE_SESSIONS = _bool_env('ENABLE_SERVER_SIDE_SESSIONS', False)
    SESSION_TYPE = os.environ.get('SESSION_TYPE') or 'redis'
    SESSION_REDIS_URL = os.environ.get('SESSION_REDIS_URL') or REDIS_URL
    SESSION_PERMANENT = True
    SESSION_USE_SIGNER = True
    SESSION_KEY_PREFIX = os.environ.get('SESSION_KEY_PREFIX') or 'retroquest:session:'

    # Blockchain Configuration
    START_BLOCKCHAIN_CHECKER = os.environ.get('START_BLOCKCHAIN_CHECKER', '1').lower() in ('1', 'true', 'yes', 'on')
    # Alchemy RPC endpoint for BNB Smart Chain
    BSC_RPC = os.environ.get('BSC_RPC') or 'https://bnb-mainnet.g.alchemy.com/v2/u1fXOEj6HM0QZhHGnXe3b'
    # Fallback RPC
    BSC_RPC_FALLBACK = os.environ.get('BSC_RPC_FALLBACK') or 'https://bsc-dataseed.binance.org/'
    
    # Wallet Configuration
    WALLET_ADDRESS = os.environ.get('WALLET_ADDRESS') or '0x907049603cf15E888327e67BB56C7AAE0ED638Fb'
    
    # Coin Contract Addresses (BEP20 on BSC)
    COIN_CONTRACTS = {
        'USDT': {
            'address': os.environ.get('USDT_CONTRACT') or '0x55d398326f99059fF775485246999027B3197955',
            'decimals': int(os.environ.get('USDT_DECIMALS') or '18'),
            'to_points': int(os.environ.get('USDT_TO_POINTS') or '4000'),
            'min_deposit': float(os.environ.get('MIN_DEPOSIT_USDT') or '5'),
        },
        'USDC': {
            'address': os.environ.get('USDC_CONTRACT') or '0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d',
            'decimals': 6,
            'to_points': int(os.environ.get('USDC_TO_POINTS') or '4000'),
            'min_deposit': float(os.environ.get('MIN_DEPOSIT_USDC') or '5'),
        },
    }

    # Allowed deposit coins in UI and validation
    ALLOWED_DEPOSIT_COINS = ('USDT', 'USDC')
    
    # Legacy config for backward compatibility
    USDT_CONTRACT = COIN_CONTRACTS['USDT']['address']
    USDT_DECIMALS = COIN_CONTRACTS['USDT']['decimals']
    USDT_TO_POINTS = COIN_CONTRACTS['USDT']['to_points']
    MIN_DEPOSIT_USDT = COIN_CONTRACTS['USDT']['min_deposit']
    
    # Deposit Configuration
    DEPOSIT_TIMEOUT = int(os.environ.get('DEPOSIT_TIMEOUT') or '1200')  # 20 minutes
    DEPOSIT_CONFIRMATIONS = int(os.environ.get('DEPOSIT_CONFIRMATIONS') or '3')
    DEPOSIT_SCAN_INTERVAL = int(os.environ.get('DEPOSIT_SCAN_INTERVAL') or '5')
    DEPOSIT_LOG_CHUNK_SIZE = int(os.environ.get('DEPOSIT_LOG_CHUNK_SIZE') or '1200')
    DEPOSIT_LOG_MIN_CHUNK_SIZE = int(os.environ.get('DEPOSIT_LOG_MIN_CHUNK_SIZE') or '25')
    DEPOSIT_LOOKBACK_BLOCKS = int(os.environ.get('DEPOSIT_LOOKBACK_BLOCKS') or '600')

    # Admin Configuration
    ADMIN_USER = os.environ.get('ADMIN_USER') or 'admin'
    ADMIN_PASS = os.environ.get('ADMIN_PASS') or 'Ab112211@$'

    # Game Configuration
    GAME_PORT = int(os.environ.get('GAME_PORT') or '3000')
    GAME_STATE_BACKEND = os.environ.get('GAME_STATE_BACKEND') or 'memory'
    GAME_STATE_PREFIX = os.environ.get('GAME_STATE_PREFIX') or 'retroquest:game'
    GAME_STATE_LOCK_TIMEOUT = int(os.environ.get('GAME_STATE_LOCK_TIMEOUT') or '10')
    GAME_STATE_LOCK_BLOCKING_TIMEOUT = int(os.environ.get('GAME_STATE_LOCK_BLOCKING_TIMEOUT') or '5')
    GAME_ROOM_TTL_SECONDS = int(os.environ.get('GAME_ROOM_TTL_SECONDS') or '7200')

    # Migration
    MIGRATIONS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'migrations')

    # Performance Settings
    # Maximum number of posts to load per page (optimized for large datasets)
    POSTS_PER_PAGE = int(os.environ.get('POSTS_PER_PAGE') or '15')

    # Work Requests
    WORK_REQUEST_FEE_TNNO = int(os.environ.get('WORK_REQUEST_FEE_TNNO') or '10000')

    # Response timeout
    RESPONSE_TIMEOUT = 30
    SLOW_REQUEST_THRESHOLD_MS = int(os.environ.get('SLOW_REQUEST_THRESHOLD_MS') or '250')

    # Enable query caching
    SQLALCHEMY_RECORD_QUERIES = False

    # JSON settings for faster encoding
    JSON_SORT_KEYS = False
    JSONIFY_PRETTYPRINT_REGULAR = False

class DevelopmentConfig(Config):
    """Development configuration"""
    DEBUG = True
    TESTING = False


class ProductionConfig(Config):
    """Production configuration - Optimized for 100K+ users"""
    DEBUG = False
    TESTING = False
    AUTO_CREATE_SCHEMA_ON_START = _bool_env('AUTO_CREATE_SCHEMA_ON_START', False)

    SESSION_COOKIE_SECURE = True
    REMEMBER_COOKIE_SECURE = True

    # Use Redis for caching/session/game-state in production
    CACHE_TYPE = os.environ.get('CACHE_TYPE') or 'redis'
    ENABLE_SERVER_SIDE_SESSIONS = _bool_env('ENABLE_SERVER_SIDE_SESSIONS', True)
    GAME_STATE_BACKEND = os.environ.get('GAME_STATE_BACKEND') or 'redis'

    # Database connection pool for production
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True,
        'pool_recycle': int(os.environ.get('DB_POOL_RECYCLE') or '300'),
        'pool_size': int(os.environ.get('DB_POOL_SIZE') or '80'),
        'max_overflow': int(os.environ.get('DB_MAX_OVERFLOW') or '120'),
        'pool_timeout': int(os.environ.get('DB_POOL_TIMEOUT') or '30'),
    }

    # Longer cache times for production
    CACHE_DEFAULT_TIMEOUT = int(os.environ.get('CACHE_TIMEOUT') or '300')  # 5 minutes


class TestingConfig(Config):
    """Testing configuration"""
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'


# Configuration dictionary
config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}
