"""
Utility Functions
Helper functions for the RetroQuest Platform
"""
import os
import io
import hashlib
import random
import string
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename
from flask import current_app
try:
    from PIL import Image, UnidentifiedImageError
except Exception:  # pragma: no cover - optional dependency during local dev
    Image = None

    class UnidentifiedImageError(Exception):
        pass
from app.models import User
from app.datetime_utils import utc_now
from app.services.cloudinary_service import CloudinaryService


# Allowed file extensions for uploads
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp', 'avif', 'jfif', 'tiff', 'tif'}
IMAGE_ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp', 'avif', 'jfif', 'tiff', 'tif'}
MAX_IMAGE_UPLOAD_BYTES = 2 * 1024 * 1024


def allowed_file(filename):
    """Check if file has allowed extension"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def generate_random_code(length=8):
    """Generate random alphanumeric code"""
    return ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(length))


def generate_unique_6digit_id():
    """Generate a unique 6-digit user ID"""
    from app.extensions import db
    from app.models import User
    
    while True:
        # Generate random 6-digit number
        user_6digit = str(random.randint(100000, 999999))
        
        # Check if it already exists
        existing = User.query.filter_by(user_6digit=user_6digit).first()
        if not existing:
            return user_6digit


def save_uploaded_file(file, subfolder=''):
    """
    Save uploaded file to static/uploads directory
    Returns the relative path from static folder for use in templates
    """
    if not file or not allowed_file(file.filename):
        return None

    cloudinary_folder = current_app.config.get('CLOUDINARY_UPLOAD_FOLDER') or 'retroquest'
    remote_url = CloudinaryService.upload(file, folder=f'{cloudinary_folder}/{subfolder or "misc"}', resource_type='auto')
    if remote_url:
        return remote_url
    
    # Generate secure filename
    filename = secure_filename(file.filename)
    
    # Add timestamp to make filename unique
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')[:-3]
    name, ext = os.path.splitext(filename)
    filename = f"{name}_{timestamp}{ext}"
    
    # Create upload folder under served static directory.
    upload_folder = current_app.config.get('UPLOAD_FOLDER') or os.path.join(current_app.static_folder, 'uploads')
    if not os.path.isabs(upload_folder):
        upload_folder = os.path.join(current_app.root_path, upload_folder)
    
    if subfolder:
        upload_folder = os.path.join(upload_folder, subfolder)
    
    os.makedirs(upload_folder, exist_ok=True)
    
    # Save file (absolute path)
    filepath = os.path.join(upload_folder, filename)
    file.save(filepath)
    
    # Return relative path from static folder for templates
    if subfolder:
        return f"uploads/{subfolder}/{filename}"
    return f"uploads/{filename}"


def save_uploaded_image_optimized(file, subfolder='posts', max_bytes=MAX_IMAGE_UPLOAD_BYTES):
    """
    Save a compressed image under static/uploads/<subfolder>.
    - validates common image uploads
    - enforces max upload size
    - deduplicates by content hash
    """
    if not file or not file.filename:
        return None

    cloudinary_folder = current_app.config.get('CLOUDINARY_UPLOAD_FOLDER') or 'retroquest'
    remote_url = CloudinaryService.upload(file, folder=f'{cloudinary_folder}/{subfolder}', resource_type='image')
    if remote_url:
        return remote_url

    safe_name = secure_filename(file.filename)
    ext = safe_name.rsplit('.', 1)[-1].lower() if '.' in safe_name else ''
    if ext and ext not in IMAGE_ALLOWED_EXTENSIONS:
        raise ValueError('Please upload a valid image file.')

    if Image is None:
        saved_path = save_uploaded_file(file, subfolder)
        if not saved_path:
            raise ValueError('Please upload a valid image file.')
        return saved_path

    raw = file.read()
    if not raw:
        raise ValueError('Empty image upload.')
    if len(raw) > max_bytes:
        raise ValueError('Image must be 2MB or smaller.')

    digest = hashlib.sha256(raw).hexdigest()[:24]

    try:
        image = Image.open(io.BytesIO(raw))
        image.load()
    except (UnidentifiedImageError, OSError):
        raise ValueError('Please upload a valid image file.')

    # Fit into a sane resolution to reduce storage and transfer cost.
    image.thumbnail((1920, 1920))

    has_alpha = 'A' in image.getbands() if hasattr(image, 'getbands') else False
    if not has_alpha and image.mode in ('P', 'LA'):
        image = image.convert('RGBA')
        has_alpha = True

    out_ext = 'png' if has_alpha else 'jpg'
    out_name = f'{digest}.{out_ext}'

    upload_folder = current_app.config.get('UPLOAD_FOLDER') or os.path.join(current_app.static_folder, 'uploads')
    if not os.path.isabs(upload_folder):
        upload_folder = os.path.join(current_app.root_path, upload_folder)
    if subfolder:
        upload_folder = os.path.join(upload_folder, subfolder)
    os.makedirs(upload_folder, exist_ok=True)

    out_path = os.path.join(upload_folder, out_name)
    if os.path.exists(out_path):
        return f'uploads/{subfolder}/{out_name}' if subfolder else f'uploads/{out_name}'

    if out_ext == 'png':
        if image.mode not in ('RGB', 'RGBA'):
            image = image.convert('RGBA')
        image.save(out_path, format='PNG', optimize=True)
    else:
        if image.mode not in ('RGB', 'L'):
            image = image.convert('RGB')
        quality = 85
        while True:
            buf = io.BytesIO()
            image.save(buf, format='JPEG', optimize=True, quality=quality, progressive=True)
            data = buf.getvalue()
            if len(data) <= max_bytes or quality <= 55:
                with open(out_path, 'wb') as f:
                    f.write(data)
                break
            quality -= 5

    if os.path.getsize(out_path) > max_bytes:
        try:
            os.remove(out_path)
        except OSError:
            pass
        raise ValueError('Image is too large after compression. Please upload a smaller file.')

    return f'uploads/{subfolder}/{out_name}' if subfolder else f'uploads/{out_name}'


def save_uploaded_file_any(file, subfolder='', allowed_exts=None):
    """Save uploaded file with a custom allowlist of extensions."""
    if not file or not file.filename:
        return None
    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    normalized_allowed = {str(item).lower() for item in (allowed_exts or set())} if allowed_exts is not None else None
    if normalized_allowed is not None and ext not in normalized_allowed:
        return None

    cloudinary_folder = current_app.config.get('CLOUDINARY_UPLOAD_FOLDER') or 'retroquest'
    remote_url = CloudinaryService.upload(file, folder=f'{cloudinary_folder}/{subfolder or "misc"}', resource_type='raw')
    if remote_url:
        return remote_url

    filename = secure_filename(file.filename)
    if not filename:
        return None
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')[:-3]
    name, ext_with_dot = os.path.splitext(filename)
    filename = f"{name}_{timestamp}{ext_with_dot}"

    upload_folder = current_app.config.get('UPLOAD_FOLDER') or os.path.join(current_app.static_folder, 'uploads')
    if not os.path.isabs(upload_folder):
        upload_folder = os.path.join(current_app.root_path, upload_folder)
    if subfolder:
        upload_folder = os.path.join(upload_folder, subfolder)
    os.makedirs(upload_folder, exist_ok=True)

    filepath = os.path.join(upload_folder, filename)
    file.save(filepath)

    if subfolder:
        return f"uploads/{subfolder}/{filename}"
    return f"uploads/{filename}"


def get_current_user():
    """Get current logged in user from session"""
    from flask_login import current_user
    if current_user.is_authenticated:
        return current_user
    return None


def is_admin(user):
    """Check if user is admin"""
    if not user:
        return False
    admin_username = current_app.config.get('ADMIN_USER', 'admin')
    return user.username == admin_username or user.role == 'admin'


def format_datetime(dt):
    """Format datetime to readable string"""
    if not dt:
        return ''
    return dt.strftime('%Y-%m-%d %H:%M:%S')


def format_datetime_ago(dt):
    """Format datetime as 'ago' string"""
    if not dt:
        return ''
    
    now = utc_now()
    diff = now - dt
    
    if diff.days > 365:
        return f"{diff.days // 365} year(s) ago"
    elif diff.days > 30:
        return f"{diff.days // 30} month(s) ago"
    elif diff.days > 0:
        return f"{diff.days} day(s) ago"
    elif diff.seconds > 3600:
        return f"{diff.seconds // 3600} hour(s) ago"
    elif diff.seconds > 60:
        return f"{diff.seconds // 60} minute(s) ago"
    else:
        return "just now"


def count_words(text: str) -> int:
    """Count words in a string."""
    if not text:
        return 0
    return len([w for w in text.strip().split() if w])


def calculate_deadline(hours=24):
    """Calculate deadline datetime"""
    return utc_now() + timedelta(hours=hours)


def paginate_query(query, page=1, per_page=20):
    """Paginate SQLAlchemy query"""
    return query.paginate(page=page, per_page=per_page, error_out=False)


def get_user_stats(user_id):
    """Get user statistics"""
    from app.models import UserMission, Post, Deposit, WithdrawRequest
    
    completed_missions = UserMission.query.filter_by(
        user_id=user_id, 
        status='completed'
    ).count()
    
    total_posts = Post.query.filter_by(user_id=user_id).count()
    total_deposits = Deposit.query.filter(
        Deposit.user_id == user_id,
        Deposit.status.in_(['success', 'completed'])
    ).count()
    total_withdraws = WithdrawRequest.query.filter_by(
        user_id=user_id, 
        status='approved'
    ).count()
    
    return {
        'completed_missions': completed_missions,
        'total_posts': total_posts,
        'total_deposits': total_deposits,
        'total_withdraws': total_withdraws
    }


def generate_qr_code(data):
    """Generate QR code for deposit address"""
    from io import BytesIO
    import base64
    try:
        import qrcode

        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(data)
        qr.make(fit=True)

        img = qr.make_image(fill_color="black", back_color="white")

        buffer = BytesIO()
        img.save(buffer, format='PNG')
        buffer.seek(0)

        img_base64 = base64.b64encode(buffer.getvalue()).decode()
        return f"data:image/png;base64,{img_base64}"
    except Exception:
        svg = (
            "<svg xmlns='http://www.w3.org/2000/svg' width='320' height='320' viewBox='0 0 320 320'>"
            "<rect width='320' height='320' fill='white'/>"
            "<rect x='16' y='16' width='288' height='288' fill='none' stroke='#4f6fb4' stroke-width='8'/>"
            "<text x='160' y='120' text-anchor='middle' font-family='monospace' font-size='22' fill='#2d3b55'>QR Unavailable</text>"
            "<text x='160' y='160' text-anchor='middle' font-family='monospace' font-size='15' fill='#60708e'>Copy the wallet address</text>"
            "<text x='160' y='188' text-anchor='middle' font-family='monospace' font-size='15' fill='#60708e'>and exact amount below.</text>"
            "</svg>"
        )
        encoded = base64.b64encode(svg.encode('utf-8')).decode('ascii')
        return f"data:image/svg+xml;base64,{encoded}"


def get_leaderboard(limit=10, game_id='emperors_circle'):
    """Get leaderboard rankings"""
    from app.models import GameScore, User
    
    scores = GameScore.query.filter_by(game_id=game_id)\
        .order_by(GameScore.score.desc())\
        .limit(limit)\
        .all()
    
    leaderboard = []
    for rank, score in enumerate(scores, 1):
        leaderboard.append({
            'rank': rank,
            'user_id': score.user_id,
            'username': score.user.username if score.user else 'Unknown',
            'score': score.score
        })
    
    return leaderboard
