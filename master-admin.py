from flask import Flask, request, jsonify
import mysql.connector
from datetime import datetime
import requests
import os
import json

app = Flask(__name__)

# =====================================================
# CONFIG
# =====================================================

API_KEY_2CHAT = os.environ.get("API_KEY_2CHAT")
FROM_NUMBER = "529991900664"

DB_CONFIG = {
    "host": os.environ.get("DB_HOST"),
    "user": os.environ.get("DB_USER"),
    "password": os.environ.get("DB_PASSWORD"),
    "database": os.environ.get("DB_NAME")
}

MASTER_ROLES = ["master"]

# =====================================================
# DB
# =====================================================

def get_db():
    return mysql.connector.connect(**DB_CONFIG)

# =====================================================
# WHATSAPP
# =====================================================

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

        r = requests.post(
            "https://api.p.2chat.io/open/whatsapp/send-message",
            json=payload,
            headers=headers,
            timeout=10
        )

        print("📤", r.status_code, r.text)

    except Exception as e:
        print("❌ SEND ERROR:", e)

# =====================================================
# NORMALIZE PHONE
# =====================================================

def normalize_phone(phone):

    if not phone:
        return None

    phone = phone.replace("+", "").replace(" ", "").strip()

    if phone.startswith("52"):
        return phone

    if len(phone) == 10:
        return "52" + phone

    return phone

# =====================================================
# MASTER VALIDATION
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
# STATES
# =====================================================

def get_state(cursor, phone):

    cursor.execute("""
        SELECT * FROM admin_states
        WHERE phone=%s
        LIMIT 1
    """, (phone,))

    return cursor.fetchone()

def save_state(cursor, conn, phone, state, temp_data=None):

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
            VALUES (%s, %s, %s, %s)
        """, (
            phone,
            state,
            temp_json,
            datetime.utcnow()
        ))

    conn.commit()

def clear_state(cursor, conn, phone):

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
        VALUES (%s, %s)
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
        VALUES (%s, %s, %s, %s)
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

# =====================================================
# WEBHOOK
# =====================================================

@app.route("/webhook", methods=["POST"])
def webhook():

    print("📩 RAW:", request.data)

    try:
        data = request.get_json(force=True, silent=True)

        if not data:
            data = request.form.to_dict() or {}

    except Exception as e:

        print("❌ JSON ERROR:", e)
        data = {}

    print("📩", data)

    phone = normalize_phone(
        data.get("remote_phone_number")
    )

    text = data.get(
        "message",
        {}
    ).get(
        "text",
        ""
    ).strip()

    lower = text.lower()

    if not phone:
        return jsonify({"status": "no phone"}), 200

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:

        master = get_master_user(cursor, phone)

        if not master:
            return jsonify({"status": "ignored"}), 200

        state_data = get_state(cursor, phone)

        state = None
        temp_data = {}

        if state_data:
            state = state_data["state"]

            if state_data["temp_data"]:
                temp_data = json.loads(
                    state_data["temp_data"]
                )

        response = ""

        # =====================================================
        # START FLOW
        # =====================================================

        if lower == "alta cafeteria":

            save_state(
                cursor,
                conn,
                phone,
                "await_cafe_name",
                {}
            )

            response = "☕ Nombre de la cafetería:"

        # =====================================================
        # CAFE NAME
        # =====================================================

        elif state == "await_cafe_name":

            temp_data["cafe_name"] = text

            save_state(
                cursor,
                conn,
                phone,
                "await_branch_name",
                temp_data
            )

            response = "📍 Nombre de la primera sucursal:"

        # =====================================================
        # BRANCH NAME
        # =====================================================

        elif state == "await_branch_name":

            temp_data["branch_name"] = text

            save_state(
                cursor,
                conn,
                phone,
                "await_branch_address",
                temp_data
            )

            response = "🏠 Dirección de la sucursal:"

        # =====================================================
        # BRANCH ADDRESS
        # =====================================================

        elif state == "await_branch_address":

            temp_data["branch_address"] = text

            save_state(
                cursor,
                conn,
                phone,
                "await_admin_username",
                temp_data
            )

            response = "👤 Username del admin:"

        # =====================================================
        # ADMIN USERNAME
        # =====================================================

        elif state == "await_admin_username":

            temp_data["admin_username"] = text

            save_state(
                cursor,
                conn,
                phone,
                "await_admin_password",
                temp_data
            )

            response = "🔐 Password del admin:"

        # =====================================================
        # ADMIN PASSWORD
        # =====================================================

        elif state == "await_admin_password":

            temp_data["admin_password"] = text

            save_state(
                cursor,
                conn,
                phone,
                "await_admin_phone",
                temp_data
            )

            response = "📱 Teléfono del admin:"

        # =====================================================
        # ADMIN PHONE
        # =====================================================

        elif state == "await_admin_phone":

            admin_phone = normalize_phone(text)

            temp_data["admin_phone"] = admin_phone

            # =====================================================
            # CREATE EVERYTHING
            # =====================================================

            cafe_id = create_cafe(
                cursor,
                conn,
                temp_data["cafe_name"]
            )

            branch_id = create_branch(
                cursor,
                conn,
                cafe_id,
                temp_data["branch_name"],
                temp_data["branch_address"]
            )

            create_user(
                cursor,
                conn,
                temp_data["admin_username"],
                temp_data["admin_password"],
                admin_phone,
                "admin",
                cafe_id,
                branch_id
            )

            clear_state(cursor, conn, phone)

            response = f"""
✅ Cafetería creada

☕ {temp_data['cafe_name']}

✅ Sucursal creada

📍 {temp_data['branch_name']}

✅ Admin creado

👤 {temp_data['admin_username']}
📱 {admin_phone}
"""

        # =====================================================
        # CANCEL
        # =====================================================

        elif lower == "cancelar":

            clear_state(cursor, conn, phone)

            response = "❌ Flujo cancelado"

        # =====================================================
        # HELP
        # =====================================================

        else:

            response = """
☕ MASTER ADMIN

Comandos:

• alta cafeteria
• cancelar
"""

        send_whatsapp(phone, response)

        return jsonify({"status": "ok"}), 200

    except Exception as e:

        print("❌ ERROR:", e)

        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

    finally:

        cursor.close()
        conn.close()

# =====================================================
# RUN
# =====================================================

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5002))
    )