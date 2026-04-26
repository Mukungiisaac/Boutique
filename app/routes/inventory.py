import os
import uuid
from flask import Blueprint, render_template, request, jsonify, current_app, flash, redirect, url_for
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from app import db
from app.models import Product, ProductVariant, Category
from app.utils import extract_upload_filename
from sqlalchemy import func

inventory_bp = Blueprint('inventory', __name__)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def save_product_image(file_obj):
    if not file_obj or not file_obj.filename or not allowed_file(file_obj.filename):
        return None
    filename = f"{uuid.uuid4().hex}_{secure_filename(file_obj.filename)}"
    upload_folder = current_app.config['UPLOAD_FOLDER']
    os.makedirs(upload_folder, exist_ok=True)
    file_obj.save(os.path.join(upload_folder, filename))
    return filename


def delete_product_image(image_value):
    filename = extract_upload_filename(image_value)
    if not filename:
        return
    image_path = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
    if os.path.exists(image_path):
        os.remove(image_path)


def parse_variant_rows(form_data):
    sizes = form_data.getlist('variant_size[]')
    colors = form_data.getlist('variant_color[]')
    stocks = form_data.getlist('variant_stock[]')
    variants = []

    row_count = max(len(sizes), len(colors), len(stocks))
    for i in range(row_count):
        size = sizes[i].strip() if i < len(sizes) and sizes[i] else ''
        color = colors[i].strip() if i < len(colors) and colors[i] else ''
        stock_raw = stocks[i].strip() if i < len(stocks) and stocks[i] else '0'
        stock = int(stock_raw) if stock_raw.isdigit() else 0

        if not size and not color and stock == 0:
            continue

        variants.append({
            'size': size,
            'color': color,
            'stock_qty': stock,
        })

    if not variants:
        variants.append({'size': 'One Size', 'color': '', 'stock_qty': 0})

    return variants


@inventory_bp.route('/inventory')
@login_required
def index():
    page = request.args.get('page', 1, type=int)
    per_page = 10
    search = request.args.get('search', '')
    category_id = request.args.get('category', '', type=str)

    query = Product.query.filter_by(is_active=True)
    if search:
        query = query.filter(
            (Product.name.ilike(f'%{search}%')) |
            (Product.sku.ilike(f'%{search}%'))
        )
    if category_id:
        query = query.filter_by(category_id=category_id)

    products = query.order_by(Product.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False)

    categories = Category.query.all()

    # Stats
    total_units = db.session.query(func.sum(ProductVariant.stock_qty)).scalar() or 0
    inventory_value = db.session.query(
        func.sum(Product.price * ProductVariant.stock_qty)
    ).join(ProductVariant).filter(Product.is_active == True).scalar() or 0
    low_stock_count = db.session.query(func.count(Product.id)).join(ProductVariant).filter(
        ProductVariant.stock_qty <= 5, ProductVariant.stock_qty > 0,
        Product.is_active == True
    ).scalar() or 0

    return render_template('inventory/index.html',
                           products=products,
                           categories=categories,
                           search=search,
                           selected_category=category_id,
                           total_units=total_units,
                           inventory_value=inventory_value,
                           low_stock_count=low_stock_count)


@inventory_bp.route('/inventory/add', methods=['GET', 'POST'])
@login_required
def add_product():
    categories = Category.query.all()
    if request.method == 'POST':
        try:
            name = request.form.get('name', '').strip()
            sku = request.form.get('sku', '').strip()
            category_id = request.form.get('category_id', type=int)
            price = request.form.get('price', 0.0, type=float)
            cost_price = request.form.get('cost_price', 0.0, type=float)
            description = request.form.get('description', '').strip()

            if not all([name, sku, category_id]):
                flash('Please fill all required fields.', 'error')
                return render_template('inventory/form.html', categories=categories, product=None)

            # Check duplicate SKU
            if Product.query.filter_by(sku=sku).first():
                flash('A product with this SKU already exists.', 'error')
                return render_template('inventory/form.html', categories=categories, product=None)

            # Handle image upload
            image_path = ''
            if 'image' in request.files:
                file = request.files['image']
                saved_image = save_product_image(file)
                if saved_image:
                    image_path = saved_image

            product = Product(
                name=name, sku=sku, category_id=category_id,
                price=price or 0.0, cost_price=cost_price,
                description=description, image=image_path
            )
            db.session.add(product)
            db.session.flush()

            # Handle variants
            variants = parse_variant_rows(request.form)
            for variant in variants:
                db.session.add(ProductVariant(
                    product_id=product.id,
                    size=variant['size'],
                    color=variant['color'],
                    stock_qty=variant['stock_qty']
                ))

            db.session.commit()
            flash(f'Product "{name}" added successfully!', 'success')
            return redirect(url_for('inventory.index'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error adding product: {str(e)}', 'error')

    return render_template('inventory/form.html', categories=categories, product=None)


@inventory_bp.route('/inventory/edit/<int:product_id>', methods=['GET', 'POST'])
@login_required
def edit_product(product_id):
    product = Product.query.get_or_404(product_id)
    categories = Category.query.all()

    if request.method == 'POST':
        try:
            product.name = request.form.get('name', '').strip()
            product.sku = request.form.get('sku', '').strip()
            product.category_id = request.form.get('category_id', type=int)
            product.price = request.form.get('price', 0.0, type=float) or 0.0
            product.cost_price = request.form.get('cost_price', 0.0, type=float)
            product.description = request.form.get('description', '').strip()

            # Image update
            if 'image' in request.files:
                file = request.files['image']
                saved_image = save_product_image(file)
                if saved_image:
                    delete_product_image(product.image)
                    product.image = saved_image

            # Update variants — delete existing and recreate
            ProductVariant.query.filter_by(product_id=product.id).delete()

            variants = parse_variant_rows(request.form)
            for variant in variants:
                db.session.add(ProductVariant(
                    product_id=product.id,
                    size=variant['size'],
                    color=variant['color'],
                    stock_qty=variant['stock_qty']
                ))

            db.session.commit()
            flash(f'Product "{product.name}" updated successfully!', 'success')
            return redirect(url_for('inventory.index'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating product: {str(e)}', 'error')

    return render_template('inventory/form.html', categories=categories, product=product)


@inventory_bp.route('/inventory/delete/<int:product_id>', methods=['POST'])
@login_required
def delete_product(product_id):
    product = Product.query.get_or_404(product_id)
    try:
        product.is_active = False  # Soft delete
        db.session.commit()
        return jsonify({'success': True, 'message': f'"{product.name}" removed from inventory.'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@inventory_bp.route('/inventory/export')
@login_required
def export_csv():
    import csv
    import io
    from flask import Response

    products = Product.query.filter_by(is_active=True).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['SKU', 'Name', 'Category', 'Price', 'Cost Price', 'Total Stock', 'Status'])
    for p in products:
        writer.writerow([
            p.sku, p.name,
            p.category.name if p.category else '',
            p.price, p.cost_price,
            p.total_stock, p.status
        ])
    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=inventory.csv'}
    )
