import os
import secrets
import csv
import io
from datetime import datetime
from flask import Flask, render_template, redirect, url_for, request, flash, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from openpyxl import load_workbook

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'kolfe_secret_key_2026')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///kolfe_coupon.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# ==================== DATABASE MODELS ====================

class Admin(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)

class Merchant(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)

class Employee(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.String(50), unique=True, nullable=False)
    full_name = db.Column(db.String(150), nullable=False)
    sector = db.Column(db.String(100), nullable=False)
    qr_token = db.Column(db.String(100), unique=True, nullable=False, default=lambda: secrets.token_urlsafe(16))
    monthly_allowance = db.Column(db.Float, default=1000.0)
    balance = db.Column(db.Float, default=1000.0)
    last_reset_date = db.Column(db.String(20), default=datetime.now().strftime('%Y-%m'))

class RedemptionLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    employee_name = db.Column(db.String(150), nullable=False)
    employee_id = db.Column(db.String(50), nullable=False)
    merchant_name = db.Column(db.String(80), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

# ==================== AUTHENTICATION DECORATORS ====================

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get('role') != 'admin':
            flash('Please log in as admin to access this page.', 'danger')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def merchant_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get('role') != 'merchant':
            flash('Please log in as merchant to access this page.', 'danger')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# ==================== ROUTES ====================

@app.route('/')
def index():
    if session.get('role') == 'admin':
        return redirect(url_for('admin_dashboard'))
    elif session.get('role') == 'merchant':
        return redirect(url_for('merchant_dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        role = request.form.get('role')

        if role == 'admin':
            admin = Admin.query.filter_by(username=username).first()
            if admin and check_password_hash(admin.password_hash, password):
                session['role'] = 'admin'
                session['username'] = admin.username
                return redirect(url_for('admin_dashboard'))
        elif role == 'merchant':
            merchant = Merchant.query.filter_by(username=username).first()
            if merchant and check_password_hash(merchant.password_hash, password):
                session['role'] = 'merchant'
                session['username'] = merchant.username
                return redirect(url_for('merchant_dashboard'))
        
        flash('Invalid username, password, or role.', 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# --- ADMIN DASHBOARD & MANAGEMENT ---

@app.route('/admin')
@admin_required
def admin_root():
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    total_employees = Employee.query.count()
    total_merchants = Merchant.query.count()
    total_redemptions = RedemptionLog.query.count()
    return render_template('admin.html', total_employees=total_employees, total_merchants=total_merchants, total_redemptions=total_redemptions)

@app.route('/employees')
@admin_required
def employees():
    all_employees = Employee.query.all()
    sectors = db.session.query(Employee.sector.distinct()).all()
    sectors = [s[0] for s in sectors if s[0]]
    return render_template('employees.html', employees=all_employees, sectors=sectors)

@app.route('/add_employee', methods=['GET', 'POST'])
@admin_required
def add_employee():
    if request.method == 'POST':
        emp_id = request.form.get('employee_id')
        full_name = request.form.get('full_name')
        sector = request.form.get('sector')
        allowance = float(request.form.get('monthly_allowance', 1000.0))

        if Employee.query.filter_by(employee_id=emp_id).first():
            flash('Employee ID already exists.', 'danger')
            return redirect(url_for('add_employee'))

        new_emp = Employee(
            employee_id=emp_id,
            full_name=full_name,
            sector=sector,
            monthly_allowance=allowance,
            balance=allowance,
            qr_token=secrets.token_urlsafe(16)
        )
        db.session.add(new_emp)
        db.session.commit()
        flash('Employee added successfully.', 'success')
        return redirect(url_for('employees'))
    return render_template('employee_form.html')

@app.route('/upload_employees', methods=['GET', 'POST'])
@admin_required
def upload_employees():
    if request.method == 'POST':
        file = request.files.get('file')
        if not file:
            flash('No file uploaded.', 'danger')
            return redirect(request.url)
        try:
            filename = file.filename.lower()
            if filename.endswith('.xlsx'):
                wb = load_workbook(file)
                sheet = wb.active
                header = [cell.value for cell in sheet[1]]
                id_idx = header.index('employee_id') if 'employee_id' in header else 0
                name_idx = header.index('full_name') if 'full_name' in header else 1
                sector_idx = header.index('sector') if 'sector' in header else 2
                allowance_idx = header.index('monthly_allowance') if 'monthly_allowance' in header else None

                for row in sheet.iter_rows(min_row=2, values_only=True):
                    if not row[id_idx]:
                        continue
                    emp_id = str(row[id_idx])
                    full_name = str(row[name_idx])
                    sector = str(row[sector_idx])
                    allowance = float(row[allowance_idx]) if allowance_idx is not None and row[allowance_idx] is not None else 1000.0

                    if not Employee.query.filter_by(employee_id=emp_id).first():
                        new_emp = Employee(
                            employee_id=emp_id,
                            full_name=full_name,
                            sector=sector,
                            monthly_allowance=allowance,
                            balance=allowance,
                            qr_token=secrets.token_urlsafe(16)
                        )
                        db.session.add(new_emp)
            else:
                stream = io.TextIOWrapper(file.stream, encoding='utf-8')
                reader = csv.DictReader(stream)
                for row in reader:
                    emp_id = str(row.get('employee_id'))
                    if not emp_id:
                        continue
                    if not Employee.query.filter_by(employee_id=emp_id).first():
                        new_emp = Employee(
                            employee_id=emp_id,
                            full_name=str(row.get('full_name')),
                            sector=str(row.get('sector')),
                            monthly_allowance=float(row.get('monthly_allowance', 1000.0)),
                            balance=float(row.get('monthly_allowance', 1000.0)),
                            qr_token=secrets.token_urlsafe(16)
                        )
                        db.session.add(new_emp)
            db.session.commit()
            flash('Employees uploaded successfully.', 'success')
            return redirect(url_for('employees'))
        except Exception as e:
            flash(f'Error processing file: {e}', 'danger')
    return render_template('upload.html')

@app.route('/bulk_delete_employees', methods=['POST'])
@admin_required
def bulk_delete_employees():
    selected_ids = request.form.getlist('selected_ids')
    sector_to_delete = request.form.get('sector_to_delete')

    if sector_to_delete:
        Employee.query.filter_by(sector=sector_to_delete).delete()
        flash(f'All employees in sector "{sector_to_delete}" deleted.', 'success')
    elif selected_ids:
        Employee.query.filter(Employee.id.in_(selected_ids)).delete(synchronize_session=False)
        flash('Selected employees deleted successfully.', 'success')
    else:
        flash('No employees or sector selected for deletion.', 'warning')
    
    db.session.commit()
    return redirect(url_for('employees'))

@app.route('/print_single_card/<int:emp_id>')
@admin_required
def print_single_card(emp_id):
    emp = Employee.query.get_or_404(emp_id)
    return render_template('standalone_qr_print.html', employees=[emp])

@app.route('/standalone_qr')
@admin_required
def standalone_qr():
    all_employees = Employee.query.all()
    return render_template('standalone_qr_print.html', employees=all_employees)

# --- MERCHANT MANAGEMENT ROUTES ---

@app.route('/merchants')
@admin_required
def merchants():
    all_merchants = Merchant.query.all()
    return render_template('merchants.html', merchants=all_merchants)

@app.route('/create_merchant', methods=['GET', 'POST'])
@admin_required
def create_merchant():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        if Merchant.query.filter_by(username=username).first():
            flash('Merchant username already exists.', 'danger')
            return redirect(url_for('create_merchant'))

        new_merchant = Merchant(
            username=username,
            password_hash=generate_password_hash(password)
        )
        db.session.add(new_merchant)
        db.session.commit()
        flash('Merchant created successfully.', 'success')
        return redirect(url_for('merchants'))
    return render_template('create_merchant.html')

@app.route('/reset_merchant_password/<int:merchant_id>', methods=['POST'])
@admin_required
def reset_merchant_password(merchant_id):
    merchant = Merchant.query.get_or_404(merchant_id)
    new_password = secrets.token_hex(4)
    merchant.password_hash = generate_password_hash(new_password)
    db.session.commit()
    flash(f'Password reset for {merchant.username}. New temporary password: {new_password}', 'success')
    return redirect(url_for('merchants'))

@app.route('/delete_merchant/<int:merchant_id>', methods=['POST'])
@admin_required
def delete_merchant(merchant_id):
    merchant = Merchant.query.get_or_404(merchant_id)
    db.session.delete(merchant)
    db.session.commit()
    flash('Merchant deleted successfully.', 'success')
    return redirect(url_for('merchants'))

# --- MERCHANT DASHBOARD (REDEMPTION) ---

@app.route('/merchant/dashboard', methods=['GET', 'POST'])
@merchant_required
def merchant_dashboard():
    if request.method == 'POST':
        qr_token = request.form.get('qr_token')
        employee = Employee.query.filter_by(qr_token=qr_token).first()

        if not employee:
            flash('Invalid QR token or employee not found.', 'danger')
            return redirect(url_for('merchant_dashboard'))

        redemption_amount = 200.0  # Default coupon deduction per scan
        if employee.balance < redemption_amount:
            flash(f'Insufficient balance! Employee balance is {employee.balance} ETB.', 'danger')
            return redirect(url_for('merchant_dashboard'))

        employee.balance -= redemption_amount
        log = RedemptionLog(
            employee_name=employee.full_name,
            employee_id=employee.employee_id,
            merchant_name=session.get('username'),
            amount=redemption_amount
        )
        db.session.add(log)
        db.session.commit()

        flash(f'Successfully redeemed {redemption_amount} ETB for {employee.full_name}. Remaining balance: {employee.balance} ETB', 'success')
        return redirect(url_for('merchant_dashboard'))

    return render_template('merchant.html')

# ==================== INITIALIZE APP ====================

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        if not Admin.query.filter_by(username='admin').first():
            default_admin = Admin(
                username='admin',
                password_hash=generate_password_hash('admin123')
            )
            db.session.add(default_admin)
            db.session.commit()
    app.run(debug=True)