
import re
import pytesseract

from PIL import Image, ImageEnhance, ImageFilter
from datetime import datetime

# Windows Tesseract path
pytesseract.pytesseract.tesseract_cmd = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe"
)

# Supported date patterns
DATE_PATTERN = re.compile(
    r'(?<!\d)(\d{1,2}[./-]\d{1,2}[./-]\d{2,4}'
    r'|\d{4}[./-]\d{1,2}[./-]\d{1,2}'
    r'|\d{1,2}[/-]\d{4})(?!\d)'
)

EXPIRY_LABELS = (
    "EXP", "EXPIRY", "EXPIRES",
    "USE BY", "BEST BEFORE"
)

MFG_LABELS = (
    "MFG", "MANUFACTURED", "MANUFACTURING"
)
def improve_image(image):
    # Convert image to grayscale
    image = image.convert("L")
    # Increase image size
    image = image.resize(
        (image.width * 2, image.height * 2)
    )
    # Improve contrast and sharpness
    image = ImageEnhance.Contrast(image).enhance(2)
    image = image.filter(ImageFilter.SHARPEN)

    return image


def validate_date(value):

    value = value.strip().replace(".", "/").replace("-", "/")

    # Month and year format: 08/2027
    if re.fullmatch(r"\d{1,2}/\d{4}", value):
        month, year = map(int, value.split("/"))

        if 1 <= month <= 12 and 2000 <= year <= 2100:
            return f"{month:02d}/{year}"

        return None

    # Year first: YYYY/MM/DD
    if re.fullmatch(r"\d{4}/\d{1,2}/\d{1,2}", value):
        formats = ["%Y/%m/%d"]

    # Indian date format: DD/MM/YYYY
    else:
        formats = [
            "%d/%m/%Y",
            "%d/%m/%y"
        ]

    for date_format in formats:
        try:
            date = datetime.strptime(value, date_format)
            return date.strftime("%d-%m-%Y")
        except ValueError:
            continue

    return None


def read_expiry_date(image):

    image = improve_image(image)

    # OCR configuration
    config = "--oem 3 --psm 6"

    text = pytesseract.image_to_string(
        image,
        lang="eng",
        config=config
    )

    print("OCR DETECTED TEXT:")
    print(text)

    lines = text.upper().splitlines()

    # Search for expiry labels first
    for index, line in enumerate(lines):

        # Ignore manufacturing-date lines
        if any(label in line for label in MFG_LABELS):
            continue

        if any(label in line for label in EXPIRY_LABELS):

            # Check the labelled line and next two lines
            nearby_text = " ".join(
                lines[index:index + 3]
            )

            dates = DATE_PATTERN.findall(nearby_text)

            for candidate in dates:
                result = validate_date(candidate)

                if result:
                    return {
                        "success": True,
                        "expiry_date": result,
                        "raw_text": text
                    }

    # Do not randomly select another date
    return {
        "success": False,
        "expiry_date": None,
        "raw_text": text,
        "message": (
            "Expiry date not detected. "
            "Please scan again or enter the date manually."
        )
    }
import pytesseract
from PIL import Image, ImageEnhance, ImageFilter

pytesseract.pytesseract.tesseract_cmd = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe"
)
