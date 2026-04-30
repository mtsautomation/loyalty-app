from flask import Flask, request, jsonify, render_template_string
import mysql.connector
from datetime import datetime, timedelta
import random
import requests
import os

app = Flask(__name__)

# 🔐 2CHAT CONFIG
API_KEY_2CHAT = os.environ.get("API_KEY_2CHAT")
URL_2CHAT = "https://api.2chat.co/v1/messaging/send/text"
FROM_NUMBER = "+529992922621"

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
    """
    Envía un mensaje de WhatsApp a través de la API de 2Chat.
    """
    try:
        # 1. Validación de Configuración
        if not API_KEY_2CHAT or API_KEY_2CHAT == "TU_API_KEY_AQUI":
            print("❌ ERROR: API KEY no configurada.")
            return False

        # 2. Preparación de Datos
        # Asumiendo que normalize_phone ya está definida en tu script
        phone_ready = normalize_phone(phone)

        payload = {
            "to_number": phone_ready,
            "from_number": FROM_NUMBER,
            "text": message
        }

        headers = {
            "X-User-API-Key": API_KEY_2CHAT,  # Header correcto para 2Chat
            "Content-Type": "application/json"
        }

        # 3. Petición
        # Usar json=payload es correcto para enviar el body como JSON
        res = requests.post(URL_2CHAT, json=payload, headers=headers, timeout=15)

        # 4. Manejo de Respuesta
        if res.status_code in [200, 201, 202]:
            print(f"✅ Mensaje enviado con éxito a {phone_ready}")
            return True
        else:
            print(f"⚠️ Error {res.status_code} en 2Chat: {res.text}")
            return False

    except requests.exceptions.Timeout:
        print("❌ Error: La solicitud excedió el tiempo de espera.")
    except Exception as e:
        print(f"❌ Error crítico en WhatsApp: {e}")

    return False

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
    # 2Chat envía los datos en una estructura específica, asegúrate de que coincida:
    # A veces es data.get("from") o data.get("sender", {}).get("phone")
    phone = normalize_phone(data.get("remote_phone_number"))
    text = data.get("text", "").strip().lower()  # 2Chat suele enviar 'text' directo o dentro de 'message'

    if not phone:
        return jsonify({"status": "no phone"}), 200

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:
        customer = get_customer(cursor, phone)
        customer_id = customer["id"] if customer else create_customer(cursor, conn, phone)

        response_text = ""

        # LÓGICA DE RESPUESTAS
        if text in ["status", "puntos"]:
            total = count_purchases(cursor, customer_id)
            response_text = f"☕ Llevas {total} cafés acumulados."

        elif text.isdigit():
            branch_id = 1
            if validate_code(cursor, text, branch_id):
                create_purchase(cursor, conn, customer_id, branch_id)
                total = count_purchases(cursor, customer_id)

                if total % 9 == 0:
                    create_reward(cursor, conn, customer_id)
                    response_text = "🎉 ¡Felicidades! Has desbloqueado un café GRATIS. Muéstrale este mensaje al barista."
                else:
                    response_text = f"☕ ¡Código aceptado! Llevas {total} cafés acumulados. Te faltan {9 - (total % 9)} para el próximo gratis."
            else:
                response_text = "❌ El código es incorrecto o ya expiró. Pide uno nuevo al cajero."

        else:
            response_text = "👋 ¡Hola! Bienvenido a nuestro programa de lealtad.\n\nEscribe el *código de 4 dígitos* que aparece en la caja para registrar tu compra.\n\nO escribe *puntos* para ver tu progreso."

        # ESTA ES LA PARTE CLAVE: Enviar el mensaje de vuelta
        send_whatsapp(phone, response_text)

        return jsonify({"status": "success"}), 200

    except Exception as e:
        print("❌ Error webhook:", str(e))
        return jsonify({"status": "error"}), 500
    finally:
        cursor.close()
        conn.close()
# -------------------------
# RUN
# -------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))