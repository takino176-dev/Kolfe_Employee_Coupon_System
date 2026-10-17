# Kolfe Employee Coupon System
Bilingual starter web app for a single merchant and 15,000+ employee records.

## Included
- Admin, merchant, employee roles
- English/Amharic language switch for main navigation and login
- Single employee creation and bulk XLSX/CSV import
- Permanent opaque QR token per employee
- Monthly allocation: working days × daily rate; prepare then release
- Employee balances/history; merchant collection totals/history
- Transaction CSV report; monthly close approval; password reset and forced first-login password change
- Password hashes and CSRF protection; PostgreSQL via DATABASE_URL

## Deploy
1. Upload the contents of this folder to a GitHub repository.
2. In Render, create a Blueprint from the repo (uses render.yaml), or set build command `pip install -r requirements.txt` and start command `gunicorn app:app --workers 2 --threads 4 --timeout 120`.
3. Ensure PostgreSQL is provisioned and `DATABASE_URL` uses its Internal Database URL.
4. Set `SECRET_KEY` to a long random secret.
5. Deploy, then visit `/setup` to create the first admin. This route disables itself once any user exists.
6. Log in and create employees or import a spreadsheet.

## Excel columns
Required `employee_id` (or `id`) and `full_name` (or `name`). Optional `sector` (or `department`) and `username` (defaults to employee ID). Existing IDs/usernames are skipped. Temporary passwords display once after import; store and distribute them securely.

## Local Windows test
Install Python 3.11+, open Command Prompt here, run:
`python -m venv .venv`
`.venv\Scripts\activate`
`pip install -r requirements.txt`
`python app.py`
Open `http://127.0.0.1:5000/setup`.

## Before production
This is a functional starter, not a security-audited financial system. Merchant account creation is not included yet; create the single merchant through a secure administrative database procedure or add a protected merchant-management form before use. Camera scanning is not included: merchant can enter QR token or employee ID. Add database migrations, login rate limits/lockout, security headers, secure password reset delivery, transaction reversal workflow, backups, and tested PostgreSQL concurrency controls. Do not use real employee data until reviewed and tested. Do not commit secrets or employee files to GitHub.
