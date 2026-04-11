"""
Merch Service
Schema helpers for merch store upgrades.
"""
from sqlalchemy import inspect, text

from app.extensions import db


class MerchService:
    """Helpers for merch store schema upgrades."""

    @staticmethod
    def ensure_merch_schema():
        """Best-effort schema patching for merch-related fields."""
        inspector = inspect(db.engine)
        table_names = set(inspector.get_table_names())

        alter_statements = []

        if 'products' in table_names:
            product_cols = {col['name'] for col in inspector.get_columns('products')}
            if 'product_type' not in product_cols:
                alter_statements.append('ALTER TABLE products ADD COLUMN product_type VARCHAR(20) DEFAULT \"digital\"')
            if 'contact_link' not in product_cols:
                alter_statements.append('ALTER TABLE products ADD COLUMN contact_link VARCHAR(255)')
            if 'physical_quantity' not in product_cols:
                alter_statements.append('ALTER TABLE products ADD COLUMN physical_quantity INTEGER DEFAULT 0')

        if 'merch_orders' in table_names:
            order_cols = {col['name'] for col in inspector.get_columns('merch_orders')}
            if 'product_type' not in order_cols:
                alter_statements.append('ALTER TABLE merch_orders ADD COLUMN product_type VARCHAR(20) DEFAULT \"digital\"')
            if 'shipping_name' not in order_cols:
                alter_statements.append('ALTER TABLE merch_orders ADD COLUMN shipping_name VARCHAR(120)')
            if 'shipping_country' not in order_cols:
                alter_statements.append('ALTER TABLE merch_orders ADD COLUMN shipping_country VARCHAR(120)')
            if 'shipping_city' not in order_cols:
                alter_statements.append('ALTER TABLE merch_orders ADD COLUMN shipping_city VARCHAR(120)')
            if 'shipping_phone' not in order_cols:
                alter_statements.append('ALTER TABLE merch_orders ADD COLUMN shipping_phone VARCHAR(40)')
            if 'shipping_lat' not in order_cols:
                alter_statements.append('ALTER TABLE merch_orders ADD COLUMN shipping_lat FLOAT')
            if 'shipping_lng' not in order_cols:
                alter_statements.append('ALTER TABLE merch_orders ADD COLUMN shipping_lng FLOAT')
            if 'shipping_location_text' not in order_cols:
                alter_statements.append('ALTER TABLE merch_orders ADD COLUMN shipping_location_text VARCHAR(255)')
            if 'delivery_eta' not in order_cols:
                alter_statements.append('ALTER TABLE merch_orders ADD COLUMN delivery_eta DATETIME')
            if 'delivered_at' not in order_cols:
                alter_statements.append('ALTER TABLE merch_orders ADD COLUMN delivered_at DATETIME')
            if 'refunded_at' not in order_cols:
                alter_statements.append('ALTER TABLE merch_orders ADD COLUMN refunded_at DATETIME')

        for statement in alter_statements:
            db.session.execute(text(statement))

        if alter_statements:
            db.session.commit()
