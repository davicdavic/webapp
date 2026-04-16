"""
Deposit Routes
Cryptocurrency deposit handling
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import login_required, current_user

from app.services import DepositService
from app.services.history_service import HistoryService
from app.utils import generate_qr_code


deposit_bp = Blueprint('deposit', __name__)
cloudpaya_bp = Blueprint('cloudpaya', __name__)


def _to_decimal(value) -> Decimal:
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal('0')


def _format_usdt(value) -> str:
    dec = _to_decimal(value)
    return f'{dec.quantize(Decimal("0.000001")):f}'.rstrip('0').rstrip('.')


def _normalize_network(network: str) -> str:
    return (network or '').strip().upper()


@cloudpaya_bp.route('/create-deposit', methods=['POST'])
@login_required
def create_deposit():
    """Create a new CloudPaya deposit and redirect the user to the payment URL."""
    amount = (request.form.get('amount') or '').strip()
    network = _normalize_network(request.form.get('network') or '')

    try:
        deposit, payment_url = DepositService.create_cloudpaya_deposit(
            user_id=current_user.id,
            raw_amount=amount,
            network=network,
        )
    except ValueError as exc:
        flash(str(exc), 'error')
        return redirect(url_for('deposit.index'))
    except RuntimeError as exc:
        flash(str(exc), 'error')
        return redirect(url_for('deposit.index'))

    return redirect(payment_url)


@cloudpaya_bp.route('/webhook', methods=['POST'])
def webhook():
    """Handle CloudPaya webhook callbacks to finalize deposit crediting."""
    payload = request.get_json(silent=True)
    if payload is None:
        return jsonify({'error': 'Invalid JSON payload.'}), 400

    payment_id = (
        payload.get('payment_id')
        or payload.get('paymentId')
        or payload.get('id')
        or payload.get('reference')
    )
    status = (
        payload.get('status')
        or payload.get('payment_status')
        or payload.get('transaction_status')
        or ''
    ).strip().lower()

    if not payment_id:
        return jsonify({'error': 'Missing payment_id.'}), 400

    deposit = DepositService.get_deposit_by_payment_id(payment_id)
    if not deposit:
        return jsonify({'error': 'Deposit not found.'}), 404

    try:
        if status == 'confirmed':
            DepositService.complete_deposit_payment(payment_id, status)
    except Exception as exc:
        return jsonify({'error': str(exc)}), 500

    return 'ok', 200


@cloudpaya_bp.route('/success')
def success():
    return render_template('deposit/success.html')


@deposit_bp.route('/')
@login_required
def index():
    """Deposit dashboard."""
    HistoryService.archive_due_items(user_id=current_user.id)
    page = request.args.get('page', 1, type=int)
    deposits = DepositService.get_user_deposits(current_user.id, page=page, per_page=20)
    coin_contracts = current_app.config.get('COIN_CONTRACTS', {})
    allowed = set(current_app.config.get('ALLOWED_DEPOSIT_COINS', ())) or set(coin_contracts.keys())
    
    # Prepare coin choices for dropdown
    coins = [
        {'type': coin, 'config': config}
        for coin, config in coin_contracts.items()
        if coin in allowed
    ]
    
    return render_template(
        'deposit/index.html',
        deposits=deposits,
        coins=coins,
        wallet_address=current_app.config.get('WALLET_ADDRESS'),
    )


@deposit_bp.route('/create', methods=['POST'])
@login_required
def create():
    """Legacy deposit creation is disabled. Use CloudPaya deposit flow."""
    flash('Legacy deposit creation is disabled. Please use the new deposit form.', 'warning')
    return redirect(url_for('deposit.index'))


@deposit_bp.route('/<int:deposit_id>')
@login_required
def view(deposit_id):
    """Payment page for a specific deposit."""
    deposit = DepositService.get_deposit_by_id(deposit_id)

    if not deposit or deposit.user_id != current_user.id:
        flash('Deposit not found', 'error')
        return redirect(url_for('deposit.index'))

    wallet_address = current_app.config.get('WALLET_ADDRESS')
    coin_type = deposit.coin_type or 'USDT'
    expected_amount = deposit.expected_amount if deposit.expected_amount is not None else deposit.usdt_amount

    qr_payload = (
        f'{coin_type} Deposit\n'
        f'Wallet: {wallet_address}\n'
        f'Amount: {_format_usdt(expected_amount)} {coin_type}'
    )
    qr_code = generate_qr_code(qr_payload)

    now = datetime.utcnow()
    seconds_left = 0
    if deposit.expires_at:
        seconds_left = max(0, int((deposit.expires_at - now).total_seconds()))

    coin_contracts = current_app.config.get('COIN_CONTRACTS', {})
    coin_config = coin_contracts.get(coin_type, {})

    return render_template(
        'deposit/payment.html',
        deposit=deposit,
        coin_type=coin_type,
        coin_config=coin_config,
        wallet_address=wallet_address,
        qr_code=qr_code,
        expected_amount_display=_format_usdt(expected_amount),
        amount_display=_format_usdt(deposit.usdt_amount),
        seconds_left=seconds_left,
    )


@deposit_bp.route('/<int:deposit_id>/status')
@login_required
def status(deposit_id):
    """Small polling endpoint for payment page status updates."""
    deposit = DepositService.get_deposit_by_id(deposit_id)

    if not deposit or deposit.user_id != current_user.id:
        return jsonify({'error': 'Deposit not found'}), 404

    now = datetime.utcnow()
    seconds_left = 0
    if deposit.expires_at:
        seconds_left = max(0, int((deposit.expires_at - now).total_seconds()))

    return jsonify({
        'id': deposit.id,
        'status': deposit.status,
        'tx_hash': deposit.tx_hash,
        'seconds_left': seconds_left,
    })
