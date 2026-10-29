from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, DateField, TextAreaField, SelectField, FloatField, BooleanField, RadioField
from wtforms.validators import DataRequired, Email, Length, Optional


class SignupForm(FlaskForm):
    name = StringField('Name', validators=[DataRequired(), Length(min=2, max=80)])
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired(), Length(min=6)])


class LoginForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired()])


class AccountProfileForm(FlaskForm):
    name = StringField('Full name', validators=[DataRequired(), Length(min=2, max=80)])
    email = StringField('Email address', validators=[DataRequired(), Email()])
    avatar = RadioField('Choose your avatar', choices=[
        ('🥑', '🥑 Avocado'),
        ('🍓', '🍓 Strawberry'),
        ('🥕', '🥕 Carrot'),
        ('🍋', '🍋 Lemon'),
        ('👩‍🍳', '👩‍🍳 Woman chef'),
        ('👨‍🍳', '👨‍🍳 Man chef'),
        ('👩‍🌾', '👩‍🌾 Woman gardener'),
        ('👨‍🌾', '👨‍🌾 Man gardener'),
    ], validators=[DataRequired()])


class ProductForm(FlaskForm):
    product_name = StringField('Product Name', validators=[DataRequired(), Length(max=200)])
    category = StringField('Category', default='General')
    expiry_date = DateField('Expiry Date', validators=[DataRequired()])
    notes = TextAreaField('Notes', validators=[Optional()])
    storage_location = StringField('Storage Location', validators=[Optional(), Length(max=120)])


class AlertSettingsForm(FlaskForm):
    sound_choice = SelectField('Sound', choices=[('bell', 'Bell'), ('ding', 'Ding'), ('chime', 'Chime')])
    volume = FloatField('Volume', default=0.5)
    enabled = BooleanField('Enable alerts')
