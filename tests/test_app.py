from datetime import date, timedelta
from io import BytesIO
import sqlite3

import pytest
from PIL import Image

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


def test_all_authenticated_pages_render_with_dashboard_data():
    app = build_app()
    client = app.test_client()
    client.post('/signup', data={
        'name': 'Page Tester',
        'email': 'pages@example.com',
        'password': 'secret123',
    })
    with app.app_context():
        user = User.query.filter_by(email='pages@example.com').one()
        product = Product(
            user_id=user.id,
            product_name='Fresh Apples',
            category='Fruit',
            expiry_date=date.today() + timedelta(days=1),
        )
        db.session.add(product)
        db.session.commit()
        product_id = product.id

    dashboard = client.get('/dashboard')
    assert dashboard.status_code == 200
    assert b'Expiring soon' in dashboard.data
    assert b'Fresh Apples' in dashboard.data
    assert b'Freshness mix' in dashboard.data
    for path in (
        '/scan',
        '/inventory',
        '/reminders',
        '/settings',
        '/profile',
        f'/product/{product_id}',
    ):
        response = client.get(path)
        assert response.status_code == 200, path


def test_manual_scan_requires_review_before_saving_and_supports_date_edit():
    app = build_app()
    client = app.test_client()
    client.post('/signup', data={
        'name': 'Scanner Alice',
        'email': 'scanner@example.com',
        'password': 'secret123',
    })

    response = client.post('/scan', data={
        'product_name': 'Yogurt',
        'category': 'Dairy',
        'manual_date': '2030-05-21',
    })
    assert response.status_code == 302
    assert response.location.endswith('/verify-scan')
    verify_page = client.get('/verify-scan')
    assert verify_page.status_code == 200
    assert b'OK \xe2\x80\x94 Correct' in verify_page.data

    edit_page = client.post('/verify-scan', data={
        'action': 'edit',
        'expiry_date': '2030-05-21',
    })
    assert edit_page.status_code == 200
    assert b'Review updated date' in edit_page.data
    updated_review = client.post('/verify-scan', data={
        'action': 'update-date',
        'expiry_date': '2030-05-25',
    })
    assert updated_review.status_code == 200
    assert b'2030-05-25' in updated_review.data

    with app.app_context():
        assert Product.query.filter_by(product_name='Yogurt').count() == 0

    saved = client.post('/verify-scan', data={
        'action': 'save',
        'product_name': 'Yogurt',
        'expiry_date': '2030-05-25',
        'category': 'Dairy',
    })
    assert saved.status_code == 302
    with app.app_context():
        product = Product.query.filter_by(product_name='Yogurt').one()
        assert product.expiry_date == date(2030, 5, 25)
        assert product.confirmation_status == 'confirmed'


def test_image_ocr_result_is_reviewed_before_it_is_saved(monkeypatch, tmp_path):
    app = build_app()
    app.config['UPLOAD_FOLDER'] = str(tmp_path / 'uploads')
    client = app.test_client()
    client.post('/signup', data={
        'name': 'OCR Alice',
        'email': 'ocr@example.com',
        'password': 'secret123',
    })
    monkeypatch.setattr(
        'food_expiry_app.routes.extract_ocr_text_from_image',
        lambda _path: 'EXP 2030-06-11',
    )
    image = BytesIO()
    Image.new('RGB', (4, 4), color='white').save(image, format='PNG')
    image.seek(0)

    scan = client.post('/scan', data={
        'product_name': 'Cereal',
        'category': 'Pantry',
        'image': (image, 'label.png'),
    })
    assert scan.status_code == 302
    verify_page = client.get('/verify-scan')
    assert verify_page.status_code == 200
    assert b'2030-06-11' in verify_page.data
    assert b'Please compare it with the package.' in verify_page.data
    with app.app_context():
        assert Product.query.filter_by(product_name='Cereal').count() == 0

    save = client.post('/verify-scan', data={
        'action': 'save',
        'product_name': 'Cereal',
        'category': 'Pantry',
        'expiry_date': '2030-06-11',
    })
    assert save.status_code == 302
    with app.app_context():
        assert Product.query.filter_by(product_name='Cereal').count() == 1


def test_inventory_search_filter_and_sort_use_user_products():
    app = build_app()
    with app.app_context():
        user = User(name='Inventory Alice', email='inventory@example.com')
        user.set_password('secret123')
        db.session.add(user)
        db.session.flush()
        db.session.add_all([
            Product(
                user_id=user.id,
                product_name='Milk',
                category='Dairy',
                expiry_date=date.today() + timedelta(days=1),
            ),
            Product(
                user_id=user.id,
                product_name='Apple',
                category='Fruit',
                expiry_date=date.today() + timedelta(days=8),
            ),
            Product(
                user_id=user.id,
                product_name='Old Bread',
                category='Bakery',
                expiry_date=date.today() - timedelta(days=1),
            ),
        ])
        db.session.commit()

    client = app.test_client()
    client.post('/login', data={
        'email': 'inventory@example.com',
        'password': 'secret123',
    })
    response = client.get('/inventory?search=milk&filter=expiring_soon&sort=product_name')
    assert response.status_code == 200
    assert b'Milk' in response.data
    assert b'Expiring soon' in response.data
    assert b'Apple' not in response.data

    no_match = client.get('/inventory?search=missing')
    assert no_match.status_code == 200
    assert b'No matches this time.' in no_match.data
    assert b'Your kitchen starts here.' not in no_match.data


def test_reminders_and_sound_settings_use_saved_preferences():
    app = build_app()
    client = app.test_client()
    client.post('/signup', data={
        'name': 'Reminder Alice',
        'email': 'reminder@example.com',
        'password': 'secret123',
    })

    response = client.post('/settings', data={
        'form_name': 'alerts',
        'sound_choice': 'chime',
        'volume': '0.75',
        'enabled': 'y',
    })
    assert response.status_code == 302
    assert response.location.endswith('/settings')

    settings_page = client.get('/settings')
    assert b'data-test-alert' in settings_page.data
    assert b'value="0.75"' in settings_page.data
    reminders = client.get('/reminders')
    assert reminders.status_code == 200
    assert b'No upcoming expiries' not in reminders.data
    assert b'All clear for now.' in reminders.data


def test_active_reminder_controls_use_saved_alert_preferences():
    app = build_app()
    client = app.test_client()
    client.post('/signup', data={
        'name': 'Alert Alice',
        'email': 'alert@example.com',
        'password': 'secret123',
    })
    with app.app_context():
        user = User.query.filter_by(email='alert@example.com').one()
        db.session.add(Product(
            user_id=user.id,
            product_name='Fresh yogurt',
            category='Dairy',
            expiry_date=date.today() + timedelta(days=1),
        ))
        db.session.commit()

    client.post('/settings', data={
        'form_name': 'alerts',
        'sound_choice': 'ding',
        'volume': '0.65',
        'enabled': 'y',
    })
    reminders = client.get('/reminders')
    assert reminders.status_code == 200
    assert b'data-alert-sound="ding"' in reminders.data
    assert b'data-alert-volume="0.65"' in reminders.data
    assert b'data-alert-start' in reminders.data
    assert b'data-alert-stop' in reminders.data
    assert b'Fresh yogurt' in reminders.data


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
