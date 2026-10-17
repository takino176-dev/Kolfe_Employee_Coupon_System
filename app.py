import os,io,csv,secrets,string
from datetime import datetime,date
from decimal import Decimal,InvalidOperation
from functools import wraps
from flask import Flask,render_template,request,redirect,url_for,flash,session,send_file,abort
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect
from werkzeug.security import generate_password_hash,check_password_hash
from werkzeug.utils import secure_filename
import qrcode
from openpyxl import load_workbook

app=Flask(__name__)
app.config["SECRET_KEY"]=os.environ.get("SECRET_KEY","CHANGE_THIS_SECRET_BEFORE_DEPLOYMENT")
url=os.environ.get("DATABASE_URL","sqlite:///coupon_system.db")
if url.startswith("postgres://"): url=url.replace("postgres://","postgresql://",1)
app.config["SQLALCHEMY_DATABASE_URI"]=url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"]=False
app.config["MAX_CONTENT_LENGTH"]=10*1024*1024
db=SQLAlchemy(app); csrf=CSRFProtect(app)
def now(): return datetime.utcnow()
class User(db.Model):
 id=db.Column(db.Integer,primary_key=True); username=db.Column(db.String(80),unique=True,nullable=False,index=True); password_hash=db.Column(db.String(255),nullable=False); role=db.Column(db.String(20),nullable=False); must_change_password=db.Column(db.Boolean,default=True,nullable=False); active=db.Column(db.Boolean,default=True,nullable=False); created_at=db.Column(db.DateTime,default=now)
class Employee(db.Model):
 id=db.Column(db.Integer,primary_key=True); employee_id=db.Column(db.String(80),unique=True,nullable=False,index=True); full_name=db.Column(db.String(180),nullable=False); sector=db.Column(db.String(120),default=""); user_id=db.Column(db.Integer,db.ForeignKey("user.id"),unique=True,nullable=False); qr_token=db.Column(db.String(64),unique=True,nullable=False,index=True); created_at=db.Column(db.DateTime,default=now); user=db.relationship("User",backref="employee_profile")
class Allocation(db.Model):
 id=db.Column(db.Integer,primary_key=True); employee_id=db.Column(db.Integer,db.ForeignKey("employee.id"),nullable=False,index=True); month=db.Column(db.String(7),nullable=False,index=True); amount=db.Column(db.Numeric(12,2),nullable=False); released=db.Column(db.Boolean,default=False,nullable=False); released_by=db.Column(db.Integer,db.ForeignKey("user.id")); released_at=db.Column(db.DateTime); employee=db.relationship("Employee",backref="allocations"); __table_args__=(db.UniqueConstraint("employee_id","month",name="uq_employee_month"),)
class MerchantMonth(db.Model):
 id=db.Column(db.Integer,primary_key=True); month=db.Column(db.String(7),unique=True,nullable=False); collected_total=db.Column(db.Numeric(12,2),default=0,nullable=False); closed=db.Column(db.Boolean,default=False,nullable=False); closed_by=db.Column(db.Integer,db.ForeignKey("user.id")); closed_at=db.Column(db.DateTime)
class Transaction(db.Model):
 id=db.Column(db.Integer,primary_key=True); employee_id=db.Column(db.Integer,db.ForeignKey("employee.id"),nullable=False,index=True); merchant_user_id=db.Column(db.Integer,db.ForeignKey("user.id"),nullable=False); month=db.Column(db.String(7),nullable=False,index=True); amount=db.Column(db.Numeric(12,2),nullable=False); reference=db.Column(db.String(32),unique=True,nullable=False); created_at=db.Column(db.DateTime,default=now,index=True); employee=db.relationship("Employee",backref="transactions"); merchant=db.relationship("User",backref="merchant_transactions")
class AuditLog(db.Model):
 id=db.Column(db.Integer,primary_key=True); actor_user_id=db.Column(db.Integer,db.ForeignKey("user.id")); action=db.Column(db.String(100),nullable=False); details=db.Column(db.Text,default=""); created_at=db.Column(db.DateTime,default=now)
def audit(a,d=""): db.session.add(AuditLog(actor_user_id=session.get("user_id"),action=a,details=d))
def user(): return db.session.get(User,session.get("user_id")) if session.get("user_id") else None
@app.context_processor
def globals_(): return {"current_user":user(),"lang":session.get("lang","en")}
def tr(en,am): return am if session.get("lang")=="am" else en
def login_required(f):
 @wraps(f)
 def w(*a,**k):
  u=user()
  if not u or not u.active: session.clear(); flash(tr("Please sign in.","እባክዎ ይግቡ።"),"error"); return redirect(url_for("login"))
  if u.must_change_password and request.endpoint not in ("change_password","logout","set_language","static"): return redirect(url_for("change_password"))
  return f(*a,**k)
 return w
def roles(*rs):
 def deco(f):
  @wraps(f)
  @login_required
  def w(*a,**k):
   if user().role not in rs: abort(403)
   return f(*a,**k)
  return w
 return deco
def monthkey(): return request.values.get("month",date.today().strftime("%Y-%m"))
def cash(v): return Decimal(v or 0).quantize(Decimal("0.01"))
def temp_password():
 chars=string.ascii_letters+string.digits+"!@#$%&*"
 return "".join(secrets.choice(chars) for _ in range(12))
def newuser(name,pw,role):
 u=User(username=name,password_hash=generate_password_hash(pw),role=role,must_change_password=True); db.session.add(u); db.session.flush(); return u
def balance(e,m):
 a=Allocation.query.filter_by(employee_id=e.id,month=m,released=True).first()
 allocated=cash(a.amount) if a else Decimal("0.00")
 spent=cash(db.session.query(db.func.coalesce(db.func.sum(Transaction.amount),0)).filter_by(employee_id=e.id,month=m).scalar())
 return allocated,cash(allocated-spent)
@app.route("/")
def home():
 u=user()
 if not u:return redirect(url_for("login"))
 if u.must_change_password:return redirect(url_for("change_password"))
 return redirect(url_for({"admin":"admin","merchant":"merchant","employee":"employee"}[u.role]))
@app.route("/language/<language>")
def set_language(language):
 if language in ("en","am"):session["lang"]=language
 return redirect(request.referrer or url_for("home"))
@app.route("/login",methods=["GET","POST"])
def login():
 if request.method=="POST":
  u=User.query.filter_by(username=request.form.get("username","").strip()).first()
  if u and u.active and check_password_hash(u.password_hash,request.form.get("password","")):
   session.clear();session["user_id"]=u.id;session["lang"]=request.form.get("lang","en") if request.form.get("lang") in ("en","am") else "en"
   return redirect(url_for("change_password") if u.must_change_password else url_for("home"))
  flash(tr("Invalid username or password.","የተጠቃሚ ስም ወይም ይለፍ ቃል ትክክል አይደለም።"),"error")
 return render_template("login.html")
@app.route("/logout")
def logout():session.clear();return redirect(url_for("login"))
@app.route("/change-password",methods=["GET","POST"])
@login_required
def change_password():
 u=user()
 if request.method=="POST":
  old=request.form.get("old_password","");new=request.form.get("new_password","")
  if not check_password_hash(u.password_hash,old):flash("Current password is incorrect.","error")
  elif len(new)<8:flash("Password must be at least 8 characters.","error")
  elif new!=request.form.get("confirm_password",""):flash("Passwords do not match.","error")
  else:u.password_hash=generate_password_hash(new);u.must_change_password=False;audit("password_changed",u.username);db.session.commit();flash("Password updated.","success");return redirect(url_for("home"))
 return render_template("change_password.html")
@app.route("/setup",methods=["GET","POST"])
def setup():
 if User.query.count():abort(404)
 if request.method=="POST":
  name=request.form.get("username","").strip();pw=request.form.get("password","")
  if not name or len(pw)<8 or pw!=request.form.get("confirm_password",""):flash("Enter username and matching password (8+ characters).","error")
  else:u=newuser(name,pw,"admin");u.must_change_password=False;audit("initial_admin_created",name);db.session.commit();return redirect(url_for("login"))
 return render_template("setup.html")
@app.route("/admin")
@roles("admin")
def admin():
 m=monthkey();ec=Employee.query.count();alloc=cash(db.session.query(db.func.coalesce(db.func.sum(Allocation.amount),0)).filter_by(month=m,released=True).scalar());spent=cash(db.session.query(db.func.coalesce(db.func.sum(Transaction.amount),0)).filter_by(month=m).scalar());mm=MerchantMonth.query.filter_by(month=m).first();tx=Transaction.query.filter_by(month=m).order_by(Transaction.created_at.desc()).limit(20).all()
 return render_template("admin.html",month=m,employees=ec,allocated=alloc,spent=spent,collected=cash(mm.collected_total if mm else 0),transactions=tx)
@app.route("/admin/employees")
@roles("admin")
def employees():
 q=request.args.get("q","").strip();page=max(1,int(request.args.get("page",1)));query=Employee.query
 if q:query=query.filter(db.or_(Employee.employee_id.ilike(f"%{q}%"),Employee.full_name.ilike(f"%{q}%"),Employee.sector.ilike(f"%{q}%")))
 rows=query.order_by(Employee.employee_id).paginate(page=page,per_page=100,error_out=False)
 return render_template("employees.html",rows=rows,q=q)
@app.route("/admin/employees/add",methods=["GET","POST"])
@roles("admin")
def add_employee():
 if request.method=="POST":
  eid=request.form.get("employee_id","").strip();name=request.form.get("full_name","").strip();sector=request.form.get("sector","").strip();username=request.form.get("username","").strip()
  if not eid or not name or not username:flash("ID, full name and username are required.","error")
  elif Employee.query.filter_by(employee_id=eid).first() or User.query.filter_by(username=username).first():flash("Employee ID or username already exists.","error")
  else:
   pw=temp_password();u=newuser(username,pw,"employee");e=Employee(employee_id=eid,full_name=name,sector=sector,user_id=u.id,qr_token=secrets.token_urlsafe(32));db.session.add(e);audit("employee_created",eid);db.session.commit();flash(f"Created {eid}. Temporary password (shown once): {pw}","success");return redirect(url_for("employees"))
 return render_template("employee_form.html")
@app.route("/admin/upload-employees",methods=["GET","POST"])
@roles("admin")
def upload_employees():
 if request.method=="POST":
  f=request.files.get("file")
  if not f or not f.filename:flash("Choose .xlsx or .csv.","error");return redirect(url_for("upload_employees"))
  filename=secure_filename(f.filename).lower()
  try:
   if filename.endswith(".xlsx"):
    raw=list(load_workbook(f,read_only=True,data_only=True).active.iter_rows(values_only=True));headers=[str(x or "").strip().lower().replace(" ","_") for x in raw[0]];data=[dict(zip(headers,r)) for r in raw[1:]]
   elif filename.endswith(".csv"):
    data=[{str(k or "").strip().lower().replace(" ","_"):v for k,v in r.items()} for r in csv.DictReader(io.TextIOWrapper(f.stream,encoding="utf-8-sig"))]
   else:raise ValueError("Only .xlsx and .csv supported.")
   created=0;skipped=0;creds=[];issues=[]
   for i,r in enumerate(data,2):
    eid=str(r.get("employee_id",r.get("id","")) or "").strip();name=str(r.get("full_name",r.get("name","")) or "").strip();sector=str(r.get("sector",r.get("department","")) or "").strip();uname=str(r.get("username",eid) or eid).strip()
    if not eid or not name:skipped+=1;issues.append(f"row {i}: ID/name missing");continue
    if Employee.query.filter_by(employee_id=eid).first() or User.query.filter_by(username=uname).first():skipped+=1;issues.append(f"row {i}: duplicate {eid}");continue
    pw=temp_password();u=newuser(uname,pw,"employee");e=Employee(employee_id=eid,full_name=name,sector=sector,user_id=u.id,qr_token=secrets.token_urlsafe(32));db.session.add(e);db.session.flush();creds.append({"id":eid,"name":name,"username":uname,"password":pw});created+=1
   audit("bulk_employee_upload",f"created={created};skipped={skipped}");db.session.commit();session["creds"]=creds;flash(f"Imported {created}; skipped {skipped}. "+ " | ".join(issues[:4]),"success" if created else "error");return redirect(url_for("upload_employees"))
  except Exception as ex:db.session.rollback();flash(f"Import failed: {ex}","error")
 creds=session.pop("creds",[])
 return render_template("upload.html",creds=creds)
@app.route("/admin/qr-list.csv")
@roles("admin")
def qrlist():
 out=io.StringIO();w=csv.writer(out);w.writerow(["employee_id","full_name","sector","qr_token"])
 for e in Employee.query.order_by(Employee.employee_id).yield_per(500):w.writerow([e.employee_id,e.full_name,e.sector,e.qr_token])
 return send_file(io.BytesIO(out.getvalue().encode("utf-8-sig")),mimetype="text/csv",as_attachment=True,download_name="employee_qr_list.csv")
@app.route("/qr/<token>.png")
@login_required
def qr_image(token):
 e=Employee.query.filter_by(qr_token=token).first_or_404()
 if user().role=="employee" and e.user_id!=user().id:abort(403)
 out=io.BytesIO();qrcode.make(token).save(out,format="PNG");out.seek(0);return send_file(out,mimetype="image/png")
@app.route("/admin/allocations",methods=["GET","POST"])
@roles("admin")
def allocations():
 m=monthkey()
 if request.method=="POST":
  try:
   action=request.form.get("action");days=int(request.form.get("working_days","0"));rate=cash(request.form.get("daily_rate","0"))
   if days<0 or days>31 or rate<0:raise ValueError("Working days must be 0–31 and rate cannot be negative.")
   if action=="prepare":
    made=0
    for e in Employee.query.join(User).filter(User.active.is_(True)).yield_per(500):
     a=Allocation.query.filter_by(employee_id=e.id,month=m).first()
     if a and a.released:continue
     if not a:a=Allocation(employee_id=e.id,month=m,amount=rate*days);db.session.add(a);made+=1
     else:a.amount=rate*days
    audit("allocations_prepared",f"{m};days={days};rate={rate};new={made}");db.session.commit();flash(f"Prepared allocations for {m}. New records: {made}.","success")
   elif action=="release":
    pending=Allocation.query.filter_by(month=m,released=False).all()
    for a in pending:a.released=True;a.released_by=user().id;a.released_at=now()
    audit("allocations_released",f"{m};count={len(pending)}");db.session.commit();flash(f"Released {len(pending)} allocations.","success")
   return redirect(url_for("allocations",month=m))
  except Exception as ex:db.session.rollback();flash(str(ex),"error")
 rows=Allocation.query.filter_by(month=m).join(Employee).order_by(Employee.employee_id).limit(1000).all()
 total=sum((cash(a.amount) for a in rows),Decimal("0.00"))
 return render_template("allocations.html",month=m,rows=rows,total=total,released=Allocation.query.filter_by(month=m,released=True).count(),pending=Allocation.query.filter_by(month=m,released=False).count())
@app.route("/admin/reset-password/<int:uid>",methods=["POST"])
@roles("admin")
def reset_password(uid):
 u=db.session.get(User,uid) or abort(404);pw=temp_password();u.password_hash=generate_password_hash(pw);u.must_change_password=True;audit("password_reset",f"user={u.username}");db.session.commit();flash(f"Temporary password for {u.username} (shown once): {pw}","success");return redirect(request.referrer or url_for("employees"))
@app.route("/admin/close",methods=["GET","POST"])
@roles("admin")
def close_month():
 m=monthkey();record=MerchantMonth.query.filter_by(month=m).first();total=cash(db.session.query(db.func.coalesce(db.func.sum(Transaction.amount),0)).filter_by(month=m).scalar());count=Transaction.query.filter_by(month=m).count()
 if request.method=="POST":
  if record and record.closed:flash("Month already closed.","error")
  else:
   if not record:record=MerchantMonth(month=m,collected_total=total);db.session.add(record)
   record.collected_total=total;record.closed=True;record.closed_by=user().id;record.closed_at=now();audit("month_closed",f"{m};total={total};count={count}");db.session.commit();flash("Month closed; records retained.","success")
  return redirect(url_for("close_month",month=m))
 return render_template("close.html",month=m,record=record,total=total,count=count)
@app.route("/admin/reports")
@roles("admin")
def reports():
 m=monthkey();txs=Transaction.query.filter_by(month=m).order_by(Transaction.created_at.desc()).limit(2000).all()
 return render_template("reports.html",month=m,txs=txs)
@app.route("/admin/reports.csv")
@roles("admin")
def reports_csv():
 m=monthkey();out=io.StringIO();w=csv.writer(out);w.writerow(["reference","month","timestamp_utc","employee_id","employee_name","sector","amount","merchant"])
 for t in Transaction.query.filter_by(month=m).order_by(Transaction.created_at).yield_per(500):w.writerow([t.reference,t.month,t.created_at.isoformat(),t.employee.employee_id,t.employee.full_name,t.employee.sector,str(t.amount),t.merchant.username])
 return send_file(io.BytesIO(out.getvalue().encode("utf-8-sig")),mimetype="text/csv",as_attachment=True,download_name=f"coupon_transactions_{m}.csv")
@app.route("/employee")
@roles("employee")
def employee():
 e=Employee.query.filter_by(user_id=user().id).first_or_404();m=monthkey();a,remaining=balance(e,m);spent=cash(a-remaining);txs=Transaction.query.filter_by(employee_id=e.id,month=m).order_by(Transaction.created_at.desc()).limit(100).all()
 return render_template("employee.html",e=e,month=m,allocated=a,remaining=remaining,spent=spent,txs=txs)
@app.route("/merchant")
@roles("merchant")
def merchant():
 m=monthkey();mm=MerchantMonth.query.filter_by(month=m).first();total=cash(db.session.query(db.func.coalesce(db.func.sum(Transaction.amount),0)).filter_by(month=m).scalar());txs=Transaction.query.filter_by(month=m).order_by(Transaction.created_at.desc()).limit(100).all()
 return render_template("merchant.html",month=m,total=total,txs=txs,closed=bool(mm and mm.closed))
@app.route("/merchant/charge",methods=["POST"])
@roles("merchant")
def charge():
 lookup=request.form.get("employee_lookup","").strip()
 try:
  amount=cash(request.form.get("amount","0"))
  if amount<=0:raise ValueError("Amount must be greater than zero.")
  e=Employee.query.filter_by(qr_token=lookup).first() or Employee.query.filter_by(employee_id=lookup).first()
  if not e:raise ValueError("Employee QR token or ID not found.")
  m=date.today().strftime("%Y-%m");mm=MerchantMonth.query.filter_by(month=m).first()
  if mm and mm.closed:raise ValueError("This month is closed.")
  allocated,remaining=balance(e,m)
  if allocated<=0:raise ValueError("No released allocation for this employee this month.")
  if amount>remaining:raise ValueError(f"Insufficient balance. Remaining: {remaining}")
  if not mm:mm=MerchantMonth(month=m,collected_total=Decimal("0.00"));db.session.add(mm)
  tx=Transaction(employee_id=e.id,merchant_user_id=user().id,month=m,amount=amount,reference=secrets.token_hex(8).upper());db.session.add(tx);mm.collected_total=cash(mm.collected_total+amount);audit("merchant_charge",f"{tx.reference};{e.employee_id};{amount}");db.session.commit();flash(f"Payment recorded. Reference {tx.reference}; employee remaining {cash(remaining-amount)}.","success")
 except (InvalidOperation,ValueError) as ex:db.session.rollback();flash(str(ex),"error")
 except Exception:db.session.rollback();flash("Payment failed. Please retry or contact admin.","error")
 return redirect(url_for("merchant"))
@app.errorhandler(403)
def forbidden(e):return render_template("message.html",title="Access denied",message="You do not have permission to view this page."),403
@app.errorhandler(404)
def missing(e):return render_template("message.html",title="Not found",message="Page not found."),404
with app.app_context():db.create_all()
if __name__=="__main__":app.run(host="0.0.0.0",port=int(os.environ.get("PORT","5000")))


@app.route('/delete_employee/<int:employee_id>', methods=['POST'])
def delete_employee(employee_id):
    if session.get('role') != 'admin':
        flash('Unauthorized access.', 'danger')
        return redirect(url_for('login'))
    
    employee = Employee.query.get_or_404(employee_id)
    db.session.delete(employee)
    db.session.commit()
    
    flash(f'Employee {employee.full_name} deleted successfully.', 'success')
    return redirect(url_for('employees'))




@app.route('/create_merchant', methods=['GET', 'POST'])
def create_merchant():
    # Allow access if user is logged in
    if 'user_id' not in session and 'role' not in session:
        flash('Please log in first.', 'danger')
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        merchant_name = request.form.get('merchant_name')
        
        # Check if username exists
        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            flash('Username already exists.', 'danger')
            return redirect(url_for('create_merchant'))
            
        hashed_password = generate_password_hash(password)
        new_merchant = User(
            username=username, 
            password=hashed_password, 
            role='merchant', 
            merchant_name=merchant_name
        )
        db.session.add(new_merchant)
        db.session.commit()
        
        flash('Merchant account created successfully!', 'success')
        return redirect(url_for('admin_dashboard'))
        
    return render_template('create_merchant.html')
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