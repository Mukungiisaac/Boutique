"""
AI advisor routes.

Uses Gemini when available and falls back to a local data-driven advisor when
the API is unavailable or rate-limited.
"""
from datetime import datetime, timedelta

from flask import Blueprint, current_app, jsonify, render_template, request
from flask_login import login_required
from sqlalchemy import func

from app import db
from app.models import Category, Customer, Product, ProductVariant, Sale, SaleItem

ai_bp = Blueprint('ai', __name__)


def _sales_revenue_since(start):
    return db.session.query(func.sum(Sale.total_amount)).filter(
        Sale.status == 'completed',
        Sale.created_at >= start,
    ).scalar() or 0


def _sales_cost_since(start):
    return db.session.query(func.sum(SaleItem.quantity * SaleItem.cost_price)).join(
        Sale
    ).filter(
        Sale.status == 'completed',
        Sale.created_at >= start,
    ).scalar() or 0


def collect_store_metrics():
    now = datetime.utcnow()
    week_start = now - timedelta(days=7)
    month_start = now - timedelta(days=30)
    year_start = now - timedelta(days=365)

    rev_week = _sales_revenue_since(week_start)
    rev_month = _sales_revenue_since(month_start)
    rev_year = _sales_revenue_since(year_start)
    cost_week = _sales_cost_since(week_start)
    profit_week = rev_week - cost_week

    daily = []
    for i in range(13, -1, -1):
        day = now - timedelta(days=i)
        day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day.replace(hour=23, minute=59, second=59)
        revenue = db.session.query(func.sum(Sale.total_amount)).filter(
            Sale.status == 'completed',
            Sale.created_at >= day_start,
            Sale.created_at <= day_end,
        ).scalar() or 0
        daily.append({'date': day.strftime('%Y-%m-%d'), 'revenue': round(revenue, 2)})

    top_products = db.session.query(
        Product.name,
        Category.name.label('category'),
        func.sum(SaleItem.quantity).label('units_sold'),
        func.sum(SaleItem.line_total).label('revenue'),
        func.sum(SaleItem.quantity * SaleItem.cost_price).label('total_cost'),
    ).join(
        SaleItem, SaleItem.product_id == Product.id
    ).join(
        Sale, SaleItem.sale_id == Sale.id
    ).join(
        Category, Product.category_id == Category.id
    ).filter(
        Sale.status == 'completed',
        Sale.created_at >= month_start,
    ).group_by(
        Product.id, Category.name
    ).order_by(
        func.sum(SaleItem.line_total).desc()
    ).limit(10).all()

    sold_ids = db.session.query(SaleItem.product_id).join(Sale).filter(
        Sale.status == 'completed',
        Sale.created_at >= month_start,
    ).distinct()

    slow_movers = Product.query.filter(
        Product.is_active == True,
        ~Product.id.in_(sold_ids),
    ).order_by(Product.name).all()

    low_stock = db.session.query(
        Product.name,
        func.sum(ProductVariant.stock_qty).label('qty'),
    ).join(
        ProductVariant
    ).filter(
        Product.is_active == True
    ).group_by(
        Product.id
    ).having(
        func.sum(ProductVariant.stock_qty) <= 5
    ).order_by(
        func.sum(ProductVariant.stock_qty).asc()
    ).all()

    out_of_stock = db.session.query(Product.name).join(ProductVariant).filter(
        Product.is_active == True
    ).group_by(
        Product.id
    ).having(
        func.sum(ProductVariant.stock_qty) == 0
    ).all()

    cat_perf = db.session.query(
        Category.name,
        func.sum(SaleItem.line_total).label('revenue'),
        func.sum(SaleItem.quantity).label('units'),
    ).join(
        Product, SaleItem.product_id == Product.id
    ).join(
        Category, Product.category_id == Category.id
    ).join(
        Sale, SaleItem.sale_id == Sale.id
    ).filter(
        Sale.status == 'completed',
        Sale.created_at >= month_start,
    ).group_by(
        Category.name
    ).order_by(
        func.sum(SaleItem.line_total).desc()
    ).all()

    total_customers = Customer.query.count()
    new_customers = Customer.query.filter(Customer.created_at >= month_start).count()
    tier_counts = db.session.query(Customer.tier, func.count()).group_by(Customer.tier).all()
    pay_split = db.session.query(
        Sale.payment_method,
        func.count().label('count'),
        func.sum(Sale.total_amount).label('revenue'),
    ).filter(
        Sale.status == 'completed',
        Sale.created_at >= month_start,
    ).group_by(Sale.payment_method).all()
    last_completed_sale = Sale.query.filter(
        Sale.status == 'completed'
    ).order_by(Sale.created_at.desc()).first()

    active_products = Product.query.filter_by(is_active=True).order_by(Product.name).all()
    margin_products = sorted(
        [p for p in active_products if p.price],
        key=lambda p: ((p.price - (p.cost_price or 0)) / p.price),
        reverse=True,
    )

    return {
        'now': now,
        'rev_week': rev_week,
        'rev_month': rev_month,
        'rev_year': rev_year,
        'cost_week': cost_week,
        'profit_week': profit_week,
        'daily': daily,
        'top_products': top_products,
        'slow_movers': slow_movers,
        'low_stock': low_stock,
        'out_of_stock': out_of_stock,
        'cat_perf': cat_perf,
        'total_customers': total_customers,
        'new_customers': new_customers,
        'tier_counts': tier_counts,
        'pay_split': pay_split,
        'last_completed_sale': last_completed_sale,
        'active_products': active_products,
        'margin_products': margin_products,
    }


def build_store_context():
    metrics = collect_store_metrics()
    ctx = f"""
=== BOUTIQUE POS - LIVE STORE REPORT ===
Generated: {metrics['now'].strftime('%Y-%m-%d %H:%M UTC')} | Currency: KES

--- REVENUE ---
7 days:  KES {metrics['rev_week']:,.0f} | Cost: KES {metrics['cost_week']:,.0f} | Profit: KES {metrics['profit_week']:,.0f}
30 days: KES {metrics['rev_month']:,.0f}
1 year:  KES {metrics['rev_year']:,.0f}

--- DAILY REVENUE (last 14 days) ---
{chr(10).join(f"  {d['date']}: KES {d['revenue']:,.0f}" for d in metrics['daily'])}

--- TOP 10 PRODUCTS (30 days) ---
{chr(10).join(f"  {i + 1}. {p.name} [{p.category}] - {int(p.units_sold or 0)} units, KES {(p.revenue or 0):,.0f} revenue, KES {((p.revenue or 0) - (p.total_cost or 0)):,.0f} profit" for i, p in enumerate(metrics['top_products']))}

--- CATEGORY PERFORMANCE (30 days) ---
{chr(10).join(f"  {c.name}: KES {(c.revenue or 0):,.0f}, {int(c.units or 0)} units" for c in metrics['cat_perf'])}

--- STOCK ALERTS ---
Low stock (<=5): {', '.join(f"{p.name}({int(p.qty or 0)})" for p in metrics['low_stock']) or 'None'}
Out of stock: {', '.join(p.name for p in metrics['out_of_stock']) or 'None'}
Slow movers (no sales 30d): {', '.join(p.name for p in metrics['slow_movers']) or 'None'}

--- CUSTOMERS ---
Total: {metrics['total_customers']} | New this month: {metrics['new_customers']}
Tiers: {', '.join(f"{tier}:{count}" for tier, count in metrics['tier_counts'])}

--- PAYMENT SPLIT (30 days) ---
{chr(10).join(f"  {p.payment_method.upper()}: {int(p.count or 0)} txns, KES {(p.revenue or 0):,.0f}" for p in metrics['pay_split'])}

--- ALL PRODUCTS & STOCK ---
{chr(10).join(f"  {p.name} | Price:KES{p.price:,.0f} Cost:KES{p.cost_price:,.0f} Stock:{p.total_stock} [{p.status}]" for p in metrics['active_products'])}
"""
    return ctx.strip()


def _fmt_money(value):
    return f"KES {value:,.0f}"


def build_local_advice(user_message):
    metrics = collect_store_metrics()
    question = user_message.lower()

    sections = [
        "## Store Snapshot\n"
        f"- Revenue (7 days): {_fmt_money(metrics['rev_week'])}\n"
        f"- Profit (7 days): {_fmt_money(metrics['profit_week'])}\n"
        f"- Revenue (30 days): {_fmt_money(metrics['rev_month'])}\n"
        f"- Active products: {len(metrics['active_products'])}\n"
        f"- Customers: {metrics['total_customers']} total, {metrics['new_customers']} new in 30 days"
    ]

    if any(term in question for term in ['low stock', 'reorder', 'urgent', 'stock']):
        lines = '\n'.join(
            f"- {item.name}: only {int(item.qty or 0)} left"
            for item in metrics['low_stock'][:8]
        ) or "- No low-stock products right now."
        sections.append("## Reorder Priorities\n" + lines)
        if metrics['rev_week'] == 0 and metrics['last_completed_sale']:
            last_sale_date = metrics['last_completed_sale'].created_at.strftime('%Y-%m-%d')
            sections.append(
                "## Sales Context\n"
                f"- There have been no completed sales in the last 7 days.\n"
                f"- The most recent completed sale in the database was on {last_sale_date}.\n"
                "- Reorder carefully and prioritize only your lowest-stock proven sellers."
            )

    if any(term in question for term in ['top', 'best selling', 'selling', 'sales', 'trend']):
        lines = '\n'.join(
            f"- {item.name}: {int(item.units_sold or 0)} units, {_fmt_money(item.revenue or 0)} revenue"
            for item in metrics['top_products'][:5]
        ) or "- No completed sales found for the last 30 days."
        sections.append("## Top Sellers\n" + lines)

    if any(term in question for term in ['profit', 'margin', 'loss']):
        lines = '\n'.join(
            f"- {item.name}: {round(((item.price - (item.cost_price or 0)) / item.price) * 100)}% margin"
            for item in metrics['margin_products'][:5]
        ) or "- Not enough pricing data to calculate margins."
        sections.append("## Margin Leaders\n" + lines)

    if any(term in question for term in ['slow', 'discount', 'promotion', 'promo']):
        slow_lines = '\n'.join(
            f"- {item.name}" for item in metrics['slow_movers'][:8]
        ) or "- No obvious slow movers in the last 30 days."
        sections.append("## Slow Movers\n" + slow_lines)
        sections.append(
            "## Promotion Suggestion\n"
            "- Pair slow movers with top sellers or run a short markdown on items with no sales in the last 30 days."
        )

    if any(term in question for term in ['categor', 'performing best']):
        lines = '\n'.join(
            f"- {item.name}: {_fmt_money(item.revenue or 0)} revenue from {int(item.units or 0)} units"
            for item in metrics['cat_perf'][:5]
        ) or "- No category performance data available."
        sections.append("## Category Performance\n" + lines)

    if any(term in question for term in ['customer', 'loyalty', 'vip', 'payment']):
        lines = '\n'.join(
            f"- {item.payment_method.upper()}: {int(item.count or 0)} sales, {_fmt_money(item.revenue or 0)}"
            for item in metrics['pay_split']
        ) or "- No payment activity in the last 30 days."
        sections.append("## Customer And Payment Insights\n" + lines)

    if len(sections) == 1:
        reorder_lines = '\n'.join(
            f"- Reorder {item.name} soon; only {int(item.qty or 0)} left."
            for item in metrics['low_stock'][:3]
        ) or "- Stock levels look healthy overall."
        sections.append("## Recommendations\n" + reorder_lines)

        if metrics['top_products']:
            leader = metrics['top_products'][0]
            sections.append(
                "## Top Opportunity\n"
                f"- Double down on {leader.name}; it leads recent revenue at {_fmt_money(leader.revenue or 0)}."
            )
        if metrics['rev_week'] == 0 and metrics['last_completed_sale']:
            sections.append(
                "## Sales Context\n"
                f"- No completed sales have been recorded in the last 7 days.\n"
                f"- The latest completed sale was on {metrics['last_completed_sale'].created_at.strftime('%Y-%m-%d')}."
            )

    sections.append(
        "_Gemini is temporarily unavailable or rate-limited, so this answer was generated from your live store data using the built-in advisor._"
    )
    return '\n\n'.join(sections)


@ai_bp.route('/ai-advisor')
@login_required
def index():
    return render_template('ai/index.html')


@ai_bp.route('/ai-advisor/chat', methods=['POST'])
@login_required
def chat():
    data = request.get_json() or {}
    user_message = (data.get('message') or '').strip()
    history = data.get('history', [])

    if not user_message:
        return jsonify({'error': 'Empty message'}), 400

    try:
        from app.models import StoreSetting

        api_key = current_app.config.get('GEMINI_API_KEY', '') or StoreSetting.get('gemini_api_key', '')
        if not api_key:
            return jsonify({'reply': build_local_advice(user_message), 'source': 'local_fallback'})

        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)
        store_ctx = build_store_context()
        system_prompt = f"""You are an expert retail AI advisor for a boutique fashion store.
You have access to real-time store data shown below. Use it to give specific, data-driven advice.

Your expertise covers:
- Inventory management and restocking decisions
- Sales trend analysis and forecasting
- Profit/loss analysis per product and category
- Identifying slow movers and recommending markdowns or promotions
- Customer segmentation and loyalty insights
- Seasonal and market trend advice for fashion retail
- Cash flow and pricing strategy

Always be specific: reference actual product names, numbers, and percentages from the data.
Be concise but thorough. Format responses with clear sections when helpful.
If asked about something outside the store data, use your fashion retail expertise.

{store_ctx}
"""

        contents = []
        for item in history[-10:]:
            role = 'user' if item.get('role') == 'user' else 'model'
            text = item.get('text', '').strip()
            if text:
                contents.append(types.Content(role=role, parts=[types.Part(text=text)]))
        contents.append(types.Content(role='user', parts=[types.Part(text=user_message)]))

        try:
            response = client.models.generate_content(
                model='gemini-2.0-flash-lite',
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=0.7,
                    max_output_tokens=800,
                ),
            )
            return jsonify({'reply': response.text, 'source': 'gemini'})
        except Exception as model_err:
            err = str(model_err)
            if '429' in err or 'RESOURCE_EXHAUSTED' in err:
                return jsonify({'reply': build_local_advice(user_message), 'source': 'local_fallback'})
            raise
    except Exception:
        current_app.logger.exception('AI advisor failed')
        return jsonify({'reply': build_local_advice(user_message), 'source': 'local_fallback'})


@ai_bp.route('/ai-advisor/context')
@login_required
def get_context():
    try:
        return jsonify({'context': build_store_context()})
    except Exception as exc:
        return jsonify({'error': str(exc)}), 500
