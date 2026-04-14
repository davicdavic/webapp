"""
Gunicorn Configuration
Production WSGI server configuration - Optimized for 100K+ users
"""
import os
import multiprocessing

# Server socket
bind = f"0.0.0.0:{os.environ.get('PORT', '5000')}"
backlog = 2048

# Worker processes - Use multiple workers for concurrency
# Rule of thumb: 2-4 workers per CPU core
# For 100K users, use more workers with gevent
workers = int(os.environ.get('WEB_CONCURRENCY', multiprocessing.cpu_count() * 2 + 1))

# Worker class - Use sync for compatibility (no extra dependencies needed)
worker_class = 'sync'

# Worker connections - Number of simultaneous clients per worker
worker_connections = int(os.environ.get('WORKER_CONNECTIONS', '1000'))

# Timeouts
timeout = int(os.environ.get('GUNICORN_TIMEOUT', '30'))
graceful_timeout = 30
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

# Preload app for memory efficiency (shared memory between workers)
preload_app = True

# Max requests per worker before recycling (prevents memory leaks)
max_requests = int(os.environ.get('MAX_REQUESTS', '1000'))
max_requests_jitter = 100

# SSL (if needed)
# keyfile = 'key.pem'
# certfile = 'cert.pem'

# Development reloader
reload = os.environ.get('FLASK_ENV') == 'development'
reload_engine = 'auto'

# For testing high concurrency locally:
# To test with 1000 concurrent users: ab -n 1000 -c 100 http://localhost:5000/
