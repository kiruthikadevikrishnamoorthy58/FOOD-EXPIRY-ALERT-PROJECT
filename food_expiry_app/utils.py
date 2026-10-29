import os
import re
from datetime import date, datetime, timedelta

import pytesseract
from PIL import Image, ImageEnhance, ImageFilter


KEYWORDS = ('EXP', 'EXPIRY', 'USE BY', 'USE-BY', 'BEST BEFORE', 'BEST-BEFORE', 'SELL BY', 'PACKED ON', 'MFG', 'MANUFACTURED')


def normalize_email(value):
    return (value or '').strip().lower()


def parse_date(value):
    if value is None:
        return None
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    patterns = [
        '%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y', '%m/%d/%Y', '%m-%d-%Y',
        '%d.%m.%Y', '%d %B %Y', '%d %b %Y', '%B %d, %Y', '%b %d, %Y',
    ]
    for pattern in patterns:
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            pass
    return None


def get_expiry_status(expiry_date):
    today = date.today()
    diff = (expiry_date - today).days
    if expiry_date < today:
        return {'label': 'Expired', 'color': 'red', 'days': diff, 'text': f'{abs(diff)} day(s) overdue'}
    if diff <= 2:
        return {'label': 'Expiring Soon', 'color': 'yellow', 'days': diff, 'text': f'{diff} day(s) remaining'}
    return {'label': 'Within Date', 'color': 'green', 'days': diff, 'text': f'{diff} day(s) remaining'}


def extract_ocr_text_from_image(file_path):
    if not os.path.exists(file_path):
        return ''
    try:
        image = Image.open(file_path)
        image = image.convert('RGB')
        image = image.resize((image.width * 2, image.height * 2))
        image = image.convert('L')
        image = ImageEnhance.Contrast(image).enhance(2.0)
        image = image.filter(ImageFilter.SHARPEN)
        text = pytesseract.image_to_string(image, config='--psm 6')
        return text
    except Exception:
        return ''


def find_best_expiry_date(text):
    if not text:
        return None
    normalized = text.replace('\n', ' ')
    lower = normalized.lower()
    match = None
    for keyword in KEYWORDS:
        idx = lower.find(keyword.lower())
        if idx != -1:
            tail = normalized[idx:idx + 250]
            match = tail
            break
    if not match:
        match = normalized
    date_patterns = [
        r'\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b',
        r'\b\d{4}[/-]\d{1,2}[/-]\d{1,2}\b',
        r'\b\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{2,4}\b',
        r'\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},\s*\d{2,4}\b',
    ]
    for pattern in date_patterns:
        dates = re.findall(pattern, match, flags=re.IGNORECASE)
        if dates:
            for value in dates:
                parsed = parse_date(value)
                if parsed:
                    return parsed
    return None
