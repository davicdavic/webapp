"""
Deposit Service
Business logic for cryptocurrency deposits
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_DOWN

from flask import current_app
from sqlalchemy import inspect, text

from app.extensions import db
from app.models import Deposit


AMOUNT_QUANT = Decimal('0.000001')
UNIQUE_STEP = Decimal('0.000001')
UNIQUE_STEPS = 9999


class DepositService:
    """Service for managing cryptocurrency deposits."""

    @staticmethod
    def ensure_deposit_schema():
        """Best-effort schema patching for existing databases without migrations."""
        inspector = inspect(db.engine)
        if 'deposits' not in inspector.get_table_names():
            return

        existing_columns = {col['name'] for col in inspector.get_columns('deposits')}
        alter_statements = []

        if 'expected_amount' not in existing_columns:
            alter_statements.append('ALTER TABLE deposits ADD COLUMN expected_amount NUMERIC(24, 6)')
        if 'expires_at' not in existing_columns:
            alter_statements.append('ALTER TABLE deposits ADD COLUMN expires_at DATETIME')
        if 'credited_at' not in existing_columns:
            alter_statements.append('ALTER TABLE deposits ADD COLUMN credited_at DATETIME')
        if 'confirmations' not in existing_columns:
            alter_statements.append('ALTER TABLE deposits ADD COLUMN confirmations INTEGER DEFAULT 0')
        if 'tx_block_number' not in existing_columns:
            alter_statements.append('ALTER TABLE deposits ADD COLUMN tx_block_number BIGINT')
        if 'scan_from_block' not in existing_columns:
            alter_statements.append('ALTER TABLE deposits ADD COLUMN scan_from_block BIGINT')
        if 'last_scanned_block' not in existing_columns:
            alter_statements.append('ALTER TABLE deposits ADD COLUMN last_scanned_block BIGINT')
        if 'coin_type' not in existing_columns:
            alter_statements.append("ALTER TABLE deposits ADD COLUMN coin_type VARCHAR(20) DEFAULT 'USDT'")
        # ensure blockchain_state table exists if not
        if 'blockchain_state' not in inspector.get_table_names():
            alter_statements.append('CREATE TABLE blockchain_state (coin_type VARCHAR(20) PRIMARY KEY, last_block BIGINT NOT NULL DEFAULT 0)')
        # ensure the new coin_type column exists for multi-coin support
        if 'coin_type' not in existing_columns:
            alter_statements.append("ALTER TABLE deposits ADD COLUMN coin_type VARCHAR(20) DEFAULT 'USDT'")
        # add seller flag to users if missing (shared patch location)
        user_cols = inspector.get_columns('users')
        user_col_names = {col['name'] for col in user_cols}
        if 'is_seller' not in user_col_names:
            alter_statements.append('ALTER TABLE users ADD COLUMN is_seller BOOLEAN DEFAULT 0')
        if 'seller_commission_rate' not in user_col_names:
            alter_statements.append('ALTER TABLE users ADD COLUMN seller_commission_rate NUMERIC(5,4) DEFAULT 0.03')

        # add seller_id to products if missing (enables per-user stores)
        if 'products' in inspector.get_table_names():
            prod_cols = {col['name'] for col in inspector.get_columns('products')}
            if 'seller_id' not in prod_cols:
                alter_statements.append('ALTER TABLE products ADD COLUMN seller_id INTEGER')
                alter_statements.append('CREATE INDEX IF NOT EXISTS ix_products_seller_id ON products (seller_id)')

        for statement in alter_statements:
            db.session.execute(text(statement))

        # Legacy status migration
        db.session.execute(text("UPDATE deposits SET status = 'success' WHERE status = 'completed'"))
        db.session.execute(text("UPDATE deposits SET status = 'expired' WHERE status = 'cancelled'"))

        # Indexes for high-traffic scanning and matching
        db.session.execute(text('CREATE INDEX IF NOT EXISTS ix_deposits_status_created ON deposits (status, created_at)'))
        db.session.execute(text('CREATE INDEX IF NOT EXISTS ix_deposits_expected_amount ON deposits (expected_amount)'))
        db.session.execute(text('CREATE INDEX IF NOT EXISTS ix_deposits_expires_at ON deposits (expires_at)'))
        db.session.commit()

        try:
            db.session.execute(text('CREATE UNIQUE INDEX IF NOT EXISTS ux_deposits_tx_hash ON deposits (tx_hash)'))
            db.session.commit()
        except Exception:
            # If legacy duplicate data exists, keep runtime duplicate checks active.
            db.session.rollback()

    @staticmethod
    def _to_decimal(value) -> Decimal:
        try:
            dec = Decimal(str(value)).quantize(AMOUNT_QUANT)
        except (InvalidOperation, TypeError, ValueError):
            raise ValueError('Invalid deposit amount.')

        if dec <= 0:
            raise ValueError('Amount must be greater than 0.')

        return dec

    @staticmethod
    def _generate_unique_expected_amount(base_amount: Decimal) -> Decimal:
        """Generate an exact unique amount by adding a micro suffix."""
        now = datetime.utcnow()

        for _ in range(60):
            suffix = UNIQUE_STEP * random.randint(1, UNIQUE_STEPS)
            candidate = (base_amount + suffix).quantize(AMOUNT_QUANT)

            exists = Deposit.query.filter(
                Deposit.status == 'pending',
                Deposit.expected_amount == candidate,
                Deposit.expires_at > now
            ).first()

            if not exists:
                return candidate

        # Deterministic fallback if random attempts collide under very high concurrency.
        for step in range(1, UNIQUE_STEPS + 1):
            candidate = (base_amount + (UNIQUE_STEP * step)).quantize(AMOUNT_QUANT)
            exists = Deposit.query.filter(
                Deposit.status == 'pending',
                Deposit.expected_amount == candidate,
                Deposit.expires_at > now
            ).first()
            if not exists:
                return candidate

        raise ValueError('Unable to generate unique amount. Please retry.')

    @staticmethod
    def _suggest_scan_start_block() -> int | None:
        try:
            from app.services.blockchain_service import BlockchainService

            service = BlockchainService()
            if not service.is_available():
                return None

            current_block = service.get_current_block()
            if current_block is None:
                return None

            return max(0, int(current_block) - 2)
        except Exception:
            return None

    @staticmethod
    def create_deposit(user_id, raw_amount, coin_type='USDT'):
        """Create a new pending crypto deposit request for a specific coin."""
        amount = DepositService._to_decimal(raw_amount)

        # Get coin configuration
        coin_contracts = current_app.config.get('COIN_CONTRACTS', {})
        if coin_type not in coin_contracts:
            raise ValueError(f'Unsupported coin type: {coin_type}')

        coin_config = coin_contracts[coin_type]
        min_deposit = Decimal(str(coin_config.get('min_deposit', 5))).quantize(AMOUNT_QUANT)
        
        if amount < min_deposit:
            raise ValueError(f'Minimum {coin_type} deposit is {min_deposit.normalize()}.')

        expected_amount = DepositService._generate_unique_expected_amount(amount)

        to_points = Decimal(str(coin_config.get('to_points', 4000)))
        points_amount = int((amount * to_points).to_integral_value(rounding=ROUND_DOWN))

        timeout_seconds = int(current_app.config.get('DEPOSIT_TIMEOUT', 1200))
        now = datetime.utcnow()
        expires_at = now + timedelta(seconds=timeout_seconds)

        deposit = Deposit(
            user_id=user_id,
            coin_type=coin_type,
            usdt_amount=float(amount),
            expected_amount=expected_amount,
            points_amount=points_amount,
            status='pending',
            blockchain_status='unverified',
            created_at=now,
            expires_at=expires_at,
            scan_from_block=DepositService._suggest_scan_start_block(),
            confirmations=0,
        )

        db.session.add(deposit)
        db.session.commit()

        return deposit

    @staticmethod
    def get_user_deposits(user_id, status=None, page=None, per_page=20, include_archived=False):
        """Get user's deposits."""
        query = Deposit.query.filter_by(user_id=user_id)
        if not include_archived:
            query = query.filter(Deposit.is_archived.is_(False))
        if status:
            query = query.filter_by(status=status)
        query = query.order_by(Deposit.created_at.desc())
        if page is not None:
            return query.paginate(page=page, per_page=per_page, error_out=False)
        return query.all()

    @staticmethod
    def get_deposit_by_id(deposit_id):
        """Get deposit by ID."""
        return Deposit.query.get(deposit_id)

    @staticmethod
    def get_pending_deposits(limit=3000):
        """Get pending deposits ordered by age for blockchain scanning."""
        return Deposit.query.filter_by(status='pending')\
            .order_by(Deposit.created_at.asc())\
            .limit(limit)\
            .all()

    @staticmethod
    def expire_overdue_deposits():
        """Expire unpaid deposits after timeout."""
        now = datetime.utcnow()

        overdue = Deposit.query.filter(
            Deposit.status == 'pending',
            Deposit.expires_at.isnot(None),
            Deposit.expires_at <= now
        ).all()

        for deposit in overdue:
            deposit.status = 'expired'
            deposit.blockchain_status = 'expired'
            deposit.last_check = now

        if overdue:
            db.session.commit()

        return len(overdue)

    @staticmethod
    def get_all_deposits(limit=100):
        """Get all deposits ordered by creation time."""
        return Deposit.query.order_by(Deposit.created_at.desc()).limit(limit).all()

    @staticmethod
    def get_deposit_stats():
        """Get deposit statistics."""
        total = Deposit.query.count()
        pending = Deposit.query.filter_by(status='pending').count()
        success = Deposit.query.filter_by(status='success').count()
        expired = Deposit.query.filter_by(status='expired').count()

        total_usdt = db.session.query(db.func.sum(Deposit.usdt_amount))\
            .filter(Deposit.status == 'success').scalar() or 0

        total_coins = db.session.query(db.func.sum(Deposit.coins_added))\
            .filter(Deposit.status == 'success').scalar() or 0

        return {
            'total': total,
            'pending': pending,
            'success': success,
            'expired': expired,
            'total_usdt': float(total_usdt),
            'total_coins': int(total_coins),
        }
