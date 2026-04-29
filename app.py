from flask import Flask, request, jsonify, render_template_string
import mysql.connector
from datetime import datetime, timedelta
import random
import requests
import os

app = Flask(__name__)

# 🔐 2CHAT CONFIG
API_KEY_2CHAT = os.environ.get("API_KEY_2CHAT")
URL_2CHAT = "https://api.p.2chat.io/open/whatsapp/send-message"

# 🔌 DB CONFIG
DB_CONFIG = {
    "host": os.environ.get("DB_HOST"),
    "user": os.environ.get("DB_USER"),
    "password": os.environ.get("DB_PASSWORD"),
    "database": os.environ.get("DB_NAME")
}

def get_db():
    return mysql.connector.connect(**DB_CONFIG)

# -------------------------
# 📱 NORMALIZE PHONE
# -------------------------
def normalize_phone(phone):
    if not phone:
        return None

    phone = phone.replace("+", "").replace(" ", "").strip()

    if phone.startswith("52"):
        return phone

    if len(phone) == 10:
        return "52" + phone

    return phone

# -------------------------
# 📲 SEND WHATSAPP
# -------------------------
def send_whatsapp(phone, message):
    try:
        if not API_KEY_2CHAT:
            print("❌ API KEY NO CONFIGURADA")
            return

        phone = normalize_phone(phone)

        payload = {
            "to_number": phone,
            "message": message
        }

        headers = {
            "X-User-API-Key": API_KEY_2CHAT,
            "Content-Type": "application/json"
        }

        res = requests.post(URL_2CHAT, json=payload, headers=headers, timeout=10)

        print("📤 WhatsApp STATUS:", res.status_code)
        print("📤 WhatsApp RESPONSE:", res.text)

    except Exception as e:
        print("❌ Error WhatsApp:", str(e))

# -------------------------
# HELPERS
# -------------------------
def get_customer(cursor, phone):
    cursor.execute("SELECT * FROM customers WHERE phone=%s", (phone,))
    return cursor.fetchone()

def create_customer(cursor, conn, phone):
    cursor.execute(
        "INSERT INTO customers (phone, created_at) VALUES (%s, %s)",
        (phone, datetime.utcnow())
    )
    conn.commit()
    return cursor.lastrowid

def validate_code(cursor, code, branch_id):
    cursor.execute("""
        SELECT id FROM cashier_codes 
        WHERE code=%s AND branch_id=%s AND expires_at > NOW()
    """, (code, branch_id))
    return cursor.fetchone() is not None

def create_purchase(cursor, conn, customer_id, branch_id):
    cursor.execute(
        "INSERT INTO purchases (customer_id, branch_id, created_at) VALUES (%s, %s, %s)",
        (customer_id, branch_id, datetime.utcnow())
    )
    conn.commit()

def count_purchases(cursor, customer_id):
    cursor.execute(
        "SELECT COUNT(*) as total FROM purchases WHERE customer_id=%s",
        (customer_id,)
    )
    result = cursor.fetchone()
    return result["total"] if result else 0

def create_reward(cursor, conn, customer_id):
    cursor.execute(
        "INSERT INTO rewards (customer_id, reward_type, status) VALUES (%s, %s, %s)",
        (customer_id, "free_coffee", "pending")
    )
    conn.commit()

# -------------------------
# 🔐 ACTIVE CODE (FIXED)
# -------------------------
@app.route("/get_active_code")
def get_active_code():
    branch_id = request.args.get("branch", 1)

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute("""
            DELETE FROM cashier_codes 
            WHERE branch_id=%s AND expires_at < NOW()
        """, (branch_id,))

        cursor.execute("""
            SELECT code, expires_at FROM cashier_codes
            WHERE branch_id=%s ORDER BY id DESC LIMIT 1
        """, (branch_id,))

        result = cursor.fetchone()

        if result:
            remaining = int((result["expires_at"] - datetime.utcnow()).total_seconds())

            return jsonify({
                "code": result["code"],
                "expires_in": max(0, remaining)
            })

        code = str(random.randint(1000, 9999))
        expires_at = datetime.utcnow() + timedelta(seconds=30)

        cursor.execute("""
            INSERT INTO cashier_codes (code, branch_id, expires_at)
            VALUES (%s, %s, %s)
        """, (code, branch_id, expires_at))

        conn.commit()

        return jsonify({
            "code": code,
            "expires_in": 30
        })

    finally:
        cursor.close()
        conn.close()

# -------------------------
# 💻 CASHIER (FIXED TIMER)
# -------------------------
@app.route("/cashier")
def cashier():
    branch_id = request.args.get("branch", 1)

    return render_template_string(f"""
    <h1>Código activo</h1>
    <h2 id="code">----</h2>
    <h3 id="countdown"></h3>

    <script>
        let secondsLeft = 0;

        function fetchCode() {{
            fetch('/get_active_code?branch={branch_id}')
            .then(r => r.json())
            .then(d => {{
                document.getElementById("code").innerText = d.code;
                secondsLeft = d.expires_in;
            }});
        }}

        function tick() {{
            if (secondsLeft <= 0) {{
                fetchCode();
                return;
            }}

            secondsLeft--;

            const m = Math.floor(secondsLeft / 60);
            const s = secondsLeft % 60;

            document.getElementById("countdown").innerText =
                "Renueva en: " + m + ":" + String(s).padStart(2, "0");
        }}

        fetchCode();
        setInterval(tick, 1000);
        setInterval(fetchCode, 30000);
    </script>
    """)

# -------------------------
# 📩 WEBHOOK WHATSAPP (CORE)
# -------------------------
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    print("📩 Incoming:", data)

    try:
        phone = normalize_phone(data.get("remote_phone_number"))
        text = data.get("message", {}).get("text", "").strip().lower()

        if not phone:
            return jsonify({"reply": "Error leyendo número"})

        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        try:
            customer = get_customer(cursor, phone)

            if not customer:
                customer_id = create_customer(cursor, conn, phone)
            else:
                customer_id = customer["id"]

            # 🔹 STATUS
            if text in ["status", "puntos"]:
                total = count_purchases(cursor, customer_id)
                return jsonify({"reply": f"☕ Llevas {total} cafés acumulados"})

            # 🔹 CODIGO
            if text.isdigit():
                branch_id = 1

                if not validate_code(cursor, text, branch_id):
                    return jsonify({"reply": "❌ Código inválido o expirado"})

                create_purchase(cursor, conn, customer_id, branch_id)

                total = count_purchases(cursor, customer_id)

                if total % 9 == 0:
                    create_reward(cursor, conn, customer_id)
                    return jsonify({"reply": "🎉 ¡Café GRATIS desbloqueado!"})

                return jsonify({"reply": f"☕ Compra registrada\nLlevas {total} cafés"})

            # 🔹 DEFAULT
            return jsonify({
                "reply": "👋 Bienvenido\n\nEnvía el código del ticket ☕\n\nEscribe *status* para ver tus cafés"
            })

        finally:
            cursor.close()
            conn.close()

    except Exception as e:
        print("❌ Error webhook:", str(e))
        return jsonify({"error": str(e)})

# -------------------------
# RUN
# -------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))