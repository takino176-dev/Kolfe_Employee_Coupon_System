import os
import io
import csv
import json
import base64
import secrets
from datetime import datetime, date, timedelta
from functools import wraps
import openpyxl
from flask import Flask, request, redirect, url_for, flash, render_template, session, send_file, abort
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import qrcode
from apscheduler.schedulers.background import BackgroundScheduler

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'change-this-secret-before-production-' + secrets.token_hex(8))
db_url = os.getenv('DATABASE_URL', 'sqlite:///kolfe_coupons.db')
if db_url.startswith('postgres://'):
    db_url = db_url.replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

try:
    from convertdate import ethiopian
except Exception:
    ethiopian = None

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='employee')
    full_name = db.Column(db.String(200), nullable=False, default='')
    employee_id = db.Column(db.String(80), unique=True, index=True)
    sector = db.Column(db.String(150), nullable=False, default='')
    must_change_password = db.Column(db.Boolean, default=True, nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def set_password(self, value):
        self.password_hash = generate_password_hash(value)
        
    def check_password(self, value):
        return check_password_hash(self.password_hash, value)

class Allocation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    month_key = db.Column(db.String(20), nullable=False, index=True)
    allocated = db.Column(db.Integer, nullable=False, default=0)
    spent = db.Column(db.Integer, nullable=False, default=0)
    expires_at = db.Column(db.Date, nullable=False)
    closed = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User', backref='allocations')
    __table_args__ = (db.UniqueConstraint('user_id', 'month_key', name='uq_user_month'),)
    
    @property
    def remaining(self):
        return max(0, self.allocated - self.spent)

class SectorBudget(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sector = db.Column(db.String(150), unique=True, nullable=False)
    monthly_amount = db.Column(db.Integer, nullable=False, default=0)

class Redemption(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    employee_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    merchant_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    allocation_id = db.Column(db.Integer, db.ForeignKey('allocation.id'), nullable=False)
    amount = db.Column(db.Integer, nullable=False)
    reference = db.Column(db.String(100), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    employee = db.relationship('User', foreign_keys=[employee_user_id])
    merchant = db.relationship('User', foreign_keys=[merchant_user_id])
    allocation = db.relationship('Allocation')

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

def role_required(*roles):
    def deco(fn):
        @wraps(fn)
        @login_required
        def wrapped(*args, **kwargs):
            if current_user.role not in roles:
                abort(403)
            if current_user.must_change_password and request.endpoint not in ('change_password', 'logout', 'static'):
                return redirect(url_for('change_password'))
            return fn(*args, **kwargs)
        return wrapped
    return deco

def ethiopian_info(d=None):
    d = d or date.today()
    if ethiopian:
        ey, em, ed = ethiopian.from_gregorian(d.year, d.month, d.day)
        names = ['መስከረም', 'ጥቅምት', 'ኅዳር', 'ታኅሳስ', 'ጥር', 'የካቲት', 'መጋቢት', 'ሚያዝያ', 'ግንቦት', 'ሰኔ', 'ሐምሌ', 'ነሐሴ', 'ጳጉሜ']
        month_key = f'{ey:04d}-{em:02d}'
        if em == 13:
            ny, nm = ey + 1, 1
        elif em == 12:
            ny, nm = ey, 13
        else:
            ny, nm = ey, em + 1
        next_g = ethiopian.to_gregorian(ny, nm, 1)
        expiry = date(*next_g) - timedelta(days=1)
        return {'year': ey, 'month': em, 'day': ed, 'month_name': names[em-1], 'key': month_key, 'expiry': expiry}
    first_next = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
    return {'year': d.year, 'month': d.month, 'day': d.day, 'month_name': d.strftime('%B'), 'key': d.strftime('%Y-%m'), 'expiry': first_next - timedelta(days=1)}

def qr_data(user):
    return f'Full Name: {user.full_name}\nID: {user.employee_id or ""}\nSector: {user.sector}'

def qr_data_uri(user):
    img = qrcode.make(qr_data(user))
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode()

def current_allocation(user):
    info = ethiopian_info()
    return Allocation.query.filter_by(user_id=user.id, month_key=info['key']).first()

def create_allocation(user, amount, info=None):
    info = info or ethiopian_info()
    existing = Allocation.query.filter_by(user_id=user.id, month_key=info['key']).first()
    if existing:
        existing.allocated = int(amount)
        existing.expires_at = info['expiry']
        existing.closed = False
        return existing
    obj = Allocation(user_id=user.id, month_key=info['key'], allocated=int(amount), spent=0, expires_at=info['expiry'])
    db.session.add(obj)
    return obj

def monthly_rollover():
    with app.app_context():
        info = ethiopian_info()
        Allocation.query.filter(Allocation.month_key != info['key'], Allocation.closed == False).update({'closed': True}, synchronize_session=False)
        budgets = {b.sector: b.monthly_amount for b in SectorBudget.query.all()}
        employees = User.query.filter_by(role='employee', active=True).all()
        for u in employees:
            if not Allocation.query.filter_by(user_id=u.id, month_key=info['key']).first():
                amount = budgets.get(u.sector, 0)
                create_allocation(u, amount, info)
        db.session.commit()

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        u = User.query.filter_by(username=request.form.get('username', '').strip()).first()
        if u and u.active and u.check_password(request.form.get('password', '')):
            login_user(u)
            return redirect(url_for('change_password' if u.must_change_password else 'dashboard'))
        flash('Invalid username/password or inactive account.')
    return render_template('login.html', title='Login')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'POST':
        old = request.form.get('old_password', '')
        new = request.form.get('new_password', '')
        if not current_user.check_password(old):
            flash('Current password is incorrect.')
        elif len(new) < 8:
            flash('New password must contain at least 8 characters.')
        else:
            current_user.set_password(new)
            current_user.must_change_password = False
            db.session.commit()
            flash('Password changed successfully.')
            return redirect(url_for('dashboard'))
    return render_template('change_password.html', title='Change password')

@app.route('/')
@login_required
def dashboard():
    if current_user.must_change_password:
        return redirect(url_for('change_password'))
    info = ethiopian_info()
    if current_user.role == 'employee':
        a = current_allocation(current_user)
        history = Redemption.query.filter_by(employee_user_id=current_user.id).order_by(Redemption.created_at.desc()).limit(20).all()
        return render_template('employee_dashboard.html', title='My balance', info=info, a=a, history=history)
    if current_user.role in ('merchant', 'authority'):
        total = db.session.query(db.func.coalesce(db.func.sum(Redemption.amount), 0)).filter_by(merchant_user_id=current_user.id).scalar()
        recent = Redemption.query.filter_by(merchant_user_id=current_user.id).order_by(Redemption.created_at.desc()).limit(20).all()
        return render_template('operator_dashboard.html', title='Operator dashboard', total=total, recent=recent)
    counts = {r: User.query.filter_by(role=r, active=True).count() for r in ('employee', 'merchant', 'authority', 'admin')}
    info = ethiopian_info()
    spent = db.session.query(db.func.coalesce(db.func.sum(Allocation.spent), 0)).filter_by(month_key=info['key']).scalar()
    alloc = db.session.query(db.func.coalesce(db.func.sum(Allocation.allocated), 0)).filter_by(month_key=info['key']).scalar()
    return render_template('admin_dashboard.html', title='Admin dashboard', counts=counts, info=info, spent=spent, alloc=alloc)

@app.route('/setup', methods=['GET', 'POST'])
def setup_system():
    if User.query.filter_by(role='admin').first():
        flash('Admin account already exists! Please log in.')
        return redirect(url_for('login'))
    if request.method == 'POST':
        username = request.form.get('username', 'admin').strip()
        password = request.form.get('password', '').strip()
        if len(password) < 8:
            flash('Password must be at least 8 characters.')
        else:
            u = User(username=username, full_name='System Administrator', role='admin', must_change_password=False)
            u.set_password(password)
            db.session.add(u)
            db.session.commit()
            flash('Admin account created successfully! Please log in.')
            return redirect(url_for('login'))
    return '''
        <!doctype html>
        <title>System Setup</title>
        <body style="font-family:Arial; padding:40px; max-width:400px; margin:auto; background:#f3f6f9;">
            <div style="background:white; padding:20px; border-radius:8px; box-shadow:0 2px 10px rgba(0,0,0,0.1);">
                <h2>System Setup</h2>
                <p>Create your initial administrator account:</p>
                <form method="post">
                    <label style="font-weight:bold; display:block; margin-top:10px;">Admin Username:</label>
                    <input type="text" name="username" value="admin" style="width:100%; padding:8px; margin-top:5px; border:1px solid #ccc; border-radius:4px;">
                    <label style="font-weight:bold; display:block; margin-top:10px;">Admin Password:</label>
                    <input type="password" name="password" placeholder="At least 8 characters" style="width:100%; padding:8px; margin-top:5px; border:1px solid #ccc; border-radius:4px;">
                    <button type="submit" style="width:100%; padding:10px; background:#176b87; color:#fff; border:none; border-radius:4px; font-weight:bold; margin-top:15px; cursor:pointer;">Create Admin Account</button>
                </form>
            </div>
        </body>
    '''

@app.route('/admin/employees')
@role_required('admin')
def employees():
    employees = User.query.filter_by(role='employee', active=True).order_by(User.employee_id).all()
    return render_template('employees.html', title='Employees', employees=employees)

@app.route('/admin/upload_employees', methods=['GET', 'POST'])
@role_required('admin')
def upload_employees():
    if request.method == 'GET':
        return redirect(url_for('employees'))
        
    file = request.files.get('file')
    if not file or not file.filename:
        flash('ፋይል አልተመረጠም (No file selected)', 'danger')
        return redirect(url_for('employees'))

    try:
        filename_lower = file.filename.lower()
        added_count = 0
        rows = []
        file_bytes = file.read()

        if filename_lower.endswith('.csv'):
            decoded_text = ''
            for enc in ['utf-8-sig', 'utf-8', 'cp1252', 'latin-1']:
                try:
                    decoded_text = file_bytes.decode(enc)
                    break
                except UnicodeDecodeError:
                    continue
            if not decoded_text:
                decoded_text = file_bytes.decode('utf-8', errors='ignore')
            
            stream = io.StringIO(decoded_text)
            raw_rows = list(csv.reader(stream))
            if not raw_rows:
                flash('ባዶ ፋይል ነው (Empty file)', 'danger')
                return redirect(url_for('employees'))
            
            for row in raw_rows[1:]:
                if row and len(row) >= 2:
                    emp_id = str(row[0]).strip() if row[0] is not None else ''
                    full_name = str(row[1]).strip() if row[1] is not None else ''
                    sector = str(row[2]).strip() if len(row) > 2 and row[2] is not None and str(row[2]).strip() else 'ከተማ ውበት'
                    if emp_id and full_name and emp_id.lower() != 'nan' and not emp_id.lower().startswith('employee'):
                        rows.append((emp_id, full_name, sector))

        elif filename_lower.endswith(('.xlsx', '.xls')):
            wb = openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
            sheet = wb.active
            for row in sheet.iter_rows(min_row=2, values_only=True):
                if row and any(row):
                    val_id = row[0] if len(row) > 0 else None
                    val_name = row[1] if len(row) > 1 else None
                    val_sector = row[2] if len(row) > 2 else None
                    
                    emp_id = str(val_id).strip() if val_id is not None else ''
                    full_name = str(val_name).strip() if val_name is not None else ''
                    sector = str(val_sector).strip() if val_sector is not None and str(val_sector).strip() else 'ከተማ ውበት'

                    if emp_id and full_name and emp_id.lower() != 'nan' and not emp_id.lower().startswith('employee'):
                        rows.append((emp_id, full_name, sector))
            wb.close()
        else:
            flash('እባክዎ ትክክለኛ የ CSV ወይም Excel (.xlsx) ፋይል ይምረጡ', 'danger')
            return redirect(url_for('employees'))

        # Pre-fetch all existing employee IDs into a set to avoid database query timeouts
        existing_ids = {u.employee_id for u in User.query.filter_by(role='employee').all()}
        new_users = []

        for emp_id, full_name, sector in rows:
            if emp_id not in existing_ids:
                username = f'emp_{emp_id}'
                new_user = User(
                    username=username,
                    employee_id=emp_id,
                    full_name=full_name,
                    sector=sector,
                    role='employee',
                    must_change_password=True
                )
                new_user.set_password('123456')
                new_users.append(new_user)
                existing_ids.add(emp_id) # Prevent duplicate entries within the same file upload
                added_count += 1

        if new_users:
            db.session.add_all(new_users)
            db.session.commit()

        flash(f'በተሳካ ሁኔታ {added_count} ሰራተኞች ተጭነዋል!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'ፋይልን በማንበብ ጊዜ ስህተት ተፈጥሯል: {str(e)}', 'danger')

    return redirect(url_for('employees'))
@app.route('/admin/allocations', methods=['GET', 'POST'])
@role_required('admin')
def allocations():
    info = ethiopian_info()
    if request.method == 'POST':
        action = request.form.get('action'); amount = request.form.get('amount', '0')
        try: amount = int(amount)
        except: amount = -1
        if amount < 0: flash('Amount must be zero or greater.'); return redirect(url_for('allocations'))
        if action == 'single':
            u = User.query.filter_by(employee_id=request.form.get('employee_id', '').strip(), role='employee', active=True).first()
            if not u: flash('Employee not found or inactive.')
            else: create_allocation(u, amount, info); db.session.commit(); flash(f'Allocated {amount} ETB to {u.full_name} for {info["key"]}.')
        elif action == 'sector':
            sector = request.form.get('sector', '').strip()
            if sector == 'ALL':
                users = User.query.filter_by(role='employee', active=True).all()
                for u in users: create_allocation(u, amount, info)
                db.session.commit(); flash(f'Allocated {amount} ETB to all {len(users)} employees across all sectors.')
            else:
                users = User.query.filter_by(role='employee', sector=sector, active=True).all()
                for u in users: create_allocation(u, amount, info)
                db.session.commit(); flash(f'Allocated {amount} ETB to {len(users)} employees in sector {sector}.')
        return redirect(url_for('allocations'))
    sectors = [x[0] for x in db.session.query(User.sector).filter_by(role='employee').distinct().order_by(User.sector).all()]
    recent = Allocation.query.filter_by(month_key=info['key']).order_by(Allocation.created_at.desc()).limit(100).all()
    return render_template('allocations.html', title='Monthly allocations', info=info, sectors=sectors, recent=recent)

@app.route('/admin/budgets', methods=['GET', 'POST'])
@role_required('admin')
def budgets():
    if request.method == 'POST':
        sector = request.form.get('sector', '').strip()
        try: amount = int(request.form.get('amount', '0'))
        except: amount = -1
        if not sector or amount < 0: flash('Enter a sector and a non-negative amount.')
        else:
            b = SectorBudget.query.filter_by(sector=sector).first()
            if not b: b = SectorBudget(sector=sector); db.session.add(b)
            b.monthly_amount = amount; db.session.commit(); flash('Sector monthly default saved.')
        return redirect(url_for('budgets'))
    return render_template('budgets.html', title='Sector budgets', budgets=SectorBudget.query.order_by(SectorBudget.sector).all(), sectors=[x[0] for x in db.session.query(User.sector).filter_by(role='employee').distinct().order_by(User.sector).all()])

@app.route('/admin/print-hub')
@role_required('admin')
def print_hub():
    sectors = [x[0] for x in db.session.query(User.sector).filter_by(role='employee').distinct().order_by(User.sector).all()]
    employees = User.query.filter_by(role='employee', active=True).order_by(User.employee_id).all()
    info = ethiopian_info()
    default_month = f'{info["month_name"]} ወር {info["year"]} ዓ.ም'
    return render_template('print_hub.html', title='Print Hub', sectors=sectors, employees=employees, default_month=default_month)

@app.route('/admin/print')
@role_required('admin')
def print_coupons():
    ids = request.args.get('ids', '').strip(); sector = request.args.get('sector', '').strip(); eid = request.args.get('employee_id', '').strip()
    q = User.query.filter_by(role='employee', active=True)
    if ids:
        try: q = q.filter(User.id.in_([int(x) for x in ids.split(',') if x.strip()]))
        except: pass
    elif eid: q = q.filter_by(employee_id=eid)
    elif sector: q = q.filter_by(sector=sector)
    else: abort(400, 'Choose an employee, sector, or selected employee IDs.')
    users = q.order_by(User.employee_id).all(); info = ethiopian_info()
    org = request.args.get('org', 'ኮልፌ ቀራኒዮ ክፍለ ከተማ አስተዳደር - ዲዛይንና ግንባታ ፑል')
    title = request.args.get('coupon_title', 'የሰራተኞች ኩፖን መጠቀሚያ'); month = request.args.get('month', f'{info["month_name"]} ወር {info["year"]} ዓ.ም')
    val_str = request.args.get('value', '40 ብር')
    usage_note = request.args.get('usage_note', 'ለአንድ ጊዜ አገልግሎት ብቻ የሚውል')
    try:
        denomination = int(''.join(filter(str.isdigit, val_str))) or 40
    except:
        denomination = 40

    budgets = {b.sector: b.monthly_amount for b in SectorBudget.query.all()}
    print_data = []
    for u in users:
        alloc = current_allocation(u)
        allocated_amount = alloc.allocated if alloc else budgets.get(u.sector, 480)
        coupon_count = int(allocated_amount / denomination) if denomination > 0 else 0
        print_data.append({
            'user': u,
            'allocation': alloc,
            'allocated_amount': allocated_amount,
            'coupon_count': coupon_count
        })

    return render_template('print.html', title='Print coupons', print_data=print_data, org=org, coupon_title=title, month=month, value=val_str, usage_note=usage_note, qr_data_uri=qr_data_uri)

@app.route('/admin/print-ids')
@role_required('admin')
def print_ids():
    ids = request.args.get('ids', '').strip(); sector = request.args.get('sector', '').strip(); eid = request.args.get('employee_id', '').strip()
    q = User.query.filter_by(role='employee', active=True)
    if ids:
        try: q = q.filter(User.id.in_([int(x) for x in ids.split(',') if x.strip()]))
        except: pass
    elif eid: q = q.filter_by(employee_id=eid)
    elif sector: q = q.filter_by(sector=sector)
    else: abort(400, 'Choose an employee, sector, or selected employee IDs.')
    users = q.order_by(User.employee_id).all()
    org = request.args.get('org', 'ኮልፌ ቀራኒዮ ክፍለ ከተማ አስተዳደር - ዲዛይንና ግንባታ ፑል')
    return render_template('print_ids.html', title='Print Employee QR Badges', users=users, org=org, qr_data_uri=qr_data_uri)

@app.route('/redeem', methods=['GET', 'POST'])
@role_required('merchant', 'authority')
def redeem():
    found = None; allocation = None
    if request.method == 'POST':
        raw = request.form.get('qr_data', '').strip(); eid = request.form.get('employee_id', '').strip(); amount = request.form.get('amount', '')
        if raw:
            try:
                data = json.loads(raw)
                eid = str(data.get('employee_id', '')).strip()
            except (json.JSONDecodeError, TypeError):
                eid = ''
                for line in raw.splitlines():
                    if ':' in line:
                        key, value = line.split(':', 1)
                        if key.strip().lower() in ('id', 'employee id', 'employee_id'):
                            eid = value.strip(); break
                if not eid:
                    eid = raw.strip() if '\n' not in raw and ':' not in raw else ''
                if not eid:
                    flash('QR text must contain an ID field.'); return render_template('redeem.html', title='Redeem coupons', found=None, allocation=None)
        found = User.query.filter_by(employee_id=eid, role='employee', active=True).first()
        if not found: flash('Employee was not found or is inactive.')
        else:
            allocation = current_allocation(found)
            if request.form.get('confirm') == 'yes':
                try: value = int(amount)
                except: value = 0
                if not allocation: flash('No allocation exists for the current Ethiopian month.')
                elif allocation.closed or value <= 0: flash('Enter a valid positive amount.')
                elif value > allocation.remaining: flash(f'Insufficient balance. Remaining: {allocation.remaining} ETB.')
                else:
                    allocation.spent += value
                    r = Redemption(employee_user_id=found.id, merchant_user_id=current_user.id, allocation_id=allocation.id, amount=value, reference=secrets.token_urlsafe(12)); db.session.add(r); db.session.commit(); flash(f'Redemption successful: {value} ETB. Remaining: {allocation.remaining} ETB.'); return redirect(url_for('redeem'))
    return render_template('redeem.html', title='Redeem coupons', found=found, allocation=allocation)

@app.route('/admin/reports')
@role_required('admin')
def reports():
    info = ethiopian_info()
    sector_rows = db.session.query(User.sector, db.func.coalesce(db.func.sum(Allocation.allocated), 0), db.func.coalesce(db.func.sum(Allocation.spent), 0)).join(Allocation, Allocation.user_id == User.id).filter(User.role == 'employee', Allocation.month_key == info['key']).group_by(User.sector).all()
    merchants = db.session.query(User.username, User.full_name, db.func.coalesce(db.func.sum(Redemption.amount), 0)).join(Redemption, Redemption.merchant_user_id == User.id).filter(User.role.in_(['merchant', 'authority']), db.func.strftime('%Y-%m', Redemption.created_at) == datetime.utcnow().strftime('%Y-%m')).group_by(User.id).all() if 'sqlite' in app.config['SQLALCHEMY_DATABASE_URI'] else []
    redemptions = Redemption.query.order_by(Redemption.created_at.desc()).limit(500).all()
    if request.args.get('download') == 'csv':
        out = io.StringIO(); w = csv.writer(out); w.writerow(['Timestamp UTC', 'Employee ID', 'Employee Name', 'Sector', 'Merchant Username', 'Amount ETB', 'Reference'])
        for r in redemptions: w.writerow([r.created_at.isoformat(), r.employee.employee_id, r.employee.full_name, r.employee.sector, r.merchant.username, r.amount, r.reference])
        return send_file(io.BytesIO(out.getvalue().encode('utf-8-sig')), mimetype='text/csv', as_attachment=True, download_name='coupon_redemptions.csv')
    return render_template('reports.html', title='Reports', info=info, sector_rows=sector_rows, merchants=merchants, redemptions=redemptions)

@app.route('/admin/users', methods=['GET', 'POST'])
@role_required('admin')
def users_admin():
    if request.method == 'POST':
        username = request.form.get('username', '').strip(); role = request.form.get('role', 'merchant'); name = request.form.get('full_name', '').strip(); sector = request.form.get('sector', '').strip(); password = request.form.get('password', '')
        if role not in ('admin', 'authority', 'merchant') or not username or not name or len(password) < 8: flash('Use a username, full name, valid role and password of at least 8 characters.')
        elif User.query.filter_by(username=username).first(): flash('Username already exists.')
        else:
            u = User(username=username, role=role, full_name=name, sector=sector, must_change_password=True); u.set_password(password); db.session.add(u); db.session.commit(); flash(f'{role.title()} account created.')
        return redirect(url_for('users_admin'))
    users = User.query.filter(User.role.in_(['admin', 'authority', 'merchant'])).order_by(User.role, User.username).all()
    return render_template('users_admin.html', title='Operator accounts', users=users)

@app.route('/health')
def health():
    return {'status': 'ok'}

with app.app_context():
    db.create_all()
    admin_username = os.getenv('ADMIN_USERNAME', 'admin')
    admin_password = os.getenv('ADMIN_PASSWORD', 'ChangeMe123!')
    if not User.query.filter_by(role='admin').first():
        u = User(username=admin_username, full_name='System Administrator', role='admin', must_change_password=True)
        u.set_password(admin_password or secrets.token_urlsafe(12))
        db.session.add(u)
        db.session.commit()

scheduler = BackgroundScheduler(daemon=True)
scheduler.add_job(monthly_rollover, 'cron', hour=0, minute=10, id='ethiopian_month_rollover', replace_existing=True)
scheduler.start()

if __name__ == '__main__':
   app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)), debug=True)