# -*- coding: utf-8 -*-
"""
AI advisor routes.

Uses Gemini when available and falls back to a local data-driven advisor when
the API is unavailable or rate-limited.
"""
from datetime import datetime, timedelta

from flask import Blueprint, current_app, jsonify, render_template, request
from flask_login import login_required, current_user
from sqlalchemy import func

from app import db
from app.models import Category, Customer, Product, ProductVariant, Sale, SaleItem, AIChatSession, AIChatMessage

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


def _general_knowledge(q, store_name='your boutique'):
    """
    Answer general retail, fashion, and business questions from built-in knowledge.
    Returns a string answer or None if the question is store-data specific.
    """
    now = datetime.utcnow()
    month = now.month

    # ── Seasonal / when to sell ────────────────────────────────────────────
    if any(t in q for t in ['when', 'season', 'best time', 'right time', 'which month',
                             'what month', 'what time of year']):

        if any(t in q for t in ['heavy', 'warm', 'winter', 'coat', 'jacket', 'sweater',
                                 'knitwear', 'wool', 'fleece', 'thick', 'layering']):
            current = 'You are currently in ' + now.strftime('%B') + '.'
            return (
                "## When to Sell Heavy / Warm Clothing\n\n"
                "**In Kenya (East Africa):**\n"
                "- **Cold seasons:** June–August (long rains cool-down) and November–January "
                "(short rains + cooler evenings in highlands)\n"
                "- **Best months to stock up:** May and October — buy before the cold sets in\n"
                "- **Nairobi highlands:** Evenings are cool year-round, so knitwear and light "
                "jackets sell steadily all year\n"
                "- **Coast (Mombasa/Malindi):** Warm year-round — heavy clothing rarely sells there\n\n"
                "**General fashion retail rule:**\n"
                "- Start displaying winter/heavy stock **6–8 weeks before** the cold season\n"
                "- Run clearance sales on heavy items **at the end** of the cold season "
                "(August and January) to free up cash for lighter stock\n\n"
                f"{current} Plan your stock accordingly."
            )

        if any(t in q for t in ['light', 'summer', 'dress', 'linen', 'cotton', 'casual',
                                 'bright', 'floral', 'swimwear', 'shorts']):
            return (
                "## When to Sell Light / Summer Clothing\n\n"
                "**In Kenya:**\n"
                "- **Hot dry seasons:** January–March and September–October\n"
                "- **Best months to stock light clothing:** December and August\n"
                "- Light cotton dresses, linen, and bright colours sell best during school "
                "holidays (April, August, December)\n\n"
                "**Tip:** Pair light clothing launches with public holidays and festive seasons "
                "— Easter, Madaraka Day (June 1), and Christmas drive strong fashion sales."
            )

        if any(t in q for t in ['accessory', 'accessories', 'jewellery', 'jewelry',
                                 'bag', 'handbag', 'scarf', 'belt']):
            return (
                "## When to Sell Accessories\n\n"
                "Accessories sell **year-round** but peak during:\n"
                "- **December** — Christmas gifting season (highest accessory sales)\n"
                "- **February** — Valentine's Day (jewellery, scarves, bags)\n"
                "- **March/April** — Easter and end-of-term shopping\n"
                "- **August** — Back-to-school and mid-year sales\n\n"
                "**Strategy:** Keep accessories near the checkout counter — they are the "
                "easiest impulse purchase and boost your average order value."
            )

        if any(t in q for t in ['shoe', 'shoes', 'boot', 'boots', 'footwear', 'sandal']):
            return (
                "## When to Sell Footwear\n\n"
                "- **Boots & closed shoes:** June–August (cold season) and November–January\n"
                "- **Sandals & open shoes:** January–March and September–October (dry/hot)\n"
                "- **School shoes:** January (back to school) and August (second term)\n\n"
                "**Tip:** Stock school shoes in December and July — parents buy 2–3 weeks "
                "before term starts."
            )

    # ── Pricing strategy ──────────────────────────────────────────────────
    if any(t in q for t in ['price', 'pricing', 'how much to charge', 'markup',
                             'mark up', 'set price', 'price my']):
        return (
            "## Pricing Strategy for a Boutique\n\n"
            "**Standard retail markup formulas:**\n"
            "- **Keystone pricing:** Sell at 2x your cost price (50% margin)\n"
            "- **Premium boutique:** 2.5x–3x cost price (60–67% margin)\n"
            "- **Fast-moving basics:** 1.5x–2x cost (33–50% margin)\n\n"
            "**Formula:** Selling Price = Cost Price / (1 - desired margin %)\n"
            "- Example: Cost KES 500, want 60% margin → KES 500 / 0.40 = **KES 1,250**\n\n"
            "**Psychological pricing tips:**\n"
            "- End prices in 99 or 95 (KES 1,499 feels cheaper than KES 1,500)\n"
            "- Use round numbers for premium items (KES 5,000 feels more luxurious)\n"
            "- Anchor with a higher 'original price' next to the sale price\n\n"
            "**Never price below cost** — check your cost prices in Inventory to ensure "
            "every product has a cost price entered."
        )

    # ── Marketing / promotion ─────────────────────────────────────────────
    if any(t in q for t in ['market', 'advertise', 'promote', 'social media',
                             'instagram', 'facebook', 'tiktok', 'whatsapp',
                             'attract customer', 'get customer', 'grow']):
        return (
            "## Marketing Your Boutique\n\n"
            "**Best channels for a boutique in Kenya:**\n\n"
            "**1. WhatsApp Business (highest ROI)**\n"
            "- Create a broadcast list of your existing customers\n"
            "- Send new arrivals with photos every Monday morning\n"
            "- Use WhatsApp Status for daily outfit inspiration\n\n"
            "**2. Instagram & TikTok**\n"
            "- Post outfit videos (Reels/TikTok) — these get 3x more reach than photos\n"
            "- Use local hashtags: #NairobiFashion #KenyanFashion #BoutiqueKE\n"
            "- Post 3–5 times per week consistently\n\n"
            "**3. Loyalty programme**\n"
            "- Your POS already tracks loyalty points — remind customers at checkout\n"
            "- Offer a free item or discount after every 10 purchases\n\n"
            "**4. Referral incentive**\n"
            "- Give existing customers 10% off their next purchase for every new "
            "customer they refer\n\n"
            "**Best posting times:** 7–9 AM, 12–1 PM, and 7–9 PM on weekdays."
        )

    # ── Inventory management ──────────────────────────────────────────────
    if any(t in q for t in ['how often', 'restock', 'when to reorder', 'inventory management',
                             'stock management', 'how to manage stock', 'overstocking',
                             'dead stock', 'how much stock']):
        return (
            "## Inventory Management Best Practices\n\n"
            "**Reorder point formula:**\n"
            "Reorder when: Stock = (Daily sales rate x Lead time in days) + Safety stock\n\n"
            "**Practical rules for a boutique:**\n"
            "- Reorder **fast sellers** when stock drops to 5–7 units\n"
            "- Reorder **slow sellers** only after selling 70% of current stock\n"
            "- Keep **2–4 weeks** of stock on hand for most items\n\n"
            "**Avoid dead stock:**\n"
            "- If an item hasn't sold in 30 days, discount it by 10–15%\n"
            "- After 60 days, bundle it with a popular item or mark down 25–30%\n"
            "- After 90 days, clear it at cost price — cash flow beats holding stock\n\n"
            "**ABC analysis:**\n"
            "- **A items** (top 20% by revenue): Always keep in stock, reorder quickly\n"
            "- **B items** (middle 30%): Maintain moderate stock\n"
            "- **C items** (bottom 50%): Keep minimal stock, consider discontinuing"
        )

    # ── Customer retention ────────────────────────────────────────────────
    if any(t in q for t in ['retain', 'retention', 'keep customer', 'loyal',
                             'repeat', 'come back', 'returning customer']):
        return (
            "## Customer Retention Strategies\n\n"
            "Retaining a customer costs **5x less** than acquiring a new one.\n\n"
            "**Immediate actions:**\n"
            "- **Follow up after purchase:** Send a WhatsApp message 2–3 days after "
            "a sale asking if they love their item\n"
            "- **Birthday discounts:** Collect birthdays and send a 15% off voucher\n"
            "- **Loyalty points:** Your POS tracks points — remind customers of their "
            "balance at every visit\n\n"
            "**Tier your customers:**\n"
            "- Bronze (new) → Silver (3+ purchases) → Gold (10+ purchases) → VIP (top spenders)\n"
            "- Give VIP customers early access to new arrivals\n\n"
            "**Re-engage inactive customers:**\n"
            "- If a customer hasn't visited in 60 days, send a 'We miss you' message "
            "with a small discount\n"
            "- Your customer list in the POS shows last purchase dates — use it!"
        )

    # ── Cash flow ─────────────────────────────────────────────────────────
    if any(t in q for t in ['cash flow', 'cashflow', 'cash', 'money', 'finance',
                             'budget', 'capital', 'investment', 'funding']):
        return (
            "## Cash Flow Management for a Boutique\n\n"
            "**The golden rule:** Never spend more than 60–70% of your revenue on restocking.\n\n"
            "**Cash flow tips:**\n"
            "- **Track daily:** Your POS dashboard shows today's revenue — check it every evening\n"
            "- **Separate accounts:** Keep business money separate from personal money\n"
            "- **Restock budget:** Set aside 50–60% of each week's revenue for new stock\n"
            "- **Emergency fund:** Keep 4–6 weeks of operating costs in reserve\n\n"
            "**Improve cash flow:**\n"
            "- Sell slow-moving stock at a small discount rather than holding it\n"
            "- Negotiate 30-day payment terms with suppliers\n"
            "- Offer M-Pesa payment — it reduces cash handling and speeds up transactions\n\n"
            "**Warning signs of poor cash flow:**\n"
            "- Buying new stock before selling current stock\n"
            "- Revenue growing but profit shrinking (check your margins)\n"
            "- Relying on credit to pay for stock"
        )

    # ── Fashion trends ────────────────────────────────────────────────────
    if any(t in q for t in ['trend', 'trending', 'fashion trend', 'what is popular',
                             'what is in', "what's in", 'in style', 'in fashion',
                             'popular now', 'latest fashion']):
        return (
            "## Current Fashion Trends (2025–2026)\n\n"
            "**Global trends relevant to East African boutiques:**\n\n"
            "**1. Quiet Luxury / Minimalism**\n"
            "- Clean lines, neutral tones (beige, cream, camel, navy)\n"
            "- High-quality basics that mix and match easily\n"
            "- Strong seller for office and professional wear\n\n"
            "**2. Bold Prints & African Prints**\n"
            "- Ankara, kitenge, and mixed-print pieces are growing globally\n"
            "- Fusion pieces (African print + Western cut) are very popular\n\n"
            "**3. Oversized & Relaxed Fits**\n"
            "- Oversized blazers, wide-leg trousers, relaxed shirts\n"
            "- Comfortable yet stylish — strong demand post-pandemic\n\n"
            "**4. Sustainable / Second-hand Chic**\n"
            "- Customers increasingly value quality over quantity\n"
            "- Emphasise durability and fabric quality in your marketing\n\n"
            "**5. Monochrome Outfits**\n"
            "- Head-to-toe single colour looks are trending on social media\n"
            "- Easy to style and photograph for Instagram\n\n"
            "**Tip:** Stock versatile pieces that work for both office and casual — "
            "Kenyan customers value value-for-money versatility."
        )

    # ── Competition ───────────────────────────────────────────────────────
    if any(t in q for t in ['competitor', 'competition', 'compete', 'stand out',
                             'differentiate', 'unique', 'better than']):
        return (
            "## How to Stand Out from Competitors\n\n"
            "**Differentiation strategies for a boutique:**\n\n"
            "**1. Curate, don't just stock**\n"
            "- Be known for a specific style or customer type "
            "(e.g., 'the go-to for Nairobi professional women')\n"
            "- Customers pay more when they trust your taste\n\n"
            "**2. Superior customer experience**\n"
            "- Remember customer names, sizes, and preferences (your POS stores this)\n"
            "- Offer personal styling advice — most boutiques don't\n\n"
            "**3. Exclusive pieces**\n"
            "- Source items not available in every other shop\n"
            "- Limited quantities create urgency\n\n"
            "**4. After-sale service**\n"
            "- Follow up, accept exchanges, build trust\n"
            "- Word-of-mouth from happy customers is your cheapest marketing\n\n"
            "**5. Consistent online presence**\n"
            "- Post daily on Instagram/TikTok — most boutiques post inconsistently\n"
            "- Consistency alone puts you ahead of 80% of competitors"
        )

    # ── VAT / tax ─────────────────────────────────────────────────────────
    if any(t in q for t in ['vat', 'tax', 'kra', 'etims', 'invoice', 'receipt',
                             'register business', 'business registration']):
        return (
            "## Tax & Compliance for a Kenyan Boutique\n\n"
            "**Key requirements:**\n\n"
            "**1. Business Registration**\n"
            "- Register with the Registrar of Companies (eCitizen portal)\n"
            "- Obtain a Single Business Permit from your county government\n\n"
            "**2. KRA PIN & Tax**\n"
            "- Register for a KRA PIN at itax.kra.go.ke\n"
            "- File monthly VAT returns if your annual turnover exceeds KES 5 million\n"
            "- Below KES 5M: file annual income tax returns\n\n"
            "**3. eTIMS (Electronic Tax Invoice Management System)**\n"
            "- KRA now requires businesses to issue electronic tax invoices\n"
            "- Register on the eTIMS portal and integrate with your billing system\n\n"
            "**4. NHIF & NSSF**\n"
            "- If you have employees, deduct and remit NHIF and NSSF monthly\n\n"
            "**Tip:** Keep all purchase receipts from suppliers — these are your "
            "input VAT claims and reduce your tax liability."
        )

    # ── Greeting / general chat ───────────────────────────────────────────
    if any(t in q for t in ['hello', 'hi', 'hey', 'good morning', 'good afternoon',
                             'good evening', 'how are you', 'what can you do',
                             'what do you know', 'help me', 'help']):
        return (
            "## Hello! I'm your AI Stock Advisor.\n\n"
            "I can help you with:\n\n"
            "**Your store data:**\n"
            "- Sales history, profit/loss, top products\n"
            "- Stock levels and reorder alerts\n"
            "- Customer insights and payment trends\n\n"
            "**General business knowledge:**\n"
            "- When to sell seasonal clothing (heavy, light, accessories)\n"
            "- Pricing strategies and markup formulas\n"
            "- Marketing your boutique on social media\n"
            "- Inventory management best practices\n"
            "- Customer retention strategies\n"
            "- Fashion trends and competition tips\n"
            "- Tax and compliance in Kenya\n\n"
            "Just ask me anything — I'll answer from your data or from retail knowledge!"
        )

    return None   # not a general question — fall through to DB lookup


def build_local_advice(user_message):
    """
    Answer any question — general retail knowledge first, then live DB data.
    """
    q = user_message.lower()

    # Try general knowledge first
    general = _general_knowledge(q)
    if general:
        return general

    # Fall through to live store data
    m = collect_store_metrics()

    # ── Last sale ──────────────────────────────────────────────────────────
    if any(t in q for t in ['last sale', 'recent sale', 'latest sale', 'last transaction',
                             'last order', 'recent order', 'latest order']):
        s = m['last_completed_sale']
        if not s:
            return "I couldn't find any completed sales in your records yet."
        items = s.items.all()
        item_lines = '\n'.join(
            f"- {i.product_name} x{i.quantity} @ KES {i.unit_price:,.0f} "
            f"(cost KES {i.cost_price:,.0f}) = KES {i.line_total:,.0f}"
            for i in items
        )
        profit = s.total_profit if s.total_profit else (s.total_amount - (s.total_cost or 0))
        return (
            f"## Last Completed Sale\n"
            f"- **Order:** {s.order_number}\n"
            f"- **Date:** {s.created_at.strftime('%d %b %Y at %H:%M')}\n"
            f"- **Customer:** {s.customer.name if s.customer else 'Walk-in'}\n"
            f"- **Payment:** {s.payment_method.upper()}\n"
            f"- **Total:** {_fmt_money(s.total_amount)}\n"
            f"- **Cost:** {_fmt_money(s.total_cost or 0)}\n"
            f"- **Profit:** {_fmt_money(profit)} "
            f"({'gain' if profit >= 0 else 'loss'})\n\n"
            f"## Items Sold\n{item_lines}"
        )

    # ── Specific product lookup ────────────────────────────────────────────
    for p in m['active_products']:
        if p.name.lower() in q:
            sold = next((x for x in m['top_products'] if x.name == p.name), None)
            margin = ((p.price - (p.cost_price or 0)) / p.price * 100) if p.price else 0
            lines = [
                f"## {p.name}",
                f"- **Selling price:** {_fmt_money(p.price)}",
                f"- **Cost price:** {_fmt_money(p.cost_price or 0)}",
                f"- **Margin:** {margin:.1f}%",
                f"- **Current stock:** {p.total_stock} units ({p.status.replace('_', ' ')})",
            ]
            if sold:
                sp = (sold.revenue or 0) - (sold.total_cost or 0)
                lines += [
                    f"- **Units sold (30d):** {int(sold.units_sold or 0)}",
                    f"- **Revenue (30d):** {_fmt_money(sold.revenue or 0)}",
                    f"- **Profit (30d):** {_fmt_money(sp)}",
                ]
            else:
                lines.append("- **Sales (30d):** No sales recorded in the last 30 days")
            return '\n'.join(lines)

    # ── Strategic / advisory questions ────────────────────────────────────
    if any(t in q for t in ['improve', 'increase', 'boost', 'grow', 'better', 'maximise',
                             'maximize', 'strategy', 'advice', 'suggest', 'recommend',
                             'how can', 'how do', 'what should', 'what can', 'tips',
                             'next sale', 'next time', 'going forward']):

        # Build context-aware advice from actual data
        margin_leader = m['margin_products'][0] if m['margin_products'] else None
        low_margin = [p for p in m['active_products']
                      if p.price and p.cost_price and
                      ((p.price - p.cost_price) / p.price) < 0.20]
        loss_prods = [p for p in m['active_products']
                      if p.cost_price and p.price and p.price < p.cost_price]
        top_seller = m['top_products'][0] if m['top_products'] else None
        week_margin_pct = (m['profit_week'] / m['rev_week'] * 100) if m['rev_week'] > 0 else 0

        lines = [
            "## How to Improve Profit on Your Next Sale",
            "",
            f"Your current profit margin this week is **{week_margin_pct:.1f}%** "
            f"({_fmt_money(m['profit_week'])} profit on {_fmt_money(m['rev_week'])} revenue). "
            "Here is what you can do right now:",
            "",
            "### 1. Push Your High-Margin Products First",
        ]
        if margin_leader:
            mg = ((margin_leader.price - (margin_leader.cost_price or 0)) / margin_leader.price * 100)
            lines.append(
                f"**{margin_leader.name}** has your highest margin at **{mg:.0f}%** "
                f"(sell {_fmt_money(margin_leader.price)}, cost {_fmt_money(margin_leader.cost_price or 0)}). "
                "Recommend it to every customer — every unit sold adds maximum profit."
            )
        else:
            lines.append("Set cost prices on your products so I can calculate margins for you.")

        lines += ["", "### 2. Fix Your Low-Margin Products"]
        if low_margin:
            lines.append("These products are eating into your profit — consider raising prices or negotiating lower costs:")
            for p in low_margin[:4]:
                mg = ((p.price - (p.cost_price or 0)) / p.price * 100) if p.price else 0
                lines.append(f"- **{p.name}**: only {mg:.0f}% margin "
                              f"(sell {_fmt_money(p.price)}, cost {_fmt_money(p.cost_price or 0)})")
        else:
            lines.append("Your product margins look healthy — no obvious low-margin items found.")

        if loss_prods:
            lines += ["", "### 3. Stop Selling at a Loss — Urgent"]
            lines.append("These products are costing you money on every sale:")
            for p in loss_prods:
                loss = p.cost_price - p.price
                lines.append(f"- **{p.name}**: losing {_fmt_money(loss)} per unit sold. "
                              f"Raise price above {_fmt_money(p.cost_price)} immediately.")

        lines += ["", "### 4. Upsell on Every Transaction"]
        if top_seller:
            lines.append(
                f"**{top_seller.name}** is your best seller this month "
                f"({_fmt_money(top_seller.revenue or 0)} revenue). "
                "When a customer buys it, suggest a complementary item to increase the basket size."
            )

        lines += [
            "",
            "### 5. Reduce Discounts",
            "Every KES 100 discount directly reduces profit. "
            "Instead of discounting, offer value-adds like free gift wrapping or loyalty points.",
            "",
            "### 6. Sell Slow Movers Before Restocking",
        ]
        if m['slow_movers']:
            names = ', '.join(p.name for p in m['slow_movers'][:3])
            lines.append(
                f"You have {len(m['slow_movers'])} products with no sales in 30 days "
                f"({names}...). Clear these with a small discount before ordering new stock — "
                "dead stock ties up cash."
            )
        else:
            lines.append("All your products have sold recently — good stock turnover.")

        return '\n'.join(lines)

    # ── Profit / loss ──────────────────────────────────────────────────────
    if any(t in q for t in ['profit', 'loss', 'margin', 'earning', 'made']):
        lines = [
            f"## Profit Summary",
            f"- **This week:** {_fmt_money(m['profit_week'])} "
            f"({'profit' if m['profit_week'] >= 0 else 'loss'}) "
            f"on {_fmt_money(m['rev_week'])} revenue",
            f"- **This month:** revenue {_fmt_money(m['rev_month'])}",
            "",
            "## Top Margin Products",
        ]
        for p in m['margin_products'][:5]:
            mg = ((p.price - (p.cost_price or 0)) / p.price * 100) if p.price else 0
            lines.append(f"- {p.name}: {mg:.0f}% margin "
                         f"(sell {_fmt_money(p.price)}, cost {_fmt_money(p.cost_price or 0)})")
        # Loss products
        loss_prods = [p for p in m['active_products']
                      if p.cost_price and p.price and p.price < p.cost_price]
        if loss_prods:
            lines.append("\n## Selling at a Loss")
            for p in loss_prods:
                lines.append(f"- {p.name}: selling {_fmt_money(p.price)}, "
                              f"costs {_fmt_money(p.cost_price)} — loss of "
                              f"{_fmt_money(p.cost_price - p.price)} per unit")
        return '\n'.join(lines)

    # ── Stock / inventory ──────────────────────────────────────────────────
    if any(t in q for t in ['stock', 'inventory', 'reorder', 'low', 'out of', 'available']):
        lines = ["## Stock Status"]
        if m['out_of_stock']:
            lines.append("\n**Out of Stock:**")
            for p in m['out_of_stock']:
                lines.append(f"- {p.name} — 0 units")
        if m['low_stock']:
            lines.append("\n**Low Stock (5 or fewer):**")
            for p in m['low_stock']:
                lines.append(f"- {p.name} — {int(p.qty or 0)} units left")
        healthy = [p for p in m['active_products']
                   if p.total_stock > 5]
        lines.append(f"\n**Healthy stock:** {len(healthy)} products with more than 5 units")
        return '\n'.join(lines)

    # ── Sales / revenue / trend ────────────────────────────────────────────
    if any(t in q for t in ['sale', 'revenue', 'trend', 'selling', 'best', 'top', 'perform']):
        lines = [
            f"## Sales Performance",
            f"- **7 days:** {_fmt_money(m['rev_week'])} revenue, {_fmt_money(m['profit_week'])} profit",
            f"- **30 days:** {_fmt_money(m['rev_month'])} revenue",
            f"- **1 year:** {_fmt_money(m['rev_year'])} revenue",
            "",
            "## Top Products (30 days)",
        ]
        for i, p in enumerate(m['top_products'][:7], 1):
            profit = (p.revenue or 0) - (p.total_cost or 0)
            lines.append(f"{i}. **{p.name}** — {int(p.units_sold or 0)} units, "
                         f"{_fmt_money(p.revenue or 0)} revenue, {_fmt_money(profit)} profit")
        if not m['top_products']:
            lines.append("- No sales recorded in the last 30 days.")
        return '\n'.join(lines)

    # ── Customers ──────────────────────────────────────────────────────────
    if any(t in q for t in ['customer', 'client', 'buyer', 'loyalty', 'vip', 'tier']):
        lines = [
            f"## Customer Overview",
            f"- **Total customers:** {m['total_customers']}",
            f"- **New this month:** {m['new_customers']}",
            "",
            "## By Tier",
        ]
        for tier, count in m['tier_counts']:
            lines.append(f"- {tier}: {count} customers")
        if m['pay_split']:
            lines.append("\n## Payment Methods (30 days)")
            for p in m['pay_split']:
                lines.append(f"- {p.payment_method.upper()}: "
                              f"{int(p.count or 0)} transactions, {_fmt_money(p.revenue or 0)}")
        return '\n'.join(lines)

    # ── Category ───────────────────────────────────────────────────────────
    if any(t in q for t in ['categor', 'department', 'type', 'range']):
        lines = ["## Category Performance (30 days)"]
        for c in m['cat_perf']:
            lines.append(f"- **{c.name}:** {_fmt_money(c.revenue or 0)}, "
                         f"{int(c.units or 0)} units sold")
        if not m['cat_perf']:
            lines.append("- No category sales data for the last 30 days.")
        return '\n'.join(lines)

    # ── Slow movers / promotions ───────────────────────────────────────────
    if any(t in q for t in ['slow', 'discount', 'promo', 'clearance', 'markdown', 'not selling']):
        lines = ["## Slow Movers (no sales in 30 days)"]
        for p in m['slow_movers'][:10]:
            lines.append(f"- {p.name} — {p.total_stock} units in stock, "
                         f"priced at {_fmt_money(p.price)}")
        if not m['slow_movers']:
            lines.append("- All products have had at least one sale in the last 30 days.")
        lines += [
            "",
            "## Suggested Actions",
            "- Bundle slow movers with your top sellers as a package deal",
            "- Run a 10-20% markdown on items with stock > 10 units and no recent sales",
            "- Feature them on social media or offer to loyalty customers first",
        ]
        return '\n'.join(lines)

    # ── Generic fallback — full store summary ─────────────────────────────
    last = m['last_completed_sale']
    last_info = (f"{last.order_number} on {last.created_at.strftime('%d %b %Y')} "
                 f"for {_fmt_money(last.total_amount)}"
                 if last else "No sales yet")

    lines = [
        f"## Store Overview",
        f"- **Revenue this week:** {_fmt_money(m['rev_week'])}",
        f"- **Profit this week:** {_fmt_money(m['profit_week'])}",
        f"- **Revenue this month:** {_fmt_money(m['rev_month'])}",
        f"- **Active products:** {len(m['active_products'])}",
        f"- **Customers:** {m['total_customers']} total",
        f"- **Last sale:** {last_info}",
        "",
    ]
    if m['low_stock']:
        lines.append("## Needs Attention")
        for p in m['low_stock'][:3]:
            lines.append(f"- {p.name}: only {int(p.qty or 0)} units left")
    if m['top_products']:
        lines.append(f"\n## Leading Product")
        leader = m['top_products'][0]
        lines.append(f"- {leader.name}: {_fmt_money(leader.revenue or 0)} revenue this month")

    lines += [
        "",
        "You can ask me more specific questions like:",
        "- *What was my last sale?*",
        "- *Which products are selling at a loss?*",
        "- *How is the Dresses category performing?*",
        "- *What stock should I reorder?*",
    ]
    return '\n'.join(lines)


@ai_bp.route('/ai-advisor')
@login_required
def index():
    return render_template('ai/index.html')


@ai_bp.route('/ai-advisor/sessions', methods=['GET'])
@login_required
def list_sessions():
    sessions = AIChatSession.query.filter_by(user_id=current_user.id)\
        .order_by(AIChatSession.updated_at.desc()).all()
    return jsonify([{
        'id':         s.id,
        'title':      s.title,
        'updated_at': s.updated_at.strftime('%d %b %Y, %H:%M'),
        'msg_count':  s.messages.count(),
    } for s in sessions])


@ai_bp.route('/ai-advisor/sessions', methods=['POST'])
@login_required
def create_session():
    s = AIChatSession(user_id=current_user.id, title='New Chat')
    db.session.add(s)
    db.session.commit()
    return jsonify({'id': s.id, 'title': s.title})


@ai_bp.route('/ai-advisor/sessions/<int:session_id>', methods=['GET'])
@login_required
def get_session(session_id):
    s = AIChatSession.query.filter_by(id=session_id, user_id=current_user.id).first_or_404()
    messages = [{'role': m.role, 'text': m.text,
                 'time': m.created_at.strftime('%H:%M')}
                for m in s.messages]
    return jsonify({'id': s.id, 'title': s.title, 'messages': messages})


@ai_bp.route('/ai-advisor/sessions/<int:session_id>', methods=['DELETE'])
@login_required
def delete_session(session_id):
    s = AIChatSession.query.filter_by(id=session_id, user_id=current_user.id).first_or_404()
    db.session.delete(s)
    db.session.commit()
    return jsonify({'success': True})


@ai_bp.route('/ai-advisor/sessions/<int:session_id>/rename', methods=['POST'])
@login_required
def rename_session(session_id):
    s = AIChatSession.query.filter_by(id=session_id, user_id=current_user.id).first_or_404()
    data = request.get_json() or {}
    title = (data.get('title') or '').strip()[:120]
    if title:
        s.title = title
        db.session.commit()
    return jsonify({'success': True, 'title': s.title})


@ai_bp.route('/ai-advisor/chat', methods=['POST'])
@login_required
def chat():
    data = request.get_json() or {}
    user_message = (data.get('message') or '').strip()
    history      = data.get('history', [])
    session_id   = data.get('session_id')

    if not user_message:
        return jsonify({'error': 'Empty message'}), 400

    # ── Resolve / create session ──────────────────────────────────────────
    if session_id:
        session = AIChatSession.query.filter_by(
            id=session_id, user_id=current_user.id).first()
    else:
        session = None

    if session is None:
        session = AIChatSession(user_id=current_user.id, title='New Chat')
        db.session.add(session)
        db.session.flush()

    # Save user message
    db.session.add(AIChatMessage(session_id=session.id, role='user', text=user_message))

    # Auto-title from first user message
    if session.title == 'New Chat':
        session.title = user_message[:80]

    try:
        from app.models import StoreSetting
        api_key = current_app.config.get('GEMINI_API_KEY', '') or StoreSetting.get('gemini_api_key', '')

        if not api_key:
            reply  = build_local_advice(user_message)
            source = 'local_fallback'
        else:
            from google import genai
            from google.genai import types

            client     = genai.Client(api_key=api_key)
            store_ctx  = build_store_context()
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
                reply  = response.text
                source = 'gemini'
            except Exception as model_err:
                err = str(model_err)
                if '429' in err or 'RESOURCE_EXHAUSTED' in err:
                    # Check if daily quota is fully exhausted (limit: 0)
                    if 'limit: 0' in err or '429' in err or 'RESOURCE_EXHAUSTED' in err:
                        reply  = build_local_advice(user_message)
                        source = 'local_fallback'
                else:
                    raise

        # Save AI reply
        db.session.add(AIChatMessage(session_id=session.id, role='ai', text=reply))
        session.updated_at = datetime.utcnow()
        db.session.commit()

        return jsonify({'reply': reply, 'source': source, 'session_id': session.id})

    except Exception:
        current_app.logger.exception('AI advisor failed')
        reply = build_local_advice(user_message)
        db.session.add(AIChatMessage(session_id=session.id, role='ai', text=reply))
        session.updated_at = datetime.utcnow()
        db.session.commit()
        return jsonify({'reply': reply, 'source': 'local_fallback', 'session_id': session.id})


@ai_bp.route('/ai-advisor/context')
@login_required
def get_context():
    try:
        return jsonify({'context': build_store_context()})
    except Exception as exc:
        return jsonify({'error': str(exc)}), 500
