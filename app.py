from flask import Flask, request, jsonify, render_template_string
import mysql.connector
from datetime import datetime, timedelta
import random
import requests
import os
import socket
import requests.packages.urllib3.util.connection as urllib3_cn

def allowed_gai_family():
    return socket.AF_INET

urllib3_cn.allowed_gai_family = allowed_gai_family

app = Flask(__name__)

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

# -------------------------
# 🔌 DB
# -------------------------
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
        "INSERT INTO customers (phone, created_at) VALUES (%s, %s)",
        (phone, datetime.utcnow())
    )
    conn.commit()
    return cursor.lastrowid

def update_state(cursor, conn, customer_id, state):
    cursor.execute(
        "UPDATE customers SET state=%s WHERE customer_id=%s",
        (state, customer_id)
    )
    conn.commit()

def get_branch_by_code(cursor, code):
    cursor.execute("""
        SELECT branch_id FROM cashier_codes
        WHERE code=%s AND expires_at > NOW()
    """, (code,))
    return cursor.fetchone()

def create_purchase(cursor, conn, customer_id, branch_id):
    cursor.execute("""
        INSERT INTO purchases (customer_id, branch_id, created_at)
        VALUES (%s, %s, %s)
    """, (customer_id, branch_id, datetime.utcnow()))
    conn.commit()

def count_purchases_by_branch(cursor, customer_id, branch_id):
    cursor.execute("""
        SELECT COUNT(*) as total 
        FROM purchases 
        WHERE customer_id=%s AND branch_id=%s
    """, (customer_id, branch_id))
    return cursor.fetchone()["total"]

def get_all_points(cursor, customer_id):
    cursor.execute("""
        SELECT branch_id, COUNT(*) as total
        FROM purchases
        WHERE customer_id=%s
        GROUP BY branch_id
    """, (customer_id,))
    return cursor.fetchall()

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

# -------------------------
# 🔐 ACTIVE CODE
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
            return jsonify({"code": result["code"], "expires_in": max(0, remaining)})

        code = str(random.randint(1000, 9999))
        expires_at = datetime.utcnow() + timedelta(seconds=60)

        cursor.execute("""
            INSERT INTO cashier_codes (code, branch_id, expires_at)
            VALUES (%s, %s, %s)
        """, (code, branch_id, expires_at))

        conn.commit()

        return jsonify({"code": code, "expires_in": 60})

    finally:
        cursor.close()
        conn.close()

# -------------------------
# 💻 CASHIER
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
# 📩 WEBHOOK (BOT CORE)
# -------------------------
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    print("📩", data)

    phone = normalize_phone(data.get("remote_phone_number"))
    text = data.get("message", {}).get("text", "").strip().lower()

    if not phone:
        return jsonify({"status": "no phone"}), 200

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:
        customer = get_customer(cursor, phone)
        customer_id = customer["id"] if customer else create_customer(cursor, conn, phone)

        state = customer.get("state") if customer else None
        response = ""

        # -------------------------
        # STATUS
        # -------------------------
        if text in ["status", "puntos"]:
            rows = get_all_points(cursor, customer_id)

            if not rows:
                response = "☕ Aún no tienes compras registradas."
            else:
                msg = "📊 Tus cafés:\n\n"
                for r in rows:
                    msg += f"Sucursal {r['branch_id']}: {r['total']} cafés\n"
                response = msg

        # -------------------------
        # REDIMIR
        # -------------------------
        elif text == "redimir":
            update_state(cursor, conn, customer_id, "redeem_wait_code")
            response = "☕ Envia el código del cajero para validar tu café gratis"

        elif state == "redeem_wait_code" and text.isdigit():
            code_data = get_branch_by_code(cursor, text)

            if not code_data:
                response = "❌ Código inválido o expirado"
            else:
                branch_id = code_data["branch_id"]
                reward = get_pending_reward(cursor, customer_id, branch_id)

                if not reward:
                    response = "❌ No tienes recompensas disponibles en esta sucursal"
                else:
                    redeem_reward(cursor, conn, reward["id"])
                    response = "🎉 Café GRATIS aplicado ☕"

            update_state(cursor, conn, customer_id, None)

        # -------------------------
        # REGISTRAR COMPRA
        # -------------------------
        elif text.isdigit():
            code_data = get_branch_by_code(cursor, text)

            if not code_data:
                response = "❌ Código inválido o expirado"
            else:
                branch_id = code_data["branch_id"]

                create_purchase(cursor, conn, customer_id, branch_id)
                total = count_purchases_by_branch(cursor, customer_id, branch_id)

                if total % 9 == 0:
                    create_reward(cursor, conn, customer_id, branch_id)
                    response = "🎉 ¡Tienes un café gratis! Escribe *redimir* para usarlo"
                else:
                    faltan = 9 - (total % 9)
                    response = f"☕ Llevas {total} cafés. Te faltan {faltan}"

        # -------------------------
        # DEFAULT
        # -------------------------
        else:
            response = """👋 Bienvenido

Envía el código de 4 dígitos para registrar tu compra

Escribe *puntos* para ver tu progreso
Escribe *redimir* para usar tu recompensa ☕"""

        send_whatsapp(phone, response)

        return jsonify({"status": "ok"}), 200

    except Exception as e:
        print("❌ ERROR:", e)
        return jsonify({"status": "error"}), 500

    finally:
        cursor.close()
        conn.close()

# -------------------------
# RUN
# -------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))