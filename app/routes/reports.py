from flask import Blueprint, render_template, request, jsonify, Response
from flask_login import login_required
from datetime import datetime, timedelta
from sqlalchemy import func
from app import db
from app.models import Sale, SaleItem, Product, Customer, Category

reports_bp = Blueprint('reports', __name__)


def get_date_range(period):
    now = datetime.utcnow()
    if period == 'today':
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = now
    elif period == 'week':
        start = now - timedelta(days=7)
        end = now
    elif period == 'month':
        start = now - timedelta(days=30)
        end = now
    elif period == 'year':
        start = now - timedelta(days=365)
        end = now
    else:
        start = now - timedelta(days=7)
        end = now
    return start, end


@reports_bp.route('/reports')
@login_required
def index():
    period = request.args.get('period', 'week')
    start, end = get_date_range(period)

    # Total revenue
    total_revenue = db.session.query(func.sum(Sale.total_amount)).filter(
        Sale.status == 'completed',
        Sale.created_at >= start,
        Sale.created_at <= end
    ).scalar() or 0

    # Avg order value
    completed_count = Sale.query.filter(
        Sale.status == 'completed',
        Sale.created_at >= start,
        Sale.created_at <= end
    ).count()
    avg_order = total_revenue / completed_count if completed_count > 0 else 0

    # Gross profit
    total_cost = db.session.query(
        func.sum(SaleItem.quantity * SaleItem.cost_price)
    ).join(Sale).filter(
        Sale.status == 'completed',
        Sale.created_at >= start,
        Sale.created_at <= end
    ).scalar() or 0
    gross_profit_pct = ((total_revenue - total_cost) / total_revenue * 100) if total_revenue > 0 else 0

    # Revenue trend (daily for week, weekly for month/year)
    days = (end - start).days + 1
    trend_labels = []
    trend_current = []
    trend_previous = []

    for i in range(min(days, 7)):
        day = start + timedelta(days=i)
        day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day.replace(hour=23, minute=59, second=59)
        rev = db.session.query(func.sum(Sale.total_amount)).filter(
            Sale.status == 'completed',
            Sale.created_at >= day_start,
            Sale.created_at <= day_end
        ).scalar() or 0
        # Previous period same day
        prev_day_start = day_start - timedelta(days=7)
        prev_day_end = day_end - timedelta(days=7)
        prev_rev = db.session.query(func.sum(Sale.total_amount)).filter(
            Sale.status == 'completed',
            Sale.created_at >= prev_day_start,
            Sale.created_at <= prev_day_end
        ).scalar() or 0
        trend_labels.append(day.strftime('%a'))
        trend_current.append(round(rev, 2))
        trend_previous.append(round(prev_rev, 2))

    # Sales by category (donut chart)
    cat_sales = db.session.query(
        Category.name,
        func.sum(SaleItem.line_total)
    ).join(Product, SaleItem.product_id == Product.id) \
     .join(Category, Product.category_id == Category.id) \
     .join(Sale, SaleItem.sale_id == Sale.id) \
     .filter(Sale.status == 'completed',
             Sale.created_at >= start, Sale.created_at <= end) \
     .group_by(Category.name).all()

    cat_labels = [c[0] for c in cat_sales]
    cat_values = [round(c[1], 2) for c in cat_sales]

    # Top performing products
    top_products = db.session.query(
        Product.name,
        Product.image,
        Category.name.label('cat_name'),
        func.sum(SaleItem.quantity).label('total_sold'),
        func.sum(SaleItem.line_total).label('revenue')
    ).join(SaleItem, SaleItem.product_id == Product.id) \
     .join(Sale, SaleItem.sale_id == Sale.id) \
     .join(Category, Product.category_id == Category.id) \
     .filter(Sale.status == 'completed',
             Sale.created_at >= start, Sale.created_at <= end) \
     .group_by(Product.id) \
     .order_by(func.sum(SaleItem.line_total).desc()) \
     .limit(5).all()

    return render_template('reports/index.html',
                           period=period,
                           total_revenue=total_revenue,
                           avg_order=avg_order,
                           gross_profit_pct=gross_profit_pct,
                           trend_labels=trend_labels,
                           trend_current=trend_current,
                           trend_previous=trend_previous,
                           cat_labels=cat_labels,
                           cat_values=cat_values,
                           top_products=top_products,
                           completed_count=completed_count)


@reports_bp.route('/reports/export')
@login_required
def export_csv():
    import csv
    import io

    period = request.args.get('period', 'week')
    start, end = get_date_range(period)

    sales = Sale.query.filter(
        Sale.status == 'completed',
        Sale.created_at >= start,
        Sale.created_at <= end
    ).order_by(Sale.created_at.desc()).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Order #', 'Date', 'Customer', 'Cashier', 'Payment', 'Subtotal', 'Discount', 'Total', 'Items'])

    for sale in sales:
        items_str = ' | '.join([f'{i.product_name} x{i.quantity}' for i in sale.items])
        writer.writerow([
            sale.order_number,
            sale.created_at.strftime('%Y-%m-%d %H:%M'),
            sale.customer.name if sale.customer else 'Walk-in',
            sale.cashier.name if sale.cashier else '',
            sale.payment_method.upper(),
            sale.subtotal,
            sale.discount,
            sale.total_amount,
            items_str
        ])

    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename=sales_report_{period}.csv'}
    )
