from flask import Flask, request, jsonify, render_template_string, session, redirect
import mysql.connector
from datetime import datetime, timedelta
import random
import requests
import os
import socket
import requests.packages.urllib3.util.connection as urllib3_cn

# -------------------------
# 🌐 FORCE IPV4 (Railway fix)
# -------------------------
def allowed_gai_family():
    return socket.AF_INET

urllib3_cn.allowed_gai_family = allowed_gai_family

# -------------------------
# 🚀 APP INIT (FIXED ORDER)
# -------------------------
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "super_secret_key")

# -------------------------
# 🔐 CONFIG
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
        payload = {
            "to_number": phone,
            "from_number": FROM_NUMBER,
            "text": message
        }

        headers = {
            "X-User-API-Key": API_KEY_2CHAT,
            "Content-Type": "application/json"
        }

        res = requests.post(
            "https://api.p.2chat.io/open/whatsapp/send-message",
            json=payload,
            headers=headers,
            timeout=10
        )

        print("📤", res.status_code, res.text)

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

def get_branch_by_code(cursor, code):
    cursor.execute("""
        SELECT id, branch_id FROM cashier_codes
        WHERE code=%s AND expires_at > NOW() AND used = 0
    """, (code,))
    return cursor.fetchone()

def mark_code_used(cursor, conn, code_id):
    cursor.execute("UPDATE cashier_codes SET used = 1 WHERE id = %s", (code_id,))
    conn.commit()

def create_purchase(cursor, conn, customer_id, branch_id):
    cursor.execute("""
        INSERT INTO purchases (customer_id, branch_id, created_at)
        VALUES (%s, %s, %s)
    """, (customer_id, branch_id, datetime.utcnow()))
    conn.commit()

def count_current_cycle(cursor, customer_id, branch_id):
    cursor.execute("""
        SELECT COUNT(*) as total
        FROM purchases
        WHERE customer_id=%s AND branch_id=%s
        AND created_at > IFNULL(
            (SELECT MAX(redeemed_at)
             FROM rewards
             WHERE customer_id=%s AND branch_id=%s AND status='redeemed'),
            '2000-01-01'
        )
    """, (customer_id, branch_id, customer_id, branch_id))

    return cursor.fetchone()["total"]

def get_last_redeem(cursor, customer_id, branch_id):
    cursor.execute("""
        SELECT redeemed_at
        FROM rewards
        WHERE customer_id=%s AND branch_id=%s AND status='redeemed'
        ORDER BY redeemed_at DESC
        LIMIT 1
    """, (customer_id, branch_id))

    return cursor.fetchone()

def create_reward(cursor, conn, customer_id, branch_id):
    cursor.execute("""
        INSERT INTO rewards (customer_id, branch_id, status)
        VALUES (%s, %s, 'pending')
    """, (customer_id, branch_id))
    conn.commit()

def get_pending_reward(cursor, customer_id, branch_id):
    cursor.execute("""
        SELECT id FROM rewards
        WHERE customer_id=%s AND branch_id=%s AND status='pending'
        LIMIT 1
    """, (customer_id, branch_id))
    return cursor.fetchone()

def redeem_reward(cursor, conn, reward_id):
    cursor.execute("""
        UPDATE rewards SET status='redeemed', redeemed_at=%s
        WHERE id=%s
    """, (datetime.utcnow(), reward_id))
    conn.commit()

def closing():
    return "\n\n👉 Para registrar otra compra escribe *hola*"

# -------------------------
# 🔐 LOGIN
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
            return redirect("/cashier")

        return "Login incorrecto", 401

    return """
    <h2>Login Cafetería</h2>
    <form method="POST">
        Usuario: <input name="username"><br><br>
        Password: <input name="password" type="password"><br><br>
        <button type="submit">Entrar</button>
    </form>
    """

# -------------------------
# 🔐 ACTIVE CODE (PROTECTED)
# -------------------------
@app.route("/get_active_code")
def get_active_code():

    if not session.get("user_id"):
        return jsonify({"error": "unauthorized"}), 403

    branch_id = session.get("branch_id")

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute("DELETE FROM cashier_codes WHERE branch_id=%s AND expires_at < NOW()", (branch_id,))

        cursor.execute("""
            SELECT code, expires_at FROM cashier_codes
            WHERE branch_id=%s AND used=0
            ORDER BY id DESC LIMIT 1
        """, (branch_id,))

        result = cursor.fetchone()

        if result:
            remaining = int((result["expires_at"] - datetime.utcnow()).total_seconds())
            return jsonify({"code": result["code"], "expires_in": max(0, remaining)})

        code = str(random.randint(1000, 9999))
        expires_at = datetime.utcnow() + timedelta(seconds=60)

        cursor.execute("""
            INSERT INTO cashier_codes (code, branch_id, expires_at, used)
            VALUES (%s, %s, %s, 0)
        """, (code, branch_id, expires_at))

        conn.commit()

        return jsonify({"code": code, "expires_in": 60})

    finally:
        cursor.close()
        conn.close()

# -------------------------
# 💻 CASHIER UI
# -------------------------
@app.route("/cashier")
def cashier():

    if not session.get("user_id"):
        return redirect("/login")

    return render_template_string("""
    <h1>Código activo</h1>
    <h2 id="code">----</h2>
    <h3 id="countdown"></h3>

    <script>
        let secondsLeft = 0;

        function fetchCode() {
            fetch('/get_active_code')
            .then(r => r.json())
            .then(d => {
                document.getElementById("code").innerText = d.code;
                secondsLeft = d.expires_in;
            });
        }

        function tick() {
            if (secondsLeft <= 0) {
                fetchCode();
                return;
            }

            secondsLeft--;

            document.getElementById("countdown").innerText =
                "Expira en: " + secondsLeft + "s";
        }

        fetchCode();
        setInterval(tick, 1000);
    </script>
    """)

# -------------------------
# LOGOUT
# -------------------------
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

# -------------------------
# RUN
# -------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))