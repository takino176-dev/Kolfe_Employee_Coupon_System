<!DOCTYPE html>
<html lang="am">
<head>
    <meta charset="UTF-8">
    <title>Print Coupon Cards - Kolfe System</title>
    <script src="https://cdn.jsdelivr.net/npm/qrcodejs@1.0.0/qrcode.min.js"></script>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: 'Segoe UI', Tahoma, Arial, sans-serif; background: #f1f5f9; padding: 15px; color: #1e293b; }

        /* Control Panel (Hidden during printing) */
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

        /* Grid Layout: 22 items per page in Landscape */
        .print-grid {
            display: grid;
            grid-template-columns: repeat(6, 1fr); /* 6 columns */
            gap: 6px;
            width: 100%;
            margin: 0 auto;
        }

        /* Compact Coupon Card */
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
            height: 145px; /* Compact height for 22 per page */
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

        /* Landscape A4 Print Setup */
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

    <!-- Control Panel -->
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

    <!-- Printable Grid Container -->
    <div id="printGrid" class="print-grid"></div>

    <script>
        // Employee data passed from Flask server
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
            grid.innerHTML = ''; // Clear previous cards
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

                    // Render QR code token for this coupon card instance
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

        // Initialize cards on page load
        window.onload = function() {
            generateCards();
        };
    </script>
</body>
</html>