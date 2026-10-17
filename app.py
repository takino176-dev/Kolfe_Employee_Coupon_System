import os
import secrets
import csv
import io
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, session, send_file
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'super-secret-key-kolfe')

# SQLite Database setup for Render environment
db_path = os.path.join('/tmp', 'coupon_system.db')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', f'sqlite:///{db_path}')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# ================= DATABASE MODELS =================

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), nullable=False)  # 'admin' or 'merchant'

class Employee(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.String(50), unique=True, nullable=False)
    full_name = db.Column(db.String(120), nullable=False)
    sector = db.Column(db.String(120), nullable=False)
    qr_token = db.Column(db.String(100), unique=True, nullable=False)

class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    reference = db.Column(db.String(100), unique=True, nullable=False)
    employee_id = db.Column(db.Integer, db.ForeignKey('employee.id'), nullable=False)
    employee = db.relationship('Employee', backref=db.backref('transactions', lazy=True))
    merchant_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# Initialize Database
with app.app_context():
    db.create_all()

# ================= APP ROUTES =================

@app.route('/')
def index():
    if 'user_id' in session:
        if session.get('role') in ['admin', 'superadmin']:
            return redirect(url_for('admin_dashboard'))
        return redirect(url_for('merchant_dashboard'))
    return redirect(url_for('login'))

@app.route('/setup', methods=['GET', 'POST'])
def setup():
    if User.query.filter_by(role='admin').first():
        flash('Admin user already exists. Please log in.', 'info')
        return redirect(url_for('login'))
        
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        if username and password:
            hashed_pw = generate_password_hash(password)
            admin = User(username=username, password=hashed_pw, role='admin')
            db.session.add(admin)
            db.session.commit()
            flash('Admin account created successfully! Please log in.', 'success')
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
            return redirect(url_for('merchant_dashboard'))
            
        flash('Invalid username or password.', 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out successfully.', 'info')
    return redirect(url_for('login'))

@app.route('/dashboard')
def admin_dashboard():
    if session.get('role') not in ['admin', 'superadmin']:
        flash('Unauthorized access.', 'danger')
        return redirect(url_for('login'))
        
    month = request.args.get('month', datetime.utcnow().strftime('%Y-%m'))
    employees_count = Employee.query.count()
    transactions = Transaction.query.order_by(Transaction.created_at.desc()).limit(10).all()
    total_spent = sum(t.amount for t in transactions)
    
    return render_template('admin.html', 
                           month=month, 
                           employees=employees_count, 
                           allocated=0.00, 
                           spent=total_spent, 
                           collected=total_spent, 
                           transactions=transactions, 
                           lang=session.get('lang', 'en'))

@app.route('/create_merchant', methods=['GET', 'POST'])
def create_merchant():
    if session.get('role') not in ['admin', 'superadmin']:
        flash('Unauthorized access.', 'danger')
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        if not username or not password:
            flash('All fields are required.', 'danger')
            return redirect(url_for('create_merchant'))

        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            flash('Username already exists.', 'danger')
            return redirect(url_for('create_merchant'))
            
        hashed_password = generate_password_hash(password)
        new_merchant = User(
            username=username,
            password=hashed_password,
            role='merchant'
        )
        db.session.add(new_merchant)
        db.session.commit()
        
        flash('Merchant account created successfully!', 'success')
        return redirect(url_for('admin_dashboard'))
        
    return render_template('create_merchant.html')

@app.route('/add_employee', methods=['GET', 'POST'])
def add_employee():
    if session.get('role') not in ['admin', 'superadmin']:
        flash('Unauthorized access.', 'danger')
        return redirect(url_for('login'))
        
    if request.method == 'POST':
        employee_id = request.form.get('employee_id')
        full_name = request.form.get('full_name')
        sector = request.form.get('sector')
        
        if Employee.query.filter_by(employee_id=employee_id).first():
            flash('Employee ID already exists.', 'danger')
            return redirect(url_for('add_employee'))
            
        qr_token = secrets.token_urlsafe(16)
        emp = Employee(employee_id=employee_id, full_name=full_name, sector=sector, qr_token=qr_token)
        db.session.add(emp)
        db.session.commit()
        
        flash('Employee added successfully!', 'success')
        return redirect(url_for('employees'))
        
    return render_template('employee_form.html')

@app.route('/delete_employee/<int:employee_id>', methods=['POST'])
def delete_employee(employee_id):
    if session.get('role') not in ['admin', 'superadmin']:
        flash('Unauthorized access.', 'danger')
        return redirect(url_for('login'))
    
    employee = Employee.query.get_or_404(employee_id)
    db.session.delete(employee)
    db.session.commit()
    
    flash(f'Employee {employee.full_name} deleted successfully.', 'success')
    return redirect(url_for('employees'))

@app.route('/employees')
def employees():
    if session.get('role') not in ['admin', 'superadmin']:
        flash('Unauthorized access.', 'danger')
        return redirect(url_for('login'))
        
    all_employees = Employee.query.all()
    return render_template('employees.html', employees=all_employees)

@app.route('/allocations')
def allocations():
    if session.get('role') not in ['admin', 'superadmin']:
        flash('Unauthorized access.', 'danger')
        return redirect(url_for('login'))
    flash('Monthly coupons module active.', 'info')
    return redirect(url_for('admin_dashboard'))

@app.route('/reports_csv')
def reports_csv():
    if session.get('role') not in ['admin', 'superadmin']:
        flash('Unauthorized access.', 'danger')
        return redirect(url_for('login'))
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['ID', 'Reference', 'Amount', 'Date'])
    for t in Transaction.query.all():
        writer.writerow([t.id, t.reference, t.amount, t.created_at])
    
    byte_output = io.BytesIO(output.getvalue().encode('utf-8'))
    output.close()
    return send_file(byte_output, mimetype='text/csv', download_name='transactions_report.csv', as_attachment=True)

@app.route('/qrlist')
def qrlist():
    if session.get('role') not in ['admin', 'superadmin']:
        flash('Unauthorized access.', 'danger')
        return redirect(url_for('login'))
        
    all_employees = Employee.query.all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['employee_id', 'full_name', 'sector', 'qr_token'])
    for emp in all_employees:
        writer.writerow([emp.employee_id, emp.full_name, emp.sector, emp.qr_token])
    
    byte_output = io.BytesIO(output.getvalue().encode('utf-8'))
    output.close()
    
    return send_file(byte_output, mimetype='text/csv', download_name='employee_qr_list.csv', as_attachment=True)

@app.route('/upload_employees', methods=['GET', 'POST'])
def upload_employees():
    if session.get('role') not in ['admin', 'superadmin']:
        flash('Unauthorized access.', 'danger')
        return redirect(url_for('login'))
        
    if request.method == 'POST':
        file = request.files.get('file')
        if file:
            stream = io.TextIOWrapper(file.stream, encoding='utf-8')
            reader = csv.DictReader(stream)
            for row in reader:
                emp_id = row.get('employee_id')
                if emp_id and not Employee.query.filter_by(employee_id=emp_id).first():
                    qr_token = secrets.token_urlsafe(16)
                    emp = Employee(
                        employee_id=emp_id,
                        full_name=row.get('full_name', ''),
                        sector=row.get('sector', ''),
                        qr_token=qr_token
                    )
                    db.session.add(emp)
            db.session.commit()
            flash('Employees uploaded successfully!', 'success')
            return redirect(url_for('employees'))
            
    return render_template('upload.html')

@app.route('/merchant')
def merchant_dashboard():
    if session.get('role') != 'merchant':
        flash('Unauthorized access.', 'danger')
        return redirect(url_for('login'))
    return render_template('merchant.html')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)