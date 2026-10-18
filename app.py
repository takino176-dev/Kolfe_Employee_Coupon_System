import os
import secrets
import csv
import io
import openpyxl
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, session, send_file
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'kolfe-secret-key-2026')

# Persistent DB path on Render
db_path = os.path.join('/tmp', 'coupon_system_v7.db')
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
    transactions = db.relationship('Transaction', backref='employee', cascade='all, delete-orphan', lazy=True)

class CouponAllocation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employee.id'), nullable=False)
    month = db.Column(db.String(20), nullable=False)
    amount = db.Column(db.Float, nullable=False, default=0.0)

class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    reference = db.Column(db.String(100), unique=True, nullable=False)
    employee_id = db.Column(db.Integer, db.ForeignKey('employee.id', ondelete='CASCADE'), nullable=False)
    merchant_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    month = db.Column(db.String(20), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    merchant_rel = db.relationship('User', backref='merchant_transactions')

with app.app_context():
    db.create_all()

# Global Error Handler so 500 Internal Server Errors show exact details instead of a blank screen
@app.errorhandler(Exception)
def handle_exception(e):
    return f"<h2 style='color:red; font-family:Arial;'>Application Error:</h2><pre>{str(e)}</pre>", 500

# ================= AUTH & GENERAL ROUTES =================

@app.route('/')
def index():
    if 'user_id' in session:
        role = session.get('role')
        if role in ['admin', 'superadmin']: 
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
            if user.role in ['admin', 'superadmin']: 
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
    flash('Logged out successfully.', 'info')
    return redirect(url_for('login'))

# ================= ADMIN ROUTES =================

@app.route('/dashboard')
@app.route('/admin')
def admin_dashboard():
    if session.get('role') not in ['admin', 'superadmin']:
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
                           allocated=total_allocated, spent=total_spent, collected=total_spent, 
                           transactions=recent_transactions)

@app.route('/employees')
def employees():
    if session.get('role') not in ['admin', 'superadmin']: 
        return redirect(url_for('login'))
    return render_template('employees.html', employees=Employee.query.all())

@app.route('/add_employee', methods=['GET', 'POST'])
def add_employee():
    if session.get('role') not in ['admin', 'superadmin']: 
        return redirect(url_for('login'))
    if request.method == 'POST':
        emp_id = request.form.get('employee_id')
        full_name = request.form.get('full_name')
        sector = request.form.get('sector')
        if Employee.query.filter_by(employee_id=emp_id).first():
            flash('ID exists.', 'danger')
            return redirect(url_for('add_employee'))
        u = User(username=emp_id, password=generate_password_hash(emp_id), role='employee')
        db.session.add(u)
        db.session.flush()
        emp = Employee(employee_id=emp_id, full_name=full_name, sector=sector, qr_token=secrets.token_urlsafe(16), user_id=u.id)
        db.session.add(emp)
        db.session.commit()
        flash('Employee added!', 'success')
        return redirect(url_for('employees'))
    return render_template('employee_form.html')

@app.route('/upload_employees', methods=['GET', 'POST'])
def upload_employees():
    if session.get('role') not in ['admin', 'superadmin']: 
        return redirect(url_for('login'))
    if request.method == 'POST':
        file = request.files.get('file')
        if file:
            try:
                wb = openpyxl.load_workbook(io.BytesIO(file.read()))
                sheet = wb.active
                rows = list(sheet.iter_rows(values_only=True))
                for row in rows[1:]:
                    if row and row[0]:
                        e_id = str(row[0]).strip()
                        if not Employee.query.filter_by(employee_id=e_id).first():
                            u = User(username=e_id, password=generate_password_hash(e_id), role='employee')
                            db.session.add(u)
                            db.session.flush()
                            db.session.add(Employee(employee_id=e_id, full_name=str(row[1]), sector=str(row[2]), qr_token=secrets.token_urlsafe(16), user_id=u.id))
                db.session.commit()
                flash('Uploaded successfully!', 'success')
            except Exception as e:
                flash(f'Error: {str(e)}', 'danger')
        return redirect(url_for('employees'))
    return render_template('upload.html')

@app.route('/print_cards')
def print_cards():
    if session.get('role') not in ['admin', 'superadmin']: 
        return redirect(url_for('login'))
    return render_template('print_cards.html', employees=Employee.query.all())

@app.route('/qrlist')
def qrlist():
    if session.get('role') not in ['admin', 'superadmin']: 
        return redirect(url_for('login'))
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['employee_id', 'full_name', 'sector', 'qr_token'])
    for emp in Employee.query.all():
        writer.writerow([emp.employee_id, emp.full_name, emp.sector, emp.qr_token])
    byte_output = io.BytesIO(output.getvalue().encode('utf-8'))
    output.close()
    return send_file(byte_output, mimetype='text/csv', download_name='employee_qr_list.csv', as_attachment=True)

@app.route('/reports')
@app.route('/reports_csv')
def reports_csv():
    if session.get('role') not in ['admin', 'superadmin']:
        return redirect(url_for('login'))
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['ID', 'Reference', 'Amount', 'Date'])
    for t in Transaction.query.all():
        writer.writerow([t.id, t.reference, t.amount, t.created_at])
    byte_output = io.BytesIO(output.getvalue().encode('utf-8'))
    output.close()
    return send_file(byte_output, mimetype='text/csv', download_name='transactions_report.csv', as_attachment=True)

@app.route('/allocations', methods=['GET', 'POST'])
def allocations():
    if session.get('role') not in ['admin', 'superadmin']: 
        return redirect(url_for('login'))
    month = request.args.get('month', datetime.utcnow().strftime('%Y-%m'))
    if request.method == 'POST':
        amount = float(request.form.get('amount', 0))
        for emp in Employee.query.all():
            alloc = CouponAllocation.query.filter_by(employee_id=emp.id, month=month).first()
            if alloc: 
                alloc.amount = amount
            else: 
                db.session.add(CouponAllocation(employee_id=emp.id, month=month, amount=amount))
        db.session.commit()
        flash('Allocated!', 'success')
    return render_template('allocations.html', employees=Employee.query.all(), month=month)

@app.route('/close_month')
def close_month():
    if session.get('role') not in ['admin', 'superadmin']: 
        return redirect(url_for('login'))
    flash('Month closed successfully.', 'info')
    return redirect(url_for('admin_dashboard'))

@app.route('/create_merchant', methods=['GET', 'POST'])
def create_merchant():
    if session.get('role') not in ['admin', 'superadmin']: 
        return redirect(url_for('login'))
    if request.method == 'POST':
        db.session.add(User(username=request.form.get('username'), password=generate_password_hash(request.form.get('password')), role='merchant'))
        db.session.commit()
        flash('Merchant created!', 'success')
        return redirect(url_for('admin_dashboard'))
    return render_template('create_merchant.html')

@app.route('/reset_password/<int:employee_id>', methods=['POST'])
def reset_password(employee_id):
    if session.get('role') not in ['admin', 'superadmin']: 
        return redirect(url_for('login'))
    emp = Employee.query.get_or_404(employee_id)
    if emp.user:
        emp.user.password = generate_password_hash(request.form.get('new_password'))
        db.session.commit()
        flash('Password reset!', 'success')
    return redirect(url_for('employees'))

# ================= EMPLOYEE PORTAL =================

@app.route('/employee/dashboard')
def employee_dashboard():
    if session.get('role') != 'employee': 
        return redirect(url_for('login'))
    user = User.query.get(session.get('user_id'))
    emp = user.employee_profile
    month = datetime.utcnow().strftime('%Y-%m')
    alloc = CouponAllocation.query.filter_by(employee_id=emp.id, month=month).first()
    allocated = alloc.amount if alloc else 0.0
    spent = sum(t.amount for t in Transaction.query.filter_by(employee_id=emp.id, month=month).all())
    return render_template('employee_dashboard.html', emp=emp, allocated=allocated, spent=spent, balance=allocated-spent, transactions=Transaction.query.filter_by(employee_id=emp.id).all(), month=month)

@app.route('/employee/change_password', methods=['POST'])
def employee_change_password():
    if session.get('role') != 'employee': 
        return redirect(url_for('login'))
    User.query.get(session.get('user_id')).password = generate_password_hash(request.form.get('new_password'))
    db.session.commit()
    flash('Password updated.', 'success')
    return redirect(url_for('employee_dashboard'))

# ================= MERCHANT PORTAL =================

@app.route('/merchant/dashboard')
def merchant_dashboard():
    if session.get('role') != 'merchant': 
        return redirect(url_for('login'))
    month = datetime.utcnow().strftime('%Y-%m')
    txs = Transaction.query.filter_by(merchant_id=session.get('user_id'), month=month).all()
    return render_template('merchant.html', transactions=txs, total_collected=sum(t.amount for t in txs), month=month)

@app.route('/merchant/scan', methods=['POST'])
def merchant_scan():
    if session.get('role') != 'merchant': 
        return redirect(url_for('login'))
    token = request.form.get('qr_token')
    amount = float(request.form.get('amount', 0))
    month = datetime.utcnow().strftime('%Y-%m')
    emp = Employee.query.filter_by(qr_token=token).first()
    if not emp:
        flash('Invalid QR.', 'danger')
        return redirect(url_for('merchant_dashboard'))
    alloc = CouponAllocation.query.filter_by(employee_id=emp.id, month=month).first()
    allocated = alloc.amount if alloc else 0.0
    spent = sum(t.amount for t in Transaction.query.filter_by(employee_id=emp.id, month=month).all())
    if amount > (allocated - spent):
        flash('Insufficient balance!', 'danger')
        return redirect(url_for('merchant_dashboard'))
    db.session.add(Transaction(reference=secrets.token_hex(6).upper(), employee_id=emp.id, merchant_id=session.get('user_id'), amount=amount, month=month))
    db.session.commit()
    flash('Redeemed successfully!', 'success')
    return redirect(url_for('merchant_dashboard'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)