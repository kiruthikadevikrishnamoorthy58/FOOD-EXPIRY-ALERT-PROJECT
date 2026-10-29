from datetime import datetime, timezone
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

from . import db


def utc_now():
    return datetime.now(timezone.utc)


class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=utc_now)
    google_id = db.Column(db.String(255), nullable=True)

    products = db.relationship('Product', backref='owner', cascade='all, delete-orphan', lazy=True)
    settings = db.relationship('AlertSettings', backref='user', cascade='all, delete-orphan', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Product(db.Model):
    __tablename__ = 'products'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    product_name = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(80), default='General')
    expiry_date = db.Column(db.Date, nullable=False)
    date_added = db.Column(db.DateTime, default=utc_now)
    ocr_text = db.Column(db.Text, nullable=True)
    confirmation_status = db.Column(db.String(30), default='pending')
    reminder_status = db.Column(db.String(30), default='active')
    notes = db.Column(db.Text, nullable=True)
    storage_location = db.Column(db.String(120), nullable=True)


class AlertSettings(db.Model):
    __tablename__ = 'alert_settings'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    sound_choice = db.Column(db.String(50), default='bell')
    volume = db.Column(db.Float, default=0.5)
    enabled = db.Column(db.Boolean, default=True)
