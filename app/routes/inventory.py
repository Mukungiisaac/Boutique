import os
import uuid
from flask import Blueprint, render_template, request, jsonify, current_app, flash, redirect, url_for
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from app import db
from app.models import Product, ProductVariant, Category
from sqlalchemy import func

inventory_bp = Blueprint('inventory', __name__)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


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
            price = request.form.get('price', type=float)
            cost_price = request.form.get('cost_price', 0.0, type=float)
            description = request.form.get('description', '').strip()

            if not all([name, sku, category_id, price]):
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
                if file and file.filename and allowed_file(file.filename):
                    filename = f"{uuid.uuid4().hex}_{secure_filename(file.filename)}"
                    upload_folder = current_app.config['UPLOAD_FOLDER']
                    file.save(os.path.join(upload_folder, filename))
                    image_path = f'/static/uploads/{filename}'

            product = Product(
                name=name, sku=sku, category_id=category_id,
                price=price, cost_price=cost_price,
                description=description, image=image_path
            )
            db.session.add(product)
            db.session.flush()

            # Handle variants
            sizes = request.form.getlist('variant_size[]')
            colors = request.form.getlist('variant_color[]')
            stocks = request.form.getlist('variant_stock[]')

            if sizes:
                for i in range(len(sizes)):
                    size = sizes[i].strip() if i < len(sizes) else ''
                    color = colors[i].strip() if i < len(colors) else ''
                    stock = int(stocks[i]) if i < len(stocks) and stocks[i].isdigit() else 0
                    v = ProductVariant(product_id=product.id, size=size, color=color, stock_qty=stock)
                    db.session.add(v)
            else:
                # Default variant
                db.session.add(ProductVariant(product_id=product.id, size='One Size', color='', stock_qty=0))

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
            product.price = request.form.get('price', type=float)
            product.cost_price = request.form.get('cost_price', 0.0, type=float)
            product.description = request.form.get('description', '').strip()

            # Image update
            if 'image' in request.files:
                file = request.files['image']
                if file and file.filename and allowed_file(file.filename):
                    filename = f"{uuid.uuid4().hex}_{secure_filename(file.filename)}"
                    upload_folder = current_app.config['UPLOAD_FOLDER']
                    file.save(os.path.join(upload_folder, filename))
                    product.image = f'/static/uploads/{filename}'

            # Update variants — delete existing and recreate
            ProductVariant.query.filter_by(product_id=product.id).delete()

            sizes = request.form.getlist('variant_size[]')
            colors = request.form.getlist('variant_color[]')
            stocks = request.form.getlist('variant_stock[]')

            for i in range(len(sizes)):
                size = sizes[i].strip() if i < len(sizes) else ''
                color = colors[i].strip() if i < len(colors) else ''
                stock = int(stocks[i]) if i < len(stocks) and stocks[i].isdigit() else 0
                v = ProductVariant(product_id=product.id, size=size, color=color, stock_qty=stock)
                db.session.add(v)

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
