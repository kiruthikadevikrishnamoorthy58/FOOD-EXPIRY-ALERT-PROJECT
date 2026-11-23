import os
import uuid
from datetime import date

from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for
from flask_login import login_required, login_user, logout_user, current_user
from werkzeug.utils import secure_filename

from . import db, login_manager
from .forms import AccountProfileForm, AlertSettingsForm, LoginForm, ProductForm, SignupForm
from .models import AlertSettings, Product, User
from .utils import (
    OCRProcessingError,
    extract_ocr_scan_from_image,
    get_expiry_status,
    normalize_email,
    parse_date,
)


auth_bp = Blueprint('auth', __name__)
main_bp = Blueprint('main', __name__)


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


@auth_bp.route('/signup', methods=['GET', 'POST'])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))

    form = SignupForm()
    if form.validate_on_submit():
        email = normalize_email(form.email.data)
        existing = User.query.filter_by(email=email).first()
        if existing:
            flash('You already have an account. Please log in.', 'warning')
            return redirect(url_for('auth.login'))
        user = User(name=form.name.data.strip(), email=email)
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        login_user(user, remember=True)
        session['pending_scan'] = None
        flash('Account created successfully.', 'success')
        return redirect(url_for('main.dashboard'))
    return render_template('auth/signup.html', form=form)


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))

    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=normalize_email(form.email.data)).first()
        if user and user.check_password(form.password.data):
            login_user(user, remember=True)
            session['pending_scan'] = None
            return redirect(url_for('main.dashboard'))
        flash('Invalid email or password.', 'danger')
    return render_template('auth/login.html', form=form)


@auth_bp.route('/logout')
@login_required
def logout():
    session.clear()
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('main.landing'))


@main_bp.route('/')
def landing():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))

    stats = None
    return render_template('landing.html', stats=stats)


@main_bp.route('/dashboard')
@login_required
def dashboard():
    products = Product.query.filter_by(user_id=current_user.id).order_by(Product.date_added.desc()).all()
    today = date.today()
    totals = {
        'total': len(products),
        'fresh': sum(1 for p in products if get_expiry_status(p.expiry_date)['label'] == 'Within Date'),
        'soon': sum(1 for p in products if get_expiry_status(p.expiry_date)['label'] == 'Expiring Soon'),
        'expired': sum(1 for p in products if get_expiry_status(p.expiry_date)['label'] == 'Expired'),
    }
    upcoming = sorted(
        (p for p in products if 0 <= (p.expiry_date - today).days <= 7),
        key=lambda product: product.expiry_date,
    )[:5]
    denominator = totals['total'] or 1
    chart = [
        {'label': 'Fresh', 'count': totals['fresh'], 'class': 'green', 'percent': totals['fresh'] / denominator * 100},
        {'label': 'Soon', 'count': totals['soon'], 'class': 'yellow', 'percent': totals['soon'] / denominator * 100},
        {'label': 'Expired', 'count': totals['expired'], 'class': 'red', 'percent': totals['expired'] / denominator * 100},
    ]
    recent = products[:5]
    return render_template(
        'dashboard/dashboard.html',
        products=products,
        totals=totals,
        recent=recent,
        upcoming=upcoming,
        chart=chart,
        today=today,
    )


@main_bp.route('/scan', methods=['GET', 'POST'])
@login_required
def scan_product():
    if request.method == 'POST':
        uploaded = request.files.get('image')
        if uploaded and uploaded.filename:
            allowed = {'png', 'jpg', 'jpeg'}
            if '.' not in uploaded.filename or uploaded.filename.rsplit('.', 1)[1].lower() not in allowed:
                flash('Unsupported image type. Please upload a JPG or PNG file.', 'danger')
                return redirect(url_for('main.scan_product'))
            filename = secure_filename(f'{uuid.uuid4().hex}_{uploaded.filename}')
            upload_dir = os.path.join(current_app.root_path, '..', current_app.config.get('UPLOAD_FOLDER', 'data/uploads'))
            os.makedirs(upload_dir, exist_ok=True)
            uploaded_path = os.path.join(upload_dir, filename)
            uploaded.save(uploaded_path)
            scan_error = None
            try:
                ocr_text, expiry_candidates = extract_ocr_scan_from_image(uploaded_path)
            except OCRProcessingError as error:
                current_app.logger.exception('OCR processing failed for uploaded scan')
                ocr_text = ''
                expiry_candidates = []
                scan_error = str(error)
            expiry_date = None
            if (len(expiry_candidates) == 1
                    and expiry_candidates[0]['confidence'] == 'labelled'):
                expiry_date = date.fromisoformat(expiry_candidates[0]['date'])
            if scan_error is None and not ocr_text.strip():
                scan_error = 'No readable text found. Check focus and lighting, then capture the expiry date again.'
            elif scan_error is None and not expiry_candidates:
                scan_error = (
                    'Expiry date not detected. Please capture a clearer image or enter the date manually.'
                )
            elif scan_error is None and len(expiry_candidates) > 1:
                scan_error = 'Multiple possible dates were detected. Select the expiry date candidate or enter it manually.'
            elif scan_error is None and expiry_date is None:
                scan_error = 'A possible date was found, but it needs your verification before saving.'
            session['pending_scan'] = {
                'ocr_text': ocr_text,
                'expiry_date': expiry_date.isoformat() if expiry_date else None,
                'expiry_candidates': expiry_candidates,
                'scan_error': scan_error,
                'product_name': request.form.get('product_name', '').strip() or 'Unknown product',
                'category': request.form.get('category', 'General').strip() or 'General',
                'storage_location': request.form.get('storage_location', '').strip(),
                'notes': request.form.get('notes', '').strip(),
            }
            if expiry_date:
                flash('Expiry date scanned automatically. Check it against the package, then save or edit if needed.', 'info')
            return redirect(url_for('main.verify_scan'))

        manual_date = request.form.get('manual_date')
        if manual_date:
            parsed = parse_date(manual_date)
            if not parsed:
                flash('Invalid manual date. Please enter a valid date.', 'danger')
                return redirect(url_for('main.scan_product'))
            session['pending_scan'] = {
                'ocr_text': request.form.get('ocr_text', '') or 'Manual entry',
                'expiry_date': parsed.isoformat(),
                'expiry_candidates': [],
                'product_name': request.form.get('product_name', 'Unknown product').strip() or 'Unknown product',
                'category': request.form.get('category', 'General').strip() or 'General',
                'storage_location': request.form.get('storage_location', '').strip(),
                'notes': request.form.get('notes', '').strip(),
            }
            return redirect(url_for('main.verify_scan'))

    return render_template('scanner/scan.html')


@main_bp.route('/verify-scan', methods=['GET', 'POST'])
@login_required
def verify_scan():
    pending = session.get('pending_scan') or {}
    if not pending:
        flash('No pending scan found. Please scan a product again.', 'warning')
        return redirect(url_for('main.scan_product'))

    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'save':
            product_name = request.form.get('product_name', pending.get('product_name', 'Unknown product')).strip() or 'Unknown product'
            submitted_date = request.form.get('expiry_date', '').strip()
            candidate_dates = {
                candidate['date'] for candidate in pending.get('expiry_candidates', [])
            }
            known_date = pending.get('expiry_date')
            if submitted_date and (
                submitted_date == known_date or submitted_date in candidate_dates
            ):
                expiry_date = parse_date(submitted_date)
            elif not known_date:
                expiry_date = parse_date(request.form.get('manual_expiry_date'))
            else:
                expiry_date = None
            if not expiry_date:
                flash('Select a detected date candidate or enter a valid expiry date before saving.', 'danger')
                return render_template(
                    'scanner/verify_scan.html',
                    pending=pending,
                    manual_expiry_date=request.form.get('manual_expiry_date', ''),
                )
            product = Product(
                user_id=current_user.id,
                product_name=product_name,
                category=request.form.get('category', pending.get('category', 'General')).strip() or 'General',
                expiry_date=expiry_date,
                ocr_text=pending.get('ocr_text', ''),
                confirmation_status='confirmed',
                reminder_status='active',
                notes=request.form.get('notes', pending.get('notes', '')).strip(),
                storage_location=request.form.get('storage_location', pending.get('storage_location', '')).strip(),
            )
            db.session.add(product)
            db.session.commit()
            session.pop('pending_scan', None)
            flash('Product saved successfully to your inventory.', 'success')
            return redirect(url_for('main.inventory'))

        if action == 'edit':
            pending['expiry_date'] = request.form.get('expiry_date', pending.get('expiry_date'))
            session['pending_scan'] = pending
            return render_template('scanner/verify_scan.html', pending=pending, edit_mode=True)

        if action == 'update-date':
            expiry_date = parse_date(request.form.get('expiry_date'))
            if not expiry_date:
                flash('Please enter a valid expiry date before continuing.', 'danger')
                return render_template('scanner/verify_scan.html', pending=pending, edit_mode=True)
            pending['expiry_date'] = expiry_date.isoformat()
            pending['product_name'] = request.form.get('product_name', pending.get('product_name', 'Unknown product')).strip() or 'Unknown product'
            pending['category'] = request.form.get('category', pending.get('category', 'General')).strip() or 'General'
            pending['notes'] = request.form.get('notes', pending.get('notes', '')).strip()
            pending['storage_location'] = request.form.get('storage_location', pending.get('storage_location', '')).strip()
            session['pending_scan'] = pending
            return render_template('scanner/verify_scan.html', pending=pending)

        if action == 'rescan':
            session.pop('pending_scan', None)
            session.modified = True
            return redirect(url_for('main.scan_product'), code=303)

    return render_template('scanner/verify_scan.html', pending=pending)


@main_bp.route('/inventory')
@login_required
def inventory():
    query = Product.query.filter_by(user_id=current_user.id)
    search = request.args.get('search', '').strip()
    filter_status = request.args.get('filter', 'all')
    sort_by = request.args.get('sort', 'expiry_date')
    if search:
        query = query.filter(Product.product_name.ilike(f'%{search}%'))
    products = query.order_by(Product.expiry_date.asc()).all()
    if sort_by == 'product_name':
        products = sorted(products, key=lambda p: p.product_name.lower())
    elif sort_by == 'date_added':
        products = sorted(products, key=lambda p: p.date_added, reverse=True)
    elif sort_by == 'expiry_date':
        products = sorted(products, key=lambda p: p.expiry_date)

    has_products = Product.query.filter_by(user_id=current_user.id).first() is not None
    filtered = []
    for product in products:
        status = get_expiry_status(product.expiry_date)['label']
        if filter_status == 'all' or filter_status == status.lower().replace(' ', '_'):
            filtered.append(product)
    today = date.today()
    return render_template(
        'inventory/inventory.html',
        products=filtered,
        filter_status=filter_status,
        sort_by=sort_by,
        search=search,
        today=today,
        has_products=has_products,
    )


@main_bp.route('/product/<int:product_id>', methods=['GET', 'POST'])
@login_required
def product_detail(product_id):
    product = Product.query.filter_by(id=product_id, user_id=current_user.id).first_or_404()
    form = ProductForm(obj=product)
    if request.method == 'POST' and form.validate_on_submit():
        product.product_name = form.product_name.data
        product.category = form.category.data or 'General'
        product.expiry_date = form.expiry_date.data
        product.notes = form.notes.data
        product.storage_location = form.storage_location.data
        db.session.commit()
        flash('Product details updated successfully.', 'success')
        return redirect(url_for('main.product_detail', product_id=product.id))
    if request.method == 'POST' and not form.validate_on_submit():
        flash('Please correct the form before saving.', 'danger')
    return render_template('product/detail.html', product=product, form=form)


@main_bp.route('/product/<int:product_id>/delete', methods=['POST'])
@login_required
def delete_product(product_id):
    product = Product.query.filter_by(id=product_id, user_id=current_user.id).first_or_404()
    db.session.delete(product)
    db.session.commit()
    flash('Product deleted.', 'info')
    return redirect(url_for('main.inventory'))


@main_bp.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    settings_record = AlertSettings.query.filter_by(user_id=current_user.id).first()
    if settings_record is None:
        settings_record = AlertSettings(user_id=current_user.id, sound_choice='bell', volume=0.8, enabled=True)
        db.session.add(settings_record)
        db.session.commit()
    alert_form = AlertSettingsForm(obj=settings_record)
    account_form = AccountProfileForm(obj=current_user)
    if request.method == 'POST' and request.form.get('form_name') == 'account':
        if account_form.validate_on_submit():
            email = normalize_email(account_form.email.data)
            existing_user = User.query.filter(
                User.email == email,
                User.id != current_user.id,
            ).first()
            if existing_user:
                account_form.email.errors.append('That email address is already associated with an account.')
            else:
                current_user.name = account_form.name.data.strip()
                current_user.email = email
                current_user.avatar = account_form.avatar.data
                db.session.commit()
                flash('Your account profile has been updated.', 'success')
                return redirect(url_for('main.settings'))
    elif request.method == 'POST' and request.form.get('form_name') == 'alerts':
        if alert_form.validate_on_submit():
            settings_record.sound_choice = alert_form.sound_choice.data
            settings_record.volume = alert_form.volume.data
            settings_record.enabled = bool(alert_form.enabled.data)
            db.session.commit()
            flash('Settings saved successfully.', 'success')
            return redirect(url_for('main.settings'))
    return render_template(
        'settings/settings.html',
        account_form=account_form,
        alert_form=alert_form,
        settings=settings_record,
    )


@main_bp.route('/profile')
@login_required
def profile():
    return render_template('profile/profile.html', user=current_user)


@main_bp.route('/reminders')
@login_required
def reminders():
    products = Product.query.filter_by(user_id=current_user.id).all()
    alert_settings = AlertSettings.query.filter_by(user_id=current_user.id).first()
    items = []
    for product in products:
        status = get_expiry_status(product.expiry_date)
        if status['label'] in {'Expiring Soon', 'Expired'}:
            items.append({'product': product, 'status': status})
    items.sort(key=lambda item: item['product'].expiry_date)
    return render_template(
        'alerts/reminders.html',
        items=items,
        alert_sound=alert_settings.sound_choice if alert_settings else 'bell',
        alert_volume=alert_settings.volume if alert_settings else 0.8,
        alerts_enabled=alert_settings.enabled if alert_settings else True,
    )


@main_bp.route('/health')
def health_check():
    return {'status': 'ok'}


@main_bp.app_errorhandler(404)
def not_found(_error):
    return render_template('errors/404.html'), 404


@main_bp.app_errorhandler(500)
def server_error(_error):
    return render_template('errors/500.html'), 500
