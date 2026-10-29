from datetime import date, timedelta

import pytest

from food_expiry_app import create_app, db
from food_expiry_app.models import Product, User
from food_expiry_app.utils import get_expiry_status


def build_app():
    app = create_app({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite://',
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
    assert resp.location.endswith('/login')

    resp = client.post('/login', data={'email': 'alice@example.com', 'password': 'secret123'}, follow_redirects=False)
    assert resp.status_code == 302
    assert resp.location.endswith('/dashboard')


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


def test_production_redirects_http_and_sets_hsts(monkeypatch):
    monkeypatch.setenv('APP_ENV', 'production')
    monkeypatch.setenv('SECRET_KEY', 'a-long-random-production-secret-for-tests')
    monkeypatch.setenv('TRUSTED_PROXY_COUNT', '1')
    app = create_app({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite://',
        'WTF_CSRF_ENABLED': False,
    })
    client = app.test_client()

    http_response = client.get('/health', base_url='http://localhost')
    assert http_response.status_code == 301
    assert http_response.headers['Location'].startswith('https://')

    https_response = client.get(
        '/health',
        base_url='http://localhost',
        headers={'X-Forwarded-Proto': 'https'},
    )
    assert https_response.status_code == 200
    assert https_response.headers['Strict-Transport-Security'] == 'max-age=31536000'
