from food_expiry_app import create_app

app = create_app()

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=False)
from flask import Flask, request, render_template
from PIL import Image
from expiry_ocr import read_expiry_date

app = Flask(__name__)
@app.route("/scan", methods=["GET", "POST"])
def scan():

    result = None

    if request.method == "POST":

        uploaded_file = request.files.get("image")

        if uploaded_file and uploaded_file.filename:

            image = Image.open(uploaded_file.stream)

            result = read_expiry_date(image)

    return render_template(
        "scan.html",
        result=result
    )
if __name__ == "__main__":
    app.run(debug=True)