import mysql.connector
import pandas as pd
from datetime import datetime, timedelta
import os
import time
import schedule
import requests
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet

# -------------------------
# CONFIG
# -------------------------
API_KEY_2CHAT = os.environ.get("API_KEY_2CHAT")
FROM_NUMBER = "529991900664"

DB_CONFIG = {
    "host": os.environ.get("DB_HOST"),
    "user": os.environ.get("DB_USER"),
    "password": os.environ.get("DB_PASSWORD"),
    "database": os.environ.get("DB_NAME")
}

# -------------------------
# DB
# -------------------------
def get_db():
    return mysql.connector.connect(**DB_CONFIG)

# -------------------------
# SEND WHATSAPP FILE
# -------------------------
def send_file(phone, file_url, caption):
    try:
        requests.post(
            "https://api.p.2chat.io/open/whatsapp/send-file",
            json={
                "to_number": phone,
                "from_number": FROM_NUMBER,
                "url": file_url,
                "filename": "reporte.pdf",
                "caption": caption
            },
            headers={
                "X-User-API-Key": API_KEY_2CHAT,
                "Content-Type": "application/json"
            },
            timeout=10
        )
    except Exception as e:
        print("Error sending file:", e)

# -------------------------
# GENERATE DATA
# -------------------------
def get_daily_data(cafe_id):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    today = datetime.utcnow().date()

    cursor.execute("""
        SELECT 
            b.name as branch,
            COUNT(p.id) as total_sales
        FROM purchases p
        JOIN branches b ON p.branch_id = b.id
        WHERE p.cafe_id = %s
        AND DATE(p.created_at) = %s
        GROUP BY b.id
    """, (cafe_id, today))

    data = cursor.fetchall()

    cursor.close()
    conn.close()

    return data

# -------------------------
# CREATE CSV
# -------------------------
def create_csv(data, cafe_id):
    df = pd.DataFrame(data)
    filename = f"report_{cafe_id}.csv"
    df.to_csv(filename, index=False)
    return filename

# -------------------------
# CREATE PDF
# -------------------------
def create_pdf(data, cafe_id):
    filename = f"report_{cafe_id}.pdf"

    doc = SimpleDocTemplate(filename)
    styles = getSampleStyleSheet()

    elements = []

    elements.append(Paragraph(f"Reporte Diario - Cafetería {cafe_id}", styles["Title"]))
    elements.append(Paragraph(f"Fecha: {datetime.utcnow().date()}", styles["Normal"]))

    table_data = [["Sucursal", "Ventas"]]

    for row in data:
        table_data.append([row["branch"], row["total_sales"]])

    table = Table(table_data)

    table.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.grey),
        ("TEXTCOLOR",(0,0),(-1,0),colors.white),
        ("GRID",(0,0),(-1,-1),1,colors.black)
    ]))

    elements.append(table)

    doc.build(elements)

    return filename

# -------------------------
# UPLOAD FILE (simple hack)
# -------------------------
def upload_file_local(filename):
    """
    ⚠️ IMPORTANTE:
    Railway no permite servir archivos directo fácilmente,
    así que aquí tienes 2 opciones:

    1. Subir a S3 (recomendado)
    2. O exponer endpoint /download

    Por ahora simulamos URL:
    """
    return f"https://your-domain.com/files/{filename}"

# -------------------------
# GET ADMINS
# -------------------------
def get_admins():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT phone, cafe_id FROM users
        WHERE role = 'admin'
    """)

    admins = cursor.fetchall()

    cursor.close()
    conn.close()

    return admins

# -------------------------
# MAIN REPORT JOB
# -------------------------
def generate_and_send_reports():

    print("⏰ Generando reportes...")

    admins = get_admins()

    cafes_done = {}

    for admin in admins:

        cafe_id = admin["cafe_id"]

        if cafe_id in cafes_done:
            continue

        data = get_daily_data(cafe_id)

        if not data:
            print(f"No data for cafe {cafe_id}")
            continue

        pdf_file = create_pdf(data, cafe_id)
        csv_file = create_csv(data, cafe_id)

        file_url = upload_file_local(pdf_file)

        # enviar a todos los admins de esa cafetería
        for a in admins:
            if a["cafe_id"] == cafe_id:
                send_file(
                    a["phone"],
                    file_url,
                    "📊 Reporte diario listo"
                )

        cafes_done[cafe_id] = True

# -------------------------
# SCHEDULER
# -------------------------
schedule.every().day.at("19:00").do(generate_and_send_reports)

print("🟢 Scheduler activo...")

while True:
    schedule.run_pending()
    time.sleep(30)