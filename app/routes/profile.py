"""
Profile Routes
User profile management
"""
from datetime import datetime
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from sqlalchemy import or_
from app.extensions import db, cache
from app.models import User, SellerRequest, SellerRating, Product, MerchOrder, UserNotification, SellerNotification, SellerChatConversation, SellerChatMessage
from app.services import UserService
from app.services.seller_service import SellerService, SELLER_PLANS
from app.utils import save_uploaded_file

profile_bp = Blueprint('profile', __name__)


@profile_bp.route('/')

@login_required
def index():
    """View own profile"""
    cache_key = f'profile_index_{current_user.id}'
    cached = cache.get(cache_key)
    if cached:
        return render_template(
            'profile/index.html',
            user=current_user,
            seller_rating=cached.get('seller_rating'),
            notif_count=cached.get('notif_count'),
            latest_notifications=cached.get('latest_notifications'),
            sales_unread_count=cached.get('sales_unread_count'),
            chat_unread_count=cached.get('chat_unread_count')
        )

    seller_rating = None
    if current_user.is_seller:
        avg_rating, rating_count = db.session.query(
            db.func.coalesce(db.func.avg(SellerRating.rating), 0),
            db.func.count(SellerRating.id)
        ).filter(SellerRating.seller_id == current_user.id).first()
        seller_rating = {'avg': float(avg_rating or 0), 'count': int(rating_count or 0)}
    user_notifications = UserNotification.query.filter_by(user_id=current_user.id)\
        .order_by(UserNotification.created_at.desc())\
        .limit(10).all()
    seller_notifications = SellerNotification.query.filter_by(seller_id=current_user.id)\
        .order_by(SellerNotification.created_at.desc())\
        .limit(10).all()
    latest_notifications = sorted(
        [{'kind': 'user', 'row': n, 'created_at': n.created_at, 'message': n.message} for n in user_notifications] +
        [{'kind': 'seller', 'row': n, 'created_at': n.created_at, 'message': n.message} for n in seller_notifications],
        key=lambda item: item['created_at'] or datetime.min,
        reverse=True
    )[:5]
    notif_count = UserNotification.query.filter_by(user_id=current_user.id, read_at=None).count()
    notif_count += SellerNotification.query.filter_by(seller_id=current_user.id, is_read=False).count()

    chat_unread_count = db.session.query(SellerChatMessage)\
        .join(SellerChatConversation, SellerChatConversation.id == SellerChatMessage.conversation_id)\
        .filter(
            or_(
                SellerChatConversation.buyer_id == current_user.id,
                SellerChatConversation.seller_id == current_user.id
            ),
            SellerChatMessage.sender_id != current_user.id,
            SellerChatMessage.is_read.is_(False)
        )\
        .count()
    sales_unread_count = 0
    if current_user.can_sell and not current_user.is_admin():
        last_seen = current_user.seller_sales_seen_at or datetime(1970, 1, 1)
        sales_unread_count = db.session.query(MerchOrder)\
            .join(Product, Product.id == MerchOrder.product_id)\
            .filter(Product.seller_id == current_user.id)\
            .filter(MerchOrder.purchased_at.isnot(None))\
            .filter(MerchOrder.purchased_at > last_seen)\
            .count()

    cache.set(cache_key, {
        'seller_rating': seller_rating,
        'notif_count': notif_count,
        'latest_notifications': latest_notifications,
        'sales_unread_count': sales_unread_count,
        'chat_unread_count': chat_unread_count
    }, timeout=20)
    return render_template(
        'profile/index.html',
        user=current_user,
        seller_rating=seller_rating,
        notif_count=notif_count,
        latest_notifications=latest_notifications,
        sales_unread_count=sales_unread_count,
        chat_unread_count=chat_unread_count
    )


@profile_bp.route('/<username>')

@login_required
def view(username):
    """View user profile"""
    if username.lower() == current_user.username.lower():
        user = current_user
        stats = UserService.get_user_stats(current_user.id)
        return render_template('profile/view.html', profile_user=user, stats=stats)

    cache_key = f'profile_view_{username}'
    cached_data = cache.get(cache_key)

    if cached_data is None:
        user = User.query.filter_by(username=username).first_or_404()
        stats = UserService.get_user_stats(user.id)
        cached_data = {'user': user, 'stats': stats}
        cache.set(cache_key, cached_data, timeout=120)

    return render_template('profile/view.html', profile_user=cached_data['user'], stats=cached_data['stats'])


@profile_bp.route('/edit', methods=['GET', 'POST'])

@login_required
def edit():
    """Edit profile"""
    if request.method == 'POST':
        bio = request.form.get('bio', '').strip()

        # Handle profile picture upload
        profile_pic = request.files.get('profile_pic')
        profile_pic_path = current_user.profile_pic

        if profile_pic and profile_pic.filename:
            from app.utils import save_uploaded_file
            profile_pic_path = save_uploaded_file(profile_pic, 'profiles')

        # Update user
        current_user.bio = bio
        if profile_pic_path:
            current_user.profile_pic = profile_pic_path

        db.session.commit()

        # Invalidate profile cache
        cache.delete(f'profile_view_{current_user.username}')
        cache.delete(f'profile_index_{current_user.id}')

        flash('Profile updated successfully!', 'success')
        return redirect(url_for('profile.index'))

    return render_template('profile/edit.html')


@profile_bp.route('/settings', methods=['GET', 'POST'])

@login_required
def settings():
    """User settings"""
    if request.method == 'POST':
        # Change password
        current_password = request.form.get('current_password', '')
        new_password = request.form.get('new_password', '')
        confirm_password = request.form.get('confirm_password', '')
        
        if current_password and new_password:
            if not current_user.check_password(current_password):
                flash('Current password is incorrect', 'error')
                return render_template('profile/settings.html')
            
            if new_password != confirm_password:
                flash('New passwords do not match', 'error')
                return render_template('profile/settings.html')
            
            if len(new_password) < 6:
                flash('Password must be at least 6 characters', 'error')
                return render_template('profile/settings.html')
            
            current_user.set_password(new_password)
            db.session.commit()
            flash('Password changed successfully!', 'success')
        
        # Update email
        email = request.form.get('email', '').strip()
        if email:
            existing = User.query.filter_by(email=email).first()
            if existing and existing.id != current_user.id:
                flash('Email already in use', 'error')
            else:
                current_user.email = email
                db.session.commit()
                flash('Email updated successfully!', 'success')
        
        # Update username
        username = request.form.get('username', '').strip()
        if username:
            existing = User.query.filter_by(username=username).first()
            if existing and existing.id != current_user.id:
                flash('Username already taken', 'error')
            elif username == current_user.username:
                flash('Username is the same as current', 'info')
            else:
                # Invalidate old cache
                cache.delete(f'profile_view_{current_user.username}')
                cache.delete(f'profile_index_{current_user.id}')
                
                current_user.username = username
                db.session.commit()
                
                # Cache with new username
                cache.delete(f'profile_view_{username}')
                cache.delete(f'profile_index_{current_user.id}')
                
                flash('Username updated successfully!', 'success')
        
        return redirect(url_for('profile.settings'))

    latest_request = SellerRequest.query.filter_by(user_id=current_user.id)\
        .order_by(SellerRequest.created_at.desc())\
        .first()

    return render_template(
        'profile/settings.html',
        seller_request=latest_request,
        seller_plans=SELLER_PLANS,
        seller_expires_at=current_user.seller_expires_at,
        seller_active=current_user.seller_active
    )


@profile_bp.route('/notifications')
@login_required
def notifications():
    """User notifications."""
    user_rows = UserNotification.query.filter_by(user_id=current_user.id)\
        .order_by(UserNotification.created_at.desc()).all()
    seller_rows = SellerNotification.query.filter_by(seller_id=current_user.id)\
        .order_by(SellerNotification.created_at.desc()).all()

    rows = sorted(
        [{'kind': 'user', 'row': n, 'created_at': n.created_at} for n in user_rows] +
        [{'kind': 'seller', 'row': n, 'created_at': n.created_at} for n in seller_rows],
        key=lambda item: item['created_at'] or datetime.min,
        reverse=True
    )

    unread = UserNotification.query.filter_by(user_id=current_user.id, read_at=None).all()
    seller_unread = SellerNotification.query.filter_by(seller_id=current_user.id, is_read=False).all()
    if unread or seller_unread:
        now = datetime.utcnow()
        for n in unread:
            n.read_at = now
        for n in seller_unread:
            n.is_read = True
        db.session.commit()
        cache.delete(f'profile_index_{current_user.id}')
    return render_template('profile/notifications.html', notifications=rows)


@profile_bp.route('/seller-request', methods=['POST'])
@login_required
def seller_request():
    """Submit seller access request."""
    existing_pending = SellerRequest.query.filter_by(
        user_id=current_user.id,
        status='pending'
    ).first()
    if existing_pending:
        flash('You already have a pending seller request.', 'error')
        return redirect(url_for('profile.settings'))

    if current_user.is_seller:
        flash('Your seller access is already approved.', 'info')
        return redirect(url_for('profile.settings'))

    real_name = (request.form.get('real_name') or '').strip()
    country = (request.form.get('country') or '').strip()
    city = (request.form.get('city') or '').strip()
    phone = (request.form.get('phone') or '').strip()
    product_description = (request.form.get('product_description') or '').strip()
    location_text = (request.form.get('location_text') or '').strip()
    location_lat = request.form.get('location_lat', type=float)
    location_lng = request.form.get('location_lng', type=float)
    plan_key = (request.form.get('plan') or '').strip()
    plan = SELLER_PLANS.get(plan_key)

    id_front = request.files.get('id_front')
    id_back = request.files.get('id_back')

    if not all([real_name, country, city, phone, product_description]):
        flash('All seller request fields are required.', 'error')
        return redirect(url_for('profile.settings'))

    if not plan:
        flash('Please choose a seller plan.', 'error')
        return redirect(url_for('profile.settings'))

    if not id_front or not id_front.filename or not id_back or not id_back.filename:
        flash('ID card front and back images are required.', 'error')
        return redirect(url_for('profile.settings'))

    id_front_path = save_uploaded_file(id_front, 'seller_ids')
    id_back_path = save_uploaded_file(id_back, 'seller_ids')
    if not id_front_path or not id_back_path:
        flash('ID images must be valid image files.', 'error')
        return redirect(url_for('profile.settings'))

    cost = int(plan['cost'])
    if current_user.coins < cost:
        flash(f'Insufficient TNNO. Need {cost:,}, you have {int(current_user.coins):,}.', 'error')
        return redirect(url_for('profile.settings'))

    # Charge plan cost at request time; refund if rejected.
    current_user.coins -= cost

    new_request = SellerRequest(
        user_id=current_user.id,
        real_name=real_name,
        country=country,
        city=city,
        phone=phone,
        product_description=product_description,
        id_front_path=id_front_path,
        id_back_path=id_back_path,
        location_text=location_text or None,
        location_lat=location_lat,
        location_lng=location_lng,
        plan_key=plan_key,
        plan_months=int(plan['months']),
        plan_cost=cost,
        status='pending'
    )
    db.session.add(new_request)
    db.session.commit()

    flash('Seller request submitted. Plan fee charged. Admin will review it soon.', 'success')
    return redirect(url_for('profile.settings'))


@profile_bp.route('/seller-plan', methods=['POST'])
@login_required
def seller_plan():
    """Purchase or renew seller subscription."""
    if not current_user.is_seller and not current_user.is_admin():
        flash('Seller access must be approved before purchasing a plan.', 'error')
        return redirect(url_for('profile.settings'))

    plan_key = (request.form.get('plan') or '').strip()
    plan = SELLER_PLANS.get(plan_key)
    if not plan:
        flash('Invalid seller plan selected.', 'error')
        return redirect(request.referrer or url_for('profile.settings'))

    cost = int(plan['cost'])
    if current_user.coins < cost:
        flash(f'Insufficient TNNO. Need {cost:,}, you have {int(current_user.coins):,}.', 'error')
        return redirect(request.referrer or url_for('profile.settings'))

    current_user.coins -= cost
    current_user.is_seller = True
    current_user.seller_expires_at = SellerService.compute_new_expiry(
        current_user.seller_expires_at,
        plan['months']
    )
    db.session.commit()

    flash('Seller plan activated successfully!', 'success')
    return redirect(request.referrer or url_for('profile.settings'))


@profile_bp.route('/delete-account', methods=['POST'])

@login_required
def delete_account():
    """Delete user account"""
    from flask_login import logout_user
    
    user_id = current_user.id
    user = User.query.get(user_id)
    
    if not user:
        flash('User not found', 'error')
        return redirect(url_for('profile.index'))
    
    # Delete user from database
    db.session.delete(user)
    db.session.commit()
    
    # Logout the user
    logout_user()
    
    flash('Account deleted successfully', 'success')
    return redirect(url_for('auth.login'))


@profile_bp.route('/leaderboard')
@login_required
def leaderboard():
    """View leaderboard - requires login for security"""
    tab = (request.args.get('tab') or 'users').lower()

    if tab == 'sellers':
        cache_key = f'leaderboard_sellers_user_{current_user.id}'
        cached = cache.get(cache_key)
        if cached is None:
            sales_subq = db.session.query(
                Product.seller_id.label('seller_id'),
                db.func.coalesce(db.func.sum(MerchOrder.total_price), 0).label('total_sales')
            ).join(Product, Product.id == MerchOrder.product_id)\
             .filter(MerchOrder.status == 'completed')\
             .group_by(Product.seller_id)\
             .subquery()

            ratings_subq = db.session.query(
                SellerRating.seller_id.label('seller_id'),
                db.func.coalesce(db.func.avg(SellerRating.rating), 0).label('avg_rating'),
                db.func.count(SellerRating.id).label('rating_count')
            ).group_by(SellerRating.seller_id)\
             .subquery()

            rows = db.session.query(
                User,
                sales_subq.c.total_sales,
                ratings_subq.c.avg_rating,
                ratings_subq.c.rating_count
            ).join(sales_subq, sales_subq.c.seller_id == User.id)\
             .outerjoin(ratings_subq, ratings_subq.c.seller_id == User.id)\
             .order_by(sales_subq.c.total_sales.desc())\
             .limit(50)\
             .all()

            cached = {'rows': rows}
            cache.set(cache_key, cached, timeout=300)

        return render_template('profile/leaderboard.html',
                               tab='sellers',
                               seller_rows=cached['rows'])

    # Default: top users by coins
    cache_key = f'leaderboard_user_{current_user.id}'
    cached = cache.get(cache_key)

    if cached is None:
        leaders = UserService.get_leaderboard(limit=50)
        # Rank = users with strictly higher coin balance + 1
        higher_count = db.session.query(db.func.count(User.id))\
            .filter(User.coins > (current_user.coins or 0))\
            .scalar() or 0
        user_rank = higher_count + 1
        cached = {'leaders': leaders, 'user_rank': user_rank}
        cache.set(cache_key, cached, timeout=300)

    return render_template('profile/leaderboard.html',
                           tab='users',
                           leaders=cached['leaders'],
                           user_rank=cached['user_rank'])
