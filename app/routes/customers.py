import os
import uuid
from flask import Blueprint, render_template, request, jsonify, current_app
from flask_login import login_required
from werkzeug.utils import secure_filename
from app import db
from app.models import Customer, Sale, SaleItem
from app.utils import upload_url

customers_bp = Blueprint('customers', __name__)


def _allowed_file(filename):
    allowed = current_app.config.get('ALLOWED_EXTENSIONS', {'png', 'jpg', 'jpeg', 'gif', 'webp'})
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed


def _save_photo(file_obj):
    """Save uploaded photo and return just the filename, or None on failure."""
    if not file_obj or file_obj.filename == '':
        return None
    if not _allowed_file(file_obj.filename):
        return None
    ext = file_obj.filename.rsplit('.', 1)[1].lower()
    filename = f"customer_{uuid.uuid4().hex}.{ext}"
    upload_folder = current_app.config['UPLOAD_FOLDER']
    os.makedirs(upload_folder, exist_ok=True)
    file_obj.save(os.path.join(upload_folder, filename))
    return filename


@customers_bp.route('/customers')
@login_required
def index():
    search = request.args.get('search', '')
    query = Customer.query
    if search:
        query = query.filter(
            (Customer.name.ilike(f'%{search}%')) |
            (Customer.phone.ilike(f'%{search}%'))
        )
    customers = query.order_by(Customer.name).all()
    selected_id = request.args.get('id', type=int)
    selected_customer = None
    if selected_id:
        selected_customer = Customer.query.get(selected_id)
    elif customers:
        selected_customer = customers[0]

    return render_template('customers/index.html',
                           customers=customers,
                           selected_customer=selected_customer,
                           search=search)


@customers_bp.route('/customers/add', methods=['POST'])
@login_required
def add_customer():
    # Support both multipart/form-data (with photo) and JSON
    if request.content_type and 'multipart/form-data' in request.content_type:
        name = request.form.get('name', '').strip()
        phone = request.form.get('phone', '').strip()
        email = request.form.get('email', '').strip()
        preferred_size = request.form.get('preferred_size', '').strip()
        staff_note = request.form.get('staff_note', '').strip()
        marketing_optin = request.form.get('marketing_optin', 'true').lower() == 'true'
        photo_file = request.files.get('photo')
    else:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'Invalid data.'}), 400
        name = data.get('name', '').strip()
        phone = data.get('phone', '').strip()
        email = data.get('email', '').strip()
        preferred_size = data.get('preferred_size', '').strip()
        staff_note = data.get('staff_note', '').strip()
        marketing_optin = data.get('marketing_optin', True)
        photo_file = None

    if not name or not phone:
        return jsonify({'success': False, 'message': 'Name and phone are required.'}), 400

    if Customer.query.filter_by(phone=phone).first():
        return jsonify({'success': False, 'message': 'A customer with this phone already exists.'}), 400

    try:
        photo_url = _save_photo(photo_file) or ''
        customer = Customer(
            name=name, phone=phone, email=email,
            preferred_size=preferred_size,
            staff_note=staff_note,
            marketing_optin=marketing_optin,
            photo=photo_url,
            tier='Bronze'
        )
        db.session.add(customer)
        db.session.commit()
        return jsonify({'success': True, 'message': 'Customer added!', 'id': customer.id})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@customers_bp.route('/customers/edit/<int:customer_id>', methods=['POST'])
@login_required
def edit_customer(customer_id):
    customer = Customer.query.get_or_404(customer_id)

    # Support multipart (with photo) or JSON
    if request.content_type and 'multipart/form-data' in request.content_type:
        name = request.form.get('name', customer.name).strip()
        phone = request.form.get('phone', customer.phone).strip()
        email = request.form.get('email', customer.email).strip()
        preferred_size = request.form.get('preferred_size', customer.preferred_size)
        staff_note = request.form.get('staff_note', customer.staff_note)
        marketing_optin_raw = request.form.get('marketing_optin')
        marketing_optin = (marketing_optin_raw.lower() == 'true') if marketing_optin_raw else customer.marketing_optin
        tier = request.form.get('tier', customer.tier)
        style_tags = request.form.get('style_tags', customer.style_tags).strip()
        store_credit_raw = request.form.get('store_credit')
        store_credit = float(store_credit_raw) if store_credit_raw else customer.store_credit
        photo_file = request.files.get('photo')
    else:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'Invalid data.'}), 400
        name = data.get('name', customer.name).strip()
        phone = data.get('phone', customer.phone).strip()
        email = data.get('email', customer.email).strip()
        preferred_size = data.get('preferred_size', customer.preferred_size)
        staff_note = data.get('staff_note', customer.staff_note)
        marketing_optin = data.get('marketing_optin', customer.marketing_optin)
        style_tags = data.get('style_tags', customer.style_tags)
        tier = data.get('tier', customer.tier)
        store_credit = data.get('store_credit', customer.store_credit)
        photo_file = None

    try:
        existing = Customer.query.filter(Customer.phone == phone, Customer.id != customer.id).first()
        if existing:
            return jsonify({'success': False, 'message': 'A customer with this phone already exists.'}), 400

        customer.name = name
        customer.phone = phone
        customer.email = email
        customer.preferred_size = preferred_size
        customer.staff_note = staff_note
        customer.marketing_optin = marketing_optin
        customer.style_tags = style_tags
        customer.tier = tier
        customer.store_credit = store_credit

        new_photo = _save_photo(photo_file)
        if new_photo:
            # Delete old photo file if it exists
            if customer.photo:
                old_path = os.path.join(current_app.config['UPLOAD_FOLDER'], customer.photo)
                if os.path.exists(old_path):
                    os.remove(old_path)
            customer.photo = new_photo

        db.session.commit()
        return jsonify({'success': True, 'message': 'Customer updated!', 'photo': customer.photo})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@customers_bp.route('/customers/<int:customer_id>')
@login_required
def get_customer(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    purchases = Sale.query.filter_by(customer_id=customer_id, status='completed') \
        .order_by(Sale.created_at.desc()).limit(10).all()

    purchase_list = []
    for sale in purchases:
        items = sale.items.all()
        purchase_list.append({
            'id': sale.id,
            'date': sale.created_at.strftime('%Y-%m-%d'),
            'items': ', '.join([i.product_name for i in items]),
            'amount': sale.total_amount,
            'order_number': sale.order_number,
            'payment_method': sale.payment_method,
        })

    return jsonify({
        'id': customer.id,
        'name': customer.name,
        'phone': customer.phone,
        'email': customer.email,
        'photo': customer.photo or '',
        'photo_url': upload_url(customer.photo),
        'tier': customer.tier,
        'loyalty_points': customer.loyalty_points,
        'store_credit': customer.store_credit,
        'preferred_size': customer.preferred_size,
        'style_tags': customer.style_tags or '',
        'staff_note': customer.staff_note,
        'marketing_optin': customer.marketing_optin,
        'total_spend': customer.total_spend,
        'avg_order_value': customer.avg_order_value,
        'last_purchase': customer.last_purchase_date.strftime('%Y-%m-%d') if customer.last_purchase_date else 'N/A',
        'since': customer.created_at.strftime('%b %Y'),
        'purchases': purchase_list
    })


@customers_bp.route('/customers/delete/<int:customer_id>', methods=['POST'])
@login_required
def delete_customer(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    try:
        # Remove photo file
        if customer.photo:
            old_path = os.path.join(current_app.config['UPLOAD_FOLDER'], customer.photo)
            if os.path.exists(old_path):
                os.remove(old_path)
        Sale.query.filter_by(customer_id=customer_id).update({'customer_id': None})
        db.session.delete(customer)
        db.session.commit()
        return jsonify({'success': True, 'message': 'Customer removed.'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500
