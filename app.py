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
            decoded_text = None
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
            
            # Read starting from row index 1 (skipping header row 0)
            for row in raw_rows[1:]:
                if row and len(row) >= 2:
                    emp_id = str(row[0]).strip() if row[0] is not None else ''
                    full_name = str(row[1]).strip() if row[1] is not None else ''
                    sector = str(row[2]).strip() if len(row) > 2 and row[2] is not None and str(row[2]).strip() else 'ከተማ ውበት'
                    if emp_id and full_name and emp_id.lower() != 'nan' and not emp_id.lower().startswith('employee'):
                        rows.append((emp_id, full_name, sector))

        elif filename_lower.endswith(('.xlsx', '.xls')):
            wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
            sheet = wb.active
            iter_rows = list(sheet.iter_rows(values_only=True))
            if not iter_rows:
                flash('ባዶ ፋይል ነው (Empty file)', 'danger')
                return redirect(url_for('employees'))

            # Read starting from row index 1 (skipping header row 0)
            for row in iter_rows[1:]:
                if row and len(row) >= 2:
                    val_id = row[0]
                    val_name = row[1]
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

        for emp_id, full_name, sector in rows:
            existing = User.query.filter_by(employee_id=emp_id).first()
            if not existing:
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
                db.session.add(new_user)
                added_count += 1

        db.session.commit()
        flash(f'በተሳካ ሁኔታ {added_count} ሰራተኞች ተጭነዋል!', 'success')
    except Exception as e:
        flash(f'ፋይልን በማንበብ ጊዜ ስህተት ተፈጥሯል: {str(e)}', 'danger')

    return redirect(url_for('employees'))