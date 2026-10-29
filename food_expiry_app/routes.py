import os
import uuid
from datetime import date

from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for
from flask_login import login_required, login_user, logout_user, current_user
from werkzeug.utils import secure_filename

from . import db, login_manager
from .forms import AlertSettingsForm, LoginForm, ProductForm, SignupForm
from .models import AlertSettings, Product, User
from .utils import extract_ocr_text_from_image, find_best_expiry_date, get_expiry_status, normalize_email, parse_date


auth_bp = Blueprint('auth', __name__)
main_bp = Blueprint('main', __name__)


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


@auth_bp.route('/signup', methods=['GET', 'POST'])
def signup():
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
    return render_template('landing.html')


@main_bp.route('/dashboard')
@login_required
def dashboard():
    products = Product.query.filter_by(user_id=current_user.id).order_by(Product.date_added.desc()).all()
    totals = {
        'total': len(products),
        'fresh': sum(1 for p in products if get_expiry_status(p.expiry_date)['label'] == 'Within Date'),
        'soon': sum(1 for p in products if get_expiry_status(p.expiry_date)['label'] == 'Expiring Soon'),
        'expired': sum(1 for p in products if get_expiry_status(p.expiry_date)['label'] == 'Expired'),
    }
    recent = products[:5]
    return render_template('dashboard/dashboard.html', products=products, totals=totals, recent=recent)


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
            ocr_text = extract_ocr_text_from_image(uploaded_path)
            expiry_date = find_best_expiry_date(ocr_text)
            session['pending_scan'] = {
                'ocr_text': ocr_text,
                'expiry_date': expiry_date.isoformat() if expiry_date else None,
                'product_name': request.form.get('product_name', '').strip() or 'Unknown product',
                'category': request.form.get('category', 'General').strip() or 'General',
                'storage_location': request.form.get('storage_location', '').strip(),
                'notes': request.form.get('notes', '').strip(),
            }
            if expiry_date:
                flash('Please verify the expiry date detected by the system. Is this date correct?', 'info')
            else:
                flash('No valid expiry date was detected. Please review the text and correct it manually.', 'warning')
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
            expiry_date = parse_date(request.form.get('expiry_date'))
            if not expiry_date:
                flash('Invalid expiry date. Please enter a valid date.', 'danger')
                return render_template('scanner/verify_scan.html', pending=pending)
            product = Product(
                user_id=current_user.id,
                product_name=product_name,
                category=request.form.get('category', pending.get('category', 'General')).strip() or 'General',
                expiry_date=expiry_date,
                ocr_text=request.form.get('ocr_text', pending.get('ocr_text', '')),
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

        if action == 'rescan':
            session.pop('pending_scan', None)
            return redirect(url_for('main.scan_product'))

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

    filtered = []
    for product in products:
        status = get_expiry_status(product.expiry_date)['label']
        if filter_status == 'all' or filter_status == status.lower().replace(' ', '_'):
            filtered.append(product)
    today = date.today()
    return render_template('inventory/inventory.html', products=filtered, filter_status=filter_status, sort_by=sort_by, search=search, today=today)


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
        settings_record = AlertSettings(user_id=current_user.id, sound_choice='bell', volume=0.5, enabled=True)
        db.session.add(settings_record)
        db.session.commit()
    form = AlertSettingsForm(obj=settings_record)
    if form.validate_on_submit():
        settings_record.sound_choice = form.sound_choice.data
        settings_record.volume = form.volume.data
        settings_record.enabled = bool(form.enabled.data)
        db.session.commit()
        flash('Settings saved successfully.', 'success')
        return redirect(url_for('main.settings'))
    return render_template('settings/settings.html', form=form, settings=settings_record)


@main_bp.route('/profile')
@login_required
def profile():
    return render_template('profile/profile.html', user=current_user)


@main_bp.route('/reminders')
@login_required
def reminders():
    products = Product.query.filter_by(user_id=current_user.id).all()
    items = []
    for product in products:
        status = get_expiry_status(product.expiry_date)
        if status['label'] in {'Expiring Soon', 'Expired'}:
            items.append({'product': product, 'status': status})
    return render_template('alerts/reminders.html', items=items)


@main_bp.route('/health')
def health_check():
    return {'status': 'ok'}


@main_bp.app_errorhandler(404)
def not_found(_error):
    return render_template('errors/404.html'), 404


@main_bp.app_errorhandler(500)
def server_error(_error):
    return render_template('errors/500.html'), 500
