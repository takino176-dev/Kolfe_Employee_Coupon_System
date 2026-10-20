import os
from flask import Flask, render_template, request, redirect, url_for, flash, session
import pandas as pd
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = 'super_secret_key_change_in_production'

DB_NAME = 'coupon_system.db'

def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Admins / Users Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT DEFAULT 'admin'
        )
    ''')
    
    # Employees Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            sector TEXT NOT NULL,
            phone TEXT,
            status TEXT DEFAULT 'Active'
        )
    ''')
    
    # Merchants Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS merchants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT,
            location TEXT
        )
    ''')

    # Allocations / Coupons Record Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS allocations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER,
            month TEXT NOT NULL,
            year TEXT NOT NULL,
            coupon_count INTEGER DEFAULT 24,
            coupon_value REAL DEFAULT 40.0,
            status TEXT DEFAULT 'Issued',
            FOREIGN KEY (employee_id) REFERENCES employees (id)
        )
    ''')
    
    # Default admin creation if none exists
    cursor.execute('SELECT * FROM users WHERE username = ?', ('admin',))
    if not cursor.fetchone():
        hashed_pw = generate_password_hash('admin123')
        cursor.execute('INSERT INTO users (username, password, role) VALUES (?, ?, ?)', ('admin', hashed_pw, 'admin'))
        
    conn.commit()
    conn.close()

init_db()

# --- ROUTES ---

@app.route('/')
def index():
    if 'user' in session:
        return redirect(url_for('admin'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        conn = get_db_connection()
        user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        conn.close()
        
        if user and check_password_hash(user['password'], password):
            session['user'] = user['username']
            session['role'] = user['role']
            return redirect(url_for('admin'))
        else:
            flash('የተሳሳተ የተጠቃሚ ስም ወይም የይለፍ ቃል!', 'danger')
            
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/admin')
def admin():
    if 'user' not in session:
        return redirect(url_for('login'))
        
    conn = get_db_connection()
    emp_count = conn.execute('SELECT COUNT(*) FROM employees').fetchone()[0]
    alloc_count = conn.execute('SELECT COUNT(*) FROM allocations').fetchone()[0]
    merchant_count = conn.execute('SELECT COUNT(*) FROM merchants').fetchone()[0]
    conn.close()
    
    return render_template('admin.html', emp_count=emp_count, alloc_count=alloc_count, merchant_count=merchant_count)

@app.route('/employees')
def employees():
    if 'user' not in session:
        return redirect(url_for('login'))
        
    conn = get_db_connection()
    emp_list = conn.execute('SELECT * FROM employees ORDER BY id DESC').fetchall()
    conn.close()
    return render_template('employees.html', employees=emp_list)

@app.route('/employee/add', methods=['GET', 'POST'])
def employee_form():
    if 'user' not in session:
        return redirect(url_for('login'))
        
    if request.method == 'POST':
        full_name = request.form.get('full_name')
        sector = request.form.get('sector')
        phone = request.form.get('phone')
        
        conn = get_db_connection()
        conn.execute('INSERT INTO employees (full_name, sector, phone) VALUES (?, ?, ?)', (full_name, sector, phone))
        conn.commit()
        conn.close()
        
        flash('ሰራተኛው በትክክል ተመዝግቧል!', 'success')
        return redirect(url_for('employees'))
        
    return render_template('employee_form.html')

@app.route('/upload', methods=['GET', 'POST'])
def upload():
    if 'user' not in session:
        return redirect(url_for('login'))
        
    if request.method == 'POST':
        file = request.files.get('file')
        if file and file.filename.endswith(('.xlsx', '.xls')):
            df = pd.read_excel(file)
            conn = get_db_connection()
            
            for _, row in df.iterrows():
                name = row.get('ስም') or row.get('full_name') or row.get('Full Name')
                sector = row.get('ዘርፍ') or row.get('ተቋም') or row.get('sector') or 'አልተገለጸም'
                phone = row.get('ስልክ') or row.get('phone') or ''
                
                if name:
                    conn.execute('INSERT INTO employees (full_name, sector, phone) VALUES (?, ?, ?)', (str(name), str(sector), str(phone)))
            
            conn.commit()
            conn.close()
            flash('የሰራተኞች መረጃ ከ Excel በትክክል ተጭኗል!', 'success')
            return redirect(url_for('employees'))
        else:
            flash('እባክዎን ትክክለኛ Excel (.xlsx) ፋይል ይምረጡ!', 'danger')
            
    return render_template('upload.html')

@app.route('/print_cards')
def print_cards():
    if 'user' not in session:
        return redirect(url_for('login'))
        
    month = request.args.get('month', 'መስከረም')
    year = request.args.get('year', '2019')
    
    conn = get_db_connection()
    employees_data = conn.execute('SELECT * FROM employees WHERE status = "Active"').fetchall()
    sectors = [row['sector'] for row in conn.execute('SELECT DISTINCT sector FROM employees').fetchall()]
    conn.close()
    
    return render_template('print_cards.html', employees=employees_data, sectors=sectors, month=month, year=year)

@app.route('/merchants')
def merchants():
    if 'user' not in session:
        return redirect(url_for('login'))
        
    conn = get_db_connection()
    merchants_list = conn.execute('SELECT * FROM merchants').fetchall()
    conn.close()
    return render_template('merchants.html', merchants=merchants_list)

@app.route('/create_merchant', methods=['GET', 'POST'])
def create_merchant():
    if 'user' not in session:
        return redirect(url_for('login'))
        
    if request.method == 'POST':
        name = request.form.get('name')
        phone = request.form.get('phone')
        location = request.form.get('location')
        
        conn = get_db_connection()
        conn.execute('INSERT INTO merchants (name, phone, location) VALUES (?, ?, ?)', (name, phone, location))
        conn.commit()
        conn.close()
        
        flash('አገልግሎት ሰጪው (Merchant) ተመዝግቧል!', 'success')
        return redirect(url_for('merchants'))
        
    return render_template('create_merchant.html')

@app.route('/allocations')
def allocations():
    if 'user' not in session:
        return redirect(url_for('login'))
        
    conn = get_db_connection()
    allocs = conn.execute('''
        SELECT a.*, e.full_name, e.sector 
        FROM allocations a 
        JOIN employees e ON a.employee_id = e.id 
        ORDER BY a.id DESC
    ''').fetchall()
    conn.close()
    return render_template('allocations.html', allocations=allocs)

@app.route('/reports')
def reports():
    if 'user' not in session:
        return redirect(url_for('login'))
        
    return render_template('reports.html')

if __name__ == '__main__':
    app.run(debug=True)