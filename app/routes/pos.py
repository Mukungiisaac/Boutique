import random
import string
from datetime import datetime
from flask import Blueprint, render_template, request, jsonify, send_file
from flask_login import login_required, current_user
from app import db
from app.models import Product, ProductVariant, Sale, SaleItem, Customer, Category
from app.pdf_generator import generate_receipt_pdf

pos_bp = Blueprint('pos', __name__)


@pos_bp.route('/pos')
@login_required
def index():
    categories = Category.query.all()
    customers = Customer.query.order_by(Customer.name).all()
    selected_customer_id = request.args.get('customer_id', type=int)
    return render_template(
        'pos/index.html',
        categories=categories,
        customers=customers,
        selected_customer_id=selected_customer_id
    )


@pos_bp.route('/pos/products')
@login_required
def get_products():
    search = request.args.get('q', '')
    cat_id = request.args.get('category', '', type=str)

    query = Product.query.filter_by(is_active=True)
    if search:
        query = query.filter(
            (Product.name.ilike(f'%{search}%')) |
            (Product.sku.ilike(f'%{search}%'))
        )
    if cat_id:
        query = query.filter_by(category_id=cat_id)

    products = query.order_by(Product.name).all()
    result = []
    for p in products:
        variants = [{'id': v.id, 'size': v.size, 'color': v.color, 'stock': v.stock_qty}
                    for v in p.variants if v.stock_qty > 0]
        image = p.image or ''
        if image and not image.startswith('/') and not image.startswith('http'):
            image = f'/static/uploads/{image}'
        result.append({
            'id': p.id,
            'name': p.name,
            'sku': p.sku,
            'price': p.price,
            'cost_price': p.cost_price or 0,
            'category': p.category.name if p.category else '',
            'image': image,
            'colors': p.colors,
            'variants': variants,
            'total_stock': p.total_stock,
        })
    return jsonify(result)


@pos_bp.route('/pos/checkout', methods=['POST'])
@login_required
def checkout():
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'Invalid request data.'}), 400

    cart_items = data.get('cart', [])
    customer_id = data.get('customer_id') or None
    payment_method = data.get('payment_method', 'cash')
    mpesa_ref = data.get('mpesa_ref', '')
    discount = float(data.get('discount', 0))

    if not cart_items:
        return jsonify({'success': False, 'message': 'Cart is empty.'}), 400

    try:
        subtotal = 0.0
        total_cost = 0.0
        sale_items = []

        for item in cart_items:
            product = db.session.get(Product, item['product_id'])
            if not product:
                return jsonify({'success': False, 'message': 'Product not found.'}), 404

            qty = int(item['quantity'])
            variant_id = item.get('variant_id')
            variant = None

            if variant_id:
                variant = db.session.get(ProductVariant, variant_id)
                if not variant or variant.product_id != product.id:
                    return jsonify({'success': False,
                                    'message': f'Invalid variant selection for {product.name}.'}), 400
                if variant.stock_qty < qty:
                    return jsonify({'success': False,
                                    'message': f'Insufficient stock for {product.name}.'}), 400
            else:
                available_variants = product.variants.order_by(ProductVariant.id.asc()).all()
                if not available_variants:
                    return jsonify({'success': False,
                                    'message': f'No sellable variants found for {product.name}.'}), 400
                if len(available_variants) > 1:
                    return jsonify({'success': False,
                                    'message': f'Please select a size or color for {product.name}.'}), 400
                variant = available_variants[0]
                variant_id = variant.id
                if variant.stock_qty < qty:
                    return jsonify({'success': False,
                                    'message': f'Insufficient stock for {product.name}.'}), 400

            unit_price = product.price
            cost_price = product.cost_price or 0.0
            line_total = unit_price * qty
            line_cost  = cost_price * qty

            subtotal   += line_total
            total_cost += line_cost

            sale_items.append({
                'product':    product,
                'variant_id': variant_id,
                'qty':        qty,
                'unit_price': unit_price,
                'cost_price': cost_price,
                'line_total': line_total,
                'size':       variant.size if variant else item.get('size', ''),
                'color':      variant.color if variant else item.get('color', ''),
            })

        total        = max(subtotal - discount, 0)
        total_profit = total - total_cost   # positive = profit, negative = loss

        order_num = f"ORD-{datetime.utcnow().strftime('%Y%m%d')}-{''.join(random.choices(string.digits, k=4))}"

        sale = Sale(
            order_number=order_num,
            customer_id=int(customer_id) if customer_id else None,
            cashier_id=current_user.id,
            subtotal=subtotal,
            discount=discount,
            total_amount=total,
            total_cost=total_cost,
            total_profit=total_profit,
            payment_method=payment_method,
            mpesa_ref=mpesa_ref,
            status='completed'
        )
        db.session.add(sale)
        db.session.flush()

        for si in sale_items:
            item_record = SaleItem(
                sale_id=sale.id,
                product_id=si['product'].id,
                variant_id=si['variant_id'],
                quantity=si['qty'],
                unit_price=si['unit_price'],
                cost_price=si['cost_price'],
                line_total=si['line_total'],
                size=si['size'],
                color=si['color'],
                product_name=si['product'].name
            )
            db.session.add(item_record)

            # Deduct stock
            if si['variant_id']:
                variant = db.session.get(ProductVariant, si['variant_id'])
                if variant:
                    variant.stock_qty = max(variant.stock_qty - si['qty'], 0)

        # Loyalty points
        if customer_id:
            customer = db.session.get(Customer, int(customer_id))
            if customer:
                customer.loyalty_points += int(total // 100)

        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'Sale completed successfully!',
            'order_number': order_num,
            'sale_id': sale.id,
            'total': total,
            'profit': total_profit,
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Checkout error: {str(e)}'}), 500


@pos_bp.route('/pos/receipt/<int:sale_id>')
@login_required
def receipt(sale_id):
    sale = Sale.query.get_or_404(sale_id)
    items = sale.items.all()
    return render_template('pos/receipt.html', sale=sale, items=items)


@pos_bp.route('/pos/receipt/<int:sale_id>/pdf')
@login_required
def receipt_pdf(sale_id):
    sale = Sale.query.get_or_404(sale_id)
    pdf_buffer = generate_receipt_pdf(sale)
    return send_file(
        pdf_buffer,
        as_attachment=True,
        download_name=f"receipt_{sale.order_number}.pdf",
        mimetype='application/pdf'
    )
