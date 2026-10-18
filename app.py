import os
import secrets
import csv
import io
import openpyxl
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'kolfe-secret-key-2026')

# SQLite Database setup
db_path = os.path.join('/tmp', 'coupon_system.db')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', f'sqlite:///{db_path}')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# ================= DATABASE MODELS =================

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), nullable=False)  # 'admin', 'merchant', 'employee'

class Employee(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.String(50), unique=True, nullable=False)
    full_name = db.Column(db.String(120), nullable=False)
    sector = db.Column(db.String(120), nullable=False)
    qr_token = db.Column(db.String(100), unique=True, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    user = db.relationship('User', backref='employee_profile', uselist=False)

class CouponAllocation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employee.id'), nullable=False)
    month = db.Column(db.String(20), nullable=False)  # e.g., '2026-10'
    amount = db.Column(db.Float, nullable=False, default=0.0)

class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    reference = db.Column(db.String(100), unique=True, nullable=False)
    employee_id = db.Column(db.Integer, db.ForeignKey('employee.id'), nullable=False)
    merchant_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    month = db.Column(db.String(20), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    employee_rel = db.relationship('Employee', backref='transactions')
    merchant_rel = db.relationship('User', backref='merchant_transactions')

with app.app_context():
    db.create_all()

# ================= AUTH & GENERAL ROUTES =================

@app.route('/')
def index():
    if 'user_id' in session:
        role = session.get('role')
        if role == 'admin':
            return redirect(url_for('admin_dashboard'))
        elif role == 'merchant':
            return redirect(url_for('merchant_dashboard'))
        elif role == 'employee':
            return redirect(url_for('employee_dashboard'))
    return redirect(url_for('login'))

@app.route('/setup', methods=['GET', 'POST'])
def setup():
    if User.query.filter_by(role='admin').first():
        flash('Admin already exists. Please log in.', 'info')
        return redirect(url_for('login'))
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        if username and password:
            admin = User(username=username, password=generate_password_hash(password), role='admin')
            db.session.add(admin)
            db.session.commit()
            flash('Admin account created successfully!', 'success')
            return redirect(url_for('login'))
    return render_template('setup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            session['user_id'] = user.id
            session['username'] = user.username
            session['role'] = user.role
            flash('Logged in successfully.', 'success')
            if user.role == 'admin':
                return redirect(url_for('admin_dashboard'))
            elif user.role == 'merchant':
                return redirect(url_for('merchant_dashboard'))
            elif user.role == 'employee':
                return redirect(url_for('employee_dashboard'))
        flash('Invalid username or password.', 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out.', 'info')
    return redirect(url_for('login'))

# ================= ADMIN ROUTES =================

@app.route('/dashboard')
def admin_dashboard():
    if session.get('role') != 'admin':
        flash('Unauthorized.', 'danger')
        return redirect(url_for('login'))
    
    month = request.args.get('month', datetime.utcnow().strftime('%Y-%m'))
    employees_count = Employee.query.count()
    
    allocations = CouponAllocation.query.filter_by(month=month).all()
    total_allocated = sum(a.amount for a in allocations)
    
    transactions = Transaction.query.filter_by(month=month).all()
    total_spent = sum(t.amount for t in transactions)
    
    recent_transactions = Transaction.query.order_by(Transaction.created_at.desc()).limit(10).all()
    
    return render_template('admin.html', month=month, employees=employees_count, 
                           allocated=total_allocated, spent=total_spent, 
                           transactions=recent_transactions)

@app.route('/employees')
def employees():
    if session.get('role') != 'admin':
        flash('Unauthorized.', 'danger')
        return redirect(url_for('login'))
    all_employees = Employee.query.all()
    return render_template('employees.html', employees=all_employees)

@app.route('/add_employee', methods=['GET', 'POST'])
def add_employee():
    if session.get('role') != 'admin':
        flash('Unauthorized.', 'danger')
        return redirect(url_for('login'))
    if request.method == 'POST':
        emp_id = request.form.get('employee_id')
        full_name = request.form.get('full_name')
        sector = request.form.get('sector')
        password = request.form.get('password') or emp_id
        
        if Employee.query.filter_by(employee_id=emp_id).first():
            flash('Employee ID already exists.', 'danger')
            return redirect(url_for('add_employee'))
        
        user = User(username=emp_id, password=generate_password_hash(password), role='employee')
        db.session.add(user)
        db.session.flush()
        
        emp = Employee(employee_id=emp_id, full_name=full_name, sector=sector, 
                       qr_token=secrets.token_urlsafe(16), user_id=user.id)
        db.session.add(emp)
        db.session.commit()
        flash('Employee added successfully with login access!', 'success')
        return redirect(url_for('employees'))
    return render_template('employee_form.html')

@app.route('/upload_employees', methods=['GET', 'POST'])
def upload_employees():
    if session.get('role') != 'admin':
        flash('Unauthorized.', 'danger')
        return redirect(url_for('login'))
    if request.method == 'POST':
        file = request.files.get('file')
        if file:
            filename = file.filename.lower()
            try:
                if filename.endswith('.xlsx') or filename.endswith('.xls'):
                    wb = openpyxl.load_workbook(io.BytesIO(file.read()))
                    sheet = wb.active
                    rows = list(sheet.iter_rows(values_only=True))
                    if not rows or len(rows) < 2:
                        flash('File is empty.', 'danger')
                        return redirect(url_for('upload_employees'))
                    header = [str(h).strip().lower() if h else '' for h in rows[0]]
                    id_i = header.index('employee_id') if 'employee_id' in header else 0
                    name_i = header.index('full_name') if 'full_name' in header else 1
                    sec_i = header.index('sector') if 'sector' in header else 2
                    
                    for row in rows[1:]:
                        if not row or not row[id_i]: continue
                        e_id = str(row[id_i]).strip()
                        if not Employee.query.filter_by(employee_id=e_id).first():
                            u = User(username=e_id, password=generate_password_hash(e_id), role='employee')
                            db.session.add(u)
                            db.session.flush()
                            emp = Employee(employee_id=e_id, full_name=str(row[name_i]).strip(), 
                                           sector=str(row[sec_i]).strip(), qr_token=secrets.token_urlsafe(16), user_id=u.id)
                            db.session.add(emp)
                else:
                    stream = io.TextIOWrapper(file.stream, encoding='utf-8')
                    reader = csv.DictReader(stream)
                    for row in reader:
                        e_id = row.get('employee_id') or row.get('id')
                        if e_id and not Employee.query.filter_by(employee_id=e_id).strip():
                            u = User(username=e_id, password=generate_password_hash(e_id), role='employee')
                            db.session.add(u)
                            db.session.flush()
                            emp = Employee(employee_id=str(e_id).strip(), full_name=row.get('full_name', ''), 
                                           sector=row.get('sector', ''), qr_token=secrets.token_urlsafe(16), user_id=u.id)
                            db.session.add(emp)
                db.session.commit()
                flash('Bulk upload successful! Default password is Employee ID.', 'success')
                return redirect(url_for('employees'))
            except Exception as e:
                flash(f'Error: {str(e)}', 'danger')
        return redirect(url_for('upload_employees'))
    return render_template('upload.html')

@app.route('/print_cards')
def print_cards():
    if session.get('role') != 'admin':
        flash('Unauthorized.', 'danger')
        return redirect(url_for('login'))
    employees = Employee.query.all()
    return render_template('print_cards.html', employees=employees)

@app.route('/allocations', methods=['GET', 'POST'])
def allocations():
    if session.get('role') != 'admin':
        flash('Unauthorized.', 'danger')
        return redirect(url_for('login'))
    month = request.args.get('month', datetime.utcnow().strftime('%Y-%m'))
    if request.method == 'POST':
        amount = float(request.form.get('amount', 0))
        emp_id = request.form.get('employee_id')
        if emp_id == 'all':
            for emp in Employee.query.all():
                alloc = CouponAllocation.query.filter_by(employee_id=emp.id, month=month).first()
                if alloc:
                    alloc.amount = amount
                else:
                    db.session.add(CouponAllocation(employee_id=emp.id, month=month, amount=amount))
            flash(f'Allocated {amount} coupons to ALL employees for {month}.', 'success')
        else:
            alloc = CouponAllocation.query.filter_by(employee_id=emp_id, month=month).first()
            if alloc:
                alloc.amount = amount
            else:
                db.session.add(CouponAllocation(employee_id=int(emp_id), month=month, amount=amount))
            flash('Allocation updated.', 'success')
        db.session.commit()
        return redirect(url_for('allocations', month=month))
    
    employees = Employee.query.all()
    return render_template('allocations.html', employees=employees, month=month)

@app.route('/create_merchant', methods=['GET', 'POST'])
def create_merchant():
    if session.get('role') != 'admin':
        flash('Unauthorized.', 'danger')
        return redirect(url_for('login'))
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        if User.query.filter_by(username=username).first():
            flash('Username exists.', 'danger')
            return redirect(url_for('create_merchant'))
        merchant = User(username=username, password=generate_password_hash(password), role='merchant')
        db.session.add(merchant)
        db.session.commit()
        flash('Merchant created successfully!', 'success')
        return redirect(url_for('admin_dashboard'))
    return render_template('create_merchant.html')

@app.route('/reset_password/<int:employee_id>', methods=['POST'])
def reset_password(employee_id):
    if session.get('role') != 'admin':
        flash('Unauthorized.', 'danger')
        return redirect(url_for('login'))
    emp = Employee.query.get_or_404(employee_id)
    new_pw = request.form.get('new_password')
    if emp.user and new_pw:
        emp.user.password = generate_password_hash(new_pw)
        db.session.commit()
        flash(f'Password reset successfully for {emp.full_name}.', 'success')
    return redirect(url_for('employees'))

# ================= EMPLOYEE PORTAL =================

@app.route('/employee/dashboard')
def employee_dashboard():
    if session.get('role') != 'employee':
        flash('Unauthorized.', 'danger')
        return redirect(url_for('login'))
    user = User.query.get(session.get('user_id'))
    emp = user.employee_profile
    month = datetime.utcnow().strftime('%Y-%m')
    
    allocation = CouponAllocation.query.filter_by(employee_id=emp.id, month=month).first()
    allocated_amt = allocation.amount if allocation else 0.0
    
    spent_amt = sum(t.amount for t in Transaction.query.filter_by(employee_id=emp.id, month=month).all())
    balance = allocated_amt - spent_amt
    
    transactions = Transaction.query.filter_by(employee_id=emp.id).order_by(Transaction.created_at.desc()).all()
    
    return render_template('employee_dashboard.html', emp=emp, allocated=allocated_amt, 
                           spent=spent_amt, balance=balance, transactions=transactions, month=month)

@app.route('/employee/change_password', methods=['POST'])
def employee_change_password():
    if session.get('role') != 'employee':
        return redirect(url_for('login'))
    user = User.query.get(session.get('user_id'))
    new_pw = request.form.get('new_password')
    if new_pw:
        user.password = generate_password_hash(new_pw)
        db.session.commit()
        flash('Password updated successfully.', 'success')
    return redirect(url_for('employee_dashboard'))

# ================= MERCHANT PORTAL =================

@app.route('/merchant/dashboard')
def merchant_dashboard():
    if session.get('role') != 'merchant':
        flash('Unauthorized.', 'danger')
        return redirect(url_for('login'))
    
    month = datetime.utcnow().strftime('%Y-%m')
    merchant_id = session.get('user_id')
    transactions = Transaction.query.filter_by(merchant_id=merchant_id, month=month).all()
    total_collected = sum(t.amount for t in transactions)
    
    return render_template('merchant.html', transactions=transactions, total_collected=total_collected, month=month)

@app.route('/merchant/scan', methods=['POST'])
def merchant_scan():
    if session.get('role') != 'merchant':
        flash('Unauthorized.', 'danger')
        return redirect(url_for('login'))
    
    qr_token = request.form.get('qr_token')
    amount = float(request.form.get('amount', 0))
    month = datetime.utcnow().strftime('%Y-%m')
    
    emp = Employee.query.filter_by(qr_token=qr_token).first()
    if not emp:
        flash('Invalid QR Code / Employee token.', 'danger')
        return redirect(url_for('merchant_dashboard'))
    
    allocation = CouponAllocation.query.filter_by(employee_id=emp.id, month=month).first()
    allocated_amt = allocation.amount if allocation else 0.0
    
    spent_amt = sum(t.amount for t in Transaction.query.filter_by(employee_id=emp.id, month=month).all())
    balance = allocated_amt - spent_amt
    
    if amount > balance:
        flash(f'Insufficient balance! Available balance is {balance:.2f}.', 'danger')
        return redirect(url_for('merchant_dashboard'))
    
    tx = Transaction(
        reference=secrets.token_hex(6).upper(),
        employee_id=emp.id,
        merchant_id=session.get('user_id'),
        amount=amount,
        month=month
    )
    db.session.add(tx)
    db.session.commit()
    flash(f'Successfully redeemed {amount:.2f} coupons for {emp.full_name}!', 'success')
    return redirect(url_for('merchant_dashboard'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)