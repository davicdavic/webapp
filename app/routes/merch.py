"""
Merch Store Routes
Digital product store with file delivery
"""
import os
import uuid
from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash, send_from_directory, jsonify, current_app
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from app.extensions import db, cache
from app.models import Product, ProductFile, ProductImage, MerchOrder, User, SellerRating, SellerReport
from app.models import SellerChatConversation, SellerChatMessage, SellerNotification
from app.services.seller_service import SELLER_PLANS
from app.services.history_service import HistoryService
from app.utils import save_uploaded_file, save_uploaded_image_optimized
from sqlalchemy import func, or_

merch_bp = Blueprint('merch', __name__)

# Allowed extensions for uploads
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'zip', 'rar', 'pdf', 'txt', 'doc', 'docx', 'mp3', 'mp4', 'avi', 'mov'}
ETA_SET_DEADLINE_DAYS = 3
ETA_MAX_DAYS = 30
CANCEL_REFUND_RATE = 0.50
CANCEL_SELLER_RATE = 0.30
DELETED_PRODUCT_MARKER = '__deleted__'

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def save_merch_file(file, subfolder='merch'):
    """Save uploaded file to merch folder"""
    if not file or not file.filename:
        return None
    
    # Create upload directory
    upload_folder = current_app.config.get('UPLOAD_FOLDER')
    merch_folder = os.path.join(upload_folder, subfolder)
    os.makedirs(merch_folder, exist_ok=True)
    
    # Generate unique filename
    ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
    unique_filename = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}.{ext}"
    
    # Save file
    filepath = os.path.join(merch_folder, unique_filename)
    file.save(filepath)
    
    return unique_filename


def _save_product_gallery_images(uploaded_images, subfolder='merch'):
    """Save up to four uploaded product images and return stored filenames."""
    saved_filenames = []
    for image in uploaded_images:
        if not image or not image.filename:
            continue
        image_path = save_uploaded_image_optimized(image, subfolder)
        image_filename = image_path.split('/')[-1] if image_path else None
        if image_filename and image_filename not in saved_filenames:
            saved_filenames.append(image_filename)
        if len(saved_filenames) >= 4:
            break
    return saved_filenames

def delete_merch_file(filename, subfolder='merch'):
    """Delete a stored merch file safely (best-effort)."""
    if not filename:
        return
    upload_folder = current_app.config.get('UPLOAD_FOLDER')
    merch_folder = os.path.join(upload_folder, subfolder)
    filepath = os.path.join(merch_folder, filename)
    try:
        if os.path.exists(filepath):
            os.remove(filepath)
    except Exception:
        # Swallow filesystem errors; DB state will be the source of truth.
        pass


def _seller_active(user):
    if not user:
        return True
    return bool(user.can_sell)


def _seller_rating_summary(seller_id):
    avg_rating, rating_count = db.session.query(
        func.coalesce(func.avg(SellerRating.rating), 0),
        func.count(SellerRating.id)
    ).filter(SellerRating.seller_id == seller_id).first()
    return float(avg_rating or 0), int(rating_count or 0)


def _apply_store_filters(query, search='', seller_search='', product_type=''):
    """Apply shared store filters for page and API results."""
    if product_type in {'digital', 'physical'}:
        query = query.filter(Product.product_type == product_type)

    if search:
        query = query.filter(Product.name.ilike(f'%{search}%'))

    if seller_search:
        seller_filters = [User.username.ilike(f'%{seller_search}%')]
        if seller_search.isdigit():
            seller_filters.append(User.id == int(seller_search))
        query = query.join(User, Product.seller_id == User.id).filter(or_(*seller_filters))

    return query

def _calculate_cancel_split(total_price: int) -> tuple[int, int, int]:
    total = max(int(total_price or 0), 0)
    buyer_refund = int(round(total * CANCEL_REFUND_RATE))
    seller_payout = int(round(total * CANCEL_SELLER_RATE))
    fee_amount = total - buyer_refund - seller_payout
    return buyer_refund, seller_payout, fee_amount

def _attach_cancel_metadata(order: MerchOrder, now: datetime) -> None:
    purchased_at = order.purchased_at or now
    eta_deadline = purchased_at + timedelta(days=ETA_SET_DEADLINE_DAYS)
    order._eta_set_deadline = eta_deadline
    order._eta_set_deadline_passed = now >= eta_deadline
    order._cancel_policy = 'none'
    if order.status == 'pending':
        if order.delivery_eta:
            order._cancel_policy = 'penalty' if now < order.delivery_eta else 'free'
        else:
            order._cancel_policy = 'free' if now >= eta_deadline else 'blocked'
    buyer_refund, seller_payout, fee_amount = _calculate_cancel_split(order.total_price)
    order._cancel_refund = buyer_refund
    order._cancel_seller = seller_payout
    order._cancel_fee = fee_amount


# ==================== USER ROUTES ====================

@merch_bp.route('/')

@login_required
def index():
    """Merch store home - display all products"""
    search = request.args.get('search', '').strip()
    seller_search = request.args.get('seller', '').strip()
    product_type = (request.args.get('type') or '').strip().lower()
    sort = request.args.get('sort', 'latest').strip()
    page = request.args.get('page', 1, type=int)
    per_page = 12
    
    query = Product.query.filter_by(is_active=True)
    query = _apply_store_filters(query, search=search, seller_search=seller_search, product_type=product_type)
    
    # Sorting
    if sort == 'price_low':
        query = query.order_by(Product.price.asc())
    elif sort == 'price_high':
        query = query.order_by(Product.price.desc())
    elif sort == 'popular':
        query = query.outerjoin(MerchOrder).group_by(Product.id).order_by(db.func.count(MerchOrder.id).desc())
    else:
        query = query.order_by(Product.created_at.desc())
    
    # Paginate
    products_page = query.paginate(page=page, per_page=per_page, error_out=False)
    products = [p for p in products_page.items if (p.seller_id is None) or _seller_active(p.seller)]

    seller_ids = {p.seller_id for p in products if p.seller_id}
    rating_map = {}
    if seller_ids:
        rows = db.session.query(
            SellerRating.seller_id,
            func.coalesce(func.avg(SellerRating.rating), 0).label('avg_rating'),
            func.count(SellerRating.id).label('rating_count')
        ).filter(SellerRating.seller_id.in_(seller_ids))\
         .group_by(SellerRating.seller_id)\
         .all()
        rating_map = {row.seller_id: {'avg': float(row.avg_rating or 0), 'count': int(row.rating_count or 0)} for row in rows}

    return render_template('merch/index.html', 
                         products=products, 
                         search=search,
                         seller_search=seller_search,
                         product_type=product_type,
                         sort=sort,
                         pagination=products_page,
                         seller_ratings=rating_map)


@merch_bp.route('/api/products')
@login_required
def api_products():
    """API endpoint for products with pagination, filtering, and search."""
    page = request.args.get('page', 1, type=int)
    limit = min(50, max(1, request.args.get('limit', 12, type=int)))
    search = request.args.get('search', '').strip()
    seller_search = request.args.get('seller', '').strip()
    product_type = (request.args.get('type') or '').strip().lower()
    sort = request.args.get('sort', 'latest').strip()
    
    # Enforce limits
    page = max(1, page)
    
    query = Product.query.filter_by(is_active=True)
    query = _apply_store_filters(query, search=search, seller_search=seller_search, product_type=product_type)
    
    # Get all matching products first for filtering active sellers
    all_products = query.all()
    products = [p for p in all_products if (p.seller_id is None) or _seller_active(p.seller)]
    
    # Sorting
    if sort == 'price_low':
        products.sort(key=lambda p: p.price)
    elif sort == 'price_high':
        products.sort(key=lambda p: p.price, reverse=True)
    elif sort == 'popular':
        products.sort(key=lambda p: p.orders.count(), reverse=True)
    else:
        products.sort(key=lambda p: p.created_at or datetime.min, reverse=True)
    
    # Pagination
    total = len(products)
    start = (page - 1) * limit
    end = start + limit
    paginated = products[start:end]
    
    return jsonify({
        'products': [{
            'id': p.id,
            'name': p.name,
            'description': p.description,
            'price': p.price,
            'image_filename': p.image_filename,
            'product_type': p.product_type,
            'seller_id': p.seller_id,
            'quantity': p.quantity,
            'seller_username': p.seller.username if p.seller else None
        } for p in paginated],
        'page': page,
        'limit': limit,
        'total': total,
        'pages': (total + limit - 1) // limit,
        'has_next': end < total,
        'has_prev': page > 1
    })


@merch_bp.route('/product/<int:product_id>')


@login_required
def product_detail(product_id):
    """View product details"""
    product = Product.query.get_or_404(product_id)
    if product.seller_id is not None and not _seller_active(product.seller) and not current_user.is_admin():
        flash('This seller is inactive. Product is hidden.', 'error')
        return redirect(url_for('merch.index'))
    seller_rating = None
    seller_sales = None
    if product.seller_id:
        avg_rating, rating_count = _seller_rating_summary(product.seller_id)
        seller_rating = {'avg': avg_rating, 'count': rating_count}
        seller_sales = db.session.query(
            func.coalesce(func.sum(MerchOrder.total_price), 0)
        ).join(Product, Product.id == MerchOrder.product_id)\
         .filter(
             Product.seller_id == product.seller_id,
             MerchOrder.status.in_(['completed', 'delivered'])
         )\
         .scalar() or 0
    return render_template('merch/product.html', product=product, seller_rating=seller_rating, seller_sales=int(seller_sales or 0))


@merch_bp.route('/seller/<int:seller_id>')
@login_required
def seller_profile(seller_id):
    """Public seller profile for ratings and stats."""
    seller = User.query.get_or_404(seller_id)
    if not seller.is_seller and not seller.is_admin():
        flash('Seller not found', 'error')
        return redirect(url_for('merch.index'))

    avg_rating, rating_count = _seller_rating_summary(seller_id)
    total_sales = db.session.query(
        func.coalesce(func.sum(MerchOrder.total_price), 0)
    ).join(Product, Product.id == MerchOrder.product_id)\
     .filter(
         Product.seller_id == seller_id,
         MerchOrder.status.in_(['completed', 'delivered'])
     )\
     .scalar() or 0

    user_rating = SellerRating.query.filter_by(
        seller_id=seller_id,
        rater_id=current_user.id
    ).first()

    products = Product.query.filter_by(seller_id=seller_id, is_active=True)\
        .order_by(Product.created_at.desc())\
        .all()

    return render_template(
        'merch/seller_profile.html',
        seller=seller,
        avg_rating=avg_rating,
        rating_count=rating_count,
        total_sales=int(total_sales),
        user_rating=user_rating.rating if user_rating else None,
        products=products
    )


@merch_bp.route('/seller/<int:seller_id>/rate', methods=['POST'])
@login_required
def rate_seller(seller_id):
    """Rate a seller (1-5)."""
    if seller_id == current_user.id:
        flash('You cannot rate yourself.', 'error')
        return redirect(url_for('merch.seller_profile', seller_id=seller_id))

    seller = User.query.get_or_404(seller_id)
    if not seller.is_seller and not seller.is_admin():
        flash('Seller not found', 'error')
        return redirect(url_for('merch.index'))

    rating = request.form.get('rating', type=int)
    if rating not in {1, 2, 3, 4, 5}:
        flash('Rating must be between 1 and 5.', 'error')
        return redirect(url_for('merch.seller_profile', seller_id=seller_id))

    existing = SellerRating.query.filter_by(seller_id=seller_id, rater_id=current_user.id).first()
    if existing:
        existing.rating = rating
    else:
        db.session.add(SellerRating(seller_id=seller_id, rater_id=current_user.id, rating=rating))
    db.session.commit()

    flash('Rating submitted.', 'success')
    return redirect(url_for('merch.seller_profile', seller_id=seller_id))


@merch_bp.route('/seller/<int:seller_id>/report', methods=['POST'])
@login_required
def report_seller(seller_id):
    """Report a seller to admin."""
    if seller_id == current_user.id:
        flash('You cannot report yourself.', 'error')
        return redirect(url_for('merch.seller_profile', seller_id=seller_id))

    seller = User.query.get_or_404(seller_id)
    if not seller.is_seller and not seller.is_admin():
        flash('Seller not found', 'error')
        return redirect(url_for('merch.index'))

    message = (request.form.get('message') or '').strip()
    evidence = request.files.get('evidence')
    if not message:
        flash('Report message is required.', 'error')
        return redirect(url_for('merch.seller_profile', seller_id=seller_id))

    evidence_path = None
    if evidence and evidence.filename:
        evidence_path = save_uploaded_file(evidence, 'seller_reports')
        if not evidence_path:
            flash('Evidence must be an image file.', 'error')
            return redirect(url_for('merch.seller_profile', seller_id=seller_id))

    report = SellerReport(
        seller_id=seller_id,
        reporter_id=current_user.id,
        message=message,
        evidence_path=evidence_path,
        status='pending'
    )
    db.session.add(report)
    db.session.commit()

    flash('Report submitted. Admin will review it.', 'success')
    return redirect(url_for('merch.seller_profile', seller_id=seller_id))


@merch_bp.route('/buy/<int:product_id>', methods=['POST'])


@login_required
def buy_product(product_id):
    """Purchase product"""
    product = Product.query.get_or_404(product_id)
    if product.seller_id is not None and not _seller_active(product.seller):
        flash('This seller is inactive. Product is unavailable.', 'error')
        return redirect(url_for('merch.index'))

    product_type = (product.product_type or 'digital').lower()
    
    # Get quantity from form
    try:
        quantity = int(request.form.get('quantity', 1))
    except ValueError:
        flash('Invalid quantity', 'error')
        return redirect(url_for('merch.index'))
    
    # Validate quantity
    if quantity < 1:
        flash('Quantity must be at least 1', 'error')
        return redirect(url_for('merch.index'))
    
    if quantity > product.quantity:
        flash(f'Not enough stock. Available: {product.quantity}', 'error')
        return redirect(url_for('merch.index'))
    
    # Calculate total price
    total_price = product.price * quantity
    
    # Check user balance
    if current_user.coins < total_price:
        flash(f'Insufficient balance. Need {total_price} TNNO, you have {current_user.coins}', 'error')
        return redirect(url_for('merch.index'))

    if product_type == 'physical':
        shipping_name = (request.form.get('shipping_name') or '').strip()
        shipping_country = (request.form.get('shipping_country') or '').strip()
        shipping_city = (request.form.get('shipping_city') or '').strip()
        shipping_phone = (request.form.get('shipping_phone') or '').strip()
        shipping_lat = request.form.get('shipping_lat', type=float)
        shipping_lng = request.form.get('shipping_lng', type=float)
        shipping_location_text = (request.form.get('shipping_location_text') or '').strip()

        if not all([shipping_name, shipping_country, shipping_city, shipping_phone]):
            flash('Name, country, city, and phone are required for physical orders', 'error')
            return redirect(url_for('merch.product_detail', product_id=product.id))

        if not shipping_location_text and (shipping_lat is None or shipping_lng is None):
            flash('Please share your location or type your address before ordering', 'error')
            return redirect(url_for('merch.product_detail', product_id=product.id))

        if not shipping_location_text:
            shipping_location_text = f'{shipping_lat},{shipping_lng}'

        try:
            # Deduct TNNO (escrow)
            current_user.coins -= total_price

            # Reduce stock
            product.physical_quantity = max(int(product.physical_quantity or 0) - quantity, 0)

            # Create order
            order = MerchOrder(
                user_id=current_user.id,
                product_id=product.id,
                product_type='physical',
                quantity=quantity,
                total_price=total_price,
                status='pending',
                shipping_name=shipping_name,
                shipping_country=shipping_country,
                shipping_city=shipping_city,
                shipping_phone=shipping_phone,
                shipping_lat=shipping_lat,
                shipping_lng=shipping_lng,
                shipping_location_text=shipping_location_text
            )
            db.session.add(order)
            db.session.commit()

            flash('Physical order placed. Awaiting delivery confirmation.', 'success')
            return redirect(url_for('merch.my_orders'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error processing order: {str(e)}', 'error')
            return redirect(url_for('merch.product_detail', product_id=product.id))
    
    # Get available files
    available_files = ProductFile.query.filter_by(
        product_id=product_id, 
        is_sold=False
    ).limit(quantity).all()
    
    if len(available_files) < quantity:
        flash('Some files are no longer available', 'error')
        return redirect(url_for('merch.index'))
    
    # Process purchase (atomic transaction)
    try:
        # Deduct TNNO
        current_user.coins -= total_price
        
        # Create order
        order = MerchOrder(
            user_id=current_user.id,
            product_id=product_id,
            product_type='digital',
            quantity=quantity,
            total_price=total_price,
            status='completed'
        )
        db.session.add(order)
        db.session.flush()  # Get order ID
        
        # Mark files as sold
        for file in available_files:
            file.is_sold = True
            file.order_id = order.id
            file.sold_at = datetime.utcnow()
        
        # Credit seller with payout after platform fee
        if product.seller:
            fee_rate = float(product.seller.seller_commission_rate or 0)
            fee_rate = max(0.0, min(fee_rate, 1.0))
            payout = total_price * (1 - fee_rate)
            product.seller.coins += payout
            
            # Create purchase notification for seller
            notification = SellerNotification(
                seller_id=product.seller_id,
                notification_type='new_purchase',
                title='New Purchase!',
                message=f'{current_user.username} purchased {quantity}x {product.name} for {total_price} TNNO',
                related_id=order.id,
                related_type='order'
            )
            db.session.add(notification)
        
        db.session.commit()
        
        flash(f'Successfully purchased {quantity}x {product.name}! Your balance: {current_user.coins} TNNO', 'success')
        return redirect(url_for('merch.my_orders'))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error processing purchase: {str(e)}', 'error')
        return redirect(url_for('merch.index'))


@merch_bp.route('/my-orders')


@login_required
def my_orders():
    """User's purchased orders"""
    HistoryService.archive_due_items(user_id=current_user.id)
    now = datetime.utcnow()
    filter_type = (request.args.get('type') or '').strip().lower()
    page = request.args.get('page', 1, type=int)
    orders_page = MerchOrder.query.filter_by(user_id=current_user.id)\
        .filter(MerchOrder.is_archived.is_(False))\
        .order_by(MerchOrder.purchased_at.desc())\
        .paginate(page=page, per_page=20, error_out=False)
    orders = orders_page.items
    digital_orders = []
    physical_orders = []
    for order in orders:
        order_type = (order.product_type or order.product.product_type or 'digital').lower()
        if filter_type and order_type != filter_type:
            continue
        if order_type == 'physical':
            _attach_cancel_metadata(order, now)
            physical_orders.append(order)
        else:
            digital_orders.append(order)
    return render_template(
        'merch/orders.html',
        orders=orders,
        orders_page=orders_page,
        digital_orders=digital_orders,
        physical_orders=physical_orders,
        now=now
    )


@merch_bp.route('/orders/<int:order_id>/arrived', methods=['POST'])
@login_required
def confirm_physical_arrived(order_id):
    """Buyer confirms physical order arrived."""
    order = MerchOrder.query.get_or_404(order_id)
    if order.user_id != current_user.id:
        flash('Access denied', 'error')
        return redirect(url_for('merch.my_orders'))

    order_type = (order.product_type or order.product.product_type or 'digital').lower()
    if order_type != 'physical':
        flash('This order is not a physical order', 'error')
        return redirect(url_for('merch.my_orders'))

    if order.status != 'pending':
        flash('Order is already resolved', 'error')
        return redirect(url_for('merch.my_orders'))

    product = order.product
    seller = product.seller
    if seller:
        fee_rate = float(seller.seller_commission_rate or 0)
        fee_rate = max(0.0, min(fee_rate, 1.0))
        payout = order.total_price * (1 - fee_rate)
        seller.coins += payout

    order.status = 'delivered'
    order.delivered_at = datetime.utcnow()
    db.session.commit()

    flash('Marked as arrived. Seller paid.', 'success')
    return redirect(url_for('merch.my_orders'))


@merch_bp.route('/orders/<int:order_id>/not-arrived', methods=['POST'])
@login_required
def report_physical_not_arrived(order_id):
    """Buyer reports physical order not arrived (refund)."""
    order = MerchOrder.query.get_or_404(order_id)
    if order.user_id != current_user.id:
        flash('Access denied', 'error')
        return redirect(url_for('merch.my_orders'))

    order_type = (order.product_type or order.product.product_type or 'digital').lower()
    if order_type != 'physical':
        flash('This order is not a physical order', 'error')
        return redirect(url_for('merch.my_orders'))

    if order.status != 'pending':
        flash('Order is already resolved', 'error')
        return redirect(url_for('merch.my_orders'))

    now = datetime.utcnow()
    purchased_at = order.purchased_at or now
    eta_deadline = purchased_at + timedelta(days=ETA_SET_DEADLINE_DAYS)
    product = order.product

    if order.delivery_eta:
        if now < order.delivery_eta:
            buyer_refund, seller_payout, fee_amount = _calculate_cancel_split(order.total_price)
            current_user.coins += buyer_refund
            if product and product.seller:
                product.seller.coins += seller_payout
            if product:
                product.physical_quantity = int(product.physical_quantity or 0) + int(order.quantity or 0)
            order.status = 'refunded'
            order.refunded_at = now
            db.session.commit()
            flash(
                f'Order cancelled with penalty. '
                f'Refunded {buyer_refund} TNNO, seller received {seller_payout} TNNO, '
                f'fee {fee_amount} TNNO.',
                'warning'
            )
            return redirect(url_for('merch.my_orders'))
        # ETA passed: full refund
        current_user.coins += order.total_price
        if product:
            product.physical_quantity = int(product.physical_quantity or 0) + int(order.quantity or 0)
        order.status = 'refunded'
        order.refunded_at = now
        db.session.commit()
        flash('Order cancelled after ETA passed. Full refund issued.', 'success')
        return redirect(url_for('merch.my_orders'))

    if now < eta_deadline:
        deadline_str = eta_deadline.strftime('%Y-%m-%d %H:%M')
        flash(f'Seller has until {deadline_str} to set delivery time. Please wait.', 'error')
        return redirect(url_for('merch.my_orders'))

    # No ETA set within deadline: full refund
    current_user.coins += order.total_price
    if product:
        product.physical_quantity = int(product.physical_quantity or 0) + int(order.quantity or 0)
    order.status = 'refunded'
    order.refunded_at = now
    db.session.commit()

    flash('Seller did not set delivery time. Full refund issued.', 'success')
    return redirect(url_for('merch.my_orders'))


@merch_bp.route('/download/<int:file_id>')


@login_required
def download_file(file_id):
    """Download purchased file"""
    product_file = ProductFile.query.get_or_404(file_id)
    
    # Check if user owns this file
    if product_file.is_sold:
        order = MerchOrder.query.get(product_file.order_id)
        if not order or order.user_id != current_user.id:
            if not current_user.is_admin():
                flash('You do not have permission to download this file', 'error')
                return redirect(url_for('merch.my_orders'))
    else:
        if not current_user.is_admin():
            flash('File not purchased', 'error')
            return redirect(url_for('merch.index'))
    
    # Serve file
    upload_folder = current_app.config.get('UPLOAD_FOLDER')
    merch_folder = os.path.join(upload_folder, 'merch')
    
    return send_from_directory(
        merch_folder, 
        product_file.file_filename,
        as_attachment=True,
        download_name=product_file.original_name or 'file'
    )


# ==================== ADMIN ROUTES ====================

@merch_bp.route('/admin/products')

@login_required
def admin_products():
    """Admin / seller: List products. Admin sees all, sellers see their own."""
    if not (current_user.is_admin() or current_user.is_seller):
        flash('Admin access required', 'error')
        return redirect(url_for('merch.index'))

    if not current_user.is_admin() and current_user.is_seller and not current_user.can_sell:
        flash('Seller plan expired. Renew to show products in the store.', 'error')
    
    search = request.args.get('search', '').strip()
    page = request.args.get('page', 1, type=int)
    per_page = 30
    query = Product.query
    if not current_user.is_admin():
        query = query.filter_by(seller_id=current_user.id)
    if search:
        query = query.filter(Product.name.ilike(f'%{search}%'))
    products_page = query.filter(
        (Product.contact_link.is_(None)) | (Product.contact_link != DELETED_PRODUCT_MARKER)
    ).order_by(Product.created_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
    return render_template(
        'merch/admin_products.html',
        products=products_page.items,
        products_page=products_page,
        search=search
    )


@merch_bp.route('/admin/create', methods=['GET', 'POST'])


@login_required
def admin_create():
    """Admin / seller: Create new product"""
    if not (current_user.is_admin() or current_user.is_seller):
        flash('Admin access required', 'error')
        return redirect(url_for('merch.index'))
    
    if request.method == 'POST':
        if not current_user.is_admin() and not current_user.can_sell:
            flash('Seller plan expired. Please renew to add products.', 'error')
            return redirect(url_for('merch.admin_create'))
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        price = request.form.get('price', type=int, default=0)
        product_type = (request.form.get('product_type') or 'digital').strip().lower()
        contact_link = (request.form.get('contact_link') or '').strip()
        physical_quantity = request.form.get('physical_quantity', type=int, default=0)
        files = request.files.getlist('files')
        uploaded_images = request.files.getlist('images')
        
        if not name:
            flash('Product name is required', 'error')
            return redirect(url_for('merch.admin_create'))
        
        if price < 1:
            flash('Price must be at least 1 TNNO', 'error')
            return redirect(url_for('merch.admin_create'))

        if product_type not in {'digital', 'physical'}:
            flash('Invalid product type', 'error')
            return redirect(url_for('merch.admin_create'))

        if product_type == 'physical':
            if physical_quantity < 1:
                flash('Physical quantity must be at least 1', 'error')
                return redirect(url_for('merch.admin_create'))
            if not contact_link:
                flash('Contact link is required for physical products', 'error')
                return redirect(url_for('merch.admin_create'))
        else:
            if not files or len(files) == 0 or not files[0].filename:
                flash('At least one product file is required', 'error')
                return redirect(url_for('merch.admin_create'))
        
        try:
            if len([img for img in uploaded_images if img and img.filename]) > 4:
                flash('You can upload up to 4 product photos.', 'error')
                return redirect(url_for('merch.admin_create'))

            # Save product gallery if provided
            image_filenames = []
            if uploaded_images:
                try:
                    image_filenames = _save_product_gallery_images(uploaded_images, 'merch')
                except ValueError as exc:
                    flash(str(exc), 'error')
                    return redirect(url_for('merch.admin_create'))
            
            # Create product
            product = Product(
                name=name,
                description=description,
                price=price,
                image_filename=image_filenames[0] if image_filenames else None,
                product_type=product_type,
                contact_link=contact_link if product_type == 'physical' else None,
                physical_quantity=physical_quantity if product_type == 'physical' else 0,
                seller_id=current_user.id if not current_user.is_admin() else None
            )
            db.session.add(product)
            db.session.flush()  # Get product ID

            for index, image_filename in enumerate(image_filenames[1:], start=1):
                db.session.add(ProductImage(
                    product_id=product.id,
                    image_filename=image_filename,
                    sort_order=index
                ))
            
            saved_files = 0
            if product_type == 'digital':
                # Save product files (1 file = 1 quantity)
                for file in files:
                    if file and file.filename:
                        if allowed_file(file.filename):
                            filename = save_merch_file(file, 'merch')
                            if filename:
                                product_file = ProductFile(
                                    product_id=product.id,
                                    file_filename=filename,
                                    original_name=secure_filename(file.filename)
                                )
                                db.session.add(product_file)
                                saved_files += 1
                        else:
                            flash(f'File type not allowed: {file.filename}', 'warning')
                
                if saved_files == 0:
                    db.session.rollback()
                    flash('No valid files were uploaded', 'error')
                    return redirect(url_for('merch.admin_create'))
            
            db.session.commit()
            if product_type == 'physical':
                flash('Physical product created successfully!', 'success')
            else:
                flash(f'Product created successfully with {saved_files} files!', 'success')
            return redirect(url_for('merch.admin_products'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error creating product: {str(e)}', 'error')
            return redirect(url_for('merch.admin_create'))
    
    return render_template(
        'merch/admin_create.html',
        seller_active=current_user.can_sell,
        seller_expires_at=current_user.seller_expires_at,
        seller_plans=SELLER_PLANS
    )


@merch_bp.route('/admin/edit/<int:product_id>', methods=['GET', 'POST'])


@login_required
def admin_edit(product_id):
    """Admin / seller: Edit product"""
    if not (current_user.is_admin() or current_user.is_seller):
        flash('Admin access required', 'error')
        return redirect(url_for('merch.index'))
    
    product = Product.query.get_or_404(product_id)
    # sellers may only modify their own products
    if not current_user.is_admin() and product.seller_id != current_user.id:
        flash('You do not have permission to edit this product', 'error')
        return redirect(url_for('merch.admin_products'))
    
    if request.method == 'POST':
        product.name = request.form.get('name', '').strip()
        product.description = request.form.get('description', '').strip()
        
        new_price = request.form.get('price', type=int, default=0)
        if new_price >= 1:
            product.price = new_price

        if product.product_type == 'physical':
            contact_link = (request.form.get('contact_link') or '').strip()
            physical_quantity = request.form.get('physical_quantity', type=int)
            if contact_link:
                product.contact_link = contact_link
            if physical_quantity is not None and physical_quantity >= 0:
                product.physical_quantity = physical_quantity
        
        # Handle gallery upload
        uploaded_images = request.files.getlist('images')
        if len([img for img in uploaded_images if img and img.filename]) > 4:
            flash('You can upload up to 4 product photos at once.', 'error')
            return redirect(url_for('merch.admin_edit', product_id=product.id))

        if uploaded_images and uploaded_images[0].filename:
            try:
                existing_gallery = product.gallery_filenames
                new_filenames = _save_product_gallery_images(uploaded_images, 'merch')
                combined_filenames = []
                for filename in existing_gallery + new_filenames:
                    if filename and filename not in combined_filenames:
                        combined_filenames.append(filename)
                if len(combined_filenames) > 4:
                    flash('A product can show up to 4 photos total.', 'error')
                    return redirect(url_for('merch.admin_edit', product_id=product.id))
                if combined_filenames:
                    product.image_filename = combined_filenames[0]
                    product.images.delete()
                    db.session.flush()
                    for index, image_filename in enumerate(combined_filenames[1:], start=1):
                        db.session.add(ProductImage(
                            product_id=product.id,
                            image_filename=image_filename,
                            sort_order=index
                        ))
            except ValueError as exc:
                flash(str(exc), 'error')
                return redirect(url_for('merch.admin_edit', product_id=product.id))
        
        # Add more files
        if product.product_type != 'physical':
            new_files = request.files.getlist('new_files')
            if new_files and new_files[0].filename:
                for file in new_files:
                    if file and file.filename and allowed_file(file.filename):
                        filename = save_merch_file(file, 'merch')
                        if filename:
                            product_file = ProductFile(
                                product_id=product.id,
                                file_filename=filename,
                                original_name=secure_filename(file.filename)
                            )
                            db.session.add(product_file)
        
        # Toggle active status
        product.is_active = 'is_active' in request.form
        
        db.session.commit()
        flash('Product updated successfully!', 'success')
        return redirect(url_for('merch.admin_products'))
    
    return render_template('merch/admin_edit.html', product=product)


@merch_bp.route('/admin/delete/<int:product_id>', methods=['POST'])


@login_required
def admin_delete(product_id):
    """Admin / seller: Delete product"""
    if not (current_user.is_admin() or current_user.is_seller):
        flash('Admin access required', 'error')
        return redirect(url_for('merch.index'))
    
    product = Product.query.get_or_404(product_id)
    if not current_user.is_admin() and product.seller_id != current_user.id:
        flash('You do not have permission to delete this product', 'error')
        return redirect(url_for('merch.admin_products'))

    try:
        order_count = product.orders.count()

        if order_count > 0:
            product_type = (product.product_type or 'digital').lower()
            if product_type == 'digital':
                unsold_files = product.files.filter_by(is_sold=False).all()
                for pf in unsold_files:
                    delete_merch_file(pf.file_filename, 'merch')
                    db.session.delete(pf)
                product.is_active = False
                # Soft-delete marker: keep DB row for historical orders/downloads,
                # but hide from admin/seller products list.
                product.contact_link = DELETED_PRODUCT_MARKER
                db.session.commit()
                flash(
                    'Product has orders, so it was removed from sale and unsold files were deleted. '
                    'Sold files are kept for buyer downloads.',
                    'success'
                )
                return redirect(url_for('merch.admin_products'))

            flash('Cannot delete a product that has orders. Use Hide instead.', 'error')
            return redirect(url_for('merch.admin_products'))

        # Delete associated files from disk (thumbnail + product files)
        if product.image_filename:
            delete_merch_file(product.image_filename, 'merch')
        for gallery_image in product.images.all():
            delete_merch_file(gallery_image.image_filename, 'merch')
        for pf in product.files.all():
            delete_merch_file(pf.file_filename, 'merch')

        db.session.delete(product)
        db.session.commit()
        flash('Product deleted (image and files removed)', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting product: {str(e)}', 'error')

    return redirect(url_for('merch.admin_products'))


@merch_bp.route('/admin/hide/<int:product_id>', methods=['POST'])
@login_required
def admin_hide(product_id):
    """Admin / seller: Hide or show a product without deleting it"""
    if not (current_user.is_admin() or current_user.is_seller):
        flash('Admin access required', 'error')
        return redirect(url_for('merch.index'))
    
    product = Product.query.get_or_404(product_id)
    if not current_user.is_admin() and product.seller_id != current_user.id:
        flash('You do not have permission to change this product', 'error')
        return redirect(url_for('merch.admin_products'))

    product.is_active = not product.is_active
    if not product.is_active:
        # Prevent new purchases: mark unsold digital files as sold
        if product.product_type != 'physical':
            for pf in product.files.filter_by(is_sold=False).all():
                pf.is_sold = True
    db.session.commit()
    flash('Product hidden from store' if not product.is_active else 'Product is visible in store', 'success')
    return redirect(url_for('merch.admin_products'))

@merch_bp.route('/admin/sales/<int:order_id>/eta', methods=['POST'])
@login_required
def set_delivery_eta(order_id):
    """Set delivery ETA for a physical order."""
    if not (current_user.is_admin() or current_user.is_seller):
        flash('Admin access required', 'error')
        return redirect(url_for('merch.index'))

    order = MerchOrder.query.get_or_404(order_id)
    order_type = (order.product_type or order.product.product_type or 'digital').lower()
    if order_type != 'physical':
        flash('This order is not a physical order', 'error')
        return redirect(url_for('merch.admin_sales'))

    if not current_user.is_admin() and order.product.seller_id != current_user.id:
        flash('You do not have permission to update this order', 'error')
        return redirect(url_for('merch.admin_sales'))

    if order.delivery_eta is not None:
        flash('Delivery ETA is already set and cannot be changed.', 'error')
        return redirect(url_for('merch.admin_sales'))

    if order.status != 'pending':
        flash('Cannot set ETA for a resolved order.', 'error')
        return redirect(url_for('merch.admin_sales'))

    eta_raw = (request.form.get('delivery_eta') or '').strip()
    if not eta_raw:
        order.delivery_eta = None
        db.session.commit()
        flash('Delivery ETA cleared', 'success')
        return redirect(url_for('merch.admin_sales'))

    try:
        eta_value = datetime.fromisoformat(eta_raw)
    except ValueError:
        flash('Invalid ETA format', 'error')
        return redirect(url_for('merch.admin_sales'))

    now = datetime.utcnow()
    purchased_at = order.purchased_at or now
    eta_deadline = purchased_at + timedelta(days=ETA_SET_DEADLINE_DAYS)
    if now > eta_deadline:
        deadline_str = eta_deadline.strftime('%Y-%m-%d %H:%M')
        flash(f'ETA can only be set within {ETA_SET_DEADLINE_DAYS} days of purchase (deadline {deadline_str}).', 'error')
        return redirect(url_for('merch.admin_sales'))

    if eta_value <= now:
        flash('ETA must be in the future.', 'error')
        return redirect(url_for('merch.admin_sales'))

    if eta_value > now + timedelta(days=ETA_MAX_DAYS):
        flash(f'ETA must be within {ETA_MAX_DAYS} days from now.', 'error')
        return redirect(url_for('merch.admin_sales'))

    order.delivery_eta = eta_value
    db.session.commit()
    flash('Delivery ETA updated', 'success')
    return redirect(url_for('merch.admin_sales'))


@merch_bp.route('/admin/sales')
@login_required
def admin_sales():
    """Admin / seller: View sales history."""
    if not (current_user.is_admin() or current_user.is_seller):
        flash('Admin access required', 'error')
        return redirect(url_for('merch.index'))

    now = datetime.utcnow()
    if current_user.is_seller and not current_user.is_admin():
        current_user.seller_sales_seen_at = now
        db.session.commit()
        cache.delete(f'profile_index_{current_user.id}')
    page = request.args.get('page', 1, type=int)
    filter_type = (request.args.get('type') or '').strip().lower()
    per_page = 50

    query = db.session.query(MerchOrder, Product, User)\
        .join(Product, Product.id == MerchOrder.product_id)\
        .join(User, User.id == MerchOrder.user_id)

    if not current_user.is_admin():
        query = query.filter(Product.seller_id == current_user.id)
    if filter_type in {'digital', 'physical'}:
        query = query.filter(Product.product_type == filter_type)

    orders = query.order_by(MerchOrder.purchased_at.desc())\
        .paginate(page=page, per_page=per_page, error_out=False)

    digital_rows = []
    physical_rows = []
    for order, product, buyer in orders.items:
        seller = product.seller
        fee_rate = float(seller.seller_commission_rate or 0) if seller else 0.0
        fee_rate = max(0.0, min(fee_rate, 1.0))
        fee_amount = order.total_price * fee_rate
        order_type = (order.product_type or product.product_type or 'digital').lower()

        if order_type == 'physical':
            purchased_at = order.purchased_at or now
            eta_deadline = purchased_at + timedelta(days=ETA_SET_DEADLINE_DAYS)
            payout = 0
            if order.status == 'delivered':
                payout = order.total_price - fee_amount
            elif (
                order.status == 'refunded'
                and order.delivery_eta
                and order.refunded_at
                and order.refunded_at < order.delivery_eta
            ):
                payout = _calculate_cancel_split(order.total_price)[1]
            physical_rows.append({
                'order': order,
                'product': product,
                'buyer': buyer,
                'seller': seller,
                'fee_rate': fee_rate,
                'fee_rate_percent': int(round(fee_rate * 100)),
                'fee_amount': fee_amount,
                'payout': payout,
                'eta_deadline': eta_deadline,
                'eta_deadline_passed': now > eta_deadline
            })
        else:
            if order.status != 'completed':
                continue
            payout = order.total_price - fee_amount
            digital_rows.append({
                'order': order,
                'product': product,
                'buyer': buyer,
                'seller': seller,
                'fee_rate': fee_rate,
                'fee_rate_percent': int(round(fee_rate * 100)),
                'fee_amount': fee_amount,
                'payout': payout
            })

    return render_template(
        'merch/admin_sales.html',
        digital_sales=digital_rows,
        physical_sales=physical_rows,
        orders=orders
    )


# ==================== Seller Chat Routes ====================

@merch_bp.route('/seller/<int:seller_id>/chat')
@login_required
def seller_chat(seller_id):
    """Open or continue chat with a seller"""
    seller = User.query.get_or_404(seller_id)
    if not seller.is_seller and not seller.is_admin():
        flash('Seller not found', 'error')
        return redirect(url_for('merch.index'))
    
    # Get or create conversation
    conversation = SellerChatConversation.query.filter_by(
        buyer_id=current_user.id,
        seller_id=seller_id
    ).first()
    
    if not conversation:
        conversation = SellerChatConversation(
            buyer_id=current_user.id,
            seller_id=seller_id
        )
        db.session.add(conversation)
        db.session.commit()
    
    # Get messages
    messages = SellerChatMessage.query.filter_by(conversation_id=conversation.id)\
        .order_by(SellerChatMessage.created_at.asc()).all()
    
    # Mark messages as read
    SellerChatMessage.query.filter(
        SellerChatMessage.conversation_id == conversation.id,
        SellerChatMessage.sender_id != current_user.id,
        SellerChatMessage.is_read == False
    ).update({'is_read': True})
    db.session.commit()
    
    return render_template(
        'merch/chat.html',
        conversation=conversation,
        seller=seller,
        messages=messages
    )


@merch_bp.route('/chat/<int:conversation_id>/send', methods=['POST'])
@login_required
def send_message(conversation_id):
    """Send a message in a chat conversation"""
    conversation = SellerChatConversation.query.get_or_404(conversation_id)
    
    # Verify user is part of the conversation
    if current_user.id != conversation.buyer_id and current_user.id != conversation.seller_id:
        flash('Access denied', 'error')
        return redirect(url_for('merch.index'))
    
    message_text = request.form.get('message', '').strip()
    image = request.files.get('image')
    
    if not message_text and not (image and image.filename):
        flash('Message or image is required', 'error')
        return redirect(url_for('merch.seller_chat', seller_id=conversation.seller_id))
    
    image_path = None
    message_type = 'text'
    
    if image and image.filename:
        try:
            image_path = save_uploaded_image_optimized(image, 'chat')
            message_type = 'image'
        except ValueError as exc:
            flash(str(exc), 'error')
            return redirect(url_for('merch.seller_chat', seller_id=conversation.seller_id))
    
    message = SellerChatMessage(
        conversation_id=conversation_id,
        sender_id=current_user.id,
        message_type=message_type,
        content=message_text if message_type == 'text' else None,
        image_path=image_path
    )
    db.session.add(message)
    
    # Update conversation timestamp
    conversation.updated_at = datetime.utcnow()
    
    # Create notification for the other party
    recipient_id = conversation.seller_id if current_user.id == conversation.buyer_id else conversation.buyer_id
    recipient = User.query.get(recipient_id)
    
    if recipient and (recipient.is_seller or recipient.is_admin()):
        notification = SellerNotification(
            seller_id=recipient_id,
            notification_type='new_message',
            title='New Message',
            message=f'{current_user.username} sent you a message',
            related_id=conversation_id,
            related_type='conversation'
        )
        db.session.add(notification)
    
    db.session.commit()
    
    return redirect(url_for('merch.seller_chat', seller_id=conversation.seller_id))


@merch_bp.route('/chat/<int:conversation_id>/messages')
@login_required
def get_messages(conversation_id):
    """Get messages for a conversation (AJAX)"""
    conversation = SellerChatConversation.query.get_or_404(conversation_id)
    
    if current_user.id != conversation.buyer_id and current_user.id != conversation.seller_id:
        return jsonify({'error': 'Access denied'}), 403
    
    messages = SellerChatMessage.query.filter_by(conversation_id=conversation_id)\
        .order_by(SellerChatMessage.created_at.asc()).all()
    
    return jsonify({
        'messages': [{
            'id': m.id,
            'sender_id': m.sender_id,
            'message_type': m.message_type,
            'content': m.content,
            'image_path': m.image_path,
            'created_at': m.created_at.isoformat() if m.created_at else None,
            'is_read': m.is_read
        } for m in messages]
    })


@merch_bp.route('/my-chats')
@login_required
def my_chats():
    """List all conversations for current user"""
    # Get buyer conversations
    buyer_convs = SellerChatConversation.query.filter_by(buyer_id=current_user.id)\
        .order_by(SellerChatConversation.updated_at.desc()).all()
    
    # Get seller conversations (for sellers)
    seller_convs = []
    if current_user.is_seller or current_user.is_admin():
        seller_convs = SellerChatConversation.query.filter_by(seller_id=current_user.id)\
            .order_by(SellerChatConversation.updated_at.desc()).all()
    
    return render_template(
        'merch/my_chats.html',
        buyer_conversations=buyer_convs,
        seller_conversations=seller_convs
    )


@merch_bp.route('/notifications')
@login_required
def notifications():
    """List seller notifications"""
    if not current_user.is_seller and not current_user.is_admin():
        flash('Access denied', 'error')
        return redirect(url_for('merch.index'))
    
    notifications_list = SellerNotification.query.filter_by(seller_id=current_user.id)\
        .order_by(SellerNotification.created_at.desc()).limit(50).all()
    
    # Mark as read
    SellerNotification.query.filter_by(seller_id=current_user.id, is_read=False)\
        .update({'is_read': True})
    db.session.commit()
    
    return render_template('merch/notifications.html', notifications=notifications_list)
