"""Utility functions and seed data for Boutique POS."""
import os
from datetime import datetime, timedelta
import random
import string
from flask import url_for


def extract_upload_filename(value):
    """Return a stored filename from a bare filename, URL path, or Windows path."""
    if not value:
        return ''
    cleaned = str(value).strip().replace('\\', '/').split('?', 1)[0].rstrip('/')
    return os.path.basename(cleaned)


def upload_url(value):
    """Build the public URL for an uploaded file while supporting legacy values."""
    if not value:
        return ''
    value = str(value).strip()
    if value.startswith(('http://', 'https://', 'data:')):
        return value
    filename = extract_upload_filename(value)
    if not filename:
        return value
    return url_for('uploaded_file', filename=filename)


def seed_data():
    """Seed initial data if database is empty."""
    from app import db
    from app.models import User, Category, Product, ProductVariant, Customer, Sale, SaleItem

    # Only seed if no users exist
    if User.query.first():
        return

    # --- Users ---
    admin = User(name='Sarah Mitchell', email='admin@boutique.com', role='admin')
    admin.set_password('admin123')
    cashier = User(name='Jane Doe', email='cashier@boutique.com', role='cashier')
    cashier.set_password('cashier123')
    db.session.add_all([admin, cashier])
    db.session.flush()

    # --- Categories ---
    cats = ['Dresses', 'Outerwear', 'Tops', 'Knitwear', 'Bottoms', 'Accessories', 'Footwear']
    cat_objs = {}
    for c in cats:
        obj = Category(name=c)
        db.session.add(obj)
        cat_objs[c] = obj
    db.session.flush()

    # --- Products ---
    products_data = [
        {'name': 'Silk Wrap Midi Dress', 'sku': 'DRS-001-SLK', 'cat': 'Dresses',
         'price': 185.0, 'cost': 80.0, 'colors': ['#C2A094', '#1a1a1a'], 'sizes': ['XS', 'S', 'M', 'L']},
        {'name': 'Tailored Linen Blazer', 'sku': 'JKT-442-LIN', 'cat': 'Outerwear',
         'price': 240.0, 'cost': 110.0, 'colors': ['#8FAF8F', '#c9a87c'], 'sizes': ['S', 'M', 'L', 'XL']},
        {'name': 'Pearl Detail Blouse', 'sku': 'TOP-221-PRL', 'cat': 'Tops',
         'price': 95.0, 'cost': 40.0, 'colors': ['#F5F5F0'], 'sizes': ['XS', 'S', 'M', 'L', 'XL']},
        {'name': 'Cashmere Turtleneck', 'sku': 'KNT-089-CSH', 'cat': 'Knitwear',
         'price': 160.0, 'cost': 70.0, 'colors': ['#6b7fa3', '#2d3a4a'], 'sizes': ['S', 'M', 'L']},
        {'name': 'High-Waist Trousers', 'sku': 'TRN-212-LIN', 'cat': 'Bottoms',
         'price': 120.0, 'cost': 55.0, 'colors': ['#2d2d2d', '#8c7b6e'], 'sizes': ['XS', 'S', 'M', 'L', 'XL']},
        {'name': 'Gold Link Necklace', 'sku': 'ACC-077-GLD', 'cat': 'Accessories',
         'price': 75.0, 'cost': 25.0, 'colors': ['#d4a843'], 'sizes': ['One Size']},
        {'name': 'Leather Chelsea Boots', 'sku': 'SHW-550-LTH', 'cat': 'Footwear',
         'price': 210.0, 'cost': 95.0, 'colors': ['#3d2b1f'], 'sizes': ['36', '37', '38', '39', '40', '41']},
        {'name': 'Satin Slip Skirt', 'sku': 'BTM-334-SAT', 'cat': 'Bottoms',
         'price': 88.0, 'cost': 38.0, 'colors': ['#1a6b4a', '#8B0000'], 'sizes': ['XS', 'S', 'M', 'L']},
        {'name': 'Tailored Wool Blazer', 'sku': 'JKT-442-WOL', 'cat': 'Outerwear',
         'price': 295.0, 'cost': 130.0, 'colors': ['#2d3a4a'], 'sizes': ['S', 'M', 'L', 'XL']},
        {'name': 'Cashmere Crewneck Sweater', 'sku': 'SWT-098-CSH', 'cat': 'Knitwear',
         'price': 145.0, 'cost': 65.0, 'colors': ['#c9a87c'], 'sizes': ['S', 'M', 'L']},
    ]

    prod_objs = []
    for pd in products_data:
        p = Product(
            name=pd['name'], sku=pd['sku'],
            category_id=cat_objs[pd['cat']].id,
            price=pd['price'], cost_price=pd['cost'],
            is_active=True
        )
        db.session.add(p)
        db.session.flush()

        # Create variants
        stock_levels = [random.randint(0, 30) for _ in pd['sizes']]
        for i, size in enumerate(pd['sizes']):
            for color in pd['colors']:
                v = ProductVariant(
                    product_id=p.id,
                    size=size, color=color,
                    stock_qty=stock_levels[i]
                )
                db.session.add(v)
        prod_objs.append(p)
    db.session.flush()

    # --- Customers ---
    customers_data = [
        {'name': 'Eleanor Vance', 'phone': '+254712345678', 'email': 'eleanor.vance@example.com',
         'tier': 'VIP', 'points': 1250, 'size': 'S', 'tags': 'Silk Scarves,Linen Dresses'},
        {'name': 'Julian Thorne', 'phone': '+254722987654', 'email': 'julian@example.com',
         'tier': 'Gold', 'points': 820, 'size': 'L', 'tags': 'Outerwear'},
        {'name': 'Sienna Brooks', 'phone': '+254733111222', 'email': 'sienna@example.com',
         'tier': 'Silver', 'points': 430, 'size': 'M', 'tags': 'Tops,Accessories'},
        {'name': 'Marcus Aurelius', 'phone': '+254701555333', 'email': 'marcus@example.com',
         'tier': 'Bronze', 'points': 120, 'size': 'XL', 'tags': 'Outerwear,Knitwear'},
        {'name': 'Leila Al-Fayed', 'phone': '+254744222999', 'email': 'leila@example.com',
         'tier': 'Gold', 'points': 950, 'size': 'XS', 'tags': 'Dresses,Accessories'},
    ]
    cust_objs = []
    for cd in customers_data:
        c = Customer(
            name=cd['name'], phone=cd['phone'], email=cd['email'],
            tier=cd['tier'], loyalty_points=cd['points'],
            preferred_size=cd['size'], style_tags=cd['tags'],
            marketing_optin=True
        )
        db.session.add(c)
        cust_objs.append(c)
    db.session.flush()

    # --- Historical Sales (last 30 days) ---
    statuses = ['completed', 'completed', 'completed', 'pending', 'cancelled']
    pay_methods = ['cash', 'cash', 'mpesa']
    for day_offset in range(30, 0, -1):
        sale_date = datetime.utcnow() - timedelta(days=day_offset)
        num_sales = random.randint(2, 8)
        for _ in range(num_sales):
            cust = random.choice(cust_objs + [None])
            prod = random.choice(prod_objs)
            variant = random.choice(prod.variants.all())
            qty = random.randint(1, 3)
            subtotal = prod.price * qty
            total_cost = (prod.cost_price or 0.0) * qty
            status = random.choice(statuses)
            pay = random.choice(pay_methods)

            sale = Sale(
                order_number=f'ORD-{sale_date.strftime("%Y%m%d")}-{random.randint(1000,9999)}',
                customer_id=cust.id if cust else None,
                cashier_id=admin.id,
                subtotal=subtotal,
                discount=0.0,
                total_amount=subtotal,
                total_cost=total_cost,
                total_profit=subtotal - total_cost,
                payment_method=pay,
                mpesa_ref=''.join(random.choices(string.ascii_uppercase + string.digits, k=10)) if pay == 'mpesa' else '',
                status=status,
                created_at=sale_date
            )
            db.session.add(sale)
            db.session.flush()

            item = SaleItem(
                sale_id=sale.id,
                product_id=prod.id,
                variant_id=variant.id,
                quantity=qty,
                unit_price=prod.price,
                line_total=subtotal,
                size=variant.size,
                color=variant.color,
                product_name=prod.name,
                cost_price=prod.cost_price or 0.0
            )
            db.session.add(item)

    db.session.commit()
    print("[OK] Database seeded successfully.")
