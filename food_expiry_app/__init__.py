import os
import secrets

from dotenv import load_dotenv
from flask import Flask
from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect
from sqlalchemy import inspect, text
from werkzeug.middleware.proxy_fix import ProxyFix

load_dotenv()

db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = 'auth.login'
login_manager.login_message_category = 'warning'
csrf = CSRFProtect()


def create_app(test_config=None):
    app = Flask(
        __name__,
        instance_relative_config=True,
        template_folder='../templates',
        static_folder='../static',
    )
    environment = os.getenv('APP_ENV', 'development').strip().lower()
    secret_key = os.getenv('SECRET_KEY')
    if environment == 'production' and not secret_key:
        raise RuntimeError('Set a strong SECRET_KEY before starting in production.')
    if environment == 'production' and len(secret_key) < 32:
        raise RuntimeError('Production SECRET_KEY must contain at least 32 characters.')

    app.config.from_mapping(
        SECRET_KEY=secret_key or secrets.token_urlsafe(32),
        SQLALCHEMY_DATABASE_URI=os.getenv('DATABASE_URL', 'sqlite:///food_expiry.db'),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        UPLOAD_FOLDER='data/uploads',
        MAX_CONTENT_LENGTH=5 * 1024 * 1024,
        WTF_CSRF_TIME_LIMIT=3600,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
        REMEMBER_COOKIE_HTTPONLY=True,
        REMEMBER_COOKIE_SAMESITE='Lax',
    )
    if test_config:
        app.config.update(test_config)

    if environment == 'production':
        app.config.update(
            SESSION_COOKIE_SECURE=True,
            REMEMBER_COOKIE_SECURE=True,
            PREFERRED_URL_SCHEME='https',
        )
        proxy_count = int(os.getenv('TRUSTED_PROXY_COUNT', '1'))
        if proxy_count:
            app.wsgi_app = ProxyFix(
                app.wsgi_app,
                x_for=proxy_count,
                x_proto=proxy_count,
                x_host=proxy_count,
            )

        @app.after_request
        def add_hsts_header(response):
            response.headers['Strict-Transport-Security'] = 'max-age=31536000'
            return response

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)

    from .models import User, Product, AlertSettings
    with app.app_context():
        db.create_all()
        user_columns = {column['name'] for column in inspect(db.engine).get_columns('users')}
        if 'avatar' not in user_columns:
            with db.engine.begin() as connection:
                connection.execute(text(
                    "ALTER TABLE users ADD COLUMN avatar VARCHAR(16) NOT NULL DEFAULT '👩‍🍳'"
                ))

    from .routes import auth_bp, main_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)

    return app
