from flask import Blueprint, jsonify, request
from flask_login import login_required
from app.models import Product, Customer, Sale
from app import db
from sqlalchemy import func

api_bp = Blueprint('api', __name__)


@api_bp.route('/search')
@login_required
def global_search():
    q = request.args.get('q', '').strip()
    if len(q) < 2:
        return jsonify({'products': [], 'customers': []})

    products = Product.query.filter(
        Product.name.ilike(f'%{q}%') | Product.sku.ilike(f'%{q}%'),
        Product.is_active == True
    ).limit(5).all()

    customers = Customer.query.filter(
        Customer.name.ilike(f'%{q}%') | Customer.phone.ilike(f'%{q}%')
    ).limit(5).all()

    return jsonify({
        'products': [{'id': p.id, 'name': p.name, 'sku': p.sku, 'price': p.price} for p in products],
        'customers': [{'id': c.id, 'name': c.name, 'phone': c.phone} for c in customers]
    })


@api_bp.route('/dashboard/stats')
@login_required
def dashboard_stats():
    from datetime import datetime, timedelta
    week_start = datetime.utcnow() - timedelta(days=7)
    weekly_data = []
    day_labels = []
    for i in range(6, -1, -1):
        day = datetime.utcnow() - timedelta(days=i)
        day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day.replace(hour=23, minute=59, second=59)
        rev = db.session.query(func.sum(Sale.total_amount)).filter(
            Sale.status == 'completed',
            Sale.created_at >= day_start,
            Sale.created_at <= day_end
        ).scalar() or 0
        weekly_data.append(round(rev, 2))
        day_labels.append(day.strftime('%a'))
    return jsonify({'labels': day_labels, 'data': weekly_data})


@api_bp.route('/notifications')
@login_required
def get_notifications():
    from datetime import datetime, timedelta
    from flask_login import current_user
    from app.models import ProductVariant, StoreSetting
    notifications = []

    # 1. Low stock alerts
    low_threshold = int(StoreSetting.get('low_stock_threshold', '5'))
    low_variants = db.session.query(ProductVariant).join(ProductVariant.product).filter(
        ProductVariant.stock_qty > 0,
        ProductVariant.stock_qty <= low_threshold
    ).limit(5).all()
    for v in low_variants:
        notifications.append({
            'type': 'low_stock',
            'title': f'Low stock: {v.product.name}',
            'body': f'{v.size or ""} {v.color or ""} — only {v.stock_qty} left'.strip(),
            'time': 'Inventory alert',
            'read': False,
        })

    # Out of stock
    out_variants = db.session.query(ProductVariant).join(ProductVariant.product).filter(
        ProductVariant.stock_qty == 0
    ).limit(3).all()
    for v in out_variants:
        notifications.append({
            'type': 'low_stock',
            'title': f'Out of stock: {v.product.name}',
            'body': f'{v.size or ""} {v.color or ""}'.strip() or 'All variants',
            'time': 'Inventory alert',
            'read': False,
        })

    # 2. Recent sales (last 24h)
    since = datetime.utcnow() - timedelta(hours=24)
    recent_sales = Sale.query.filter(
        Sale.status == 'completed',
        Sale.created_at >= since
    ).order_by(Sale.created_at.desc()).limit(5).all()
    for s in recent_sales:
        ago = _time_ago(s.created_at)
        notifications.append({
            'type': 'new_sale',
            'title': f'Sale {s.order_number}',
            'body': f'KES {s.total_amount:,.0f} via {s.payment_method.upper()}',
            'time': ago,
            'read': True,
        })

    # 3. New customers (last 48h)
    since2 = datetime.utcnow() - timedelta(hours=48)
    new_customers = Customer.query.filter(Customer.created_at >= since2)\
        .order_by(Customer.created_at.desc()).limit(3).all()
    for c in new_customers:
        notifications.append({
            'type': 'new_customer',
            'title': f'New customer: {c.name}',
            'body': c.phone,
            'time': _time_ago(c.created_at),
            'read': True,
        })

    unread = sum(1 for n in notifications if not n['read'])
    return jsonify({'notifications': notifications[:12], 'unread': unread})


@api_bp.route('/notifications/count')
@login_required
def notifications_count():
    from app.models import ProductVariant, StoreSetting
    low_threshold = int(StoreSetting.get('low_stock_threshold', '5'))
    count = db.session.query(ProductVariant).filter(
        ProductVariant.stock_qty <= low_threshold
    ).count()
    return jsonify({'unread': count})


@api_bp.route('/notifications/read', methods=['POST'])
@login_required
def mark_notifications_read():
    # Stateless — just acknowledge; real persistence would need a Notification model
    return jsonify({'success': True})


def _time_ago(dt):
    from datetime import datetime
    diff = datetime.utcnow() - dt
    s = int(diff.total_seconds())
    if s < 60:    return 'Just now'
    if s < 3600:  return f'{s//60}m ago'
    if s < 86400: return f'{s//3600}h ago'
    return f'{s//86400}d ago'
