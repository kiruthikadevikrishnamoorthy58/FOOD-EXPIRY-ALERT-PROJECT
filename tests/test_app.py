from datetime import date, timedelta
from io import BytesIO
import os
import shutil
import sqlite3

import pytest
import pytesseract
from PIL import Image, ImageDraw, ImageFont

from food_expiry_app import create_app, db, normalize_database_url
from food_expiry_app.models import Product, User
from food_expiry_app.utils import (
    OCRProcessingError,
    _estimate_skew_angle,
    extract_ocr_scan_from_image,
    extract_ocr_text_from_image,
    find_best_expiry_date,
    find_expiry_date_candidates,
    get_expiry_status,
)


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


def test_database_url_uses_psycopg_driver_for_render_postgres():
    assert normalize_database_url('postgres://user:pass@host/db') == (
        'postgresql+psycopg://user:pass@host/db'
    )
    assert normalize_database_url('postgresql://user:pass@host/db') == (
        'postgresql+psycopg://user:pass@host/db'
    )
    assert normalize_database_url('sqlite:///food_expiry.db') == 'sqlite:///food_expiry.db'


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
        if path == '/scan':
            assert b'id="camera-scan-line"' in response.data
            assert b'id="camera-scan-status-text">Camera off' in response.data
            assert b'id="start-camera"' in response.data
            assert b'id="camera-stream"' in response.data
            assert b'name="manual_date"' not in response.data


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
    assert b'Scanned expiry date: 21/05/2030' in verify_page.data
    assert b'Save product with scanned date' in verify_page.data
    assert b'type="date"' not in verify_page.data

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


def test_rescan_returns_to_scanner_and_discards_pending_scan():
    app = build_app()
    client = app.test_client()
    client.post('/signup', data={
        'name': 'Rescan Alice',
        'email': 'rescan@example.com',
        'password': 'secret123',
    })
    client.post('/scan', data={
        'product_name': 'Yogurt',
        'category': 'Dairy',
        'manual_date': '2030-05-21',
    })

    rescan = client.post('/verify-scan', data={
        'action': 'rescan',
    }, follow_redirects=True)
    assert rescan.status_code == 200
    assert rescan.request.path == '/scan'
    assert b'id="open-camera"' not in rescan.data
    assert b'id="capture-photo"' in rescan.data
    assert b'id="start-camera"' in rescan.data
    assert b'id="camera-frame"' in rescan.data
    assert b'class="upload-camera-button"><span aria-hidden="true">\xf0\x9f\x93\xb7</span> Open Camera' in rescan.data
    assert b'capture="environment"' in rescan.data

    verify_without_pending_scan = client.get('/verify-scan', follow_redirects=False)
    assert verify_without_pending_scan.status_code == 302
    assert verify_without_pending_scan.location.endswith('/scan')
    with app.app_context():
        assert Product.query.filter_by(product_name='Yogurt').count() == 0


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
        'food_expiry_app.routes.extract_ocr_scan_from_image',
        lambda _path: (
            'EXP 2030-06-11',
            find_expiry_date_candidates('EXP 2030-06-11'),
        ),
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
    assert b'name="expiry_date"' in verify_page.data
    assert b'id="ocr_text" name="ocr_text" readonly' in verify_page.data
    assert b'<details class="ocr-details" open>' in verify_page.data
    assert b'EXP 2030-06-11' in verify_page.data
    assert b'Scanned expiry date: 11/06/2030' in verify_page.data
    assert b'Please compare it with the package.' in verify_page.data
    assert b'class="flash flash-warning"' not in verify_page.data
    assert verify_page.data.count(b'class="scan-warning"') == 0
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
    inventory = client.get('/inventory')
    assert b'Jun 11, 2030' in inventory.data


def test_multiple_expiry_candidates_require_user_selection(monkeypatch, tmp_path):
    app = build_app()
    app.config['UPLOAD_FOLDER'] = str(tmp_path / 'uploads')
    client = app.test_client()
    client.post('/signup', data={
        'name': 'Candidate Alice',
        'email': 'candidate@example.com',
        'password': 'secret123',
    })
    monkeypatch.setattr(
        'food_expiry_app.routes.extract_ocr_scan_from_image',
        lambda _path: (
            'MFG 28/07/2026\nEXP 25/12/2026\nBEST BEFORE 31/12/2026',
            find_expiry_date_candidates(
                'MFG 28/07/2026\nEXP 25/12/2026\nBEST BEFORE 31/12/2026'
            ),
        ),
    )
    image = BytesIO()
    Image.new('RGB', (4, 4), color='white').save(image, format='PNG')
    image.seek(0)

    client.post('/scan', data={'image': (image, 'label.png')})
    review = client.get('/verify-scan')
    assert b'More than one possible date needs verification.' in review.data
    assert b'value="2026-07-28"' not in review.data
    assert b'value="2026-12-25"' in review.data
    assert b'value="2026-12-31"' in review.data

    saved = client.post('/verify-scan', data={
        'action': 'save',
        'product_name': 'Cereal',
        'expiry_date': '2026-12-31',
    })
    assert saved.status_code == 302
    with app.app_context():
        product = Product.query.filter_by(product_name='Cereal').one()
        assert product.expiry_date == date(2026, 12, 31)


def test_no_readable_text_shows_manual_fallback_and_never_guesses(monkeypatch, tmp_path):
    app = build_app()
    app.config['UPLOAD_FOLDER'] = str(tmp_path / 'uploads')
    client = app.test_client()
    client.post('/signup', data={
        'name': 'Manual Fallback Alice',
        'email': 'manual-fallback@example.com',
        'password': 'secret123',
    })
    monkeypatch.setattr(
        'food_expiry_app.routes.extract_ocr_scan_from_image',
        lambda _path: ('', []),
    )
    image = BytesIO()
    Image.new('RGB', (4, 4), color='white').save(image, format='PNG')
    image.seek(0)

    client.post('/scan', data={'image': (image, 'label.png')})
    review = client.get('/verify-scan')
    assert b'Expiry date not detected. Please capture a clearer image or enter the date manually.' in review.data
    assert b'id="manual_expiry_date"' in review.data
    assert b'name="expiry_date"' not in review.data

    saved = client.post('/verify-scan', data={
        'action': 'save',
        'product_name': 'Oat milk',
        'manual_expiry_date': '2030-07-18',
    })
    assert saved.status_code == 302
    with app.app_context():
        product = Product.query.filter_by(product_name='Oat milk').one()
        assert product.expiry_date == date(2030, 7, 18)


def test_ocr_checks_the_entire_image_in_all_orientations(monkeypatch, tmp_path):
    image_path = tmp_path / 'label.png'
    Image.new('RGB', (40, 20), color='white').save(image_path)
    calls = []
    monkeypatch.setenv('TESSERACT_CMD', 'test-tesseract')
    monkeypatch.setattr(
        pytesseract.pytesseract,
        'tesseract_cmd',
        pytesseract.pytesseract.tesseract_cmd,
    )

    def fake_ocr(_image, config, output_type, timeout):
        calls.append(config)
        assert timeout == 3.0
        assert output_type == pytesseract.Output.DICT
        return {
            'text': ['EXP', '2030-06-11'],
            'conf': ['90', '90'],
            'left': [0, 50],
            'top': [0, 0],
            'width': [40, 100],
            'height': [20, 20],
        }

    monkeypatch.setattr('food_expiry_app.utils.pytesseract.image_to_data', fake_ocr)

    text = extract_ocr_text_from_image(str(image_path))

    assert len(calls) == 6
    assert pytesseract.pytesseract.tesseract_cmd == 'test-tesseract'
    assert '--psm 11' in calls[0]
    assert any('--psm 6' in config for config in calls)
    assert any('--psm 7' in config for config in calls)
    assert find_best_expiry_date(text) == date(2030, 6, 11)


def test_ocr_retries_sideways_image_orientation_when_first_pass_misses_date(monkeypatch, tmp_path):
    image_path = tmp_path / 'label.png'
    Image.new('RGB', (40, 20), color='white').save(image_path)
    calls = []

    def fake_ocr(_image, config, output_type, timeout):
        calls.append(config)
        assert timeout == 3.0
        assert output_type == pytesseract.Output.DICT
        if len(calls) == 1:
            text = []
        else:
            text = ['BEST', 'BEFORE', '31/12/2030']
        return {
            'text': text,
            'conf': ['90'] * len(text),
            'left': [index * 50 for index in range(len(text))],
            'top': [0] * len(text),
            'width': [40] * len(text),
            'height': [20] * len(text),
        }

    monkeypatch.setattr('food_expiry_app.utils.pytesseract.image_to_data', fake_ocr)

    text = extract_ocr_text_from_image(str(image_path))

    assert len(calls) == 7
    assert '--psm 11' in calls[0]
    assert '--psm 11' in calls[1]
    assert find_best_expiry_date(text) == date(2030, 12, 31)


def test_ocr_checks_more_orientations_when_first_pass_only_finds_preparation_date(
    monkeypatch, tmp_path
):
    image_path = tmp_path / 'label.png'
    Image.new('RGB', (40, 20), color='white').save(image_path)
    calls = []
    responses = (['MFG', '01/01/2026'], ['USE', 'BY', '31/12/2026'])

    def fake_ocr(_image, config, output_type, timeout):
        calls.append(config)
        assert timeout == 3.0
        assert output_type == pytesseract.Output.DICT
        text = responses[min(len(calls) - 1, len(responses) - 1)]
        return {
            'text': text,
            'conf': ['90'] * len(text),
            'left': [index * 50 for index in range(len(text))],
            'top': [0] * len(text),
            'width': [40] * len(text),
            'height': [20] * len(text),
        }

    monkeypatch.setattr('food_expiry_app.utils.pytesseract.image_to_data', fake_ocr)

    text = extract_ocr_text_from_image(str(image_path))

    assert len(calls) == 8
    assert find_best_expiry_date(text) == date(2026, 12, 31)


def test_ocr_uses_word_positions_to_match_expiry_label_and_split_date(monkeypatch, tmp_path):
    image_path = tmp_path / 'label.png'
    Image.new('RGB', (40, 20), color='white').save(image_path)
    words = ['USE', 'BY', '28107', '126']
    left = [0, 35, 100, 152]
    widths = [30, 20, 50, 30]

    def fake_ocr(_image, config, output_type, timeout):
        assert timeout == 3.0
        assert output_type == pytesseract.Output.DICT
        return {
            'text': words,
            'conf': ['90'] * len(words),
            'left': left,
            'top': [100, 100, 95, 95],
            'width': widths,
            'height': [30, 30, 32, 32],
        }

    monkeypatch.setattr('food_expiry_app.utils.pytesseract.image_to_data', fake_ocr)

    text = extract_ocr_text_from_image(str(image_path))

    assert find_best_expiry_date(text) == date(2026, 7, 28)


def test_real_tesseract_prefers_expiry_over_mfg_on_synthetic_label(monkeypatch, tmp_path):
    executable = os.getenv('TESSERACT_CMD', 'tesseract')
    if not os.path.isfile(executable) and not shutil.which(executable):
        executable = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
    if not os.path.isfile(executable) and not shutil.which(executable):
        pytest.skip('Tesseract executable is not installed.')

    font_path = r'C:\Windows\Fonts\arial.ttf'
    if not os.path.isfile(font_path):
        pytest.skip('Arial font is unavailable for the synthetic OCR label.')
    monkeypatch.setenv('TESSERACT_CMD', executable)

    image_path = tmp_path / 'synthetic-food-label.png'
    image = Image.new('RGB', (1500, 620), 'white')
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(font_path, 54)
    draw.text((100, 200), 'MFG 28/07/2026', fill='black', font=font)
    draw.text((100, 360), 'EXP 25/12/2026', fill='black', font=font)
    image.save(image_path)

    ocr_text, candidates = extract_ocr_scan_from_image(str(image_path))

    assert 'MFG' in ocr_text
    assert 'EXP' in ocr_text
    assert [candidate['date'] for candidate in candidates] == ['2026-12-25']
    assert candidates[0]['confidence'] == 'labelled'
    assert candidates[0]['ocr_confidence'] >= 45


def test_ocr_parses_slashes_misread_as_ones_near_use_by_label():
    assert find_best_expiry_date('USE BY\n\n28107126') == date(2026, 7, 28)


def test_ocr_parses_month_year_expiry_as_last_day_of_month():
    assert find_best_expiry_date('BEST BEFORE 06/2030') is None
    candidate = find_expiry_date_candidates('BEST BEFORE 06/2030')[0]
    assert candidate['date'] == '2030-06-30'
    assert candidate['precision'] == 'month'


def test_ocr_two_digit_years_use_a_defined_century_pivot():
    assert find_best_expiry_date('EXP 31/12/26') == date(2026, 12, 31)
    assert find_best_expiry_date('EXP 31/12/99') == date(1999, 12, 31)


def test_ocr_prefers_expiry_date_over_manufacturing_date():
    assert find_best_expiry_date('MFG 28/07/26\nEXP 25/12/26') == date(2026, 12, 25)


def test_ocr_ignores_prepared_date_when_selecting_an_unmarked_expiry():
    text = 'Prepared on 28/07/26\nLot details\n25/12/26'
    assert find_best_expiry_date(text) is None
    candidates = find_expiry_date_candidates(text)
    assert [candidate['date'] for candidate in candidates] == ['2026-12-25']


def test_ocr_does_not_return_prepared_date_as_expiry_when_it_is_the_only_date():
    assert find_best_expiry_date('Manufactured on 28/07/26') is None


def test_ocr_returns_multiple_unlabelled_dates_for_verification():
    assert find_best_expiry_date('28/07/26\n25/12/26') is None
    candidates = find_expiry_date_candidates('28/07/26\n25/12/26')
    assert [candidate['date'] for candidate in candidates] == [
        '2026-07-28',
        '2026-12-25',
    ]


def test_ocr_does_not_guess_ambiguous_day_month_order():
    assert find_best_expiry_date('EXP 04/05/2026') is None
    candidates = find_expiry_date_candidates('EXP 04/05/2026')
    assert {candidate['date'] for candidate in candidates} == {
        '2026-05-04',
        '2026-04-05',
    }


def test_ocr_returns_all_labeled_expiry_dates_but_ignores_mfg():
    candidates = find_expiry_date_candidates(
        'MFG 28/07/2026\nEXP 25/12/2026\nBEST BEFORE 31/12/2026'
    )
    assert [candidate['date'] for candidate in candidates] == [
        '2026-12-25',
        '2026-12-31',
    ]
    assert all(candidate['label'] for candidate in candidates)


def test_ocr_does_not_invent_date_from_unseparated_numbers():
    assert find_best_expiry_date('MRP 5.00 USP 0.15 1826') is None


def test_ocr_skew_estimator_detects_small_text_rotation():
    rows = [{
        'words': [
            {'left': 0, 'top': 20},
            {'left': 100, 'top': 24},
            {'left': 200, 'top': 28},
        ],
    }]
    assert 2.0 < _estimate_skew_angle(rows) < 2.5
    assert _estimate_skew_angle([{'words': [{'left': 0, 'top': 0}, {'left': 30, 'top': 1}]}]) == 0


@pytest.mark.parametrize(('text', 'expected'), [
    ('EXP 31/12/2026', date(2026, 12, 31)),
    ('EXP 12/31/2026', date(2026, 12, 31)),
    ('EXP 31.12.26', date(2026, 12, 31)),
    ('EXP 12/31/26', date(2026, 12, 31)),
    ('EXP 3I/12/2O26', date(2026, 12, 31)),
    ('BEST BEFORE 31 12 2026', date(2026, 12, 31)),
])
def test_ocr_parses_common_numeric_expiry_formats(text, expected):
    assert find_best_expiry_date(text) == expected


def test_ocr_still_parses_iso_date_format():
    assert find_best_expiry_date('EXP 2030-06-11') == date(2030, 6, 11)


def test_ocr_engine_error_requests_rescan_when_date_is_unavailable(monkeypatch, tmp_path):
    app = build_app()
    app.config['UPLOAD_FOLDER'] = str(tmp_path / 'uploads')
    client = app.test_client()
    client.post('/signup', data={
        'name': 'OCR Error Alice',
        'email': 'ocr-error@example.com',
        'password': 'secret123',
    })
    def fail_ocr(_path):
        raise OCRProcessingError('The OCR engine is unavailable. Please try scanning again later.')

    monkeypatch.setattr('food_expiry_app.routes.extract_ocr_scan_from_image', fail_ocr)
    image = BytesIO()
    Image.new('RGB', (4, 4), color='white').save(image, format='PNG')
    image.seek(0)

    response = client.post('/scan', data={
        'image': (image, 'label.png'),
    }, follow_redirects=True)

    assert response.status_code == 200
    assert b'The OCR engine is unavailable. Please try scanning again later.' in response.data
    assert b'class="scan-error"' in response.data
    assert b'class="flash flash-warning"' not in response.data
    assert b'name="expiry_date"' not in response.data
    assert b'name="action" value="rescan" formnovalidate' in response.data
    assert b'id="manual_expiry_date"' in response.data
    assert b'Save product with scanned date' not in response.data
    assert b'Re-scan' in response.data


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
