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

    ADMIN_HTML = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>Admin Dashboard - Kolfe Coupon System</title>
        <style>
            * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
            body { background-color: #f1f5f9; color: #334155; padding-bottom: 50px; }
            .navbar { background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%); padding: 16px 32px; display: flex; justify-content: space-between; align-items: center; color: #fff; }
            .container { max-width: 1100px; margin: 30px auto; padding: 0 20px; }
            .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 20px; margin-bottom: 25px; }
            .card { background: #ffffff; padding: 24px; border-radius: 12px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05); }
            .actions-bar { background: #ffffff; padding: 20px; border-radius: 12px; margin-bottom: 25px; display: flex; flex-wrap: wrap; gap: 10px; }
            .btn { text-decoration: none; padding: 10px 16px; border-radius: 6px; font-weight: 600; font-size: 14px; color: #fff; border: none; cursor: pointer; display: inline-block; }
            .btn-blue { background: #2563eb; }
            .btn-green { background: #16a34a; }
            .btn-dark { background: #475569; }
            .btn-red { background: #dc2626; }
            table { width: 100%; border-collapse: collapse; text-align: left; background: #fff; border-radius: 12px; overflow: hidden; margin-bottom: 25px; }
            th { background-color: #f8fafc; padding: 12px 16px; font-size: 13px; font-weight: 700; color: #475569; border-bottom: 2px solid #e2e8f0; }
            td { padding: 12px 16px; border-bottom: 1px solid #f1f5f9; font-size: 14px; }
            .alert { padding: 12px 18px; border-radius: 8px; margin-bottom: 20px; font-weight: 700; background-color: #dcfce7; color: #15803d; }
        </style>
    </head>
    <body>
        <nav class="navbar">
            <h2>👑 Admin Control Dashboard</h2>
            <div>
                <a href="{{ url_for('admin_change_password') }}" style="color:#38bdf8; text-decoration:none; margin-right:15px; font-weight:600;">🔐 Change Password</a>
                <a href="{{ url_for('logout') }}" class="btn btn-red" style="padding:6px 12px;">Logout</a>
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

            <form method="GET" class="card" style="margin-bottom: 25px; display:flex; gap:15px; align-items:center;">
                <label style="font-weight:700;">Select Month:</label>
                <input type="text" name="month" value="{{ month }}" style="padding:8px; border:1px solid #cbd5e1; border-radius:6px;">
                <button type="submit" class="btn btn-blue" style="padding:8px 16px;">Filter Month Data</button>
            </form>

            <div class="grid">
                <div class="card" style="border-top: 4px solid #2563eb;">
                    <h6 style="color:#64748b; font-size:12px; font-weight:700; text-transform:uppercase;">Total Employees</h6>
                    <h3 style="font-size:26px; font-weight:800; margin-top:5px;">{{ employees }}</h3>
                </div>
                <div class="card" style="border-top: 4px solid #d97706;">
                    <h6 style="color:#64748b; font-size:12px; font-weight:700; text-transform:uppercase;">Released Allocation ({{ month }})</h6>
                    <h3 style="font-size:26px; font-weight:800; margin-top:5px;">{{ "%.2f"|format(allocated) }} ETB</h3>
                </div>
                <div class="card" style="border-top: 4px solid #ef4444;">
                    <h6 style="color:#64748b; font-size:12px; font-weight:700; text-transform:uppercase;">Total Spent ({{ month }})</h6>
                    <h3 style="font-size:26px; font-weight:800; margin-top:5px;">{{ "%.2f"|format(spent) }} ETB</h3>
                </div>
                <div class="card" style="border-top: 4px solid #16a34a;">
                    <h6 style="color:#64748b; font-size:12px; font-weight:700; text-transform:uppercase;">Merchant Collected ({{ month }})</h6>
                    <h3 style="font-size:26px; font-weight:800; margin-top:5px;">{{ "%.2f"|format(spent) }} ETB</h3>
                </div>
            </div>

            <div class="actions-bar">
                <a href="{{ url_for('add_employee') }}" class="btn btn-blue">+ Add Employee</a>
                <a href="{{ url_for('employees') }}" class="btn btn-dark">Manage & Bulk Delete Employees</a>
                <a href="{{ url_for('merchants') }}" class="btn btn-green">Manage Merchants</a>
                <a href="{{ url_for('upload_employees') }}" class="btn btn-dark">Bulk Excel Upload</a>
                <a href="{{ url_for('allocations') }}" class="btn" style="background:#b45309;">Release Allocations</a>
                <a href="{{ url_for('print_cards') }}" class="btn btn-dark">Print QR Cards (22 Per Page)</a>
                <a href="{{ url_for('qrlist') }}" class="btn btn-dark">Export QR List</a>
                <a href="{{ url_for('reports_csv') }}?month={{ month }}" class="btn btn-red">Export Monthly Sector Report (CSV)</a>
            </div>

            <div class="card" style="margin-bottom: 25px;">
                <h3 style="margin-bottom: 15px; font-size:18px;">🛒 Collections by Merchant & Employee Sector (Month: {{ month }})</h3>
                <table>
                    <thead>
                        <tr><th>Merchant Name</th><th>Employee Sector</th><th>Total Collected Amount</th></tr>
                    </thead>
                    <tbody>
                        {% for merchant, sectors in merchant_sector_breakdown.items() %}
                            {% for sector, amount in sectors.items() %}
                            <tr>
                                <td style="font-weight:700; color:#2563eb;">{{ merchant }}</td>
                                <td style="font-weight:600;">{{ sector }}</td>
                                <td style="font-weight:700; color:#16a34a;">{{ "%.2f"|format(amount) }} ETB</td>
                            </tr>
                            {% endfor %}
                        {% else %}
                        <tr><td colspan="3" style="text-align:center; color:#94a3b8; padding:20px;">No merchant collection records found for this month.</td></tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>

            <div class="card">
                <h3 style="margin-bottom: 15px; font-size:18px;">Recent Transactions ({{ month }})</h3>
                <table>
                    <thead>
                        <tr><th>Date & Time</th><th>Reference</th><th>Merchant</th><th>Employee</th><th>Sector</th><th>Amount</th></tr>
                    </thead>
                    <tbody>
                        {% for t in transactions %}
                        <tr>
                            <td>{{ t.created_at.strftime('%Y-%m-%d %H:%M') }}</td>
                            <td><code>{{ t.reference }}</code></td>
                            <td style="font-weight:600;">{{ t.merchant_rel.username if t.merchant_rel else 'N/A' }}</td>
                            <td>{{ t.employee.full_name if t.employee else 'N/A' }}</td>
                            <td>{{ t.employee.sector if t.employee else 'N/A' }}</td>
                            <td style="font-weight:700; color:#ef4444;">-{{ "%.2f"|format(t.amount) }} ETB</td>
                        </tr>
                        {% else %}
                        <tr><td colspan="6" style="text-align:center; color:#94a3b8; padding:20px;">No transactions recorded for this month.</td></tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
    </body>
    </html>
    """
    return render_template_string(ADMIN_HTML, month=month, employees=employees_count, 
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

# ================= PRINT CARDS (EMBEDDED 22 PER PAGE LANDSCAPE) =================

@app.route('/print_cards')
def print_cards():
    if session.get('role') not in ['admin', 'superadmin']: return redirect(url_for('login'))
    all_emps = Employee.query.all()
    
    PRINT_HTML = """
    <!DOCTYPE html>
    <html lang="am">
    <head>
        <meta charset="UTF-8">
        <title>Print Coupon Cards - Kolfe System</title>
        <script src="https://cdn.jsdelivr.net/npm/qrcodejs@1.0.0/qrcode.min.js"></script>
        <style>
            * { box-sizing: border-box; margin: 0; padding: 0; }
            body { font-family: 'Segoe UI', Tahoma, Arial, sans-serif; background: #f1f5f9; padding: 15px; color: #1e293b; }

            .control-panel {
                background: #ffffff;
                padding: 20px;
                border-radius: 12px;
                box-shadow: 0 4px 6px rgba(0,0,0,0.08);
                max-width: 1000px;
                margin: 0 auto 20px auto;
                display: flex;
                flex-wrap: wrap;
                gap: 20px;
                align-items: center;
                justify-content: space-between;
            }

            .control-group { display: flex; flex-direction: column; gap: 5px; }
            .control-group label { font-size: 13px; font-weight: bold; color: #475569; }
            .control-group input, .control-group select {
                padding: 8px 12px;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                font-size: 14px;
            }

            .btn {
                padding: 10px 20px;
                border-radius: 6px;
                font-size: 14px;
                font-weight: bold;
                color: #fff;
                border: none;
                cursor: pointer;
                text-decoration: none;
                display: inline-block;
            }
            .btn-blue { background: #2563eb; }
            .btn-dark { background: #475569; }

            .print-grid {
                display: grid;
                grid-template-columns: repeat(6, 1fr);
                gap: 6px;
                width: 100%;
                margin: 0 auto;
            }

            .coupon-card {
                background: #ffffff;
                border: 1px solid #000000;
                border-radius: 4px;
                padding: 5px;
                text-align: center;
                font-size: 9px;
                display: flex;
                flex-direction: column;
                justify-content: space-between;
                height: 145px;
                box-sizing: border-box;
                page-break-inside: avoid;
            }

            .header-title { font-size: 9px; font-weight: bold; line-height: 1.1; color: #000; }
            .sub-title { font-size: 8px; font-weight: bold; color: #333; margin: 2px 0; }

            .emp-info {
                text-align: left;
                font-size: 8px;
                line-height: 1.2;
                background: #f8fafc;
                padding: 3px;
                border: 0.5px solid #ccc;
                border-radius: 3px;
                margin: 2px 0;
            }

            .qr-box {
                display: flex;
                justify-content: center;
                align-items: center;
                margin: 2px 0;
            }

            .footer-note {
                font-size: 7.5px;
                font-weight: bold;
                color: #000;
                border-top: 0.5px solid #000;
                padding-top: 2px;
            }

            @media print {
                @page {
                    size: A4 landscape;
                    margin: 6mm;
                }
                body { background: none; padding: 0; }
                .no-print { display: none !important; }
                .print-grid {
                    grid-template-columns: repeat(6, 1fr);
                    gap: 4px;
                }
                .coupon-card {
                    box-shadow: none;
                    border: 1px solid #000;
                }
            }
        </style>
    </head>
    <body>

        <div class="control-panel no-print">
            <div class="control-group">
                <label for="monthInput">🗓️ Select / Type Month for All Coupons:</label>
                <input type="text" id="monthInput" value="መስከረም 2019 ዓ.ም" oninput="updateMonthText(this.value)" placeholder="e.g. መስከረም 2019">
            </div>

            <div class="control-group">
                <label for="copiesSelect">🔢 Coupons Per Person (On Page):</label>
                <select id="copiesSelect" onchange="generateCards()">
                    <option value="1">1 Coupon per Employee</option>
                    <option value="2">2 Coupons per Employee</option>
                    <option value="4">4 Coupons per Employee</option>
                    <option value="10">10 Coupons per Employee</option>
                    <option value="22" selected>22 Coupons per Page / Person</option>
                </select>
            </div>

            <div>
                <button onclick="window.print()" class="btn btn-blue">🖨️ Print Landscape Pages</button>
                <a href="{{ url_for('admin_dashboard') }}" class="btn btn-dark" style="margin-left: 8px;">Back</a>
            </div>
        </div>

        <div id="printGrid" class="print-grid"></div>

        <script>
            const rawEmployees = [
                {% for emp in employees %}
                {
                    id: "{{ emp.id }}",
                    employee_id: "{{ emp.employee_id }}",
                    full_name: "{{ emp.full_name }}",
                    sector: "{{ emp.sector }}",
                    qr_token: "{{ emp.qr_token }}"
                }{% if not loop.last %},{% endif %}
                {% endfor %}
            ];

            function generateCards() {
                const grid = document.getElementById('printGrid');
                grid.innerHTML = '';
                const copiesCount = parseInt(document.getElementById('copiesSelect').value) || 1;
                const currentMonth = document.getElementById('monthInput').value || 'መስከረም 2019 ዓ.ም';

                let globalCardIndex = 0;

                rawEmployees.forEach(emp => {
                    for (let i = 0; i < copiesCount; i++) {
                        globalCardIndex++;
                        const cardDiv = document.createElement('div');
                        cardDiv.className = 'coupon-card';
                        
                        const qrContainerId = `qrcode-${emp.id}-${globalCardIndex}`;

                        cardDiv.innerHTML = `
                            <div>
                                <div class="header-title">በኮልፌ ቀራኒዮ ክፍለ ከተማ አስተዳደር</div>
                                <div class="sub-title">የሰራተኞች የቁርስ/ምግብ መስተንግዶ ኩፖን</div>
                            </div>

                            <div class="emp-info">
                                <div><strong>ስም:</strong> ${emp.full_name}</div>
                                <div><strong>መታወቂያ:</strong> <code>${emp.employee_id}</code></div>
                                <div><strong>ዘርፍ:</strong> ${emp.sector}</div>
                                <div><strong>ወር:</strong> <span class="month-display">${currentMonth}</span></div>
                            </div>

                            <div class="qr-box">
                                <div id="${qrContainerId}"></div>
                            </div>

                            <div class="footer-note">
                                ለአንድ ጊዜ አገልግሎት ብቻ የሚውል
                            </div>
                        `;

                        grid.appendChild(cardDiv);

                        new QRCode(document.getElementById(qrContainerId), {
                            text: emp.qr_token,
                            width: 48,
                            height: 48
                        });
                    }
                });
            }

            function updateMonthText(newMonth) {
                const monthDisplays = document.querySelectorAll('.month-display');
                monthDisplays.forEach(el => {
                    el.innerText = newMonth;
                });
            }

            window.onload = function() {
                generateCards();
            };
        </script>
    </body>
    </html>
    """
    return render_template_string(PRINT_HTML, employees=all_emps)

@app.route('/print_card/<int:emp_id>')
def print_single_card(emp_id):
    if session.get('role') not in ['admin', 'superadmin']: return redirect(url_for('login'))
    emp = Employee.query.get_or_404(emp_id)
    return redirect(url_for('print_cards'))

# ================= EMPLOYEE MANAGEMENT =================

@app.route('/employees')
def employees():
    if session.get('role') not in ['admin', 'superadmin']: return redirect(url_for('login'))
    all_emps = Employee.query.all()
    sectors = sorted(list(set(e.sector for e in all_emps if e.sector)))
    
    EMPLOYEES_HTML = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>Manage Employees</title>
        <style>
            body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; padding: 30px; background: #f1f5f9; color: #334155; }
            .card { background: #fff; padding: 24px; border-radius: 12px; max-width: 1000px; margin: 0 auto; box-shadow: 0 4px 6px rgba(0,0,0,0.05); }
            table { width: 100%; border-collapse: collapse; margin-top: 20px; text-align: left; }
            th { background: #f8fafc; padding: 12px; font-size: 13px; border-bottom: 2px solid #e2e8f0; }
            td { padding: 12px; border-bottom: 1px solid #f1f5f9; }
            .btn { text-decoration: none; padding: 8px 14px; border-radius: 6px; font-size: 13px; font-weight: 600; color: #fff; border: none; cursor: pointer; display: inline-block; }
            .btn-blue { background: #2563eb; }
            .btn-red { background: #dc2626; }
            .alert { padding: 12px; border-radius: 6px; margin-bottom: 15px; background: #dcfce7; color: #15803d; font-weight: bold; }
            .bulk-bar { background: #f8fafc; padding: 15px; border-radius: 8px; border: 1px solid #e2e8f0; margin-top: 20px; display: flex; gap: 15px; align-items: center; justify-content: space-between; }
        </style>
    </head>
    <body>
        <div class="card">
            <h2>👥 Employee Management</h2>
            <div style="margin-top: 15px; display:flex; gap:10px;">
                <a href="{{ url_for('add_employee') }}" class="btn btn-blue">+ Add Employee</a>
                <a href="{{ url_for('upload_employees') }}" class="btn" style="background:#475569;">Bulk Excel Upload</a>
                <a href="{{ url_for('admin_dashboard') }}" class="btn" style="background:#64748b;">← Back to Dashboard</a>
            </div>
            <hr style="margin: 20px 0; border:0; border-top:1px solid #e2e8f0;">

            {% with messages = get_flashed_messages(with_categories=true) %}
                {% if messages %}
                    {% for category, message in messages %}
                        <div class="alert">{{ message }}</div>
                    {% endfor %}
                {% endif %}
            {% endwith %}

            <form action="{{ url_for('bulk_delete_employees') }}" method="POST">
                <div class="bulk-bar">
                    <div><strong>Bulk Actions:</strong> Select employees OR pick an entire sector to delete:</div>
                    <div style="display:flex; gap:10px; align-items:center;">
                        <select name="sector_to_delete" style="padding:6px; border-radius:6px; border:1px solid #cbd5e1;">
                            <option value="">-- Select Sector to Delete --</option>
                            {% for sec in sectors %}
                            <option value="{{ sec }}">{{ sec }}</option>
                            {% endfor %}
                        </select>
                        <button type="submit" class="btn btn-red" onclick="return confirm('Delete selected employees or entire sector?');">🗑️ Delete Selected / Sector</button>
                    </div>
                </div>

                <table>
                    <thead>
                        <tr>
                            <th><input type="checkbox" id="selectAll" onclick="toggleSelectAll(this)"></th>
                            <th>Employee ID</th>
                            <th>Full Name</th>
                            <th>Sector</th>
                            <th>Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for emp in employees %}
                        <tr>
                            <td><input type="checkbox" name="selected_ids" value="{{ emp.id }}" class="emp-checkbox"></td>
                            <td style="font-weight:600;">{{ emp.employee_id }}</td>
                            <td>{{ emp.full_name }}</td>
                            <td><span style="background:#e0f2fe; color:#0369a1; padding:3px 8px; border-radius:4px; font-weight:600; font-size:12px;">{{ emp.sector }}</span></td>
                            <td>
                                <a href="{{ url_for('print_cards') }}" class="btn btn-blue" style="padding:4px 8px; font-size:12px;">Print Cards</a>
                            </td>
                        </tr>
                        {% else %}
                        <tr><td colspan="5" style="text-align:center; color:#94a3b8; padding:20px;">No employees found.</td></tr>
                        {% endfor %}
                    </tbody>
                </table>
            </form>
        </div>
        <script>
            function toggleSelectAll(master) {
                let checkboxes = document.getElementsByClassName('emp-checkbox');
                for (let i = 0; i < checkboxes.length; i++) {
                    checkboxes[i].checked = master.checked;
                }
            }
        </script>
    </body>
    </html>
    """
    return render_template_string(EMPLOYEES_HTML, employees=all_emps, sectors=sectors)

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

# ================= ALLOCATIONS MANAGEMENT =================

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
            flash(f'Released {amount} ETB allocation to Sector "{target_sector}" for {month}!', 'success')
            
        elif target == 'single':
            emp_id = request.form.get('employee_id')
            alloc = CouponAllocation.query.filter_by(employee_id=emp_id, month=month).first()
            if alloc: alloc.amount = amount
            else: db.session.add(CouponAllocation(employee_id=emp_id, month=month, amount=amount))
            flash(f'Released allocation for single employee for {month}!', 'success')
            
        db.session.commit()
        return redirect(url_for('allocations', month=month))
        
    ALLOCATIONS_HTML = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>Release & Manage Allocations</title>
        <style>
            body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; padding: 30px; background: #f1f5f9; color: #334155; }
            .card { background: #fff; padding: 24px; border-radius: 12px; max-width: 900px; margin: 0 auto 20px auto; box-shadow: 0 4px 6px rgba(0,0,0,0.05); }
            .btn { text-decoration: none; padding: 8px 14px; border-radius: 6px; font-size: 13px; font-weight: 600; color: #fff; border: none; cursor: pointer; display: inline-block; }
            .btn-blue { background: #2563eb; }
            .btn-red { background: #dc2626; }
            .alert { padding: 12px; border-radius: 6px; margin-bottom: 15px; background: #dcfce7; color: #15803d; font-weight: bold; }
            table { width: 100%; border-collapse: collapse; margin-top: 15px; }
            th { background: #f8fafc; padding: 12px; font-size: 13px; border-bottom: 2px solid #e2e8f0; text-align: left; }
            td { padding: 12px; border-bottom: 1px solid #f1f5f9; }
            input, select { padding: 8px; border: 1px solid #cbd5e1; border-radius: 6px; margin-top: 5px; width: 100%; }
        </style>
    </head>
    <body>
        <div class="card">
            <h2>💰 Release Coupon Allocations (Cycle: {{ month }})</h2>
            <div style="margin-top: 15px;">
                <a href="{{ url_for('admin_dashboard') }}" class="btn" style="background:#64748b;">← Back to Dashboard</a>
            </div>
            <hr style="margin: 20px 0; border:0; border-top:1px solid #e2e8f0;">

            {% with messages = get_flashed_messages(with_categories=true) %}
                {% if messages %}
                    {% for category, message in messages %}
                        <div class="alert">{{ message }}</div>
                    {% endfor %}
                {% endif %}
            {% endwith %}

            <form method="POST">
                <div style="display:grid; grid-template-columns: 1fr 1fr 1fr; gap: 15px; align-items:end;">
                    <div>
                        <label><strong>Target Group:</strong></label>
                        <select name="target" id="targetSelect" onchange="toggleTargetFields()">
                            <option value="all">All Employees System-Wide</option>
                            <option value="sector">Bulk by Sector</option>
                            <option value="single">Single Employee</option>
                        </select>
                    </div>

                    <div id="sectorBox" style="display:none;">
                        <label><strong>Select Sector:</strong></label>
                        <select name="sector_name">
                            {% for sec in sectors %}
                            <option value="{{ sec }}">{{ sec }}</option>
                            {% endfor %}
                        </select>
                    </div>

                    <div id="employeeBox" style="display:none;">
                        <label><strong>Select Employee:</strong></label>
                        <select name="employee_id">
                            {% for emp in employees %}
                            <option value="{{ emp.id }}">{{ emp.full_name }} ({{ emp.employee_id }})</option>
                            {% endfor %}
                        </select>
                    </div>

                    <div>
                        <label><strong>Allocation Amount (ETB):</strong></label>
                        <input type="number" step="0.01" name="amount" required placeholder="e.g. 1000">
                    </div>
                </div>

                <button type="submit" class="btn btn-blue" style="margin-top:20px; width:100%; padding:12px;">🚀 Release Allocation Now</button>
            </form>
        </div>

        <div class="card">
            <h3>🔴 Remove / Reset Allocations</h3>
            <p style="font-size:13px; color:#64748b; margin-top:5px;">Reset employee active coupon balances back to 0.00 ETB for cycle {{ month }}.</p>
            
            <form action="{{ url_for('remove_allocations') }}?month={{ month }}" method="POST" style="margin-top:15px;">
                <div style="display:grid; grid-template-columns: 1fr 1fr; gap:15px; margin-bottom:15px;">
                    <div>
                        <label><strong>Remove/Reset Entire Sector:</strong></label>
                        <select name="sector_to_remove">
                            <option value="">-- Choose Sector to Reset --</option>
                            {% for sec in sectors %}
                            <option value="{{ sec }}">{{ sec }}</option>
                            {% endfor %}
                        </select>
                    </div>
                    <div style="display:flex; align-items:flex-end;">
                        <button type="submit" class="btn btn-red" style="width:100%; padding:10px;" onclick="return confirm('Reset selected allocation amounts to zero?');">🗑️ Remove / Reset Allocation</button>
                    </div>
                </div>

                <table>
                    <thead>
                        <tr>
                            <th><input type="checkbox" id="selectAllAlloc" onclick="toggleAllocCheckboxes(this)"></th>
                            <th>Employee ID</th>
                            <th>Full Name</th>
                            <th>Sector</th>
                            <th>Current Allocation ({{ month }})</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for emp in employees %}
                        <tr>
                            <td><input type="checkbox" name="selected_emp_ids" value="{{ emp.id }}" class="alloc-checkbox"></td>
                            <td>{{ emp.employee_id }}</td>
                            <td>{{ emp.full_name }}</td>
                            <td>{{ emp.sector }}</td>
                            <td style="font-weight:700; color:#16a34a;">
                                {% set alloc = emp.id|get_alloc(month) %}
                                {{ "%.2f"|format(alloc) }} ETB
                            </td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </form>
        </div>

        <script>
            function toggleTargetFields() {
                var target = document.getElementById("targetSelect").value;
                document.getElementById("sectorBox").style.display = (target === "sector") ? "block" : "none";
                document.getElementById("employeeBox").style.display = (target === "single") ? "block" : "none";
            }
            function toggleAllocCheckboxes(master) {
                let checkboxes = document.getElementsByClassName('alloc-checkbox');
                for (let i = 0; i < checkboxes.length; i++) {
                    checkboxes[i].checked = master.checked;
                }
            }
        </script>
    </body>
    </html>
    """
    return render_template_string(ALLOCATIONS_HTML, employees=all_emps, sectors=sectors, month=month)

@app.template_filter('get_alloc')
def get_alloc_filter(emp_id, month):
    alloc = CouponAllocation.query.filter_by(employee_id=emp_id, month=month).first()
    return alloc.amount if alloc else 0.0

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
    
    MERCHANTS_HTML = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>Merchant Management</title>
        <style>
            body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; padding: 30px; background: #f1f5f9; color: #334155; }
            .card { background: #fff; padding: 24px; border-radius: 12px; max-width: 800px; margin: 0 auto; box-shadow: 0 4px 6px rgba(0,0,0,0.05); }
            table { width: 100%; border-collapse: collapse; margin-top: 20px; text-align: left; }
            th { background: #f8fafc; padding: 12px; font-size: 13px; border-bottom: 2px solid #e2e8f0; }
            td { padding: 12px; border-bottom: 1px solid #f1f5f9; }
            .btn { text-decoration: none; padding: 6px 12px; border-radius: 6px; font-size: 13px; font-weight: 600; color: #fff; border: none; cursor: pointer; display: inline-block; }
            .btn-blue { background: #2563eb; }
            .btn-red { background: #dc2626; }
            .btn-amber { background: #d97706; }
            .alert { padding: 12px; border-radius: 6px; margin-bottom: 15px; background: #dcfce7; color: #15803d; font-weight: bold; }
        </style>
    </head>
    <body>
        <div class="card">
            <h2>🛒 Merchant Management</h2>
            <div style="margin-top: 15px;">
                <a href="{{ url_for('create_merchant') }}" class="btn btn-blue">+ Add New Merchant</a>
                <a href="{{ url_for('admin_dashboard') }}" class="btn" style="background:#475569;">← Back to Dashboard</a>
            </div>
            <hr style="margin: 20px 0; border:0; border-top:1px solid #e2e8f0;">
            
            {% with messages = get_flashed_messages(with_categories=true) %}
                {% if messages %}
                    {% for category, message in messages %}
                        <div class="alert">{{ message }}</div>
                    {% endfor %}
                {% endif %}
            {% endwith %}

            <table>
                <thead>
                    <tr><th>Username</th><th>Actions</th></tr>
                </thead>
                <tbody>
                    {% for m in merchants %}
                    <tr>
                        <td style="font-weight: 600;">{{ m.username }}</td>
                        <td>
                            <form action="{{ url_for('reset_merchant_password', merchant_id=m.id) }}" method="POST" style="display:inline; margin-right:5px;" onsubmit="return confirm('Reset password for {{ m.username }}?');">
                                <button type="submit" class="btn btn-amber">Reset Password</button>
                            </form>
                            <form action="{{ url_for('delete_merchant', merchant_id=m.id) }}" method="POST" style="display:inline;" onsubmit="return confirm('Delete merchant {{ m.username }}?');">
                                <button type="submit" class="btn btn-red">Delete</button>
                            </form>
                        </td>
                    </tr>
                    {% else %}
                    <tr><td colspan="2" style="text-align:center; color:#94a3b8; padding:20px;">No merchants found.</td></tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </body>
    </html>
    """
    return render_template_string(MERCHANTS_HTML, merchants=all_merchants)

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

    EMP_HTML = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>Employee Portal</title>
        <script src="https://cdn.jsdelivr.net/npm/qrcodejs@1.0.0/qrcode.min.js"></script>
        <style>
            * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
            body { background-color: #f1f5f9; color: #334155; padding-bottom: 50px; }
            .navbar { background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%); padding: 16px 32px; display: flex; justify-content: space-between; align-items: center; color: #fff; }
            .container { max-width: 900px; margin: 30px auto; padding: 0 20px; }
            .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 20px; margin-bottom: 25px; }
            .card { background: #ffffff; padding: 24px; border-radius: 12px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05); }
            .qr-box { text-align: center; margin: 20px 0; }
            #qrcode { display: inline-block; padding: 15px; background: #fff; border: 2px dashed #cbd5e1; border-radius: 12px; }
            table { width: 100%; border-collapse: collapse; text-align: left; }
            th { background-color: #f8fafc; padding: 12px 16px; font-size: 13px; font-weight: 700; color: #475569; border-bottom: 2px solid #e2e8f0; }
            td { padding: 14px 16px; border-bottom: 1px solid #f1f5f9; font-size: 14px; }
            .alert { padding: 12px 18px; border-radius: 8px; margin-bottom: 20px; font-weight: 700; background-color: #dcfce7; color: #15803d; }
        </style>
    </head>
    <body>
        <nav class="navbar">
            <h2>👤 Employee Portal ({{ emp.full_name if emp else user.username }})</h2>
            <div>
                <a href="{{ url_for('employee_change_password') }}" style="color:#38bdf8; text-decoration:none; margin-right:15px; font-weight:600;">🔐 Change Password</a>
                <a href="{{ url_for('logout') }}" style="background:#ef4444; color:#fff; padding:6px 12px; border-radius:6px; text-decoration:none; font-weight:600;">Logout</a>
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
                    <h6 style="color:#64748b; font-size:12px; text-transform:uppercase;">Current Allocation ({{ month }})</h6>
                    <h3 style="font-size:24px; font-weight:800; color:#2563eb; margin-top:5px;">{{ "%.2f"|format(allocated) }} ETB</h3>
                </div>
                <div class="card" style="border-top: 4px solid #ef4444;">
                    <h6 style="color:#64748b; font-size:12px; text-transform:uppercase;">Total Spent</h6>
                    <h3 style="font-size:24px; font-weight:800; color:#ef4444; margin-top:5px;">{{ "%.2f"|format(spent) }} ETB</h3>
                </div>
                <div class="card" style="border-top: 4px solid #16a34a;">
                    <h6 style="color:#64748b; font-size:12px; text-transform:uppercase;">Remaining Balance</h6>
                    <h3 style="font-size:24px; font-weight:800; color:#16a34a; margin-top:5px;">{{ "%.2f"|format(balance) }} ETB</h3>
                </div>
            </div>
            <div class="card" style="margin-bottom: 25px;">
                <h4 style="margin-bottom:10px;">Your Digital Coupon QR Card (Active Cycle: {{ month }})</h4>
                <div class="qr-box">
                    <div id="qrcode"></div>
                    <p style="margin-top:10px; font-family:monospace; font-weight:700; color:#475569;">Token: {{ emp.qr_token if emp else 'N/A' }}</p>
                </div>
            </div>
            <div class="card">
                <h4 style="margin-bottom:15px;">Your Monthly Redemption History</h4>
                <table>
                    <thead><tr><th>Date & Time</th><th>Reference</th><th>Amount Redeemed</th></tr></thead>
                    <tbody>
                        {% for t in transactions %}
                        <tr>
                            <td>{{ t.created_at.strftime('%Y-%m-%d %H:%M:%S') }}</td>
                            <td><code>{{ t.reference }}</code></td>
                            <td style="font-weight:700; color:#ef4444;">-{{ "%.2f"|format(t.amount) }} ETB</td>
                        </tr>
                        {% else %}
                        <tr><td colspan="3" style="text-align:center; color:#94a3b8; padding:20px;">No redemptions for this monthly cycle.</td></tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
        <script>
            {% if emp and emp.qr_token %}
            new QRCode(document.getElementById("qrcode"), { text: "{{ emp.qr_token }}", width: 160, height: 160 });
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
            flash('Password set successfully!', 'success')
            return redirect(url_for('employee_dashboard'))
            
    PWD_HTML = """
    <!DOCTYPE html><html><head><title>Set Password</title>
    <style>body{font-family:sans-serif;background:#f1f5f9;display:flex;justify-content:center;align-items:center;height:100vh;}
    .card{background:#fff;padding:30px;border-radius:12px;width:350px;box-shadow:0 4px 6px rgba(0,0,0,0.1);}
    input{width:100%;padding:10px;margin:10px 0 20px 0;border:1px solid #ccc;border-radius:6px;box-sizing:border-box;}
    button{width:100%;padding:10px;background:#2563eb;color:#fff;border:none;border-radius:6px;font-weight:bold;cursor:pointer;}</style></head>
    <body><div class="card"><h3>🔐 Set New Password</h3>
    <form method="POST"><label>New Password:</label><input type="password" name="new_password" required><button type="submit">Save Password</button></form></div></body></html>
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
        flash('Insufficient employee balance for this monthly cycle!', 'danger')
        return redirect(url_for('merchant_dashboard'))
    db.session.add(Transaction(reference=secrets.token_hex(6).upper(), employee_id=emp.id, merchant_id=session.get('user_id'), amount=amount, month=month))
    db.session.commit()
    flash('Redeemed successfully!', 'success')
    return redirect(url_for('merchant_dashboard'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)