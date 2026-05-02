from flask import Flask, request, jsonify, render_template_string
import mysql.connector
from datetime import datetime, timedelta
import random
import requests
import os
import socket
import requests.packages.urllib3.util.connection as urllib3_cn
from flask import session, redirect

def allowed_gai_family():
    return socket.AF_INET

urllib3_cn.allowed_gai_family = allowed_gai_family

app = Flask(__name__)
app.secret_key = "super_secret_key"

# -------------------------
# CONFIG
# -------------------------
API_KEY_2CHAT = os.environ.get("API_KEY_2CHAT")
FROM_NUMBER = "529992922621"

DB_CONFIG = {
    "host": os.environ.get("DB_HOST"),
    "user": os.environ.get("DB_USER"),
    "password": os.environ.get("DB_PASSWORD"),
    "database": os.environ.get("DB_NAME")
}

def get_db():
    return mysql.connector.connect(**DB_CONFIG)

# -------------------------
# PHONE
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
# WHATSAPP
# -------------------------
def send_whatsapp(phone, message):
    try:
        requests.post(
            "https://api.p.2chat.io/open/whatsapp/send-message",
            json={
                "to_number": phone,
                "from_number": FROM_NUMBER,
                "text": message
            },
            headers={
                "X-User-API-Key": API_KEY_2CHAT,
                "Content-Type": "application/json"
            },
            timeout=10
        )
    except Exception as e:
        print("❌ WhatsApp error:", e)

# -------------------------
# HELPERS
# -------------------------
def get_customer(cursor, phone):
    cursor.execute("SELECT * FROM customers WHERE phone=%s", (phone,))
    return cursor.fetchone()

def create_customer(cursor, conn, phone):
    cursor.execute(
        "INSERT INTO customers (phone, created_at, state) VALUES (%s, %s, %s)",
        (phone, datetime.utcnow(), None)
    )
    conn.commit()
    return cursor.lastrowid

def update_state(cursor, conn, customer_id, state):
    cursor.execute(
        "UPDATE customers SET state=%s WHERE id=%s",
        (state, customer_id)
    )
    conn.commit()

def get_branch_by_code(cursor, code, cafe_id):
    cursor.execute("""
        SELECT id, branch_id FROM cashier_codes
        WHERE code=%s AND cafe_id=%s AND expires_at > NOW() AND used = 0
    """, (code, cafe_id))
    return cursor.fetchone()

def mark_code_used(cursor, conn, code_id):
    cursor.execute("UPDATE cashier_codes SET used=1 WHERE id=%s", (code_id,))
    conn.commit()

def create_purchase(cursor, conn, customer_id, branch_id, cafe_id):
    cursor.execute("""
        INSERT INTO purchases (customer_id, branch_id, cafe_id, created_at)
        VALUES (%s, %s, %s, %s)
    """, (customer_id, branch_id, cafe_id, datetime.utcnow()))
    conn.commit()

def create_reward(cursor, conn, customer_id, branch_id, cafe_id):
    cursor.execute("""
        INSERT INTO rewards (customer_id, branch_id, cafe_id, status)
        VALUES (%s, %s, %s, 'pending')
    """, (customer_id, branch_id, cafe_id))
    conn.commit()

# -------------------------
# ACTIVE CODE
# -------------------------
@app.route("/get_active_code")
def get_active_code():

    if not session.get("user_id"):
        return jsonify({"error": "unauthorized"}), 403

    branch_id = session.get("branch_id")
    cafe_id = session.get("cafe_id")

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute("""
            DELETE FROM cashier_codes 
            WHERE branch_id=%s AND cafe_id=%s AND expires_at < NOW()
        """, (branch_id, cafe_id))

        cursor.execute("""
            SELECT code, expires_at FROM cashier_codes
            WHERE branch_id=%s AND cafe_id=%s AND used=0
            ORDER BY id DESC LIMIT 1
        """, (branch_id, cafe_id))

        result = cursor.fetchone()

        if result:
            remaining = int((result["expires_at"] - datetime.utcnow()).total_seconds())
            return jsonify({"code": result["code"], "expires_in": max(0, remaining)})

        code = str(random.randint(1000, 9999))
        expires_at = datetime.utcnow() + timedelta(seconds=60)

        cursor.execute("""
            INSERT INTO cashier_codes (code, branch_id, cafe_id, expires_at, used)
            VALUES (%s, %s, %s, %s, 0)
        """, (code, branch_id, cafe_id, expires_at))

        conn.commit()

        return jsonify({"code": code, "expires_in": 60})

    finally:
        cursor.close()
        conn.close()

# -------------------------
# LOGIN
# -------------------------
@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT * FROM users 
            WHERE username=%s AND password=%s
        """, (username, password))

        user = cursor.fetchone()

        cursor.close()
        conn.close()

        if user:
            session["user_id"] = user["id"]
            session["branch_id"] = user["branch_id"]
            session["cafe_id"] = user["cafe_id"]
            return redirect("/cashier")

        return "Login incorrecto", 401

    return "<h2>Login</h2>"

# -------------------------
# CASHIER
# -------------------------
@app.route("/cashier")
def cashier():

    if not session.get("user_id"):
        return redirect("/login")

    return render_template_string("""
    <h1>Código activo</h1>
    <div id="code">----</div>
    <div id="countdown"></div>

    <script>
    let seconds = 0;

    async function load(){
        let r = await fetch('/get_active_code')
        let d = await r.json()
        document.getElementById("code").innerText = d.code
        seconds = d.expires_in
    }

    function tick(){
        seconds--
        document.getElementById("countdown").innerText = seconds
        if(seconds <= 0){
            load()
        }
    }

    setInterval(tick,1000)
    setInterval(load,30000)
    load()
    </script>
    """)

# -------------------------
# WEBHOOK
# -------------------------
@app.route("/webhook", methods=["POST"])
def webhook():

    data = request.get_json()

    phone = normalize_phone(data.get("remote_phone_number"))
    text = data.get("message", {}).get("text", "").strip().lower()

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:
        customer = get_customer(cursor, phone)
        customer_id = customer["id"] if customer else create_customer(cursor, conn, phone)

        if text.isdigit():

            # 🔥 AHORA EL CODIGO BUSCA EN TODAS LAS CAFETERIAS
            cursor.execute("""
                SELECT id, branch_id, cafe_id FROM cashier_codes
                WHERE code=%s AND expires_at > NOW() AND used=0
            """, (text,))

            code_data = cursor.fetchone()

            if not code_data:
                send_whatsapp(phone, "❌ Código inválido")
                return jsonify({"ok": True})

            create_purchase(cursor, conn, customer_id, code_data["branch_id"], code_data["cafe_id"])
            mark_code_used(cursor, conn, code_data["id"])

            send_whatsapp(phone, "☕ Compra registrada")

        return jsonify({"ok": True})

    finally:
        cursor.close()
        conn.close()

# -------------------------
# RUN
# -------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)