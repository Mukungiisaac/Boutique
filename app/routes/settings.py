from flask import Blueprint, render_template, request, jsonify, current_app
from flask_login import login_required, current_user
from app import db
from app.models import User, Category, StoreSetting
from werkzeug.security import generate_password_hash
import os
import uuid

settings_bp = Blueprint('settings', __name__)


def _allowed_file(filename):
    allowed = current_app.config.get('ALLOWED_EXTENSIONS', {'png', 'jpg', 'jpeg', 'gif', 'webp'})
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed


def _save_upload(file_obj, prefix='user'):
    if not file_obj or file_obj.filename == '':
        return None
    if not _allowed_file(file_obj.filename):
        return None
    ext = file_obj.filename.rsplit('.', 1)[1].lower()
    filename = f"{prefix}_{uuid.uuid4().hex}.{ext}"
    upload_folder = current_app.config['UPLOAD_FOLDER']
    os.makedirs(upload_folder, exist_ok=True)
    file_obj.save(os.path.join(upload_folder, filename))
    return filename


def _require_admin():
    if current_user.is_admin:
        return None
    return jsonify({'success': False, 'message': 'Admin access is required for this action.'}), 403


@settings_bp.route('/settings')
@login_required
def index():
    categories = Category.query.order_by(Category.name).all()
    users = User.query.all() if current_user.is_admin else []
    store_name = StoreSetting.get('store_name', 'Boutique POS')
    theme_color = StoreSetting.get('theme_color', '#00D4C8')
    return render_template('settings/index.html',
                           categories=categories,
                           users=users,
                           store_name=store_name,
                           theme_color=theme_color)


@settings_bp.route('/settings/change-password', methods=['POST'])
@login_required
def change_password():
    data = request.get_json()
    current_pw = data.get('current_password', '')
    new_pw = data.get('new_password', '')
    if not current_user.check_password(current_pw):
        return jsonify({'success': False, 'message': 'Current password is incorrect.'}), 400
    if len(new_pw) < 6:
        return jsonify({'success': False, 'message': 'Password must be at least 6 characters.'}), 400
    current_user.set_password(new_pw)
    db.session.commit()
    return jsonify({'success': True, 'message': 'Password changed successfully!'})


@settings_bp.route('/settings/add-category', methods=['POST'])
@login_required
def add_category():
    admin_error = _require_admin()
    if admin_error:
        return admin_error
    data = request.get_json()
    name = data.get('name', '').strip()
    if not name:
        return jsonify({'success': False, 'message': 'Category name is required.'}), 400
    if Category.query.filter_by(name=name).first():
        return jsonify({'success': False, 'message': 'Category already exists.'}), 400
    cat = Category(name=name)
    db.session.add(cat)
    db.session.commit()
    return jsonify({'success': True, 'message': 'Category added!', 'id': cat.id, 'name': cat.name})


@settings_bp.route('/settings/delete-category/<int:cat_id>', methods=['POST'])
@login_required
def delete_category(cat_id):
    admin_error = _require_admin()
    if admin_error:
        return admin_error
    cat = Category.query.get_or_404(cat_id)
    if cat.products.count() > 0:
        return jsonify({'success': False, 'message': 'Cannot delete category with products.'}), 400
    db.session.delete(cat)
    db.session.commit()
    return jsonify({'success': True, 'message': 'Category deleted.'})


@settings_bp.route('/settings/save-branding', methods=['POST'])
@login_required
def save_branding():
    admin_error = _require_admin()
    if admin_error:
        return admin_error
    data = request.get_json()
    store_name = data.get('store_name', '').strip()
    theme_color = data.get('theme_color', '').strip()

    if not store_name:
        return jsonify({'success': False, 'message': 'Store name cannot be empty.'}), 400
    if not theme_color or not theme_color.startswith('#'):
        return jsonify({'success': False, 'message': 'Invalid color value.'}), 400

    StoreSetting.set('store_name', store_name)
    StoreSetting.set('theme_color', theme_color)
    db.session.commit()
    return jsonify({'success': True, 'message': 'Branding saved!',
                    'store_name': store_name, 'theme_color': theme_color})


@settings_bp.route('/settings/update-profile', methods=['POST'])
@login_required
def update_profile():
    name  = request.form.get('name', '').strip()
    email = request.form.get('email', '').strip()

    if not name:
        return jsonify({'success': False, 'message': 'Name cannot be empty.'}), 400
    if not email:
        return jsonify({'success': False, 'message': 'Email cannot be empty.'}), 400

    # Check if email is taken by another user
    existing = User.query.filter(User.email == email, User.id != current_user.id).first()
    if existing:
        return jsonify({'success': False, 'message': 'Email already in use by another account.'}), 400

    try:
        current_user.name  = name
        current_user.email = email

        # Handle avatar upload
        avatar_file = request.files.get('avatar')
        new_avatar = _save_upload(avatar_file, prefix='user')
        if new_avatar:
            # Delete old avatar if exists
            if current_user.avatar:
                old_path = os.path.join(current_app.config['UPLOAD_FOLDER'], current_user.avatar)
                if os.path.exists(old_path):
                    os.remove(old_path)
            current_user.avatar = new_avatar

        db.session.commit()
        return jsonify({'success': True, 'message': 'Profile updated!', 'avatar': current_user.avatar})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500
