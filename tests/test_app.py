from datetime import date, timedelta
import sqlite3

import pytest

from food_expiry_app import create_app, db
from food_expiry_app.models import Product, User
from food_expiry_app.utils import get_expiry_status


def build_app(database_uri='sqlite://'):
    app = create_app({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': database_uri,
        'WTF_CSRF_ENABLED': False,
    })
    with app.app_context():
        db.create_all()
    return app


def test_signup_and_login_work():
    app = build_app()
    client = app.test_client()

    resp = client.post('/signup', data={'name': 'Alice', 'email': 'alice@example.com', 'password': 'secret123'}, follow_redirects=False)
    assert resp.status_code == 302
    assert resp.location.endswith('/dashboard')
    assert client.get('/dashboard').status_code == 200
    assert client.get_cookie('remember_token') is not None
    assert client.get('/signup').location.endswith('/dashboard')
    assert client.get('/login').location.endswith('/dashboard')

    resumed_client = app.test_client()
    resumed_client.set_cookie('remember_token', client.get_cookie('remember_token').value)
    assert resumed_client.get('/dashboard').status_code == 200

    client.get('/logout', follow_redirects=False)
    assert client.get_cookie('remember_token') is None
    duplicate = client.post('/signup', data={
        'name': 'Alice Again',
        'email': 'alice@example.com',
        'password': 'different-password',
    }, follow_redirects=False)
    assert duplicate.status_code == 302
    assert duplicate.location.endswith('/login')
    resp = client.post('/login', data={'email': 'alice@example.com', 'password': 'secret123'}, follow_redirects=False)
    assert resp.status_code == 302
    assert resp.location.endswith('/dashboard')
    assert client.get_cookie('remember_token') is not None


def test_signup_account_survives_app_restart(tmp_path):
    database_uri = f"sqlite:///{str(tmp_path / 'accounts.db').replace('\\', '/')}"
    app = build_app(database_uri)
    client = app.test_client()

    response = client.post('/signup', data={
        'name': 'Persistent Alice',
        'email': 'persistent@example.com',
        'password': 'secret123',
    })
    assert response.status_code == 302

    restarted_app = build_app(database_uri)
    login_response = restarted_app.test_client().post('/login', data={
        'email': 'persistent@example.com',
        'password': 'secret123',
    })
    assert login_response.status_code == 302
    assert login_response.location.endswith('/dashboard')


def test_settings_shows_signup_account_details():
    app = build_app()
    client = app.test_client()
    client.post('/signup', data={
        'name': 'Settings Alice',
        'email': 'settings@example.com',
        'password': 'secret123',
    })

    response = client.get('/settings')
    assert response.status_code == 200
    assert b'Settings Alice' in response.data
    assert b'settings@example.com' in response.data
    assert b'Member since' in response.data
    assert b'password stays private' in response.data


def test_settings_updates_account_and_login_uses_new_email():
    app = build_app()
    client = app.test_client()
    client.post('/signup', data={
        'name': 'Settings Alice',
        'email': 'settings@example.com',
        'password': 'secret123',
    })

    response = client.post('/settings', data={
        'form_name': 'account',
        'name': 'Updated Alice',
        'email': 'updated@example.com',
        'avatar': '🥑',
    }, follow_redirects=False)
    assert response.status_code == 302
    assert response.location.endswith('/settings')

    settings_response = client.get('/settings')
    assert b'Updated Alice' in settings_response.data
    assert b'updated@example.com' in settings_response.data
    assert '🥑'.encode() in settings_response.data

    client.get('/logout')
    invalid_login = client.post('/login', data={
        'email': 'settings@example.com',
        'password': 'secret123',
    })
    assert b'Invalid email or password.' in invalid_login.data

    valid_login = client.post('/login', data={
        'email': 'updated@example.com',
        'password': 'secret123',
    }, follow_redirects=False)
    assert valid_login.status_code == 302
    assert valid_login.location.endswith('/dashboard')


def test_existing_database_gets_default_avatar_column(tmp_path):
    database_path = tmp_path / 'legacy-accounts.db'
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            'CREATE TABLE users ('
            'id INTEGER PRIMARY KEY, '
            'name VARCHAR(120) NOT NULL, '
            'email VARCHAR(120) NOT NULL UNIQUE, '
            'password_hash VARCHAR(255) NOT NULL, '
            'created_at DATETIME, '
            'google_id VARCHAR(255))'
        )
        connection.execute(
            'INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)',
            ('Legacy Alice', 'legacy@example.com', 'existing-hash'),
        )

    app = build_app(f"sqlite:///{str(database_path).replace('\\', '/')}")
    with app.app_context():
        user = User.query.filter_by(email='legacy@example.com').one()
        assert user.avatar == '👩‍🍳'


def test_inventory_shows_user_products():
    app = build_app()
    with app.app_context():
        user = User(name='Bob', email='bob@example.com')
        user.set_password('pw')
        db.session.add(user)
        db.session.commit()
        product = Product(user_id=user.id, product_name='Milk', category='Dairy', expiry_date=date.today() + timedelta(days=5))
        db.session.add(product)
        db.session.commit()

    client = app.test_client()
    with client:
        client.post('/login', data={'email': 'bob@example.com', 'password': 'pw'}, follow_redirects=False)
        resp = client.get('/inventory')
        assert resp.status_code == 200
        assert b'Milk' in resp.data


def test_expiry_status_follows_two_day_rule():
    assert get_expiry_status(date.today() + timedelta(days=3))['label'] == 'Within Date'
    assert get_expiry_status(date.today() + timedelta(days=2))['label'] == 'Expiring Soon'
    assert get_expiry_status(date.today() - timedelta(days=1))['label'] == 'Expired'


def test_production_requires_secret_key(monkeypatch):
    monkeypatch.setenv('APP_ENV', 'production')
    monkeypatch.delenv('SECRET_KEY', raising=False)

    with pytest.raises(RuntimeError, match='SECRET_KEY'):
        create_app()


def test_production_enables_secure_cookies_and_hsts(monkeypatch):
    monkeypatch.setenv('APP_ENV', 'production')
    monkeypatch.setenv('SECRET_KEY', 'a-long-random-production-secret-for-tests')
    monkeypatch.setenv('TRUSTED_PROXY_COUNT', '1')
    app = create_app({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite://',
        'WTF_CSRF_ENABLED': False,
    })
    client = app.test_client()

    assert app.config['SESSION_COOKIE_SECURE'] is True
    assert app.config['REMEMBER_COOKIE_SECURE'] is True
    response = client.get('/health', base_url='https://localhost')
    assert response.status_code == 200
    assert response.headers['Strict-Transport-Security'] == 'max-age=31536000'
