import mysql.connector
from flask import Flask, request, jsonify, render_template_string, session, redirect, url_for
from datetime import datetime, timedelta
import random
import requests
import os
import socket
import requests.packages.urllib3.util.connection as urllib3_cn


# 🌐 PARCHE DE RED PARA RAILWAY (Evita el NameResolutionError)
def allowed_gai_family():
    return socket.AF_INET


urllib3_cn.allowed_gai_family = allowed_gai_family

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_KEY", "motosur_ultra_secret_key_2024")
app.permanent_session_lifetime = timedelta(hours=8)

# -------------------------
# 🔐 CONFIGURACIÓN
# -------------------------
API_KEY_2CHAT = os.environ.get("API_KEY_2CHAT")
URL_2CHAT_API = "https://api.2chat.io/v1/messaging/send-text"
FROM_NUMBER = "+529992922621"

DB_CONFIG = {
    "host": os.environ.get("DB_HOST"),
    "user": os.environ.get("DB_USER"),
    "password": os.environ.get("DB_PASSWORD"),
    "database": os.environ.get("DB_NAME")
}


def get_db():
    return mysql.connector.connect(**DB_CONFIG)


# -------------------------
# 📱 HELPERS DE SISTEMA
# -------------------------
def normalize_phone(phone):
    if not phone: return None
    phone = "".join(filter(str.isdigit, phone))
    if len(phone) == 10: phone = "52" + phone
    return phone


def send_whatsapp(phone, message):
    try:
        payload = {"to_number": phone, "from_number": FROM_NUMBER, "text": message}
        headers = {"X-User-API-Key": API_KEY_2CHAT, "Content-Type": "application/json"}
        res = requests.post(URL_2CHAT_API, json=payload, headers=headers, timeout=20)
        return res.status_code in [200, 201, 202]
    except Exception as e:
        print(f"❌ Error WhatsApp: {e}")
        return False


# -------------------------
# 📊 HELPERS DE NEGOCIO (WEBHOOK)
# -------------------------
def get_customer(cursor, phone):
    cursor.execute("SELECT * FROM customers WHERE phone=%s", (phone,))
    return cursor.fetchone()


def create_customer(cursor, conn, phone):
    cursor.execute("INSERT INTO customers (phone, created_at, state) VALUES (%s, %s, %s)",
                   (phone, datetime.utcnow(), None))
    conn.commit()
    return cursor.lastrowid


def update_state(cursor, conn, customer_id, state):
    cursor.execute("UPDATE customers SET state=%s WHERE id=%s", (state, customer_id))
    conn.commit()


def get_branch_by_code(cursor, code):
    cursor.execute("SELECT id, branch_id FROM cashier_codes WHERE code=%s AND expires_at > NOW() AND used = 0", (code,))
    return cursor.fetchone()


def mark_code_used(cursor, conn, code_id):
    cursor.execute("UPDATE cashier_codes SET used = 1 WHERE id = %s", (code_id,))
    conn.commit()


def create_purchase(cursor, conn, customer_id, branch_id):
    cursor.execute("INSERT INTO purchases (customer_id, branch_id, created_at) VALUES (%s, %s, %s)",
                   (customer_id, branch_id, datetime.utcnow()))
    conn.commit()


def count_current_cycle(cursor, customer_id, branch_id):
    cursor.execute("""
        SELECT COUNT(*) as total FROM purchases 
        WHERE customer_id=%s AND branch_id=%s 
        AND created_at > IFNULL(
            (SELECT MAX(redeemed_at) FROM rewards WHERE customer_id=%s AND branch_id=%s AND status='redeemed'),
            '2000-01-01'
        )
    """, (customer_id, branch_id, customer_id, branch_id))
    return cursor.fetchone()["total"]


def get_last_redeem(cursor, customer_id, branch_id):
    cursor.execute(
        "SELECT redeemed_at FROM rewards WHERE customer_id=%s AND branch_id=%s AND status='redeemed' ORDER BY redeemed_at DESC LIMIT 1",
        (customer_id, branch_id))
    return cursor.fetchone()


def get_all_points(cursor, customer_id):
    cursor.execute("SELECT branch_id, COUNT(*) as total FROM purchases WHERE customer_id=%s GROUP BY branch_id",
                   (customer_id,))
    return cursor.fetchall()


def create_reward(cursor, conn, customer_id, branch_id):
    cursor.execute("INSERT INTO rewards (customer_id, branch_id, status) VALUES (%s, %s, 'pending')",
                   (customer_id, branch_id))
    conn.commit()


def get_pending_reward(cursor, customer_id, branch_id):
    cursor.execute("SELECT id FROM rewards WHERE customer_id=%s AND branch_id=%s AND status='pending' LIMIT 1",
                   (customer_id, branch_id))
    return cursor.fetchone()


def redeem_reward(cursor, conn, reward_id):
    cursor.execute("UPDATE rewards SET status='redeemed', redeemed_at=%s WHERE id=%s", (datetime.utcnow(), reward_id))
    conn.commit()


def closing():
    return "\n\n👉 Para registrar otra compra escribe *hola*"


# -------------------------
# 🔑 LOGIN POR USUARIO + OTP
# -------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users WHERE username=%s", (username,))
        user = cursor.fetchone()

        if user:
            otp = str(random.randint(1000, 9999))
            expiry = datetime.utcnow() + timedelta(minutes=5)
            cursor.execute("UPDATE users SET otp_code=%s, otp_expiry=%s WHERE id=%s", (otp, expiry, user["id"]))
            conn.commit()
            send_whatsapp(normalize_phone(user["phone"]), f"🔐 Tu código de acceso es: {otp}")
            session["tmp_user_id"] = user["id"]
            return redirect(url_for("verify"))
        return "Usuario no encontrado", 404

    return '<h2>Login</h2><form method="POST">Usuario: <input name="username"><button>Enviar OTP</button></form>'


@app.route("/verify", methods=["GET", "POST"])
def verify():
    if "tmp_user_id" not in session: return redirect(url_for("login"))
    if request.method == "POST":
        otp = request.form.get("otp")
        conn = get_db()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users WHERE id=%s", (session["tmp_user_id"],))
        user = cursor.fetchone()
        if user["otp_code"] == otp and datetime.utcnow() < user["otp_expiry"]:
            session.permanent = True
            session["user_id"] = user["id"]
            session["branch_id"] = user["branch_id"]
            return redirect(url_for("cashier"))
        return "OTP Incorrecto"
    return '<h2>Verificar OTP</h2><form method="POST"><input name="otp"><button>Entrar</button></form>'


# -------------------------
# 🖥️ CASHIER
# -------------------------
@app.route("/cashier")
def cashier():
    if "user_id" not in session: return redirect(url_for("login"))
    return render_template_string('''
        <h1>Código Activo</h1>
        <div id="code" style="font-size:100px;">----</div>
        <script>
            async function update() {
                let r = await fetch('/get_active_code');
                let d = await r.json();
                document.getElementById("code").innerText = d.code;
            }
            setInterval(update, 10000); update();
        </script>
        <br><a href="/logout">Salir</a>
    ''')


@app.route("/get_active_code")
def get_active_code():
    if "user_id" not in session: return jsonify({"error": "403"}), 403
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT code FROM cashier_codes WHERE branch_id=%s AND used=0 AND expires_at > NOW() ORDER BY id DESC LIMIT 1",
        (session["branch_id"],))
    res = cursor.fetchone()
    if res: return jsonify({"code": res["code"]})

    new_c = str(random.randint(1000, 9999))
    cursor.execute("INSERT INTO cashier_codes (code, branch_id, expires_at, used) VALUES (%s, %s, %s, 0)",
                   (new_c, session["branch_id"], datetime.utcnow() + timedelta(seconds=60)))
    conn.commit()
    return jsonify({"code": new_c})


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# -------------------------
# 📩 WEBHOOK COMPLETO
# -------------------------
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    phone = normalize_phone(data.get("remote_phone_number"))
    text = (data.get("message", {}).get("text", "") or data.get("text", "")).strip().lower()
    if not phone: return jsonify({"status": "ok"}), 200

    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        customer = get_customer(cursor, phone)
        customer_id = customer["id"] if customer else create_customer(cursor, conn, phone)
        state = customer.get("state") if customer else None
        response = ""

        if text in ["status", "puntos"]:
            rows = get_all_points(cursor, customer_id)
            if not rows:
                response = "☕ No tienes compras aún."
            else:
                msg = "📊 Tus puntos:\n"
                for r in rows:
                    total = count_current_cycle(cursor, customer_id, r["branch_id"])
                    msg += f"📍 Sucursal {r['branch_id']}: {total}/9\n"
                response = msg + closing()

        elif text == "redimir":
            update_state(cursor, conn, customer_id, "redeem")
            response = "🎟️ Envía el código del cajero para cobrar tu café gratis."

        elif state == "redeem" and text.isdigit():
            code_data = get_branch_by_code(cursor, text)
            if not code_data:
                response = "❌ Código inválido."
            else:
                reward = get_pending_reward(cursor, customer_id, code_data["branch_id"])
                if not reward:
                    response = "❌ No tienes premios pendientes aquí."
                else:
                    redeem_reward(cursor, conn, reward["id"])
                    mark_code_used(cursor, conn, code_data["id"])
                    response = "🎉 ¡Disfruta tu café gratis!" + closing()
            update_state(cursor, conn, customer_id, None)

        elif text.isdigit() and not state:
            code_data = get_branch_by_code(cursor, text)
            if not code_data:
                response = "❌ Código inválido o expirado."
            else:
                create_purchase(cursor, conn, customer_id, code_data["branch_id"])
                mark_code_used(cursor, conn, code_data["id"])
                total = count_current_cycle(cursor, customer_id, code_data["branch_id"])
                if total >= 9:
                    create_reward(cursor, conn, customer_id, code_data["branch_id"])
                    response = "🎉 ¡Café gratis disponible! Escribe *redimir*."
                else:
                    response = f"☕ Registrado. Llevas {total}/9." + closing()

        elif text == "hola" or not response:
            update_state(cursor, conn, customer_id, None)
            response = "👋 ¡Hola! Envía tu código de caja para sumar puntos o escribe *puntos*."

        send_whatsapp(phone, response)
        return jsonify({"status": "ok"}), 200
    finally:
        cursor.close();
        conn.close()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))