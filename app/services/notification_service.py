"""
Notification Service
Schema helpers for user notifications
"""
from __future__ import annotations

from sqlalchemy import inspect, text
from app.extensions import db


class NotificationService:
    """Helpers for user notifications schema."""

    @staticmethod
    def ensure_notification_schema():
        inspector = inspect(db.engine)
        if 'user_notifications' not in inspector.get_table_names():
            db.session.execute(text(
                'CREATE TABLE user_notifications ('
                'id INTEGER PRIMARY KEY AUTOINCREMENT, '
                'user_id INTEGER NOT NULL, '
                'message TEXT NOT NULL, '
                'attachment_path VARCHAR(255), '
                'created_at DATETIME, '
                'read_at DATETIME, '
                'sent_by INTEGER'
                ')'
            ))
            db.session.execute(text('CREATE INDEX IF NOT EXISTS ix_user_notifications_user_id ON user_notifications (user_id)'))
            db.session.execute(text('CREATE INDEX IF NOT EXISTS ix_user_notifications_created_at ON user_notifications (created_at)'))
            db.session.commit()
