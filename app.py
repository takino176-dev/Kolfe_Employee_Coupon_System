import os
import secrets
import csv
import io
import openpyxl
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, session, send_file
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
TEMPLATE_DIR = os.path.join(BASE_DIR, 'templates')

app = Flask(__name__, template_folder=TEMPLATE_DIR)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'kolfe-secret-key-2026')

db_path = os.path.join(BASE_DIR, 'coupon_system.db')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', f'sqlite:///{db_path}')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=True)
    role = db.Column(db.String(20), nullable=False)
    is_first_login = db.Column(db.Boolean, default=True)

class Employee(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.String(50), unique=True, nullable=False)
    full_name = db.Column(db.String(120), nullable=False)
    sector = db.Column(db.String(120), nullable=False)
    qr_token = db.Column(db.String(100), unique=True, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    user = db.relationship('User', backref='employee_profiles')
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

@app.template_filter('get_alloc')
def get_alloc_filter(emp_id, month):
    alloc = CouponAllocation.query.filter_by(employee_id=emp_id, month=month).first()
    return alloc.amount if alloc else 0.0

@app.errorhandler(Exception)
def handle_exception(e):
    return f"<h2 style='color:red; font-family:Arial;'>Application Error:</h2><pre>{str(e)}</pre>", 500

# ================= AUTHENTICATION =================

@app.route('/')
def index():
    if 'user_id' in session:
        role = session.get('role')
        if role in ['admin', 'superadmin']: return redirect(url_for('admin_dashboard'))
        elif role == 'merchant': return redirect(url_for('merchant_dashboard'))
        elif role == 'employee': return redirect(url_for('employee_dashboard'))
    if User.query.filter_by(role='admin').first():
        return redirect(url_for('login'))
    return redirect(url_for('setup'))

@app.route('/setup', methods=['GET', 'POST'])
def setup():
    if User.query.filter_by(role='admin').first():
        return redirect(url_for('login'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password')
        if username and password:
            admin = User(username=username, password=generate_password_hash(password), role='admin', is_first_login=False)
            db.session.add(admin)
            db.session.commit()
            flash('Admin account created successfully!', 'success')
            return redirect(url_for('login'))
    return render_template('setup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        
        user = User.query.filter_by(username=username).first()
        if user:
            if user.role == 'employee' and user.is_first_login:
                session['user_id'] = user.id
                session['username'] = user.username
                session['role'] = 'employee'
                flash('First login detected! Please set your new personal password.', 'info')
                return redirect(url_for('employee_change_password'))

            if user.password and check_password_hash(user.password, password):
                session['user_id'] = user.id
                session['username'] = user.username
                session['role'] = user.role
                flash('Logged in successfully.', 'success')
                if user.role in ['admin', 'superadmin']: return redirect(url_for('admin_dashboard'))
                elif user.role == 'merchant': return redirect(url_for('merchant_dashboard'))
                elif user.role == 'employee': return redirect(url_for('employee_dashboard'))
            else:
                flash('Invalid password for this account.', 'danger')
        else:
            flash('Invalid Employee ID or Username.', 'danger')

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out successfully.', 'info')
    return redirect(url_for('login'))

# ================= ADMIN DASHBOARD =================

@app.route('/dashboard')
@app.route('/admin')
def admin_dashboard():
    if session.get('role') not in ['admin', 'superadmin']:
        return redirect(url_for('login'))
    month = request.args.get('month', datetime.utcnow().strftime('%Y-%m'))
    employees_count = Employee.query.count()
    allocations = CouponAllocation.query.filter_by(month=month).all()
    total_allocated = sum(a.amount for a in allocations)
    transactions = Transaction.query.filter_by(month=month).all()
    total_spent = sum(t.amount for t in transactions)
    recent_transactions = Transaction.query.order_by(Transaction.created_at.desc()).limit(10).all()

    merchant_sector_breakdown = {}
    for t in transactions:
        merchant_name = t.merchant_rel.username if t.merchant_rel else 'Unknown Merchant'
        sector_name = t.employee.sector if t.employee and t.employee.sector else 'Unassigned'
        if merchant_name not in merchant_sector_breakdown:
            merchant_sector_breakdown[merchant_name] = {}
        merchant_sector_breakdown[merchant_name][sector_name] = merchant_sector_breakdown[merchant_name].get(sector_name, 0.0) + t.amount

    return render_template('admin.html', month=month, employees=employees_count, 
                           allocated=total_allocated, spent=total_spent, 
                           merchant_sector_breakdown=merchant_sector_breakdown, transactions=recent_transactions)

@app.route('/admin/change_password', methods=['GET', 'POST'])
def admin_change_password():
    if session.get('role') not in ['admin', 'superadmin']: return redirect(url_for('login'))
    if request.method == 'POST':
        new_password = request.form.get('new_password')
        admin = User.query.get(session.get('user_id'))
        if admin and new_password:
            admin.password = generate_password_hash(new_password)
            db.session.commit()
            flash('Admin password updated successfully!', 'success')
            return redirect(url_for('admin_dashboard'))
    return render_template('admin_password.html')

# ================= EMPLOYEE MANAGEMENT =================

@app.route('/employees')
def employees():
    if session.get('role') not in ['admin', 'superadmin']: return redirect(url_for('login'))
    all_emps = Employee.query.all()
    sectors = sorted(list(set(e.sector for e in all_emps if e.sector)))
    return render_template('employees.html', employees=all_emps, sectors=sectors)

@app.route('/add_employee', methods=['GET', 'POST'])
def add_employee():
    if session.get('role') not in ['admin', 'superadmin']: return redirect(url_for('login'))
    if request.method == 'POST':
        emp_id = request.form.get('employee_id', '').strip()
        full_name = request.form.get('full_name', '').strip()
        sector = request.form.get('sector', '').strip()
        
        u = User.query.filter_by(username=emp_id).first()
        if not u:
            u = User(username=emp_id, password=None, role='employee', is_first_login=True)
            db.session.add(u)
            db.session.flush()

        emp = Employee.query.filter_by(employee_id=emp_id).first()
        if emp:
            emp.full_name = full_name
            emp.sector = sector
            emp.user_id = u.id
        else:
            db.session.add(Employee(employee_id=emp_id, full_name=full_name, sector=sector, qr_token=secrets.token_urlsafe(16), user_id=u.id))

        db.session.commit()
        flash(f'Employee {full_name} added successfully!', 'success')
        return redirect(url_for('employees'))
    return render_template('employee_form.html')

@app.route('/bulk_delete_employees', methods=['POST'])
def bulk_delete_employees():
    if session.get('role') not in ['admin', 'superadmin']: return redirect(url_for('login'))
    
    sector_to_delete = request.form.get('sector_to_delete', '').strip()
    selected_ids = request.form.getlist('selected_ids')
    
    deleted_count = 0
    if sector_to_delete:
        emps = Employee.query.filter_by(sector=sector_to_delete).all()
        for emp in emps:
            if emp.user_id:
                u = User.query.get(emp.user_id)
                if u: db.session.delete(u)
            CouponAllocation.query.filter_by(employee_id=emp.id).delete()
            db.session.delete(emp)
            deleted_count += 1
        flash(f'Successfully deleted all {deleted_count} employees in sector: "{sector_to_delete}"', 'success')
    elif selected_ids:
        for emp_id in selected_ids:
            emp = Employee.query.get(int(emp_id))
            if emp:
                if emp.user_id:
                    u = User.query.get(emp.user_id)
                    if u: db.session.delete(u)
                CouponAllocation.query.filter_by(employee_id=emp.id).delete()
                db.session.delete(emp)
                deleted_count += 1
        flash(f'Successfully deleted {deleted_count} selected employees.', 'success')
    else:
        flash('No employees or sector selected for deletion.', 'warning')
        
    db.session.commit()
    return redirect(url_for('employees'))

# ================= ALLOCATION MANAGEMENT =================

@app.route('/allocations', methods=['GET', 'POST'])
def allocations():
    if session.get('role') not in ['admin', 'superadmin']: return redirect(url_for('login'))
    month = request.args.get('month', datetime.utcnow().strftime('%Y-%m'))
    all_emps = Employee.query.all()
    sectors = sorted(list(set(e.sector for e in all_emps if e.sector)))
    
    if request.method == 'POST':
        target = request.form.get('target', 'all')
        amount = float(request.form.get('amount', 0))
        
        if target == 'all':
            for emp in all_emps:
                alloc = CouponAllocation.query.filter_by(employee_id=emp.id, month=month).first()
                if alloc: alloc.amount = amount
                else: db.session.add(CouponAllocation(employee_id=emp.id, month=month, amount=amount))
            flash(f'Released {amount} ETB allocation to ALL employees for {month}!', 'success')
            
        elif target == 'sector':
            target_sector = request.form.get('sector_name', '').strip()
            sector_emps = Employee.query.filter_by(sector=target_sector).all()
            for emp in sector_emps:
                alloc = CouponAllocation.query.filter_by(employee_id=emp.id, month=month).first()
                if alloc: alloc.amount = amount
                else: db.session.add(CouponAllocation(employee_id=emp.id, month=month, amount=amount))
            flash(f'Released {amount} ETB allocation to all employees in Sector "{target_sector}" for {month}!', 'success')
            
        elif target == 'single':
            emp_id = request.form.get('employee_id')
            alloc = CouponAllocation.query.filter_by(employee_id=emp_id, month=month).first()
            if alloc: alloc.amount = amount
            else: db.session.add(CouponAllocation(employee_id=emp_id, month=month, amount=amount))
            flash(f'Released allocation for single employee for {month}!', 'success')
            
        db.session.commit()
        return redirect(url_for('allocations', month=month))
        
    return render_template('allocations.html', employees=all_emps, sectors=sectors, month=month)

@app.route('/remove_allocations', methods=['POST'])
def remove_allocations():
    if session.get('role') not in ['admin', 'superadmin']: return redirect(url_for('login'))
    month = request.args.get('month', datetime.utcnow().strftime('%Y-%m'))
    
    sector_to_remove = request.form.get('sector_to_remove', '').strip()
    selected_emp_ids = request.form.getlist('selected_emp_ids')
    
    count = 0
    if sector_to_remove:
        emps = Employee.query.filter_by(sector=sector_to_remove).all()
        for emp in emps:
            alloc = CouponAllocation.query.filter_by(employee_id=emp.id, month=month).first()
            if alloc:
                alloc.amount = 0.0
                count += 1
        flash(f'Reset allocations to 0.00 ETB for all {count} employees in sector "{sector_to_remove}".', 'success')
    elif selected_emp_ids:
        for emp_id in selected_emp_ids:
            alloc = CouponAllocation.query.filter_by(employee_id=int(emp_id), month=month).first()
            if alloc:
                alloc.amount = 0.0
                count += 1
        flash(f'Reset allocations to 0.00 ETB for {count} selected employees.', 'success')
    else:
        flash('No sector or employees selected for allocation removal.', 'warning')

    db.session.commit()
    return redirect(url_for('allocations', month=month))

# ================= MERCHANT MANAGEMENT =================

@app.route('/merchants')
def merchants():
    if session.get('role') not in ['admin', 'superadmin']: return redirect(url_for('login'))
    all_merchants = User.query.filter_by(role='merchant').all()
    return render_template('merchants.html', merchants=all_merchants)

@app.route('/create_merchant', methods=['GET', 'POST'])
def create_merchant():
    if session.get('role') not in ['admin', 'superadmin']: return redirect(url_for('login'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password')
        if not username or not password:
            flash('Username and password are required.', 'danger')
            return redirect(url_for('create_merchant'))
        if User.query.filter_by(username=username).first():
            flash('Merchant username already exists.', 'danger')
            return redirect(url_for('create_merchant'))
        db.session.add(User(username=username, password=generate_password_hash(password), role='merchant', is_first_login=False))
        db.session.commit()
        flash('Merchant created successfully!', 'success')
        return redirect(url_for('merchants'))
    return render_template('create_merchant.html')

@app.route('/delete_merchant/<int:merchant_id>', methods=['POST'])
def delete_merchant(merchant_id):
    if session.get('role') not in ['admin', 'superadmin']: return redirect(url_for('login'))
    merchant = User.query.get_or_404(merchant_id)
    if merchant.role == 'merchant':
        db.session.delete(merchant)
        db.session.commit()
        flash('Merchant account removed successfully.', 'success')
    return redirect(url_for('merchants'))

@app.route('/merchant/reset_password/<int:merchant_id>', methods=['POST'])
def reset_merchant_password(merchant_id):
    if session.get('role') not in ['admin', 'superadmin']: return redirect(url_for('login'))
    merchant = User.query.get_or_404(merchant_id)
    if merchant.role == 'merchant':
        merchant.password = generate_password_hash('merchant123')
        db.session.commit()
        flash(f'Merchant password reset successfully! New temporary password is: merchant123', 'success')
    return redirect(url_for('merchants'))

@app.route('/upload_employees', methods=['GET', 'POST'])
def upload_employees():
    if session.get('role') not in ['admin', 'superadmin']: return redirect(url_for('login'))
    if request.method == 'POST':
        file = request.files.get('file')
        if file:
            filename = file.filename.lower()
            try:
                file_bytes = file.read()
                if filename.endswith('.xlsx') or filename.endswith('.xls'):
                    wb = openpyxl.load_workbook(io.BytesIO(file_bytes))
                    sheet = wb.active
                    excel_rows = list(sheet.iter_rows(values_only=True))
                    for row in excel_rows[1:]:
                        if row and row[0]:
                            e_id = str(row[0]).strip()
                            u = User.query.filter_by(username=e_id).first()
                            if not u:
                                u = User(username=e_id, password=None, role='employee', is_first_login=True)
                                db.session.add(u)
                                db.session.flush()
                            emp = Employee.query.filter_by(employee_id=e_id).first()
                            if not emp:
                                db.session.add(Employee(employee_id=e_id, full_name=str(row[1] or ''), sector=str(row[2] or ''), qr_token=secrets.token_urlsafe(16), user_id=u.id))
                else:
                    stream = io.TextIOWrapper(io.BytesIO(file_bytes), encoding='utf-8')
                    csv_reader = csv.reader(stream)
                    next(csv_reader, None)
                    for row in csv_reader:
                        if row and row[0]:
                            e_id = str(row[0]).strip()
                            u = User.query.filter_by(username=e_id).first()
                            if not u:
                                u = User(username=e_id, password=None, role='employee', is_first_login=True)
                                db.session.add(u)
                                db.session.flush()
                            emp = Employee.query.filter_by(employee_id=e_id).first()
                            if not emp:
                                db.session.add(Employee(employee_id=e_id, full_name=str(row[1] if len(row) > 1 else ''), sector=str(row[2] if len(row) > 2 else ''), qr_token=secrets.token_urlsafe(16), user_id=u.id))
                db.session.commit()
                flash('Employees uploaded successfully!', 'success')
            except Exception as e:
                flash(f'Error processing file: {str(e)}', 'danger')
        return redirect(url_for('employees'))
    return render_template('upload.html')

@app.route('/print_cards')
def print_cards():
    if session.get('role') not in ['admin', 'superadmin']: return redirect(url_for('login'))
    all_emps = Employee.query.all()
    return render_template('print_cards.html', employees=all_emps, single=False)

@app.route('/print_card/<int:emp_id>')
def print_single_card(emp_id):
    if session.get('role') not in ['admin', 'superadmin']: return redirect(url_for('login'))
    emp = Employee.query.get_or_404(emp_id)
    return render_template('print_cards.html', employees=[emp], single=True)

@app.route('/standalone_qr_print')
def standalone_qr_print():
    if session.get('role') not in ['admin', 'superadmin']: 
        return redirect(url_for('login'))
    all_emps = Employee.query.all()
    return render_template('standalone_qr_print.html', employees=all_emps)

@app.route('/qrlist')
def qrlist():
    if session.get('role') not in ['admin', 'superadmin']: return redirect(url_for('login'))
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['employee_id', 'full_name', 'sector', 'qr_token'])
    for emp in Employee.query.all():
        writer.writerow([emp.employee_id, emp.full_name, emp.sector, emp.qr_token])
    byte_output = io.BytesIO(output.getvalue().encode('utf-8'))
    output.close()
    return send_file(byte_output, mimetype='text/csv', download_name='employee_qr_list.csv', as_attachment=True)

@app.route('/reports_csv')
def reports_csv():
    if session.get('role') not in ['admin', 'superadmin']: return redirect(url_for('login'))
    month = request.args.get('month', datetime.utcnow().strftime('%Y-%m'))
    transactions = Transaction.query.filter_by(month=month).all()
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Month', 'Merchant Name', 'Employee Sector', 'Total Spent / Payable Amount (ETB)', 'Transaction Reference', 'Date'])
    
    for t in transactions:
        merchant_name = t.merchant_rel.username if t.merchant_rel else 'Unknown Merchant'
        sector_name = t.employee.sector if t.employee and t.employee.sector else 'Unassigned'
        writer.writerow([t.month, merchant_name, sector_name, t.amount, t.reference, t.created_at.strftime('%Y-%m-%d %H:%M')])
        
    byte_output = io.BytesIO(output.getvalue().encode('utf-8'))
    output.close()
    return send_file(byte_output, mimetype='text/csv', download_name=f'merchant_sector_report_{month}.csv', as_attachment=True)

# ================= EMPLOYEE PORTAL =================

@app.route('/employee/dashboard')
def employee_dashboard():
    if session.get('role') != 'employee': return redirect(url_for('login'))
    user = User.query.get(session.get('user_id'))
    if user and user.is_first_login:
        flash('Please create a password for your account first.', 'warning')
        return redirect(url_for('employee_change_password'))

    emp = Employee.query.filter_by(user_id=user.id).first() or Employee.query.filter_by(employee_id=user.username).first()
    month = datetime.utcnow().strftime('%Y-%m')
    
    alloc = CouponAllocation.query.filter_by(employee_id=emp.id, month=month).first() if emp else None
    allocated = alloc.amount if alloc else 0.0
    
    spent = sum(t.amount for t in Transaction.query.filter_by(employee_id=emp.id, month=month).all()) if emp else 0.0
    all_txs = Transaction.query.filter_by(employee_id=emp.id, month=month).order_by(Transaction.created_at.desc()).all() if emp else []

    return render_template('employee_dashboard.html', user=user, emp=emp, allocated=allocated, spent=spent, balance=allocated-spent, transactions=all_txs, month=month)

@app.route('/employee/change_password', methods=['GET', 'POST'])
def employee_change_password():
    if session.get('role') != 'employee': return redirect(url_for('login'))
    if request.method == 'POST':
        user = User.query.get(session.get('user_id'))
        new_password = request.form.get('new_password')
        if user and new_password:
            user.password = generate_password_hash(new_password)
            user.is_first_login = False
            db.session.commit()
            flash('Password set successfully!', 'success')
            return redirect(url_for('employee_dashboard'))
            
    return render_template('employee_password.html')

# ================= MERCHANT PORTAL =================

@app.route('/merchant/dashboard')
def merchant_dashboard():
    if session.get('role') != 'merchant': return redirect(url_for('login'))
    month = datetime.utcnow().strftime('%Y-%m')
    txs = Transaction.query.filter_by(merchant_id=session.get('user_id'), month=month).all()
    return render_template('merchant.html', transactions=txs, total_collected=sum(t.amount for t in txs), month=month)

@app.route('/merchant/scan', methods=['POST'])
def merchant_scan():
    if session.get('role') != 'merchant': return redirect(url_for('merchant_dashboard'))
    token = request.form.get('qr_token', '').strip()
    amount = float(request.form.get('amount', 0))
    month = datetime.utcnow().strftime('%Y-%m')
    emp = Employee.query.filter_by(qr_token=token).first()
    if not emp:
        flash('Invalid QR Token.', 'danger')
        return redirect(url_for('merchant_dashboard'))
    alloc = CouponAllocation.query.filter_by(employee_id=emp.id, month=month).first()
    allocated = alloc.amount if alloc else 0.0
    spent = sum(t.amount for t in Transaction.query.filter_by(employee_id=emp.id, month=month).all())
    if amount > (allocated - spent):
        flash('Insufficient employee balance for this monthly cycle!', 'danger')
        return redirect(url_for('merchant_dashboard'))
    db.session.add(Transaction(reference=secrets.token_hex(6).upper(), employee_id=emp.id, merchant_id=session.get('user_id'), amount=amount, month=month))
    db.session.commit()
    flash('Redeemed successfully!', 'success')
    return redirect(url_for('merchant_dashboard'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)