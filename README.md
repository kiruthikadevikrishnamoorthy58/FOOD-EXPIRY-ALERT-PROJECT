# Smart Food Expiry Detection and Waste Prevention System

A Flask-based food inventory and expiry tracking web app built for the capstone project brief. It allows users to register and log in, scan food labels, verify detected expiry dates, and manage products in a personal inventory with status-based reminders.

## Features
- Secure user registration and login using hashed passwords
- Automatic sign-in after registration and persistent sign-in across browser restarts until logout or remember-cookie expiration
- Inventory page for each authenticated user
- Expiry status rules based on the current date:
  - Green: more than 2 days remaining
  - Yellow: today or within 2 days
  - Red: expired
- Product scan workflow with OCR-based expiry detection and manual validation step
- Camera scanning on HTTPS-supported browsers, with capture, preview, and retake controls
- Reminder section for soon-to-expire or expired items
- Settings page for alert preferences
- SQLite database for local development
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
4. Start the local development server:
   py -3.12 app.py
5. Open:
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

The blueprint sets `APP_ENV=production`, generates a strong secret key, and trusts the single Render proxy for the forwarded HTTPS scheme. The app marks session cookies secure, redirects HTTP to HTTPS, and sends an HSTS header.

On the scan page, choose **Open Camera** and allow camera permission in your browser. The browser only provides camera access on HTTPS (or localhost during development). On a phone the app requests the rear-facing camera when available. If camera access is blocked or unavailable, use **Or upload an image** instead.

**Free prototype limitations:** the free web service can sleep when idle, and its filesystem is ephemeral. This setup uses SQLite, so user accounts and inventory can be lost when the service restarts or redeploys. Use a persistent database and storage plan before relying on saved data. Do not upload sensitive or important data to the prototype.

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

## Production Notes
This project is a capstone MVP, not a fully audited production service. Before handling real users or food-inventory data, configure a persistent database, backups, OAuth if required, and host-level monitoring and rate limiting. Never share hosting credentials in chat or commit them to the repository.
