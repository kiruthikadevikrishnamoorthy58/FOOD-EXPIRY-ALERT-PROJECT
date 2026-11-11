# Smart Food Expiry Detection and Waste Prevention System

A Flask-based food inventory and expiry tracking web app built for the capstone project brief. It allows users to register and log in, scan food labels, verify detected expiry dates, and manage products in a personal inventory with status-based reminders.

## Features
- Secure user registration and login using hashed passwords
- Automatic sign-in after registration and persistent sign-in across browser restarts until logout or remember-cookie expiration
- Editable name, email, and selectable food/person avatar in Settings; one-time registration per email address
- Inventory page for each authenticated user
- Expiry status rules based on the current date:
  - Green: more than 2 days remaining
  - Yellow: today or within 2 days
  - Red: expired
- Product scan workflow with OCR-based expiry detection and manual validation step
- Camera scanning on HTTPS-supported browsers, starting at 1× with adjustable zoom, capture, preview, and retake controls
- OCR date results are shown for confirmation and can be edited before saving; OCR failures explain how to retry or enter the date manually
- Reminder section for soon-to-expire or expired items
- Browser reminder tones with selectable sound and volume; start and acknowledge sounds on the reminders page (no background-alert service)
- Responsive food-tech interface with user-specific dashboard summaries and inventory chart
- Settings page for alert preferences
- SQLite database for local development, PostgreSQL for Render deployment
- Lightweight HTML/CSS templates with responsive layout

## Tech Stack
- Python 3.12
- Flask
- Flask-Login
- Flask-SQLAlchemy
- WTForms
- Pillow
- pytesseract
- SQLite

## Project Structure
- app.py — app entry point
- food_expiry_app/ — Flask application package
- templates/ — HTML templates
- static/ — CSS and frontend assets
- tests/ — basic app validation tests
- data/ — demo data and upload storage

## Local Development (Windows)
1. Install Python 3.12.
2. Open PowerShell in the project folder.
3. Run:
   py -3.12 -m pip install -r requirements.txt
4. Install the Tesseract OCR engine (the `pytesseract` Python package alone is not enough):
   winget install --id UB-Mannheim.TesseractOCR --exact
5. If Tesseract is installed outside `C:\Program Files\Tesseract-OCR\tesseract.exe`, set `TESSERACT_CMD` in `.env` to the full executable path.
6. Restart the Flask app after installing Tesseract, then start the local development server:
   py -3.12 app.py
7. Open:
   http://127.0.0.1:5000

Local development uses HTTP on loopback only. Do not expose this development server to the internet. A public HTTPS website must run on a hosting provider that terminates TLS with a trusted certificate.

## Environment Variables
Copy .env.example to .env and update values if needed:

APP_ENV=development
SECRET_KEY=a-random-secret-at-least-32-characters-long
DATABASE_URL=sqlite:///food_expiry.db

Generate a secret with:

py -3.12 -c "import secrets; print(secrets.token_urlsafe(48))"

## Public HTTPS Deployment on Render
The repository includes a Render Blueprint (`render.yaml`) and a Dockerfile that installs Tesseract OCR. To publish:

1. Push the project to a GitHub repository.
2. Sign in to Render and choose **New → Blueprint**.
3. Connect the GitHub repository containing this project and deploy the blueprint.
4. Wait for the image build and health check to succeed. Render provides the public `https://…onrender.com` address and manages its trusted TLS certificate.

The blueprint sets `APP_ENV=production`, generates a strong secret key, connects the web service to PostgreSQL, and sends an HSTS header. Sign-up logs users in immediately. A signed Flask-Login remember cookie keeps them signed in for 30 days across browser restarts; logging out clears it. JWT is not used because this is a server-rendered website, not a token-authenticated API.

On the scan page, choose **Open Camera** and allow camera permission in your browser. The camera starts at 1×; use the zoom slider only when needed. The browser only provides camera access on HTTPS (or localhost during development). On a phone the app requests the rear-facing camera when available. After capture, choose **Scan date and review** to see and edit the detected date before saving. If camera access is blocked or unavailable, use **Or upload a photo** instead.

**Free prototype limitations:** the free web service can sleep when idle, and its filesystem is ephemeral. PostgreSQL keeps accounts and inventory when the web service sleeps or redeploys, but Render's free Postgres database expires after 30 days. Export or back up data and upgrade to a paid database before that deadline if you need it long-term. Do not use the free prototype for important or sensitive data.

For hosted use, set `DATABASE_URL` to a persistent database supplied by your hosting provider. Without persistent database storage, a host restart or redeploy can remove saved accounts, and users may then need to register again.

## Demo Data
The repository includes demo inventory entries in the data folder and is clearly marked as sample data for testing only.

## Testing
Run the test suite:

py -3.12 -m pytest -q

## Security Notes
- Keep secrets in environment variables
- Avoid committing real credentials
- Use HTTPS in production
- Restrict access to authenticated pages
- Store user records and products per user account
- A website cannot reliably detect when a user uninstalls an installed web app; uninstalling alone may not clear the browser's login cookie.
- Reminder sounds require a user gesture and remain active only while the reminders page is open. Browser and device policies may prevent or interrupt audio.
- Google OAuth and password recovery are not configured in this project; login and signup use email and password.

## Production Notes
This project is a capstone MVP, not a fully audited production service. Before handling real users or food-inventory data, configure a persistent database, backups, OAuth if required, and host-level monitoring and rate limiting. Never share hosting credentials in chat or commit them to the repository.
