"""
Routes Package
All Flask blueprints for the RetroQuest Platform
"""
from app.routes.auth import auth_bp
from app.routes.missions import missions_bp
from app.routes.deposit import cloudpaya_bp, deposit_bp
from app.routes.feed import feed_bp
from app.routes.admin import admin_bp
from app.routes.profile import profile_bp
from app.routes.work import work_bp
from app.routes.api import api_bp
from app.routes.game import game_bp

__all__ = [
    'auth_bp',
    'missions_bp',
    'deposit_bp',
    'cloudpaya_bp',
    'feed_bp',
    'admin_bp',
    'profile_bp',
    'work_bp',
    'api_bp',
    'game_bp'
]
