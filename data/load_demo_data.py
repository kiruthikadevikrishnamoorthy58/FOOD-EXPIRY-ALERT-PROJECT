import json
from pathlib import Path

from food_expiry_app import create_app, db
from food_expiry_app.models import Product, User

app = create_app({
    'TESTING': False,
    'SQLALCHEMY_DATABASE_URI': 'sqlite:///food_expiry.db',
    'WTF_CSRF_ENABLED': True,
})

with app.app_context():
    demo_file = Path(__file__).with_name('demo_products.json')
    data = json.loads(demo_file.read_text(encoding='utf-8'))

    user = User.query.filter_by(email='demo@foodexpiry.com').first()
    if user is None:
        user = User(name='Demo User', email='demo@foodexpiry.com')
        user.set_password('demo123')
        db.session.add(user)
        db.session.commit()

    for item in data['products']:
        existing = Product.query.filter_by(user_id=user.id, product_name=item['product_name']).first()
        if not existing:
            product = Product(
                user_id=user.id,
                product_name=item['product_name'],
                category=item['category'],
                expiry_date=item['expiry_date'],
                notes=item['notes'],
                storage_location=item['storage_location'],
                confirmation_status='confirmed',
                reminder_status='active',
            )
            db.session.add(product)

    db.session.commit()
    print('Demo data loaded for demo@foodexpiry.com')
