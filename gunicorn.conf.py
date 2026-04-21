"""Gunicorn configuration tuned for small-to-medium Render instances."""
import os

# Server socket
bind = f"0.0.0.0:{os.environ.get('PORT', '5000')}"
backlog = 2048

# Render containers can report misleading CPU counts, so keep the default modest.
workers = int(os.environ.get('WEB_CONCURRENCY', '2'))

# Worker class - use sync for compatibility
worker_class = 'sync'

# Timeouts
timeout = int(os.environ.get('GUNICORN_TIMEOUT', '60'))
graceful_timeout = int(os.environ.get('GUNICORN_GRACEFUL_TIMEOUT', '30'))
keepalive = 5

# Logging
accesslog = os.environ.get('GUNICORN_ACCESS_LOG', '-')
errorlog = os.environ.get('GUNICORN_ERROR_LOG', '-')
loglevel = os.environ.get('GUNICORN_LOG_LEVEL', 'info')
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# Process naming
proc_name = 'retroquest'

# Server mechanics
daemon = False
pidfile = None
umask = 0
user = None
group = None
tmp_upload_dir = None

# Keep startup isolated per worker to avoid surprises from import-time side effects.
preload_app = False

# Max requests per worker before recycling (prevents memory leaks)
max_requests = int(os.environ.get('MAX_REQUESTS', '1000'))
max_requests_jitter = 100

# SSL (if needed)
# keyfile = 'key.pem'
# certfile = 'cert.pem'

# Development reloader
reload = os.environ.get('FLASK_ENV') == 'development'
reload_engine = 'auto'
