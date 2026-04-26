from app.routes.auth import auth_bp
from app.routes.dashboard import dashboard_bp
from app.routes.pos import pos_bp
from app.routes.inventory import inventory_bp
from app.routes.customers import customers_bp
from app.routes.reports import reports_bp
from app.routes.settings import settings_bp
from app.routes.api import api_bp

__all__ = [
    'auth_bp', 'dashboard_bp', 'pos_bp', 'inventory_bp',
    'customers_bp', 'reports_bp', 'settings_bp', 'api_bp'
]
