import calendar
import os
import re
from datetime import date, datetime, timedelta

import pytesseract
from PIL import Image, ImageEnhance, ImageFilter, ImageOps


KEYWORDS = (
    r'\bEXP(?:IRY|IRATION|IRES?)?\b',
    r'\bUSE[\s-]+(?:B|8|O)[\s-]*[YV]\b',
    r'\bUSE\b',
    r'\bBEST[\s-]+BEFORE\b',
    r'\bSELL[\s-]+BY\b',
)
PREPARATION_KEYWORDS = (
    r'\bMFG\b',
    r'\bMFD\b',
    r'\bMANUFACTUR(?:E|ED|ING)\b',
    r'\bPREPARED?\b',
    r'\bPACKED\b',
    r'\bPACKING\b',
    r'\bPKD\b',
    r'\bPROD(?:UCTION)?\b',
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

        def read_text(source, config):
            return pytesseract.image_to_string(source, config=config, timeout=2.5)

        results = []
        for angle in (0, 270, 90, 180):
            oriented = image.rotate(angle, expand=True) if angle else image.copy()
            scale = min(3, 1800 / max(oriented.size))
            if scale != 1:
                oriented = oriented.resize(
                    (round(oriented.width * scale), round(oriented.height * scale)),
                    Image.Resampling.LANCZOS,
                )
            grayscale = ImageOps.autocontrast(oriented.convert('L'))
            enhanced = ImageEnhance.Contrast(grayscale).enhance(1.7).filter(ImageFilter.SHARPEN)
            text = read_text(enhanced, '--oem 3 --psm 11')
            results.append(text)
            if _has_labeled_expiry_date(text):
                return text.strip()

        for angle in (270, 90):
            oriented = image.rotate(angle, expand=True)
            center = oriented.crop((
                round(oriented.width * 0.12),
                round(oriented.height * 0.12),
                round(oriented.width * 0.88),
                round(oriented.height * 0.88),
            ))
            scale = min(3, 2200 / max(center.size))
            if scale != 1:
                center = center.resize(
                    (round(center.width * scale), round(center.height * scale)),
                    Image.Resampling.LANCZOS,
                )
            grayscale = ImageOps.autocontrast(center.convert('L'))
            enhanced = ImageEnhance.Contrast(grayscale).enhance(1.7).filter(ImageFilter.SHARPEN)
            text = read_text(enhanced, '--oem 3 --psm 11')
            results.append(text)
            if _has_labeled_expiry_date(text):
                return text.strip()

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
    if allow_space:
        separator_as_one = re.compile(
            r'(?<![A-Za-z0-9])([0-9OQDIl|]{2})1([0-9OQDIl|]{2})1([0-9OQDIl|]{2})(?![A-Za-z0-9])',
            re.IGNORECASE,
        )
        for candidate in separator_as_one.finditer(text):
            value = '/'.join(candidate.group(index).translate(ocr_digit_map) for index in (1, 2, 3))
            parsed = parse_date(value)
            if parsed:
                yield candidate.start(), parsed

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
    lines = text.splitlines(keepends=True)
    if not lines:
        return None

    line_ranges = []
    offset = 0
    for line in lines:
        line_ranges.append((offset, offset + len(line)))
        offset += len(line)

    def line_for_position(position):
        return next(
            (index for index, (start, end) in enumerate(line_ranges) if start <= position < end),
            len(line_ranges) - 1,
        )

    expiry_labels = [
        match.start()
        for keyword in KEYWORDS
        for match in re.finditer(keyword, text, flags=re.IGNORECASE)
    ]
    preparation_labels = [
        match.start()
        for keyword in PREPARATION_KEYWORDS
        for match in re.finditer(keyword, text, flags=re.IGNORECASE)
    ]
    expiry_candidates = []
    unmarked_candidates = []

    for position, parsed in _date_candidates(text, allow_space=True):
        candidate_line = line_for_position(position)

        def nearest_label(labels, max_line_distance):
            distances = [
                abs(position - label_position)
                for label_position in labels
                if abs(candidate_line - line_for_position(label_position)) <= max_line_distance
            ]
            return min(distances, default=None)

        expiry_distance = nearest_label(expiry_labels, 2)
        preparation_distance = nearest_label(preparation_labels, 1)
        if expiry_distance is not None and (
            preparation_distance is None or expiry_distance < preparation_distance
        ):
            expiry_candidates.append((expiry_distance, parsed))
        elif preparation_distance is None:
            unmarked_candidates.append(parsed)

    if expiry_candidates:
        selected = min(
            expiry_candidates,
            key=lambda candidate: (candidate[0], -candidate[1].toordinal()),
        )
        return selected[1]
    if not allow_unmarked or not unmarked_candidates:
        return None
    return max(unmarked_candidates)


def _has_labeled_expiry_date(text):
    if not text:
        return False
    lines = text.splitlines(keepends=True)
    label_positions = [
        match.start()
        for keyword in KEYWORDS
        for match in re.finditer(keyword, text, flags=re.IGNORECASE)
    ]
    if not label_positions:
        return False
    line_ranges = []
    offset = 0
    for line in lines:
        line_ranges.append((offset, offset + len(line)))
        offset += len(line)

    def line_for_position(position):
        return next(
            (index for index, (start, end) in enumerate(line_ranges) if start <= position < end),
            0,
        )

    return any(
        abs(line_for_position(position) - line_for_position(label)) <= 2
        for position, _ in _date_candidates(text, allow_space=True)
        for label in label_positions
    )
