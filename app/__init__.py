import os
import shutil
from flask import Flask, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from config import config

db = SQLAlchemy()
login_manager = LoginManager()


def create_app(config_name='default'):
    app = Flask(__name__)
    app.config.from_object(config[config_name])

    # Ensure upload folder exists
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    legacy_upload_folder = os.path.join(app.root_path, 'static', 'uploads')
    if os.path.isdir(legacy_upload_folder):
        for filename in os.listdir(legacy_upload_folder):
            legacy_path = os.path.join(legacy_upload_folder, filename)
            target_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            if os.path.isfile(legacy_path) and not os.path.exists(target_path):
                shutil.copy2(legacy_path, target_path)

    # Init extensions
    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Please sign in to access the dashboard.'
    login_manager.login_message_category = 'warning'

    # Add Jinja2 globals
    from app.utils import upload_url
    app.jinja_env.globals['enumerate'] = enumerate
    app.jinja_env.globals['upload_url'] = upload_url
    app.jinja_env.filters['multiply'] = lambda x, y: x * y

    @app.route('/uploads/<path:filename>')
    def uploaded_file(filename):
        return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

    # Context processor — inject store settings into every template
    @app.context_processor
    def inject_store_settings():
        from app.models import StoreSetting
        return {
            'store_name': StoreSetting.get('store_name', 'Boutique POS'),
            'theme_color': StoreSetting.get('theme_color', '#00D4C8'),
        }

    # Register blueprints
    from app.routes.auth import auth_bp
    from app.routes.dashboard import dashboard_bp
    from app.routes.pos import pos_bp
    from app.routes.inventory import inventory_bp
    from app.routes.customers import customers_bp
    from app.routes.reports import reports_bp
    from app.routes.settings import settings_bp
    from app.routes.api import api_bp
    from app.routes.ai_advisor import ai_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(pos_bp)
    app.register_blueprint(inventory_bp)
    app.register_blueprint(customers_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(api_bp, url_prefix='/api')
    app.register_blueprint(ai_bp)

    # Create tables and seed data
    with app.app_context():
        from app import models  # noqa
        db.create_all()
        from app.utils import seed_data
        seed_data()

    return app
