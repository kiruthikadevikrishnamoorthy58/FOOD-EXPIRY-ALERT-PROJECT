import calendar
import os
import re
from datetime import date, datetime, timedelta

import pytesseract
from PIL import Image, ImageEnhance, ImageFilter, ImageOps


KEYWORDS = (
    r'\bEXP(?:IRY|IRATION|IRES?)?\b',
    r'\bUSE[\s-]+BY\b',
    r'\bBEST[\s-]+BEFORE\b',
    r'\bSELL[\s-]+BY\b',
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
    numeric_date = re.fullmatch(
        r'(\d{1,2})\s*[./-]\s*(\d{1,2})\s*[./-]\s*(\d{2,4})',
        text,
    )
    if numeric_date:
        first, second, raw_year = numeric_date.groups()
        year = int(raw_year)
        if len(raw_year) == 2:
            year += 2000
        for month, day in ((int(second), int(first)), (int(first), int(second))):
            try:
                return date(year, month, day)
            except ValueError:
                continue
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
        scale = min(3, 1800 / max(image.size))
        if scale != 1:
            image = image.resize(
                (round(image.width * scale), round(image.height * scale)),
                Image.Resampling.LANCZOS,
            )
        grayscale = ImageOps.autocontrast(image.convert('L'))
        enhanced = ImageEnhance.Contrast(grayscale).enhance(1.7).filter(ImageFilter.SHARPEN)

        def read_text(source, config):
            return pytesseract.image_to_string(source, config=config, timeout=3)

        results = [read_text(enhanced, '--oem 3 --psm 11')]
        if find_best_expiry_date(results[0]):
            return results[0].strip()

        center = enhanced.crop((
            round(enhanced.width * 0.12),
            round(enhanced.height * 0.2),
            round(enhanced.width * 0.88),
            round(enhanced.height * 0.8),
        ))
        center_scale = min(4, 2200 / max(center.size))
        if center_scale != 1:
            center = center.resize(
                (round(center.width * center_scale), round(center.height * center_scale)),
                Image.Resampling.LANCZOS,
            )
        center = ImageOps.autocontrast(center)
        center = ImageEnhance.Contrast(center).enhance(1.5).filter(
            ImageFilter.UnsharpMask(radius=2, percent=150, threshold=3)
        )
        results.append(read_text(
            center,
            '--oem 3 --psm 11 -c tessedit_char_whitelist=0123456789OQDIl|./-',
        ))
        return '\n'.join(dict.fromkeys(text.strip() for text in results if text.strip()))
    except pytesseract.TesseractNotFoundError as error:
        raise OCRProcessingError(
            'The OCR engine is unavailable. Enter the date manually or install Tesseract OCR.'
        ) from error
    except (OSError, ValueError, RuntimeError, pytesseract.TesseractError) as error:
        raise OCRProcessingError(
            'The photo could not be read quickly. Try a close, sharp photo with the expiry date centered, or enter it manually.'
        ) from error


def _date_candidates(text, allow_space=False):
    year_first = re.compile(
        r'(?<![A-Za-z0-9])(\d{4})\s*[./-]\s*(\d{1,2})\s*[./-]\s*(\d{1,2})(?![A-Za-z0-9])'
    )
    for candidate in year_first.finditer(text):
        parsed = parse_date(
            f'{candidate.group(1)}-{candidate.group(2)}-{candidate.group(3)}'
        )
        if parsed:
            yield candidate.start(), parsed

    separator = r'([./-]|\s)' if allow_space else r'([./-])'
    numeric_date = re.compile(
        rf'(?<![A-Za-z0-9])([0-9OQDIl|]{{1,2}})\s*{separator}\s*'
        rf'([0-9OQDIl|]{{1,2}})\s*{separator}\s*([0-9OQDIl|]{{2,4}})(?![A-Za-z0-9])',
        re.IGNORECASE,
    )
    ocr_digit_map = str.maketrans({
        'O': '0', 'o': '0', 'Q': '0', 'q': '0',
        'D': '0', 'd': '0', 'I': '1', 'i': '1',
        'l': '1', '|': '1',
    })
    for candidate in numeric_date.finditer(text):
        value = '/'.join(candidate.group(index).translate(ocr_digit_map) for index in (1, 3, 5))
        parsed = parse_date(value)
        if parsed:
            yield candidate.start(), parsed

    month_year = re.compile(
        r'(?<![A-Za-z0-9./-])(?:'
        r'(0?[1-9]|1[0-2])\s*[./-]\s*((?:[1-9]\d)|20\d{2})|'
        r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(20\d{2})'
        r')(?![A-Za-z0-9./-])',
        re.IGNORECASE,
    )
    for candidate in month_year.finditer(text):
        if candidate.group(1):
            month, year = int(candidate.group(1)), int(candidate.group(2))
            if year < 100:
                year += 2000
        else:
            month = datetime.strptime(candidate.group(3)[:3].title(), '%b').month
            year = int(candidate.group(4))
        yield candidate.start(), date(year, month, calendar.monthrange(year, month)[1])


def find_best_expiry_date(text, allow_unmarked=True):
    if not text:
        return None
    lines = text.splitlines()
    for index, line in enumerate(lines):
        for keyword in KEYWORDS:
            match = re.search(keyword, line, flags=re.IGNORECASE)
            if not match:
                continue
            line_candidates = list(_date_candidates(line[match.end():], allow_space=True))
            if not line_candidates and index + 1 < len(lines):
                line_candidates = list(_date_candidates(lines[index + 1], allow_space=True))
            if line_candidates:
                return line_candidates[0][1]

    if not allow_unmarked:
        return None
    candidates = list(_date_candidates(text))
    if not candidates:
        return None
    return max(candidates, key=lambda candidate: candidate[1])[1]
