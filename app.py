import os
import secrets
import csv
import io
import openpyxl
from datetime import datetime
from flask import Flask, render_template, render_template_string, request, redirect, url_for, flash, session, send_file
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
        username = request.form.get('username')
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
            # PASSWORD-FREE FIRST LOGIN FOR EMPLOYEES
            if user.role == 'employee' and user.is_first_login:
                session['user_id'] = user.id
                session['username'] = user.username
                session['role'] = 'employee'
                flash('First login detected! Please set your new personal password.', 'info')
                return redirect(url_for('employee_change_password'))

            # REGULAR PASSWORD CHECK
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

# ================= ADMIN MANAGEMENT =================

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
    return render_template('admin.html', month=month, employees=employees_count, 
                           allocated=total_allocated, spent=total_spent, collected=total_spent, 
                           transactions=recent_transactions)

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

@app.route('/employees')
def employees():
    if session.get('role') not in ['admin', 'superadmin']: return redirect(url_for('login'))
    all_emps = Employee.query.all()
    return render_template('employees.html', employees=all_emps, rows=all_emps)

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
        flash(f'Employee {full_name} added! They can log in using Employee ID: {emp_id}', 'success')
        return redirect(url_for('employees'))
    return render_template('employee_form.html')

@app.route('/delete_employee/<int:emp_id>', methods=['POST'])
def delete_employee(emp_id):
    if session.get('role') not in ['admin', 'superadmin']: return redirect(url_for('login'))
    emp = Employee.query.get_or_404(emp_id)
    if emp.user_id:
        u = User.query.get(emp.user_id)
        if u: db.session.delete(u)
    CouponAllocation.query.filter_by(employee_id=emp.id).delete()
    db.session.delete(emp)
    db.session.commit()
    flash('Employee removed successfully.', 'success')
    return redirect(url_for('employees'))

@app.route('/reset_password/<int:employee_id>', methods=['POST'])
def reset_password(employee_id):
    if session.get('role') not in ['admin', 'superadmin']: return redirect(url_for('login'))
    emp = Employee.query.get_or_404(employee_id)
    if emp.user_id:
        u = User.query.get(emp.user_id)
        if u:
            u.password = None
            u.is_first_login = True
            db.session.commit()
            flash('Employee password reset! They can log in password-free to set a new password.', 'success')
    return redirect(url_for('employees'))

@app.route('/merchants')
def merchants():
    if session.get('role') not in ['admin', 'superadmin']: return redirect(url_for('login'))
    all_merchants = User.query.filter_by(role='merchant').all()
    
    MERCHANTS_HTML = """
    <!DOCTYPE html><html><head><title>Merchants</title>
    <style>body{font-family:sans-serif;padding:30px;background:#f1f5f9;}.card{background:#fff;padding:24px;border-radius:12px;}</style></head>
    <body><div class="card"><h2>Merchant Management</h2><a href="{{ url_for('create_merchant') }}">+ Add Merchant</a> | <a href="{{ url_for('admin_dashboard') }}">Dashboard</a>
    <hr><ul>{% for m in merchants %}<li>{{ m.username }}</li>{% else %}<li>No merchants found.</li>{% endfor %}</ul></div></body></html>
    """
    return render_template_string(MERCHANTS_HTML, merchants=all_merchants)

@app.route('/create_merchant', methods=['GET', 'POST'])
def create_merchant():
    if session.get('role') not in ['admin', 'superadmin']: return redirect(url_for('login'))
    if request.method == 'POST':
        username = request.form.get('username').strip()
        password = request.form.get('password')
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

@app.route('/allocations', methods=['GET', 'POST'])
def allocations():
    if session.get('role') not in ['admin', 'superadmin']: return redirect(url_for('login'))
    month = request.args.get('month', datetime.utcnow().strftime('%Y-%m'))
    all_emps = Employee.query.all()
    if request.method == 'POST':
        target = request.form.get('target', 'all')
        amount = float(request.form.get('amount', 0))
        if target == 'all':
            for emp in all_emps:
                alloc = CouponAllocation.query.filter_by(employee_id=emp.id, month=month).first()
                if alloc: alloc.amount = amount
                else: db.session.add(CouponAllocation(employee_id=emp.id, month=month, amount=amount))
            flash('Allocation released successfully to all employees!', 'success')
        else:
            emp_id = request.form.get('employee_id')
            alloc = CouponAllocation.query.filter_by(employee_id=emp_id, month=month).first()
            if alloc: alloc.amount = amount
            else: db.session.add(CouponAllocation(employee_id=emp_id, month=month, amount=amount))
            flash('Allocation released successfully for single employee!', 'success')
        db.session.commit()
    return render_template('allocations.html', employees=all_emps, month=month)

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
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['ID', 'Reference', 'Amount', 'Date'])
    for t in Transaction.query.all():
        writer.writerow([t.id, t.reference, t.amount, t.created_at])
    byte_output = io.BytesIO(output.getvalue().encode('utf-8'))
    output.close()
    return send_file(byte_output, mimetype='text/csv', download_name='transactions_report.csv', as_attachment=True)

# ================= EMPLOYEE PORTAL (EMBEDDED) =================

@app.route('/employee/dashboard')
def employee_dashboard():
    if session.get('role') != 'employee': 
        return redirect(url_for('login'))
    
    user = User.query.get(session.get('user_id'))
    if user and user.is_first_login:
        flash('Please create a password for your account first.', 'warning')
        return redirect(url_for('employee_change_password'))

    emp = Employee.query.filter_by(user_id=user.id).first() or Employee.query.filter_by(employee_id=user.username).first()
    month = datetime.utcnow().strftime('%Y-%m')
    alloc = CouponAllocation.query.filter_by(employee_id=emp.id, month=month).first() if emp else None
    allocated = alloc.amount if alloc else 0.0
    spent = sum(t.amount for t in Transaction.query.filter_by(employee_id=emp.id, month=month).all()) if emp else 0.0
    all_txs = Transaction.query.filter_by(employee_id=emp.id).order_by(Transaction.created_at.desc()).all() if emp else []

    EMP_HTML = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Employee Portal - Kolfe Coupon System</title>
        <script src="https://cdn.jsdelivr.net/npm/qrcodejs@1.0.0/qrcode.min.js"></script>
        <style>
            * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
            body { background-color: #f1f5f9; color: #334155; padding-bottom: 50px; }
            .navbar { background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%); padding: 16px 32px; display: flex; justify-content: space-between; align-items: center; box-shadow: 0 4px 12px rgba(0,0,0,0.15); }
            .navbar-brand { color: #ffffff; font-size: 20px; font-weight: 700; }
            .nav-btn { text-decoration: none; padding: 8px 16px; border-radius: 6px; font-size: 14px; font-weight: 600; color: #ffffff; background: #ef4444; border: none; }
            .container { max-width: 900px; margin: 30px auto; padding: 0 20px; }
            .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 20px; margin-bottom: 25px; }
            .card { background: #ffffff; padding: 24px; border-radius: 12px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05); }
            .card h6 { font-size: 13px; text-transform: uppercase; color: #64748b; font-weight: 700; margin-bottom: 6px; }
            .card h3 { font-size: 28px; font-weight: 800; }
            .qr-box { text-align: center; margin: 20px 0; }
            #qrcode { display: inline-block; padding: 15px; background: #fff; border: 2px dashed #cbd5e1; border-radius: 12px; }
            table { width: 100%; border-collapse: collapse; text-align: left; }
            th { background-color: #f8fafc; padding: 12px 16px; font-size: 13px; font-weight: 700; color: #475569; border-bottom: 2px solid #e2e8f0; }
            td { padding: 14px 16px; border-bottom: 1px solid #f1f5f9; font-size: 14px; color: #334155; }
            .alert { padding: 12px 18px; border-radius: 8px; margin-bottom: 20px; font-weight: 700; background-color: #dcfce7; color: #15803d; }
        </style>
    </head>
    <body>
        <nav class="navbar">
            <div class="navbar-brand">👤 Employee Portal ({{ emp.full_name if emp else user.username }})</div>
            <div>
                <a href="{{ url_for('employee_change_password') }}" style="color:#38bdf8; text-decoration:none; margin-right:15px; font-weight:600;">🔐 Change Password</a>
                <a href="{{ url_for('logout') }}" class="nav-btn">Logout</a>
            </div>
        </nav>

        <div class="container">
            {% with messages = get_flashed_messages(with_categories=true) %}
                {% if messages %}
                    {% for category, message in messages %}
                        <div class="alert">{{ message }}</div>
                    {% endfor %}
                {% endif %}
            {% endwith %}

            <div class="grid">
                <div class="card" style="border-top: 4px solid #2563eb;">
                    <h6>Monthly Allocation ({{ month }})</h6>
                    <h3 style="color:#2563eb;">{{ "%.2f"|format(allocated) }} ETB</h3>
                </div>
                <div class="card" style="border-top: 4px solid #ef4444;">
                    <h6>Total Spent</h6>
                    <h3 style="color:#ef4444;">{{ "%.2f"|format(spent) }} ETB</h3>
                </div>
                <div class="card" style="border-top: 4px solid #16a34a;">
                    <h6>Remaining Balance</h6>
                    <h3 style="color:#16a34a;">{{ "%.2f"|format(balance) }} ETB</h3>
                </div>
            </div>

            <div class="card" style="margin-bottom: 25px;">
                <h4 style="font-size: 18px; font-weight:700; margin-bottom:10px;">Your Digital Coupon QR Card</h4>
                <p style="font-size: 14px; color:#64748b;">Show this QR code to cafeteria merchants to redeem your coupon.</p>
                <div class="qr-box">
                    <div id="qrcode"></div>
                    <p style="margin-top:10px; font-family:monospace; font-weight:700; color:#475569;">Token: {{ emp.qr_token if emp else 'N/A' }}</p>
                </div>
            </div>

            <div class="card">
                <h4 style="font-size: 18px; font-weight:700; margin-bottom:15px;">Your Redemption History</h4>
                <table>
                    <thead>
                        <tr><th>Date & Time</th><th>Reference</th><th>Amount Redeemed</th></tr>
                    </thead>
                    <tbody>
                        {% for t in transactions %}
                        <tr>
                            <td>{{ t.created_at.strftime('%Y-%m-%d %H:%M:%S') }}</td>
                            <td><code>{{ t.reference }}</code></td>
                            <td style="font-weight:700; color:#ef4444;">-{{ "%.2f"|format(t.amount) }} ETB</td>
                        </tr>
                        {% else %}
                        <tr><td colspan="3" style="text-align:center; color:#94a3b8; padding:20px;">No coupon redemptions recorded yet.</td></tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>

        <script>
            {% if emp and emp.qr_token %}
            new QRCode(document.getElementById("qrcode"), {
                text: "{{ emp.qr_token }}",
                width: 180,
                height: 180
            });
            {% endif %}
        </script>
    </body>
    </html>
    """
    return render_template_string(EMP_HTML, user=user, emp=emp, allocated=allocated, spent=spent, balance=allocated-spent, transactions=all_txs, month=month)

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
            flash('Password set successfully! Welcome to your dashboard.', 'success')
            return redirect(url_for('employee_dashboard'))
            
    PWD_HTML = """
    <!DOCTYPE html><html><head><title>Create Password</title>
    <style>body{font-family:sans-serif;background:#f1f5f9;display:flex;justify-content:center;align-items:center;height:100vh;}
    .card{background:#fff;padding:30px;border-radius:12px;width:350px;box-shadow:0 4px 6px rgba(0,0,0,0.1);}
    input{width:100%;padding:10px;margin:10px 0 20px 0;border:1px solid #ccc;border-radius:6px;box-sizing:border-box;}
    button{width:100%;padding:10px;background:#2563eb;color:#fff;border:none;border-radius:6px;font-weight:bold;cursor:pointer;}</style></head>
    <body><div class="card"><h3>🔐 Set New Password</h3><p style="font-size:13px;color:#64748b;">Please create a new password for your employee account.</p>
    <form method="POST"><label>New Password:</label><input type="password" name="new_password" required placeholder="Enter new password"><button type="submit">Save Password</button></form></div></body></html>
    """
    return render_template_string(PWD_HTML)

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
        flash('Insufficient employee balance!', 'danger')
        return redirect(url_for('merchant_dashboard'))
    db.session.add(Transaction(reference=secrets.token_hex(6).upper(), employee_id=emp.id, merchant_id=session.get('user_id'), amount=amount, month=month))
    db.session.commit()
    flash('Redeemed successfully!', 'success')
    return redirect(url_for('merchant_dashboard'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)