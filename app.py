from flask import Flask, request, jsonify, render_template_string
import mysql.connector
from datetime import datetime, timedelta, timezone
import random
import requests
import os
import socket
import requests.packages.urllib3.util.connection as urllib3_cn
from flask import session, redirect
import secrets
import json
from werkzeug.security import generate_password_hash, check_password_hash
import re


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
def normalize_phone(phone):

    if not phone:
        return None

    phone = re.sub(r"\D", "", phone)

    if len(phone) == 10:
        phone = "52" + phone

    return phone
def normalize_name(name):

    name = name.lower().strip()

    name = re.sub(r"\s+", "", name)

    name = re.sub(r"[^a-z0-9]", "", name)

    return name

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


def create_purchase(cursor, conn, customer_id, branch_id, cafe_id):
    cursor.execute("""
        INSERT INTO purchases (
            customer_id,
            branch_id,
            cafe_id,
            created_at
        )
        VALUES (%s,%s,%s,%s)
    """, (
        customer_id,
        branch_id,
        cafe_id,
        datetime.utcnow()
    ))

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
        AND updated_at > NOW() - INTERVAL 30 MINUTE
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


    return cursor.lastrowid

# =====================================================
# CREATE BRANCH
# =====================================================

def create_branch(
    cursor,
    conn,
    cafe_id,
    name,
    address,
    street=None,
    neighborhood=None,
    zip_code=None,
    city=None,
    state_name=None
):
    cursor.execute("""
        INSERT INTO branches
        (
            name,
            address,
            cafe_id,
            street,
            neighborhood,
            zip_code,
            city,
            state_name,
            created_at
        )
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """, (
        name,
        address,
        cafe_id,
        street,
        neighborhood,
        zip_code,
        city,
        state_name,
        datetime.utcnow()
    ))

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

    hashed_password = generate_password_hash(password)

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
        hashed_password,
        phone,
        role,
        cafe_id,
        branch_id,
        datetime.utcnow()
    ))



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
            WHERE branch_id=%s
            AND cafe_id=%s
            AND used=0
            AND expires_at > NOW()
            ORDER BY id DESC LIMIT 1
        """, (branch_id, cafe_id))

        result = cursor.fetchone()

        if result:
            remaining = int((result["expires_at"] - datetime.utcnow()).total_seconds())
            return jsonify({"code": result["code"], "expires_in": max(0, remaining)})

        code = secrets.token_hex(4).upper()
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
            WHERE username=%s
        """, (username,))

        user = cursor.fetchone()

        cursor.close()
        conn.close()

        if user and check_password_hash(user["password"], password):
            session["user_id"] = user["id"]
            session["branch_id"] = user["branch_id"]
            session["cafe_id"] = user["cafe_id"]
            session["role"] = user["role"]
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

    if session.get("role") not in ["admin", "cashier", "master"]:
        return "No autorizado", 403

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

    raw_text = data.get("message", {}).get("text", "").strip()
    text = raw_text.lower()

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
        print("PHONE:", phone)
        print("MASTER:", master)

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

        # ---------------------------------
        # CANCEL FLOW
        # ---------------------------------
        if master and text == "cancelar":

            clear_admin_state(cursor, conn, phone)

            conn.commit()

            response = "❌ Flujo cancelado"

            send_whatsapp(phone, response)

            return jsonify({"status": "cancelled"}), 200


        # =====================================================
        # CREATE NEW CAFE
        # =====================================================

        # ---------------------------------
        # START FLOW
        # ---------------------------------
        elif master and text == "alta cafeteria":

            save_admin_state(
                cursor,
                conn,
                phone,
                "await_cafe_name",
                {}
            )

            response = "☕ Nombre de la cafetería:"

            send_whatsapp(phone, response)

            return jsonify({"status": "ok"}), 200


        # ---------------------------------
        # CAFE NAME
        # ---------------------------------
        elif master and admin_state == "await_cafe_name":
            normalized_input = normalize_name(text)

            cursor.execute("""
                SELECT id, name FROM cafes
            """)

            cafes = cursor.fetchall()

            existing_cafe = None

            for cafe in cafes:

                if normalize_name(cafe["name"]) == normalized_input:
                    existing_cafe = cafe
                    break

            if existing_cafe:
                send_whatsapp(
                    phone,
                    "❌ Ya existe una cafetería con ese nombre."
                )

                return jsonify({"status": "duplicate cafe"}), 200

            admin_temp["cafe_name"] = raw_text

            save_admin_state(
                cursor,
                conn,
                phone,
                "await_branch_count",
                admin_temp
            )

            response = "🏢 ¿Cuántas sucursales tendrá?"

            send_whatsapp(phone, response)

            return jsonify({"status": "ok"}), 200


        # ---------------------------------
        # BRANCH COUNT
        # ---------------------------------
        elif master and admin_state == "await_branch_count":

            if not text.isdigit():
                send_whatsapp(
                    phone,
                    "❌ Debes enviar un número"
                )

                return jsonify({"status": "invalid"}), 200

            branch_count = int(text)

            if branch_count <= 0:
                send_whatsapp(
                    phone,
                    "❌ Número inválido"
                )

                return jsonify({"status": "invalid"}), 200

            admin_temp["branch_count"] = branch_count
            admin_temp["current_branch"] = 1
            admin_temp["branches"] = []

            save_admin_state(
                cursor,
                conn,
                phone,
                "await_branch_name",
                admin_temp
            )

            response = "📍 Nombre de sucursal #1:"

            send_whatsapp(phone, response)

            return jsonify({"status": "ok"}), 200


        # ---------------------------------
        # BRANCH NAME
        # ---------------------------------
        elif master and admin_state == "await_branch_name":

            admin_temp["temp_branch_name"] = raw_text

            save_admin_state(
                cursor,
                conn,
                phone,
                "await_branch_address",
                admin_temp
            )

            response = f"""
        🏠 Dirección de sucursal #{admin_temp['current_branch']}:
        """

            send_whatsapp(phone, response)

            return jsonify({"status": "ok"}), 200


        # ---------------------------------
        # BRANCH ADDRESS
        # ---------------------------------
        elif master and admin_state == "await_branch_address":

            admin_temp["temp_street"] = raw_text

            save_admin_state(
                cursor,
                conn,
                phone,
                "await_branch_neighborhood",
                admin_temp
            )

            response = "🏘️ Colonia:"

            send_whatsapp(phone, response)

            return jsonify({"status": "ok"}), 200


        elif master and admin_state == "await_branch_neighborhood":

            admin_temp["temp_neighborhood"] = raw_text

            save_admin_state(
                cursor,
                conn,
                phone,
                "await_branch_zipcode",
                admin_temp
            )

            response = "📮 Código postal:"

            send_whatsapp(phone, response)

            return jsonify({"status": "ok"}), 200


        elif master and admin_state == "await_branch_zipcode":

            if not raw_text.isdigit():
                send_whatsapp(

                    phone,

                    "❌ Código postal inválido"

                )

                return jsonify({"status": "invalid zip"}), 200

            admin_temp["temp_zipcode"] = raw_text

            full_address = f"""

        Calle: {admin_temp['temp_street']}

        Colonia: {admin_temp['temp_neighborhood']}

        CP: {admin_temp['temp_zipcode']}

        """

            branch_data = {
                "name": admin_temp["temp_branch_name"],
                "address": full_address,
                "street": admin_temp["temp_street"],
                "neighborhood": admin_temp["temp_neighborhood"],
                "zip_code": admin_temp["temp_zipcode"]
            }

            admin_temp["branches"].append(branch_data)

            current = admin_temp["current_branch"]
            total = admin_temp["branch_count"]

            if current < total:
                admin_temp["current_branch"] += 1

                save_admin_state(
                    cursor,
                    conn,
                    phone,
                    "await_branch_name",
                    admin_temp
                )

                response = f"""
        ✅ Sucursal #{current} guardada

        📍 Nombre sucursal #{admin_temp['current_branch']}:
        """

                send_whatsapp(phone, response)

                return jsonify({"status": "ok"}), 200

            save_admin_state(
                cursor,
                conn,
                phone,
                "await_admin_username",
                admin_temp
            )

            response = "👤 Username del usuario:"

            send_whatsapp(phone, response)

            return jsonify({"status": "ok"}), 200

        # ---------------------------------
        # USERNAME
        # ---------------------------------
        elif master and admin_state == "await_admin_username":

            text = text.lower().strip()

            cursor.execute(
                "SELECT id FROM users WHERE username=%s",
                (text,)
            )

            existing_user = cursor.fetchone()

            if existing_user:
                send_whatsapp(
                    phone,
                    "❌ Username ya existe"
                )

                return jsonify({"status": "duplicate"}), 200

            admin_temp["admin_username"] = text

            save_admin_state(
                cursor,
                conn,
                phone,
                "await_admin_password",
                admin_temp
            )

            response = "🔐 Password del usuario:"

            send_whatsapp(phone, response)

            return jsonify({"status": "ok"}), 200


        # ---------------------------------
        # PASSWORD
        # ---------------------------------
        elif master and admin_state == "await_admin_password":

            admin_temp["admin_password"] = raw_text

            save_admin_state(
                cursor,
                conn,
                phone,
                "await_admin_phone",
                admin_temp
            )

            response = "📱 Teléfono del usuario:"

            send_whatsapp(phone, response)

            return jsonify({"status": "ok"}), 200


        # ---------------------------------
        # PHONE
        # ---------------------------------
        elif master and admin_state == "await_admin_phone":

            admin_phone = normalize_phone(text)

            cursor.execute(
                "SELECT id FROM users WHERE phone=%s",
                (admin_phone,)
            )

            existing_phone = cursor.fetchone()

            if existing_phone:
                send_whatsapp(
                    phone,
                    "❌ Teléfono ya registrado"
                )

                return jsonify({"status": "duplicate"}), 200

            admin_temp["admin_phone"] = admin_phone

            save_admin_state(
                cursor,
                conn,
                phone,
                "await_role",
                admin_temp
            )

            response = """
        👤 Selecciona rol:

        • admin
        • cashier
        """

            send_whatsapp(phone, response)

            return jsonify({"status": "ok"}), 200


        # ---------------------------------
        # ROLE
        # ---------------------------------
        elif master and admin_state == "await_role":

            allowed_roles = ["admin", "cashier"]

            if text not in allowed_roles:
                send_whatsapp(
                    phone,
                    "❌ Rol inválido"
                )

                return jsonify({"status": "invalid role"}), 200

            admin_temp["role"] = text

            save_admin_state(
                cursor,
                conn,
                phone,
                "confirm_create",
                admin_temp
            )

            branch_text = ""

            for i, branch in enumerate(admin_temp["branches"], start=1):
                branch_text += f"""
        {i}. {branch['name']}
        📌 {branch['address']}
        """

            response = f"""
        📋 CONFIRMAR DATOS

        ☕ Cafetería:
        {admin_temp['cafe_name']}

        🏢 Sucursales:
        {branch_text}

        👤 Usuario:
        {admin_temp['admin_username']}

        📱 Teléfono:
        {admin_temp['admin_phone']}

        🔐 Password:
        {admin_temp['admin_password']}

        🛡️ Rol:
        {admin_temp['role']}

        ----------------------------

        ✅ confirmar
        ❌ cancelar
        """

            send_whatsapp(phone, response)

            return jsonify({"status": "ok"}), 200


        # ---------------------------------
        # FINAL CONFIRMATION
        # ---------------------------------

        elif master and admin_state == "confirm_create":

            print("ENTERED CONFIRM_CREATE")

            print("AUTOCOMMIT:", conn.autocommit)

            print("IN_TRANSACTION BEFORE:", conn.in_transaction)

            if conn.in_transaction:
                print("COMMITTING PREVIOUS TRANSACTION")
                conn.commit()

            if text != "confirmar":
                send_whatsapp(

                    phone,

                    "❌ Debes escribir confirmar o cancelar"

                )

                return jsonify({"status": "waiting"}), 200

            conn.autocommit = False

            print("AFTER AUTOCOMMIT FALSE")

            print("IN_TRANSACTION:", conn.in_transaction)

            conn.start_transaction()

            try:

                cafe_id = create_cafe(
                    cursor,
                    conn,
                    admin_temp["cafe_name"]
                )

                first_branch_id = None

                for branch in admin_temp["branches"]:

                    new_branch_id = create_branch(
                        cursor,
                        conn,
                        cafe_id,
                        branch["name"],
                        branch["address"],
                        branch.get("street"),
                        branch.get("neighborhood"),
                        branch.get("zip_code")
                    )

                    if first_branch_id is None:
                        first_branch_id = new_branch_id

                print("CAFE ID:", cafe_id)
                print("BRANCHES:", admin_temp["branches"])
                print("FIRST BRANCH:", first_branch_id)

                create_user(
                    cursor,
                    conn,
                    admin_temp["admin_username"],
                    admin_temp["admin_password"],
                    admin_temp["admin_phone"],
                    admin_temp["role"],
                    cafe_id,
                    first_branch_id
                )

                clear_admin_state(cursor, conn, phone)

                conn.commit()

                response = f"""
        ✅ Cafetería creada

        ☕ {admin_temp['cafe_name']}

        🏢 Sucursales creadas:
        {len(admin_temp['branches'])}

        👤 Usuario:
        {admin_temp['admin_username']}

        🛡️ Rol:
        {admin_temp['role']}
        """

            except Exception as e:

                conn.rollback()

                print("❌ CREATE CAFE ERROR:", e)

                response = "❌ Error creando cafetería"

            finally:

                conn.autocommit = True

            send_whatsapp(phone, response)

            return jsonify({"status": "created"}), 200


        # =====================================================
        # ADD NEW BRANCH TO EXISTING CAFE
        # =====================================================

        # ---------------------------------
        # START ADD BRANCH
        # ---------------------------------
        elif master and text == "agregar sucursal":

            cursor.execute("""
                SELECT id, name
                FROM cafes
                ORDER BY id
            """)

            cafes = cursor.fetchall()

            if not cafes:
                send_whatsapp(
                    phone,
                    "❌ No existen cafeterías"
                )

                return jsonify({"status": "no cafes"}), 200

            cafe_text = ""

            for cafe in cafes:
                cafe_text += f"""
        {cafe['id']} - {cafe['name']}
        """

            save_admin_state(
                cursor,
                conn,
                phone,
                "await_upgrade_cafe",
                {}
            )

            response = f"""
        ☕ Selecciona ID de cafetería:

        {cafe_text}
        """

            send_whatsapp(phone, response)

            return jsonify({"status": "ok"}), 200


        # ---------------------------------
        # SELECT CAFE
        # ---------------------------------
        elif master and admin_state == "await_upgrade_cafe":

            if not text.isdigit():
                send_whatsapp(
                    phone,
                    "❌ Debes enviar un ID válido"
                )

                return jsonify({"status": "invalid"}), 200

            cafe_id = int(text)

            cursor.execute("""
                SELECT id, name
                FROM cafes
                WHERE id=%s
                LIMIT 1
            """, (cafe_id,))

            cafe = cursor.fetchone()

            if not cafe:
                send_whatsapp(
                    phone,
                    "❌ Cafetería no encontrada"
                )

                return jsonify({"status": "not found"}), 200

            admin_temp["upgrade_cafe_id"] = cafe_id

            save_admin_state(
                cursor,
                conn,
                phone,
                "await_new_branch_name",
                admin_temp
            )

            response = "📍 Nombre de nueva sucursal:"

            send_whatsapp(phone, response)

            return jsonify({"status": "ok"}), 200


        # ---------------------------------
        # NEW BRANCH NAME
        # ---------------------------------
        elif master and admin_state == "await_new_branch_name":

            admin_temp["new_branch_name"] = raw_text

            save_admin_state(
                cursor,
                conn,
                phone,
                "await_new_branch_address",
                admin_temp
            )

            response = "🏠 Dirección de nueva sucursal:"

            send_whatsapp(phone, response)

            return jsonify({"status": "ok"}), 200


        # ---------------------------------
        # CREATE NEW BRANCH
        # ---------------------------------
        elif master and admin_state == "await_new_branch_address":

            create_branch(
                cursor,
                conn,
                admin_temp["upgrade_cafe_id"],
                admin_temp["new_branch_name"],
                text
            )

            clear_admin_state(cursor, conn, phone)

            conn.commit()

            response = f"""
        ✅ Nueva sucursal agregada

        📍 {admin_temp['new_branch_name']}
        """

            send_whatsapp(phone, response)

            return jsonify({"status": "branch added"}), 200
        elif master and text == "alta usuario":

            cursor.execute("""
                SELECT id, name
                FROM cafes
                ORDER BY name
            """)

            cafes = cursor.fetchall()

            if not cafes:
                send_whatsapp(
                    phone,
                    "❌ No existen cafeterías"
                )

                return jsonify({"status": "no cafes"}), 200

            cafe_text = ""

            for cafe in cafes:
                cafe_text += f"""
        {cafe['id']} - {cafe['name']}
        """

            save_admin_state(
                cursor,
                conn,
                phone,
                "await_user_cafe",
                {}
            )

            response = f"""
        ☕ Selecciona cafetería:

        {cafe_text}
        """

            send_whatsapp(phone, response)

            return jsonify({"status": "ok"}), 200

        # ---------------------------------
        # SELECT USER CAFE
        # ---------------------------------
        elif master and admin_state == "await_user_cafe":

            if not text.isdigit():
                send_whatsapp(
                    phone,
                    "❌ ID inválido"
                )

                return jsonify({"status": "invalid"}), 200

            cafe_id = int(text)

            cursor.execute("""
                SELECT id, name
                FROM cafes
                WHERE id=%s
                LIMIT 1
            """, (cafe_id,))

            cafe = cursor.fetchone()

            if not cafe:
                send_whatsapp(
                    phone,
                    "❌ Cafetería no encontrada"
                )

                return jsonify({"status": "not found"}), 200

            admin_temp["selected_cafe"] = cafe_id

            cursor.execute("""
                SELECT id, name
                FROM branches
                WHERE cafe_id=%s
                ORDER BY name
            """, (cafe_id,))

            branches = cursor.fetchall()

            if not branches:
                send_whatsapp(
                    phone,
                    "❌ Esta cafetería no tiene sucursales"
                )

                return jsonify({"status": "no branches"}), 200

            branch_text = ""

            for branch in branches:
                branch_text += f"""
        {branch['id']} - {branch['name']}
        """

            save_admin_state(
                cursor,
                conn,
                phone,
                "await_user_branch",
                admin_temp
            )

            response = f"""
        🏢 Selecciona sucursal:

        {branch_text}
        """

            send_whatsapp(phone, response)

            return jsonify({"status": "ok"}), 200

# ---------------------------------
# SELECT USER BRANCH
# ---------------------------------
        elif master and admin_state == "await_user_branch":

            if not text.isdigit():
                send_whatsapp(phone, "❌ ID inválido")
                return jsonify({"status": "invalid"}), 200

            branch_id = int(text)

            cursor.execute("""
                SELECT id, name
                FROM branches
                WHERE id=%s
                AND cafe_id=%s
                LIMIT 1
            """, (
                branch_id,
                admin_temp["selected_cafe"]
            ))

            branch = cursor.fetchone()

            if not branch:
                send_whatsapp(
                    phone,
                    "❌ Sucursal inválida"
                )

                return jsonify({"status": "invalid branch"}), 200

            admin_temp["selected_branch"] = branch_id

            save_admin_state(
                cursor,
                conn,
                phone,
                "await_new_username",
                admin_temp
            )

            response = "👤 Username del usuario:"

            send_whatsapp(phone, response)

            return jsonify({"status": "ok"}), 200


# ---------------------------------
# NEW USERNAME
# ---------------------------------
        elif master and admin_state == "await_new_username":

            text = text.lower().strip()

            cursor.execute(
                "SELECT id FROM users WHERE username=%s",
                (text,)
            )

            existing_user = cursor.fetchone()

            if existing_user:
                send_whatsapp(
                    phone,
                    "❌ Username ya existe"
                )

                return jsonify({"status": "duplicate"}), 200

            admin_temp["new_username"] = text

            save_admin_state(
                cursor,
                conn,
                phone,
                "await_new_password",
                admin_temp
            )

            response = "🔐 Password del usuario:"

            send_whatsapp(phone, response)

            return jsonify({"status": "ok"}), 200


# ---------------------------------
# NEW PASSWORD
# ---------------------------------
        elif master and admin_state == "await_new_password":

            admin_temp["new_password"] = raw_text

            save_admin_state(
                cursor,
                conn,
                phone,
                "await_new_phone",
                admin_temp
            )

            response = "📱 Teléfono del usuario:"

            send_whatsapp(phone, response)

            return jsonify({"status": "ok"}), 200


# ---------------------------------
# NEW PHONE
# ---------------------------------
        elif master and admin_state == "await_new_phone":

            new_phone = normalize_phone(text)

            cursor.execute(
                "SELECT id FROM users WHERE phone=%s",
                (new_phone,)
            )

            existing_phone = cursor.fetchone()

            if existing_phone:
                send_whatsapp(
                    phone,
                    "❌ Teléfono ya registrado"
                )

                return jsonify({"status": "duplicate"}), 200

            admin_temp["new_phone"] = new_phone

            save_admin_state(
                cursor,
                conn,
                phone,
                "await_new_role",
                admin_temp
            )

            response = """
        👤 Selecciona rol:

        • admin
        • cashier
        """

            send_whatsapp(phone, response)

            return jsonify({"status": "ok"}), 200


        # ---------------------------------
        # NEW ROLE + CREATE USER
        # ---------------------------------
        elif master and admin_state == "await_new_role":

            allowed_roles = ["admin", "cashier"]

            if text not in allowed_roles:
                send_whatsapp(
                    phone,
                    "❌ Rol inválido"
                )

                return jsonify({"status": "invalid"}), 200

            admin_temp["new_role"] = text

            create_user(
                cursor,
                conn,
                admin_temp["new_username"],
                admin_temp["new_password"],
                admin_temp["new_phone"],
                admin_temp["new_role"],
                admin_temp["selected_cafe"],
                admin_temp["selected_branch"]
            )

            clear_admin_state(cursor, conn, phone)

            conn.commit()

            response = f"""
        ✅ Usuario creado correctamente

        👤 Usuario:
        {admin_temp['new_username']}

        📱 Teléfono:
        {admin_temp['new_phone']}

        🛡️ Rol:
        {admin_temp['new_role']}
        """

            send_whatsapp(phone, response)

            return jsonify({"status": "created"}), 200
        # =====================================================
        # NORMAL CUSTOMER FLOW
        # =====================================================
        customer = get_customer(cursor, phone)
        if customer:
            customer_id = customer["id"]
            state = customer.get("state")

        else:
            customer_id = create_customer(cursor, conn, phone)
            state = None

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
        #--------------------------------------------------------------------
        # REDIMIR RECOMPENSA
        #--------------------------------------------------------------------
        elif text == "redimir":
            update_state(cursor, conn, customer_id, "redeem")
            response = "Envía código del cajero"

        elif state == "redeem" and re.fullmatch(r"[A-F0-9]{8}", text.upper()):
            conn.autocommit = False


            try:
                cursor.execute("""
                    SELECT id, branch_id, cafe_id
                    FROM cashier_codes
                    WHERE code=%s
                    AND expires_at > NOW()
                    AND used=0
                    FOR UPDATE
                """, (text.upper(),))

                code_data = cursor.fetchone()

                if not code_data:
                    response = "❌ Código inválido"
                    update_state(cursor, conn, customer_id, None)
                    conn.commit()

                else:
                    reward = get_pending_reward(
                        cursor,
                        customer_id,
                        code_data["branch_id"]
                    )

                    if not reward:
                        response = "❌ Sin recompensa"

                    else:
                        redeem_reward(
                           cursor,
                            conn,
                            reward["id"]
                        )
                        mark_code_used(
                            cursor,
                            conn,
                            code_data["id"]
                        )

                        response = "🎉 Café GRATIS aplicado" + closing()

                    update_state(cursor, conn, customer_id, None)

                    conn.commit()

            except Exception as e:

                conn.rollback()

                print("❌ Redeem transaction error:", e)

                response = "❌ Error procesando redención"

            finally:

                conn.autocommit = True

        #---------------------------------------------------------------------------------
        # REGISTRAR COMPRA
        #---------------------------------------------------------------------------------

        elif re.fullmatch(r"[A-F0-9]{8}", text.upper()) and state is None:

            conn.autocommit = False
            # conn.start_transaction()

            try:

                cursor.execute("""
                    SELECT id, branch_id, cafe_id
                    FROM cashier_codes
                    WHERE code=%s
                    AND expires_at > NOW()
                    AND used=0
                    FOR UPDATE
                    
                """, (text.upper(),))

                code_data = cursor.fetchone()

                if not code_data:

                    response = "❌ Código inválido o usado"

                    conn.commit()

                else:

                    branch_id = code_data["branch_id"]
                    cafe_id = code_data["cafe_id"]

                    create_purchase(
                        cursor,
                        conn,
                        customer_id,
                        branch_id,
                        cafe_id
                    )

                    mark_code_used(
                        cursor,
                        conn,
                        code_data["id"]
                    )

                    total = count_current_cycle(
                        cursor,
                        customer_id,
                        branch_id
                    )

                    existing_reward = get_pending_reward(
                        cursor,
                        customer_id,
                        branch_id
                    )

                    if total % 9 == 0 and not existing_reward:

                        create_reward(
                            cursor,
                            conn,
                            customer_id,
                            branch_id,
                            cafe_id
                        )

                        response = "🎉 Café gratis disponible" + closing()

                    else:

                        faltan = 9 - (total % 9)

                        if faltan == 9:
                            faltan = 0

                        response = f"☕ {total} compras. Te faltan {faltan}" + closing()

                    conn.commit()

            except Exception as e:

                conn.rollback()

                print("❌ Purchase transaction error:", e)

                response = "❌ Error procesando compra"

            finally:

                conn.autocommit = True

        #--------------------------------------------------------------------------------
        # RESET
        #--------------------------------------------------------------------------------
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