import calendar
import math
import os
import re
from datetime import date, datetime, timedelta

import pytesseract
from PIL import Image, ImageEnhance, ImageFilter, ImageOps


KEYWORDS = (
    r'\bEXP(?:IRY|IRATION|IRES?)?\b',
    r'\bUSE[\s-]*(?:B|8|O)[\s-]*[YV]\b',
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


def _expand_year(raw_year):
    year = int(raw_year)
    if len(raw_year) == 2:
        year += 2000 if year <= 49 else 1900
    return year


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
        year = _expand_year(raw_year)
        first, second = int(first), int(second)
        if first > 12 and second <= 12:
            month, day = second, first
        elif second > 12 and first <= 12:
            month, day = first, second
        elif first == second:
            month, day = first, second
        else:
            return None
        try:
            return date(year, month, day)
        except ValueError:
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


def _estimate_skew_angle(rows):
    angles = []
    for row in rows:
        words = sorted(row['words'], key=lambda item: item['left'])
        if len(words) < 3:
            continue
        horizontal_span = words[-1]['left'] - words[0]['left']
        if horizontal_span < 100:
            continue
        vertical_span = words[-1]['top'] - words[0]['top']
        angle = math.degrees(math.atan2(vertical_span, horizontal_span))
        if 0.5 <= abs(angle) <= 7:
            angles.append(angle)
    if not angles:
        return 0
    return sorted(angles)[len(angles) // 2]


def extract_ocr_scan_from_image(file_path):
    if not os.path.exists(file_path):
        raise OCRProcessingError('The uploaded image could not be found. Please take another photo.')
    try:
        configure_tesseract()
        with Image.open(file_path) as source:
            image = ImageOps.exif_transpose(source).convert('RGB')
            if image.width * image.height > 30_000_000:
                raise OCRProcessingError(
                    'This image is too large to scan. Please capture a smaller, focused photo of the date.'
                )

        def prepare(image_to_process, threshold=False, denoise=False):
            grayscale = ImageOps.autocontrast(image_to_process.convert('L'), cutoff=1)
            enhanced = ImageEnhance.Brightness(grayscale).enhance(1.08)
            enhanced = ImageEnhance.Contrast(enhanced).enhance(1.6)
            enhanced = enhanced.filter(ImageFilter.UnsharpMask(radius=1.5, percent=130, threshold=3))
            if denoise:
                enhanced = enhanced.filter(ImageFilter.MedianFilter(size=3))
            if threshold:
                cutoff = _otsu_threshold(enhanced)
                return enhanced.point(lambda pixel: 255 if pixel >= cutoff else 0)
            return enhanced

        def enlarge_for_ocr(image_to_process, max_scale=2.5):
            largest_edge = max(image_to_process.size)
            if largest_edge >= 1600:
                return image_to_process
            scale = min(max_scale, 1600 / largest_edge)
            return image_to_process.resize(
                (round(image_to_process.width * scale), round(image_to_process.height * scale)),
                Image.Resampling.LANCZOS,
            )

        def read_text(image_to_process, config):
            data = pytesseract.image_to_data(
                image_to_process,
                config=config,
                output_type=pytesseract.Output.DICT,
                timeout=3.0,
            )
            words = []
            for index, value in enumerate(data['text']):
                value = value.strip()
                if not value:
                    continue
                left = int(data['left'][index])
                top = int(data['top'][index])
                width = int(data['width'][index])
                height = int(data['height'][index])
                words.append({
                    'text': value,
                    'confidence': float(data['conf'][index]),
                    'left': left,
                    'right': left + width,
                    'top': top,
                    'bottom': top + height,
                    'height': height,
                })

            rows = []
            for word in sorted(words, key=lambda item: (item['top'], item['left'])):
                matching_rows = []
                for row in rows:
                    overlap = min(row['bottom'], word['bottom']) - max(row['top'], word['top'])
                    min_height = min(row['height'], word['height'])
                    if min_height and overlap >= min_height * 0.3:
                        matching_rows.append((overlap / min_height, row))
                if matching_rows:
                    row = max(matching_rows, key=lambda match: match[0])[1]
                    row['words'].append(word)
                    row['top'] = min(row['top'], word['top'])
                    row['bottom'] = max(row['bottom'], word['bottom'])
                    row['height'] = row['bottom'] - row['top']
                else:
                    rows.append({
                        'top': word['top'],
                        'bottom': word['bottom'],
                        'height': word['height'],
                        'words': [word],
                    })

            text_rows = []
            for row in rows:
                row_words = sorted(row['words'], key=lambda item: item['left'])
                parts = []
                previous = None
                for word in row_words:
                    if (previous
                            and re.fullmatch(r'[0-9OQDIl|]+', previous['text'])
                            and re.fullmatch(r'[0-9OQDIl|]+', word['text'])
                            and word['left'] - previous['right'] <= max(previous['height'], word['height'])):
                        parts[-1] += word['text']
                    else:
                        parts.append(word['text'])
                    previous = word
                text_rows.append(' '.join(parts))
            return '\n'.join(text_rows), words, rows

        original_oriented = image.copy()
        results = []
        primary = enlarge_for_ocr(prepare(original_oriented))
        primary_text, _, primary_rows = read_text(primary, '--oem 3 --psm 11')
        if primary_text.strip():
            results.append(primary_text)
        primary_candidates = find_expiry_date_candidates(primary_text)
        primary_has_expiry_label = any(candidate['label'] for candidate in primary_candidates)
        rotation_boxes = (primary, primary_rows)
        skew_angle = _estimate_skew_angle(primary_rows)
        if skew_angle:
            deskewed = original_oriented.rotate(
                skew_angle,
                resample=Image.Resampling.BICUBIC,
                expand=True,
                fillcolor='white',
            )
            deskewed = enlarge_for_ocr(prepare(deskewed))
            deskew_text, _, _ = read_text(deskewed, '--oem 3 --psm 11')
            if deskew_text.strip():
                results.append(deskew_text)
        else:
            deskew_text = ''

        for angle in (270, 90, 180):
            oriented = original_oriented.rotate(angle, expand=True)
            processed = enlarge_for_ocr(prepare(oriented))
            text, _, _ = read_text(processed, '--oem 3 --psm 11')
            if text.strip():
                results.append(text)

        normal = enlarge_for_ocr(prepare(original_oriented))
        text, _, _ = read_text(normal, '--oem 3 --psm 6')
        if text.strip():
            results.append(text)

        if not primary_has_expiry_label:
            for angle in (0, 90):
                oriented = original_oriented.rotate(angle, expand=True) if angle else original_oriented.copy()
                thresholded = enlarge_for_ocr(prepare(oriented, threshold=True, denoise=True))
                text, _, _ = read_text(thresholded, '--oem 3 --psm 11')
                if text.strip():
                    results.append(text)

        crop_image, rows = rotation_boxes
        date_rows = []
        for row in rows:
            row_words = row['words']
            row_text = ' '.join(word['text'] for word in sorted(row_words, key=lambda item: item['left']))
            if re.search(r'\d', row_text) and (
                re.search(r'[./-]', row_text)
                or any(re.search(keyword, row_text, flags=re.IGNORECASE) for keyword in KEYWORDS)
            ):
                date_rows.append(row)

        for row in date_rows[:2]:
            row_words = row['words']
            left = max(0, min(word['left'] for word in row_words) - 30)
            right = min(crop_image.width, max(word['right'] for word in row_words) + 30)
            top = min(crop_image.height - 1, max(0, min(word['top'] for word in row_words) - 24))
            bottom = min(crop_image.height, max(word['bottom'] for word in row_words) + 24)
            if right <= left or bottom <= top:
                continue
            crop = crop_image.crop((left, top, right, bottom))
            crop = enlarge_for_ocr(prepare(crop), max_scale=4)
            text, _, _ = read_text(crop, '--oem 3 --psm 7')
            if text.strip():
                results.append(text)

        full_text = '\n'.join(dict.fromkeys(text.strip() for text in results if text.strip()))
        deskew_candidates = find_expiry_date_candidates(deskew_text)
        if primary_has_expiry_label:
            candidates = primary_candidates
        elif any(candidate['label'] for candidate in deskew_candidates):
            candidates = deskew_candidates
        else:
            candidates = find_expiry_date_candidates(full_text)
        if primary_has_expiry_label:
            for candidate in candidates:
                candidate_line = primary_text[:candidate['position']].count('\n')
                if candidate_line < len(primary_rows):
                    scores = [
                        word['confidence']
                        for word in primary_rows[candidate_line]['words']
                        if word['confidence'] >= 0
                    ]
                else:
                    scores = []
                candidate['ocr_confidence'] = round(sum(scores) / len(scores)) if scores else 0
                if candidate['ocr_confidence'] < 45:
                    candidate['confidence'] = 'review'
        else:
            for candidate in candidates:
                candidate['confidence'] = 'review'
        return full_text, candidates
    except OCRProcessingError:
        raise
    except pytesseract.TesseractNotFoundError as error:
        raise OCRProcessingError(
            'The OCR engine is unavailable. Please install Tesseract OCR or try scanning again later.'
        ) from error
    except Image.DecompressionBombError as error:
        raise OCRProcessingError(
            'This image is too large to scan. Please capture a smaller, focused photo of the date.'
        ) from error
    except RuntimeError as error:
        if 'timeout' in str(error).lower():
            raise OCRProcessingError(
                'Text recognition took too long. Try a closer, clearer photo centered on the expiry date.'
            ) from error
        raise OCRProcessingError(
            'The photo could not be processed. Check that it is a clear JPG or PNG with good lighting, then scan again.'
        ) from error
    except (OSError, ValueError, pytesseract.TesseractError) as error:
        raise OCRProcessingError(
            'The photo could not be processed. Check that it is a clear JPG or PNG with good lighting, then scan again.'
        ) from error


def extract_ocr_text_from_image(file_path):
    text, _ = extract_ocr_scan_from_image(file_path)
    return text


def _date_candidates(text, allow_space=False):
    def numeric_options(first, second, raw_year):
        first = int(first.translate(_OCR_DIGIT_MAP))
        second = int(second.translate(_OCR_DIGIT_MAP))
        year = _expand_year(raw_year.translate(_OCR_DIGIT_MAP))

        if first > 12 and second <= 12:
            interpretations = ((second, first),)
        elif second > 12 and first <= 12:
            interpretations = ((first, second),)
        elif first == second:
            interpretations = ((first, second),)
        else:
            interpretations = ((second, first), (first, second))

        for month, day in interpretations:
            try:
                yield date(year, month, day)
            except ValueError:
                continue

    year_first = re.compile(
        r'(?<![A-Za-z0-9])(\d{4})\s*[./-]\s*(\d{1,2})\s*[./-]\s*(\d{1,2})(?![A-Za-z0-9])'
    )
    for candidate in year_first.finditer(text):
        parsed = parse_date(f'{candidate.group(1)}-{candidate.group(2)}-{candidate.group(3)}')
        if parsed:
            yield candidate.start(), parsed, candidate.group(0)

    separator = r'([./-]|\s)' if allow_space else r'([./-])'
    numeric_date = re.compile(
        rf'(?<![A-Za-z0-9])([0-9OQDIl|]{{1,2}})\s*{separator}\s*'
        rf'([0-9OQDIl|]{{1,2}})\s*{separator}\s*([0-9OQDIl|]{{2,4}})(?![A-Za-z0-9])',
        re.IGNORECASE,
    )
    if allow_space:
        separator_as_one = re.compile(
            r'(?<![A-Za-z0-9])([0-9OQDIl|]{2})1([0-9OQDIl|]{2})1([0-9OQDIl|]{2})(?![A-Za-z0-9])',
            re.IGNORECASE,
        )
        for candidate in separator_as_one.finditer(text):
            for parsed in numeric_options(*(candidate.group(index) for index in (1, 2, 3))):
                yield candidate.start(), parsed, candidate.group(0)

    for candidate in numeric_date.finditer(text):
        for parsed in numeric_options(*(candidate.group(index) for index in (1, 3, 5))):
            yield candidate.start(), parsed, candidate.group(0)

    named_date = re.compile(
        r'(?<![A-Za-z0-9])(?:'
        r'(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*,?\s+(\d{2,4})|'
        r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{1,2}),?\s+(\d{2,4})'
        r')(?![A-Za-z0-9])',
        re.IGNORECASE,
    )
    for candidate in named_date.finditer(text):
        if candidate.group(1):
            day, month_name, raw_year = candidate.group(1), candidate.group(2), candidate.group(3)
        else:
            month_name, day, raw_year = candidate.group(4), candidate.group(5), candidate.group(6)
        year = _expand_year(raw_year)
        try:
            parsed = date(year, datetime.strptime(month_name[:3].title(), '%b').month, int(day))
        except ValueError:
            continue
        yield candidate.start(), parsed, candidate.group(0)

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
                year = _expand_year(candidate.group(2))
        else:
            month = datetime.strptime(candidate.group(3)[:3].title(), '%b').month
            year = int(candidate.group(4))
        parsed = date(year, month, calendar.monthrange(year, month)[1])
        yield candidate.start(), parsed, candidate.group(0)


_OCR_DIGIT_MAP = str.maketrans({
    'O': '0', 'o': '0', 'Q': '0', 'q': '0',
    'D': '0', 'd': '0', 'I': '1', 'i': '1',
    'l': '1', '|': '1',
})


def _otsu_threshold(image):
    histogram = image.histogram()
    total = sum(histogram)
    if not total:
        return 128
    weighted_sum = sum(index * count for index, count in enumerate(histogram))
    background_weight = 0
    background_sum = 0
    best_variance = -1
    threshold = 128
    for level, count in enumerate(histogram):
        background_weight += count
        if not background_weight:
            continue
        foreground_weight = total - background_weight
        if not foreground_weight:
            break
        background_sum += level * count
        background_mean = background_sum / background_weight
        foreground_mean = (weighted_sum - background_sum) / foreground_weight
        variance = background_weight * foreground_weight * (background_mean - foreground_mean) ** 2
        if variance > best_variance:
            best_variance = variance
            threshold = level
    return threshold


def find_expiry_date_candidates(text):
    if not text:
        return []
    lines = text.splitlines(keepends=True)
    if not lines:
        return []

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
        match
        for keyword in KEYWORDS
        for match in re.finditer(keyword, text, flags=re.IGNORECASE)
    ]
    preparation_labels = [
        match
        for keyword in PREPARATION_KEYWORDS
        for match in re.finditer(keyword, text, flags=re.IGNORECASE)
    ]
    expiry_candidates = []
    unmarked_candidates = []

    for position, parsed, raw in _date_candidates(text, allow_space=True):
        candidate_line = line_for_position(position)

        def nearest_label(labels, max_line_distance):
            nearby = [
                (abs(candidate_line - line_for_position(match.start())), abs(position - match.start()), match)
                for match in labels
                if abs(candidate_line - line_for_position(match.start())) <= max_line_distance
            ]
            return min(nearby, default=None, key=lambda item: (item[0], item[1]))

        expiry_match = nearest_label(expiry_labels, 2)
        preparation_match = nearest_label(preparation_labels, 1)
        month_precision = bool(re.fullmatch(
            r'\s*(?:\d{1,2}[./-]\d{2,4}|'
            r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{2,4})\s*',
            raw,
            flags=re.IGNORECASE,
        ))
        if expiry_match and (not preparation_match or expiry_match[:2] < preparation_match[:2]):
            expiry_candidates.append({
                'date': parsed.isoformat(),
                'raw': raw,
                'label': expiry_match[2].group(0),
                'confidence': 'review' if month_precision else 'labelled',
                'precision': 'month' if month_precision else 'day',
                'position': position,
            })
        elif not preparation_match and not expiry_match:
            unmarked_candidates.append({
                'date': parsed.isoformat(),
                'raw': raw,
                'label': '',
                'confidence': 'unlabelled',
                'precision': 'month' if month_precision else 'day',
                'position': position,
            })

    candidates = expiry_candidates or unmarked_candidates
    deduplicated = {}
    for candidate in candidates:
        deduplicated.setdefault(candidate['date'], candidate)
    return list(deduplicated.values())


def find_best_expiry_date(text, allow_unmarked=False):
    candidates = find_expiry_date_candidates(text)
    if len(candidates) != 1:
        return None
    if candidates[0]['precision'] == 'month':
        return None
    if not candidates[0]['label'] and not allow_unmarked:
        return None
    return date.fromisoformat(candidates[0]['date'])
