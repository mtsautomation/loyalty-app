import mysql.connector
from flask import Flask, request, jsonify, render_template_string, session, redirect
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
app.secret_key = "super_secret_key"


def allowed_gai_family():
    return socket.AF_INET

urllib3_cn.allowed_gai_family = allowed_gai_family

app = Flask(__name__)
app.secret_key = "super_secret_key"
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


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":

        username = request.form.get("username")
        password = request.form.get("password")

        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT * FROM users WHERE username=%s AND password=%s
        """, (username, password))

        user = cursor.fetchone()

        if not user:
            return "Credenciales incorrectas", 401

        # generar OTP
        otp = str(random.randint(1000, 9999))
        expiry = datetime.utcnow() + timedelta(minutes=5)

        cursor.execute("""
            UPDATE users 
            SET otp_code=%s, otp_expiry=%s 
            WHERE id=%s
        """, (otp, expiry, user["id"]))
        conn.commit()

        # enviar por WhatsApp
        send_whatsapp(user["phone"], f"🔐 Tu código de acceso es: {otp}")

        session["tmp_user"] = user["id"]

        cursor.close()
        conn.close()

        return redirect("/verify")

    return """
    <h2>Login</h2>
    <form method="POST">
        Usuario: <input name="username"><br><br>
        Password: <input type="password" name="password"><br><br>
        <button>Ingresar</button>
    </form>
    """


# -------------------------
# VERIFY OTP
# -------------------------
@app.route("/verify", methods=["GET", "POST"])
def verify():
    if "tmp_user" not in session:
        return redirect("/login")

    if request.method == "POST":

        otp = request.form.get("otp")

        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("SELECT * FROM users WHERE id=%s", (session["tmp_user"],))
        user = cursor.fetchone()

        if user["otp_code"] == otp and datetime.utcnow() < user["otp_expiry"]:
            session["user_id"] = user["id"]
            session["branch_id"] = user["branch_id"]
            session.pop("tmp_user", None)

            return redirect("/cashier")

        return "OTP inválido o expirado"

    return """
    <h2>Verificar código</h2>
    <form method="POST">
        Código OTP: <input name="otp"><br><br>
        <button>Verificar</button>
    </form>
    """


# -------------------------
# 🔐 PROTECCIÓN CASHIER
# -------------------------
@app.route("/cashier")
def cashier():
    if not session.get("user_id"):
        return redirect("/login")

    return render_template_string("""
    <h1>Código dinámico activo</h1>
    <div id="code">----</div>

    <script>
        async function load(){
            let r = await fetch('/get_active_code')
            let d = await r.json()
            document.getElementById("code").innerText = d.code
        }
        setInterval(load, 3000)
        load()
    </script>
    """)


# -------------------------
# 🔐 GET CODE (YA PROTEGIDO)
# -------------------------
@app.route("/get_active_code")
def get_active_code():
    if not session.get("user_id"):
        return jsonify({"error": "unauthorized"}), 403

    branch_id = session.get("branch_id")

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT code FROM cashier_codes
        WHERE branch_id=%s AND used=0
        ORDER BY id DESC LIMIT 1
    """, (branch_id,))

    result = cursor.fetchone()

    if result:
        return jsonify({"code": result["code"]})

    code = str(random.randint(1000, 9999))

    cursor.execute("""
        INSERT INTO cashier_codes (code, branch_id, expires_at, used)
        VALUES (%s, %s, %s, 0)
    """, (code, branch_id, datetime.utcnow() + timedelta(seconds=60)))

    conn.commit()

    return jsonify({"code": code})


# -------------------------
# LOGOUT
# -------------------------
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")
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

            if not rows:
                response = "☕ Aún no tienes compras acumuladas."
            else:
                msg = "📊 Tus compras anteriores:\n\n"

                for r in rows:
                    branch_id = r["branch_id"]

                    total_actual = count_current_cycle(cursor, customer_id, branch_id)
                    ultimo = get_last_redeem(cursor, customer_id, branch_id)

                    msg += f"📍 Sucursal {branch_id}\n"
                    msg += f"☕ Progreso actual: {total_actual}/9\n"

                    if ultimo and ultimo["redeemed_at"]:
                        fecha = ultimo["redeemed_at"].strftime("%d/%m/%Y")
                        msg += f"🎁 Último café gratis: {fecha}\n"
                    else:
                        msg += "🎁 Aún no has canjeado cafés\n"

                    msg += "\n"

                msg += "✨ Sigue acumulando compras para tu próximo café gratis ☕"

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

                total = count_current_cycle(cursor, customer_id, branch_id)

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
            response = """👋 ¡Bienvenido a el programa de recompensas! ☕
            1️⃣ Compra tu café  
            2️⃣ Envía el código que ves en caja  
            3️⃣ Acumula y gana cafés gratis 🎉  

            📊 Escribe *puntos* para ver tu progreso  
            🎁 Escribe *redimir* para usar tu recompensa  

            ☕ ¡Disfruta tu café!"""
        else:
            response = "Escribe *Hola* para comenzar"

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