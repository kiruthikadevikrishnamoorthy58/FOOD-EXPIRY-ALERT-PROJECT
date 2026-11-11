import calendar
import os
import re
from datetime import date, datetime, timedelta

import pytesseract
from PIL import Image, ImageEnhance, ImageFilter, ImageOps


KEYWORDS = (
    'EXPIRATION', 'EXPIRY', 'EXP DATE', 'EXP', 'USE BY', 'USE-BY',
    'BEST BEFORE', 'BEST-BEFORE', 'SELL BY',
)


class OCRProcessingError(Exception):
    pass


def configure_tesseract():
    command = os.getenv('TESSERACT_CMD', 'tesseract').strip() or 'tesseract'
    if command.lower() == 'tesseract' and os.name == 'nt':
        windows_paths = (
            r'C:\Program Files\Tesseract-OCR\tesseract.exe',
            r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe',
        )
        command = next((path for path in windows_paths if os.path.isfile(path)), command)
    pytesseract.pytesseract.tesseract_cmd = command


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
        raise OCRProcessingError('The uploaded image could not be found. Please take another photo.')
    try:
        configure_tesseract()
        with Image.open(file_path) as source:
            image = ImageOps.exif_transpose(source).convert('RGB')
        scale = min(3, max(1, 1800 / image.width))
        if scale > 1:
            image = image.resize(
                (round(image.width * scale), round(image.height * scale)),
                Image.Resampling.LANCZOS,
            )
        grayscale = ImageOps.autocontrast(image.convert('L'))
        enhanced = ImageEnhance.Contrast(grayscale).enhance(1.7).filter(ImageFilter.SHARPEN)
        thresholded = enhanced.point(lambda pixel: 255 if pixel > 160 else 0)
        results = [
            pytesseract.image_to_string(enhanced, config='--oem 3 --psm 6'),
            pytesseract.image_to_string(thresholded, config='--oem 3 --psm 11'),
        ]
        return '\n'.join(dict.fromkeys(text.strip() for text in results if text.strip()))
    except pytesseract.TesseractNotFoundError as error:
        raise OCRProcessingError(
            'The OCR engine is unavailable. Enter the date manually or install Tesseract OCR.'
        ) from error
    except (OSError, ValueError, pytesseract.TesseractError) as error:
        raise OCRProcessingError(
            'The photo could not be read. Try a brighter, sharper photo or enter the date manually.'
        ) from error


def find_best_expiry_date(text):
    if not text:
        return None
    normalized = text.replace('\n', ' ')
    lower = normalized.lower()
    keyword_matches = [
        (lower.find(keyword.lower()), keyword)
        for keyword in KEYWORDS
        if lower.find(keyword.lower()) != -1
    ]
    match = normalized[min(keyword_matches)[0]:min(keyword_matches)[0] + 250] if keyword_matches else None
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
    month_year = re.search(
        r'\b(0?[1-9]|1[0-2])\s*[/-]\s*(20\d{2})\b',
        match,
    )
    if month_year:
        year, month = int(month_year.group(2)), int(month_year.group(1))
        return date(year, month, calendar.monthrange(year, month)[1])
    named_month_year = re.search(
        r'\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(20\d{2})\b',
        match,
        flags=re.IGNORECASE,
    )
    if named_month_year:
        month = datetime.strptime(named_month_year.group(1)[:3].title(), '%b').month
        year = int(named_month_year.group(2))
        return date(year, month, calendar.monthrange(year, month)[1])
    return None
