from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from app import db, login_manager


# ---------------------------------------------------------------------------
# User / Auth
# ---------------------------------------------------------------------------
class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), default='cashier')  # admin | cashier
    avatar = db.Column(db.String(200), default='')
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime)

    # Relationships
    sales = db.relationship('Sale', backref='cashier', lazy='dynamic')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_admin(self):
        return self.role == 'admin'

    def __repr__(self):
        return f'<User {self.email}>'


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


# ---------------------------------------------------------------------------
# Customer
# ---------------------------------------------------------------------------
class Customer(db.Model):
    __tablename__ = 'customers'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(30), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), default='')
    photo = db.Column(db.String(300), default='')
    tier = db.Column(db.String(20), default='Bronze')  # VIP | Gold | Silver | Bronze
    loyalty_points = db.Column(db.Integer, default=0)
    store_credit = db.Column(db.Float, default=0.0)
    preferred_size = db.Column(db.String(10), default='')
    style_tags = db.Column(db.String(300), default='')  # comma-separated
    staff_note = db.Column(db.Text, default='')
    marketing_optin = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    sales = db.relationship('Sale', backref='customer', lazy='dynamic')

    @property
    def total_spend(self):
        return sum(s.total_amount for s in self.sales if s.status == 'completed')

    @property
    def avg_order_value(self):
        completed = [s for s in self.sales if s.status == 'completed']
        if not completed:
            return 0
        return self.total_spend / len(completed)

    @property
    def last_purchase_date(self):
        last = self.sales.filter_by(status='completed').order_by(Sale.created_at.desc()).first()
        return last.created_at if last else None

    def __repr__(self):
        return f'<Customer {self.name}>'


# ---------------------------------------------------------------------------
# Store Settings
# ---------------------------------------------------------------------------
class StoreSetting(db.Model):
    __tablename__ = 'store_settings'

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(80), unique=True, nullable=False, index=True)
    value = db.Column(db.Text, default='')

    @staticmethod
    def get(key, default=''):
        row = StoreSetting.query.filter_by(key=key).first()
        return row.value if row else default

    @staticmethod
    def set(key, value):
        row = StoreSetting.query.filter_by(key=key).first()
        if row:
            row.value = value
        else:
            row = StoreSetting(key=key, value=value)
            db.session.add(row)

    def __repr__(self):
        return f'<StoreSetting {self.key}={self.value}>'


# ---------------------------------------------------------------------------
# AI Chat Sessions
# ---------------------------------------------------------------------------
class AIChatSession(db.Model):
    __tablename__ = 'ai_chat_sessions'

    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    title      = db.Column(db.String(200), default='New Chat')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    messages = db.relationship('AIChatMessage', backref='session',
                               lazy='dynamic', cascade='all, delete-orphan',
                               order_by='AIChatMessage.created_at')

    def __repr__(self):
        return f'<AIChatSession {self.id} {self.title}>'


class AIChatMessage(db.Model):
    __tablename__ = 'ai_chat_messages'

    id         = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('ai_chat_sessions.id'), nullable=False)
    role       = db.Column(db.String(10), nullable=False)   # 'user' | 'ai'
    text       = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<AIChatMessage {self.role} {self.id}>'


# ---------------------------------------------------------------------------
# Goals
# ---------------------------------------------------------------------------
class Goal(db.Model):
    __tablename__ = 'goals'

    id          = db.Column(db.Integer, primary_key=True)
    user_id     = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    title       = db.Column(db.String(120), nullable=False)
    goal_type   = db.Column(db.String(20), nullable=False)   # revenue | profit | transactions | stock
    period      = db.Column(db.String(10), nullable=False)   # day | week | month
    target      = db.Column(db.Float, nullable=False)
    # For stock goals: link to a specific product (optional — null = all products)
    product_id  = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=True)
    is_active   = db.Column(db.Boolean, default=True)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)

    product = db.relationship('Product', foreign_keys=[product_id])

    def __repr__(self):
        return f'<Goal {self.title} {self.target}>'
class Category(db.Model):
    __tablename__ = 'categories'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    products = db.relationship('Product', backref='category', lazy='dynamic')

    def __repr__(self):
        return f'<Category {self.name}>'


class Product(db.Model):
    __tablename__ = 'products'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    sku = db.Column(db.String(50), unique=True, nullable=False, index=True)
    category_id = db.Column(db.Integer, db.ForeignKey('categories.id'), nullable=False)
    price = db.Column(db.Float, nullable=False)
    cost_price = db.Column(db.Float, default=0.0)
    description = db.Column(db.Text, default='')
    image = db.Column(db.String(300), default='')
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    variants = db.relationship('ProductVariant', backref='product', lazy='dynamic',
                               cascade='all, delete-orphan')
    sale_items = db.relationship('SaleItem', backref='product', lazy='dynamic')

    @property
    def total_stock(self):
        return sum(v.stock_qty for v in self.variants)

    @property
    def colors(self):
        return list({v.color for v in self.variants if v.color})

    @property
    def sizes(self):
        return list({v.size for v in self.variants if v.size})

    @property
    def status(self):
        stock = self.total_stock
        if stock == 0:
            return 'out_of_stock'
        elif stock <= 5:
            return 'low_stock'
        return 'in_stock'

    def __repr__(self):
        return f'<Product {self.name}>'


class ProductVariant(db.Model):
    __tablename__ = 'product_variants'

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    size = db.Column(db.String(20), default='')
    color = db.Column(db.String(50), default='')
    stock_qty = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<Variant {self.product_id} {self.size}/{self.color}>'


# ---------------------------------------------------------------------------
# Sales
# ---------------------------------------------------------------------------
class Sale(db.Model):
    __tablename__ = 'sales'

    id = db.Column(db.Integer, primary_key=True)
    order_number = db.Column(db.String(20), unique=True, nullable=False, index=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id'), nullable=True)
    cashier_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    subtotal = db.Column(db.Float, default=0.0)
    discount = db.Column(db.Float, default=0.0)
    total_amount = db.Column(db.Float, default=0.0)
    total_cost = db.Column(db.Float, default=0.0)    # sum of cost prices
    total_profit = db.Column(db.Float, default=0.0)  # revenue - cost
    payment_method = db.Column(db.String(20), default='cash')  # cash | mpesa
    mpesa_ref = db.Column(db.String(50), default='')
    status = db.Column(db.String(20), default='completed')  # completed | pending | cancelled
    notes = db.Column(db.Text, default='')
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    # Relationships
    items = db.relationship('SaleItem', backref='sale', lazy='dynamic',
                            cascade='all, delete-orphan')

    def generate_order_number(self):
        import random
        self.order_number = f'ORD-{datetime.utcnow().strftime("%Y%m%d")}-{random.randint(1000, 9999)}'

    def __repr__(self):
        return f'<Sale {self.order_number}>'


class SaleItem(db.Model):
    __tablename__ = 'sale_items'

    id = db.Column(db.Integer, primary_key=True)
    sale_id = db.Column(db.Integer, db.ForeignKey('sales.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    variant_id = db.Column(db.Integer, db.ForeignKey('product_variants.id'), nullable=True)
    quantity = db.Column(db.Integer, default=1)
    unit_price = db.Column(db.Float, nullable=False)
    line_total = db.Column(db.Float, nullable=False)

    # Variant snapshot
    size = db.Column(db.String(20), default='')
    color = db.Column(db.String(50), default='')
    product_name = db.Column(db.String(200), default='')  # snapshot
    cost_price = db.Column(db.Float, default=0.0)         # cost at time of sale

    @property
    def profit(self):
        return (self.unit_price - self.cost_price) * self.quantity

    def __repr__(self):
        return f'<SaleItem {self.product_name} x{self.quantity}>'
