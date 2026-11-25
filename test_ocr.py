print("TEST STARTED")

import pytesseract

print("Pytesseract imported successfully")

pytesseract.pytesseract.tesseract_cmd = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe"
)

print("Tesseract Version:")
print(pytesseract.get_tesseract_version())

print("OCR connection successful!")
