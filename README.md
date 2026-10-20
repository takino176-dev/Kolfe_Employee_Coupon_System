# Kolfe Employee Coupon, QR & Monthly Budget System

A starter web application for the Kolfe employee coupon workflow. It includes role-based login, employee import, monthly allocations, sector default budgets, QR-backed A4 coupon printing, merchant/authority redemption, employee balance/history, and CSV reporting.

## Included

- Admin, Authority, Merchant and Employee roles.
- Admin pages support English and Amharic labels where relevant.
- Employee creation one-by-one or bulk `.xlsx` / `.csv` import (15,000+ records are supported by paginated lists; use a properly sized PostgreSQL plan for production).
- Permanent QR content is plain text containing only `Full Name`, `ID`, and `Sector`, as requested. The same employee identity QR is embedded in each of the 24 monthly coupon blocks; balances are never stored in the QR. The QR does not contain a balance; balance is read from the database at redemption time.
- A4 print layout: 3 columns × 8 rows = 24 coupons per employee page, sequence #01–#24, editable header/title/month/value, and plain-text identity QR code on each coupon. Merchant redemption includes a live browser-camera scanner powered by html5-qrcode, with manual entry as a fallback.
- Merchant and Authority accounts can redeem only; they cannot create employees or increase allocations.
- Every redemption records employee, operator, amount, timestamp and reference. Employee balance decreases and operator collection increases through the same transaction.
- Ethiopian-calendar month key and expiry calculation use `convertdate`. The scheduled rollover closes prior allocations and creates this month's allocation using the configured sector default. Configure sector defaults before relying on automatic provisioning.
- Passwords are hashed. Users must change temporary passwords on first login; minimum password length is 8 characters.
- Admin reports include sector allocation/spend summaries and CSV transaction export.

## Run locally

Python 3.11+ is recommended.

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# macOS/Linux:
source .venv/bin/activate
pip install -r requirements.txt
```

Set environment variables before starting (recommended):

```bash
export SECRET_KEY='replace-with-a-long-random-secret'
export ADMIN_USERNAME='admin'
export ADMIN_PASSWORD='replace-with-a-strong-password'
python app.py
```

Open `http://127.0.0.1:5000`. If no `ADMIN_PASSWORD` is set, the development fallback is `ChangeMe123!`; change it immediately. Never deploy with the fallback password.

## Deploy to Render + GitHub

1. Create a GitHub repository and upload the files in this ZIP to the repository root.
2. In Render, choose **New + → Blueprint** and connect the repository. Render reads `render.yaml`.
3. Set `ADMIN_PASSWORD` to a strong password in the Render service environment. Set/retain a strong `SECRET_KEY` (Render generates one in the blueprint).
4. Confirm the PostgreSQL database is created and the web service is healthy at `/health`.
5. Log in with the configured `ADMIN_USERNAME` and `ADMIN_PASSWORD`. The first login forces a password change.
6. Import employees, create merchant/authority accounts, configure sector monthly budgets, then allocate the current month's budgets.

If the database is newly provisioned, the application creates its tables on startup. For future schema changes, use database migrations rather than relying on `create_all()`.

## Employee Excel template

Accepted column headers (case-insensitive):

- `Employee ID` or `User ID` or `ID`
- `Full Name` or `Name`
- `Sector` or `Department`

The employee ID becomes the default username. Imported users receive a random temporary password; use **Reset password** in the admin employee table to issue a visible temporary password to the employee. The user must change it on first login.

## Monthly budget setup

1. Open **Sector budgets** and set a default monthly amount for each sector. This default is used when the scheduler provisions an upcoming Ethiopian month.
2. Use **Allocations** to set the current month for one employee or all employees in a sector. Allocations can be adjusted by re-saving the same employee/month; existing spend is preserved.
3. Prior-month balances are closed at the Ethiopian calendar month rollover; the historical allocation and redemption records remain in the database.

The scheduler runs at 00:10 server time. On a production deployment, keep one web worker/process for this initial build so the in-process scheduler is not duplicated. A production-hardening pass should move scheduled work to a separate worker/cron service and add monitoring.

## Redemption

The current portal supports scanning by pasting the QR's JSON text into the QR data box, or entering the employee ID manually. It validates the employee against the database and checks the current month's remaining balance before allowing deduction. A live camera scanner UI is not included in this initial package; add a camera scanner integration before operational rollout if staff must scan directly inside the browser.

## Important production checklist

- Replace development secrets; set `ADMIN_PASSWORD` and `SECRET_KEY` in Render.
- Test with a copy of your real Excel data before importing all employees.
- Confirm the organization's exact coupon header, amount rules and monthly sector defaults.
- Run test redemptions, month-end rollover, CSV exports, and print alignment on the target printer.
- Back up PostgreSQL and restrict administrator accounts. QR codes intentionally contain employee name/ID/sector, so printed cards should be handled as personal information.
- The app is a practical first version, not a formal security audit. Before live financial use, have a developer review concurrency, audit logging, password reset delivery, scanner workflow, and operational monitoring.
