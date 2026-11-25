
import pytesseract
from PIL import Image, ImageEnhance

pytesseract.pytesseract.tesseract_cmd = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe"
)

# Open food package image
image = Image.open("food.jpg")

# Improve image quality
image = image.convert("L")
image = ImageEnhance.Contrast(image).enhance(2)

# Read text using OCR
detected_text = pytesseract.image_to_string(
    image,
    lang="eng",
    config="--oem 3 --psm 6"
)

print("========== SCANNED TEXT ==========")
print(detected_text)
print("=================================")
