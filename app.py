@app.route('/admin/upload_employees', methods=['GET', 'POST'])
@role_required('admin')
def upload_employees():
    if request.method == 'GET':
        return redirect(url_for('employees'))
        
    file = request.files.get('file')
    if not file or not file.filename:
        flash('ፋይል አልተመረጠም', 'danger')
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
            reader = list(csv.reader(stream))
            if not reader:
                flash('ባዶ ፋይል ነው', 'danger')
                return redirect(url_for('employees'))
            
            header_row = [str(h).strip().lower() if h is not None else '' for h in reader[0]]
            id_idx = -1
            name_idx = -1
            sector_idx = -1
            
            for i, h in enumerate(header_row):
                if any(k in h for k in ['id', 'መለያ', 'ቁጥር', 'លេខ']) and id_idx == -1:
                    id_idx = i
                elif any(k in h for k in ['name', 'ስም']) and name_idx == -1:
                    name_idx = i
                elif any(k in h for k in ['sector', 'department', 'መስሪያ', 'ክፍል', 'የስራ', 'መሥሪያቤት']) and sector_idx == -1:
                    sector_idx = i

            if id_idx == -1: id_idx = 0
            if name_idx == -1: name_idx = 1
            if sector_idx == -1 and len(header_row) > 2: sector_idx = 2

            for row in reader[1:]:
                if row and len(row) > max(id_idx, name_idx):
                    emp_id = str(row[id_idx]).strip() if row[id_idx] is not None else ''
                    full_name = str(row[name_idx]).strip() if row[name_idx] is not None else ''
                    sector = str(row[sector_idx]).strip() if sector_idx != -1 and len(row) > sector_idx and row[sector_idx] is not None and str(row[sector_idx]).strip() else 'ከተማ ውበት'
                    if emp_id and full_name and emp_id.lower() != 'nan' and emp_id != reader[0][id_idx]:
                        rows.append((emp_id, full_name, sector))

        elif filename_lower.endswith(('.xlsx', '.xls')):
            wb = openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
            sheet = wb.active
            iter_rows = list(sheet.iter_rows(values_only=True))
            if not iter_rows:
                flash('ባዶ ፋይል ነው', 'danger')
                return redirect(url_for('employees'))

            header_row = [str(h).strip().lower() if h is not None else '' for h in iter_rows[0]]
            id_idx = -1
            name_idx = -1
            sector_idx = -1

            for i, h in enumerate(header_row):
                if any(k in h for k in ['id', 'መለያ', 'ቁጥር', 'លេខ']) and id_idx == -1:
                    id_idx = i
                elif any(k in h for k in ['name', 'ስም']) and name_idx == -1:
                    name_idx = i
                elif any(k in h for k in ['sector', 'department', 'መስሪያ', 'ክፍል', 'የስራ', 'መሥሪያቤት']) and sector_idx == -1:
                    sector_idx = i

            if id_idx == -1: id_idx = 0
            if name_idx == -1: name_idx = 1
            if sector_idx == -1 and len(header_row) > 2: sector_idx = 2

            for row in iter_rows[1:]:
                if row and len(row) > max(id_idx, name_idx):
                    val_id = row[id_idx] if id_idx < len(row) else None
                    val_name = row[name_idx] if name_idx < len(row) else None
                    val_sector = row[sector_idx] if sector_idx != -1 and sector_idx < len(row) else None
                    
                    emp_id = str(val_id).strip() if val_id is not None else ''
                    full_name = str(val_name).strip() if val_name is not None else ''
                    sector = str(val_sector).strip() if val_sector is not None and str(val_sector).strip() else 'ከተማ ውበት'

                    if emp_id and full_name and emp_id.lower() != 'nan':
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