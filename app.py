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
    cursor.execute("""
        UPDATE cashier_codes SET used = 1 WHERE id = %s
    """, (code_id,))
    conn.commit()

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

def get_purchase_history(cursor, customer_id):
    cursor.execute("""
        SELECT branch_id, DATE(created_at) as day
        FROM purchases
        WHERE customer_id=%s
        ORDER BY created_at DESC
        LIMIT 10
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

def closing():
    return "\n\n👉 Para registrar otra compra escribe *hola*"

# -------------------------
# 🔐 ACTIVE CODE
# -------------------------
@app.route("/get_active_code")
def get_active_code():
    branch_id = request.args.get("branch", 1)

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
# 📩 WEBHOOK
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

        # STATUS + HISTORIAL
        if text in ["status", "puntos"]:
            rows = get_all_points(cursor, customer_id)
            history = get_purchase_history(cursor, customer_id)

            if not rows:
                response = "☕ Aún no tienes compras acumuladas."
            else:
                msg = "📊 Tus cafés:\n\n"
                for r in rows:
                    msg += f"Sucursal {r['branch_id']}: {r['total']}\n"

                msg += "\n🗓 Tus últimas compras:\n"
                for h in history:
                    msg += f"{h['day']} (Sucursal {h['branch_id']})\n"

                response = msg + closing()

        # REDIMIR
        elif text == "redimir":
            update_state(cursor, conn, customer_id, "redeem")
            response = "Envía código del cajero"

        elif state == "redeem" and text.isdigit():
            code_data = get_branch_by_code(cursor, text)

            if not code_data:
                response = "❌ Código inválido"
            else:
                reward = get_pending_reward(cursor, customer_id, code_data["branch_id"])

                if not reward:
                    response = "❌ Sin recompensa"
                else:
                    redeem_reward(cursor, conn, reward["id"])
                    mark_code_used(cursor, conn, code_data["id"])
                    response = "🎉 Café GRATIS aplicado" + closing()

            update_state(cursor, conn, customer_id, None)

        # REGISTRAR COMPRA
        elif text.isdigit() and state is None:
            code_data = get_branch_by_code(cursor, text)

            if not code_data:
                response = "❌ Lo sentimos el Código que enviasté es  inválido o ya ha sido usado :/"
            else:
                branch_id = code_data["branch_id"]

                create_purchase(cursor, conn, customer_id, branch_id)
                mark_code_used(cursor, conn, code_data["id"])

                total = count_purchases_by_branch(cursor, customer_id, branch_id)

                if total % 9 == 0:
                    create_reward(cursor, conn, customer_id, branch_id)
                    response = "🎉 Ya tienes un Café gratis disponible. Escribe *redimir* para recibir tu recompensa" + closing()
                else:
                    faltan = 9 - (total % 9)
                    if faltan == 9:
                        faltan = 0
                    response = f"☕ has registrado  {total} compras. Te faltan {faltan}" + closing()

        # RESET
        elif text == "hola":
            update_state(cursor, conn, customer_id, None)
            response = """👋 Bienvenido a el programa de recompensas

-Envía el código de 4 dígitos que te da tu cajero, para registrar tu compra 
-Escribe *puntos* para conocer tus registros anteriores 
-Escribe *redimir* para canjear tu recompensa """

        else:
            response = "Escribe *hola* para comenzar"

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