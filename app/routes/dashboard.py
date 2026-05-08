from flask import Blueprint, render_template, jsonify
from flask_login import login_required, current_user
from datetime import datetime, timedelta
from sqlalchemy import func
from app import db
from app.models import Sale, SaleItem, Product, Customer, ProductVariant

dashboard_bp = Blueprint('dashboard', __name__)


@dashboard_bp.route('/dashboard')
@login_required
def index():
    today = datetime.utcnow().date()
    week_start = datetime.utcnow() - timedelta(days=7)
    month_start = datetime.utcnow() - timedelta(days=30)

    total_revenue = db.session.query(func.sum(Sale.total_amount)).filter(
        Sale.status == 'completed').scalar() or 0
    total_transactions = Sale.query.filter_by(status='completed').count()
    active_inventory = db.session.query(func.sum(ProductVariant.stock_qty)).scalar() or 0
    new_customers = Customer.query.filter(Customer.created_at >= month_start).count()

    weekly_data = []
    day_labels = []
    for i in range(6, -1, -1):
        day = datetime.utcnow() - timedelta(days=i)
        day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end   = day.replace(hour=23, minute=59, second=59)
        rev = db.session.query(func.sum(Sale.total_amount)).filter(
            Sale.status == 'completed',
            Sale.created_at >= day_start,
            Sale.created_at <= day_end
        ).scalar() or 0
        weekly_data.append(round(rev, 2))
        day_labels.append(day.strftime('%a'))

    recent_sales = Sale.query.order_by(Sale.created_at.desc()).limit(10).all()

    low_stock_variants = db.session.query(ProductVariant).filter(
        ProductVariant.stock_qty <= 5, ProductVariant.stock_qty > 0
    ).join(Product).filter(Product.is_active == True).limit(5).all()

    out_of_stock = db.session.query(ProductVariant).filter(
        ProductVariant.stock_qty == 0
    ).join(Product).filter(Product.is_active == True).limit(3).all()

    monthly_target  = 50000
    monthly_revenue = db.session.query(func.sum(Sale.total_amount)).filter(
        Sale.status == 'completed', Sale.created_at >= month_start
    ).scalar() or 0
    goal_progress = min(int((monthly_revenue / monthly_target) * 100), 100)

    return render_template('dashboard/index.html',
                           total_revenue=total_revenue,
                           total_transactions=total_transactions,
                           active_inventory=active_inventory,
                           new_customers=new_customers,
                           weekly_data=weekly_data,
                           day_labels=day_labels,
                           recent_sales=recent_sales,
                           low_stock_variants=low_stock_variants,
                           out_of_stock=out_of_stock,
                           goal_progress=goal_progress,
                           monthly_revenue=monthly_revenue,
                           monthly_target=monthly_target)


@dashboard_bp.route('/dashboard/live')
@login_required
def live():
    """Real-time data endpoint — polled every 30 s by the dashboard JS."""
    month_start = datetime.utcnow() - timedelta(days=30)
    monthly_target = 50000

    # ── KPIs ──────────────────────────────────────────────────────────────
    total_revenue = db.session.query(func.sum(Sale.total_amount)).filter(
        Sale.status == 'completed').scalar() or 0
    total_transactions = Sale.query.filter_by(status='completed').count()
    active_inventory = db.session.query(func.sum(ProductVariant.stock_qty)).scalar() or 0
    new_customers = Customer.query.filter(Customer.created_at >= month_start).count()

    # Today's revenue
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today_revenue = db.session.query(func.sum(Sale.total_amount)).filter(
        Sale.status == 'completed', Sale.created_at >= today_start
    ).scalar() or 0
    today_txns = Sale.query.filter(
        Sale.status == 'completed', Sale.created_at >= today_start
    ).count()

    # ── Weekly chart ──────────────────────────────────────────────────────
    weekly_data = []
    day_labels  = []
    for i in range(6, -1, -1):
        day = datetime.utcnow() - timedelta(days=i)
        ds  = day.replace(hour=0, minute=0, second=0, microsecond=0)
        de  = day.replace(hour=23, minute=59, second=59)
        rev = db.session.query(func.sum(Sale.total_amount)).filter(
            Sale.status == 'completed',
            Sale.created_at >= ds, Sale.created_at <= de
        ).scalar() or 0
        weekly_data.append(round(rev, 2))
        day_labels.append(day.strftime('%a'))

    # ── Recent transactions ───────────────────────────────────────────────
    recent = Sale.query.order_by(Sale.created_at.desc()).limit(10).all()
    recent_list = []
    for s in recent:
        first_item = s.items.first()
        recent_list.append({
            'id':           s.id,
            'order_number': s.order_number,
            'customer':     s.customer.name if s.customer else 'Walk-in',
            'product':      first_item.product_name if first_item else '—',
            'total':        s.total_amount,
            'status':       s.status,
            'time':         s.created_at.strftime('%d %b, %H:%M'),
        })

    # ── Stock alerts ──────────────────────────────────────────────────────
    low_variants = db.session.query(ProductVariant).filter(
        ProductVariant.stock_qty <= 5, ProductVariant.stock_qty > 0
    ).join(Product).filter(Product.is_active == True).limit(5).all()

    out_variants = db.session.query(ProductVariant).filter(
        ProductVariant.stock_qty == 0
    ).join(Product).filter(Product.is_active == True).limit(3).all()

    alerts = []
    for v in out_variants:
        alerts.append({'name': v.product.name, 'qty': 0, 'level': 'critical'})
    for v in low_variants:
        alerts.append({'name': v.product.name, 'qty': v.stock_qty, 'level': 'warning'})

    # ── Goal ──────────────────────────────────────────────────────────────
    monthly_revenue = db.session.query(func.sum(Sale.total_amount)).filter(
        Sale.status == 'completed', Sale.created_at >= month_start
    ).scalar() or 0
    goal_progress = min(int((monthly_revenue / monthly_target) * 100), 100)
    gap = max(monthly_target - monthly_revenue, 0)

    return jsonify({
        'ts':                 datetime.utcnow().strftime('%H:%M:%S'),
        'total_revenue':      total_revenue,
        'total_transactions': total_transactions,
        'active_inventory':   active_inventory,
        'new_customers':      new_customers,
        'today_revenue':      today_revenue,
        'today_txns':         today_txns,
        'weekly_data':        weekly_data,
        'day_labels':         day_labels,
        'recent':             recent_list,
        'alerts':             alerts,
        'goal_progress':      goal_progress,
        'monthly_revenue':    monthly_revenue,
        'monthly_target':     monthly_target,
        'goal_gap':           gap,
    })
