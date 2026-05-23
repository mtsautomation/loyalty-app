from flask import Flask, request, jsonify, render_template_string
import mysql.connector
from datetime import datetime, timedelta
import random
import requests
import os
import socket
import requests.packages.urllib3.util.connection as urllib3_cn
from flask import session, redirect
from datetime import datetime, timezone
import secrets
import json

datetime.now(timezone.utc)



def allowed_gai_family():
    return socket.AF_INET

urllib3_cn.allowed_gai_family = allowed_gai_family

app = Flask(__name__)
app.secret_key = "super_secret_key"
MASTER_ROLES = ["master"]
# -------------------------
# 🔐 CONFIG
# -------------------------
API_KEY_2CHAT = os.environ.get("API_KEY_2CHAT")
FROM_NUMBER = "529991900664"

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

def get_branch_by_code(cursor, code, cafe_id):
    cursor.execute("""
        SELECT id, branch_id, cafe_id FROM cashier_codes
        WHERE code=%s AND cafe_id=%s AND expires_at > NOW() AND used = 0
    """, (code, cafe_id))
    return cursor.fetchone()

def mark_code_used(cursor, conn, code_id):
    cursor.execute("""
        UPDATE cashier_codes SET used = 1 WHERE id = %s
    """, (code_id,))
    conn.commit()

def create_purchase(cursor, conn, customer_id, branch_id, cafe_id):
    cursor.execute("""
        INSERT INTO purchases (customer_id, branch_id, cafe_id, created_at)
        VALUES (%s, %s, %s, %s)
    """, (customer_id, branch_id, cafe_id, datetime.utcnow()))
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

def create_reward(cursor, conn, customer_id, branch_id, cafe_id):
    cursor.execute("""
        INSERT INTO rewards (customer_id, branch_id, cafe_id, status)
        VALUES (%s, %s, %s, 'pending')
    """, (customer_id, branch_id, cafe_id))
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
# =====================================================
# MASTER ADMIN HELPERS
# =====================================================

def get_master_user(cursor, phone):

    cursor.execute("""
        SELECT * FROM users
        WHERE phone=%s
        AND role='master'
        LIMIT 1
    """, (phone,))

    return cursor.fetchone()

# =====================================================
# ADMIN STATES
# =====================================================

def get_admin_state(cursor, phone):

    cursor.execute("""
        SELECT * FROM admin_states
        WHERE phone=%s
        LIMIT 1
    """, (phone,))

    return cursor.fetchone()

def save_admin_state(cursor, conn, phone, state, temp_data=None):

    cursor.execute("""
        SELECT id FROM admin_states
        WHERE phone=%s
        LIMIT 1
    """, (phone,))

    exists = cursor.fetchone()

    temp_json = json.dumps(temp_data or {})

    if exists:

        cursor.execute("""
            UPDATE admin_states
            SET state=%s,
                temp_data=%s,
                updated_at=%s
            WHERE phone=%s
        """, (
            state,
            temp_json,
            datetime.utcnow(),
            phone
        ))

    else:

        cursor.execute("""
            INSERT INTO admin_states
            (phone, state, temp_data, updated_at)
            VALUES (%s,%s,%s,%s)
        """, (
            phone,
            state,
            temp_json,
            datetime.utcnow()
        ))

    conn.commit()

def clear_admin_state(cursor, conn, phone):

    cursor.execute("""
        DELETE FROM admin_states
        WHERE phone=%s
    """, (phone,))

    conn.commit()

# =====================================================
# CREATE CAFE
# =====================================================

def create_cafe(cursor, conn, name):

    cursor.execute("""
        INSERT INTO cafes (name, created_at)
        VALUES (%s,%s)
    """, (
        name,
        datetime.utcnow()
    ))

    conn.commit()

    return cursor.lastrowid

# =====================================================
# CREATE BRANCH
# =====================================================

def create_branch(cursor, conn, cafe_id, name, address):

    cursor.execute("""
        INSERT INTO branches
        (name, address, cafe_id, created_at)
        VALUES (%s,%s,%s,%s)
    """, (
        name,
        address,
        cafe_id,
        datetime.utcnow()
    ))

    conn.commit()

    return cursor.lastrowid

# =====================================================
# CREATE USER
# =====================================================

def create_user(
    cursor,
    conn,
    username,
    password,
    phone,
    role,
    cafe_id,
    branch_id
):

    cursor.execute("""
        INSERT INTO users
        (
            username,
            password,
            phone,
            role,
            cafe_id,
            branch_id,
            created_at
        )
        VALUES (%s,%s,%s,%s,%s,%s,%s)
    """, (
        username,
        password,
        phone,
        role,
        cafe_id,
        branch_id,
        datetime.utcnow()
    ))

    conn.commit()
# -------------------------
# 🔐 ACTIVE CODE
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

        code = secrets.token_hex(3).upper()
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
        else:
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
# 💻 CASHIER (UI MEJORADO)
# -------------------------
@app.route("/cashier")
def cashier():

    if not session.get("user_id"):
        return redirect("/login")

    branch_id = session.get("branch_id")
    cafe_id = session["cafe_id"]

    return render_template_string(f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Código Caja</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">

        <style>
            body {{
                font-family: Arial, sans-serif;
                background: #0f172a;
                color: white;
                text-align: center;
                padding: 20px;
            }}

            .card {{
                background: #1e293b;
                border-radius: 20px;
                padding: 30px;
                max-width: 400px;
                margin: auto;
                box-shadow: 0 10px 25px rgba(0,0,0,0.3);
            }}

            h1 {{
                font-size: 22px;
                margin-bottom: 10px;
                opacity: 0.8;
            }}

            #code {{
                font-size: 64px;
                font-weight: bold;
                letter-spacing: 8px;
                margin: 20px 0;
            }}

            #countdown {{
                font-size: 20px;
                margin-top: 10px;
            }}

            .low {{
                color: #f87171;
            }}

            .ok {{
                color: #4ade80;
            }}

        </style>
    </head>

    <body>
        <div class="card">
            <h1>🔐 Código activo</h1>
            <div id="code">----</div>
            <div id="countdown">Cargando...</div>

        </div>

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

                const el = document.getElementById("countdown");

                const m = Math.floor(secondsLeft / 60);
                const s = secondsLeft % 60;

                el.innerText = "Expira en: " + m + ":" + String(s).padStart(2, "0");

                if (secondsLeft <= 10) {{
                    el.className = "low";
                }} else {{
                    el.className = "ok";
                }}
            }}

            fetchCode();
            setInterval(tick, 1000);
            setInterval(fetchCode, 30000);
        </script>
    </body>
    </html>
    """)
# -------------------------
# USER LOGOUT
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
    print("📩 RAW:", request.data)
    try:
        data = request.get_json(force=True, silent=True)
        if not data:
            data = request.form.to_dict() or {}
    except Exception as e:
        print("❌ JSON parse error:", e)
        data = {}
    print("📩", data)

    phone = normalize_phone(data.get("remote_phone_number"))
    text = data.get("message", {}).get("text", "").strip().lower()

    if not phone:
        return jsonify({"status": "no phone"}), 200

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:

        response = ""
        # =====================================================
        # MASTER FLOW
        # =====================================================

        master = get_master_user(cursor, phone)

        admin_state_data = get_admin_state(cursor, phone)

        admin_state = None
        admin_temp = {}

        if admin_state_data:

            admin_state = admin_state_data["state"]

            if admin_state_data["temp_data"]:
                admin_temp = json.loads(
                    admin_state_data["temp_data"]
                )

        # =====================================================
        # START MASTER FLOW
        # =====================================================

        if master and text == "alta cafeteria":

            save_admin_state(
                cursor,
                conn,
                phone,
                "await_cafe_name",
                {}
            )

            response = "☕ Nombre de la cafetería:"

        elif master and admin_state == "await_cafe_name":

            admin_temp["cafe_name"] = text

            save_admin_state(
                cursor,
                conn,
                phone,
                "await_branch_name",
                admin_temp
            )

            response = "📍 Nombre de la primera sucursal:"

        elif master and admin_state == "await_branch_name":

            admin_temp["branch_name"] = text

            save_admin_state(
                cursor,
                conn,
                phone,
                "await_branch_address",
                admin_temp
            )

            response = "🏠 Dirección de la sucursal:"

        elif master and admin_state == "await_branch_address":

            admin_temp["branch_address"] = text

            save_admin_state(
                cursor,
                conn,
                phone,
                "await_admin_username",
                admin_temp
            )

            response = "👤 Username del admin:"

        elif master and admin_state == "await_admin_username":

            admin_temp["admin_username"] = text

            save_admin_state(
                cursor,
                conn,
                phone,
                "await_admin_password",
                admin_temp
            )

            response = "🔐 Password del admin:"

        elif master and admin_state == "await_admin_password":

            admin_temp["admin_password"] = text

            save_admin_state(
                cursor,
                conn,
                phone,
                "await_admin_phone",
                admin_temp
            )

            response = "📱 Teléfono del admin:"

        elif master and admin_state == "await_admin_phone":

            admin_phone = normalize_phone(text)

            admin_temp["admin_phone"] = admin_phone

            cafe_id = create_cafe(
                cursor,
                conn,
                admin_temp["cafe_name"]
            )

            branch_id = create_branch(
                cursor,
                conn,
                cafe_id,
                admin_temp["branch_name"],
                admin_temp["branch_address"]
            )

            create_user(
                cursor,
                conn,
                admin_temp["admin_username"],
                admin_temp["admin_password"],
                admin_phone,
                "admin",
                cafe_id,
                branch_id
            )

            clear_admin_state(cursor, conn, phone)

            response = f"""
        ✅ Cafetería creada

        ☕ {admin_temp['cafe_name']}

        ✅ Sucursal creada

        📍 {admin_temp['branch_name']}

        ✅ Admin creado

        👤 {admin_temp['admin_username']}
        📱 {admin_phone}
        """

        elif master and text == "cancelar":

            clear_admin_state(cursor, conn, phone)

            response = "❌ Flujo cancelado"

        elif master and admin_state and response:

            send_whatsapp(phone, response)
            return jsonify({"status": "ok"}), 200

        # =====================================================
        # NORMAL CUSTOMER FLOW
        # =====================================================
        customer = get_customer(cursor, phone)
        customer_id = customer["id"] if customer else create_customer(cursor, conn, phone)

        state = customer.get("state") if customer else None

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

            cursor.execute("""

                SELECT id, branch_id, cafe_id FROM cashier_codes

                WHERE code=%s AND expires_at > NOW() AND used=0

            """, (text,))

            code_data = cursor.fetchone()

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

            cursor.execute("""
                SELECT id, branch_id, cafe_id FROM cashier_codes
                WHERE code=%s AND expires_at > NOW() AND used=0
                ORDER BY id DESC
                LIMIT 1
            """, (text,))

            code_data = cursor.fetchone()

            if not code_data:
                response = "❌ Código inválido o usado"
            else:
                branch_id = code_data["branch_id"]
                cafe_id = code_data["cafe_id"]

                create_purchase(cursor, conn, customer_id, branch_id, cafe_id)
                mark_code_used(cursor, conn, code_data["id"])

                total = count_current_cycle(cursor, customer_id, branch_id)

                if total % 9 == 0:
                    create_reward(cursor, conn, customer_id, branch_id, cafe_id)
                    response = "🎉 Café gratis disponible" + closing()
                else:
                    faltan = 9 - (total % 9)
                    if faltan == 9:
                        faltan = 0
                    response = f"☕ {total} compras. Te faltan {faltan}" + closing()

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