from flask import Flask, request, session, redirect, jsonify, render_template_string
import mysql.connector
from datetime import datetime, timedelta
import random
import requests
import os

app = Flask(__name__)
app.secret_key = "super_secret_key_admin"

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
        print("WhatsApp error:", e)

# -------------------------
# LOGIN STEP 1
# -------------------------
@app.route("/", methods=["GET", "POST"])
def login():

    if request.method == "POST":
        username = request.form.get("username")

        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("SELECT * FROM users WHERE username=%s", (username,))
        user = cursor.fetchone()

        if not user:
            return "Usuario no existe", 404

        # generar OTP
        otp = str(random.randint(1000, 9999))
        expiry = datetime.utcnow() + timedelta(minutes=5)

        cursor.execute("""
            UPDATE users SET reset_code=%s, reset_expires=%s WHERE id=%s
        """, (otp, expiry, user["id"]))
        conn.commit()

        # enviar por WhatsApp
        send_whatsapp(user["phone"], f"🔐 Tu código de acceso es: {otp}")

        cursor.close()
        conn.close()

        session["temp_user"] = user["id"]

        return redirect("/verify")

    return """
    <h2>Login Administrador</h2>
    <form method="POST">
        Usuario:<br>
        <input name="username" required><br><br>

        <button type="submit">Solicitar acceso</button>
    </form>
    """
# -------------------------
# VERIFY OTP
# -------------------------
@app.route("/verify", methods=["GET", "POST"])
def verify():

    if not session.get("temp_user"):
        return redirect("/")

    if request.method == "POST":
        otp = request.form.get("otp")

        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT * FROM users WHERE id=%s
        """, (session["temp_user"],))

        user = cursor.fetchone()

        if user and user["reset_code"] == otp and user["reset_expires"] > datetime.utcnow():

            session["user_id"] = user["id"]
            session["branch_id"] = user["branch_id"]
            session.pop("temp_user", None)

            cursor.close()
            conn.close()

            return redirect("/admin/cashier")

        cursor.close()
        conn.close()

        return "OTP incorrecto o expirado", 401

    return """
    <h2>Verificación</h2>
    <form method="POST">
        Código OTP:<br>
        <input name="otp" required><br><br>

        <button type="submit">Ingresar</button>
    </form>
    """
# -------------------------
# CASHIER
# -------------------------
@app.route("/admin/cashier")
def cashier():

    if not session.get("user_id"):
        return redirect("/")

    return render_template_string("""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Código de Caja</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">

        <style>
            body {
                margin: 0;
                font-family: 'Segoe UI', sans-serif;
                background: linear-gradient(135deg, #2c1b12, #1a120d);
                color: #f5e6d3;
                display: flex;
                align-items: center;
                justify-content: center;
                height: 100vh;
            }

            .card {
                background: #3b2a21;
                padding: 40px;
                border-radius: 20px;
                width: 90%;
                max-width: 420px;
                text-align: center;
                box-shadow: 0 20px 50px rgba(0,0,0,0.6);
                border: 1px solid rgba(255,255,255,0.05);
            }

            .title {
                font-size: 18px;
                letter-spacing: 2px;
                text-transform: uppercase;
                opacity: 0.7;
            }

            .brand {
                font-size: 22px;
                margin-top: 5px;
                color: #d6a85f;
                font-weight: bold;
            }

            #code {
                font-size: 72px;
                font-weight: bold;
                letter-spacing: 12px;
                margin: 30px 0;
                color: #fff3e0;
                text-shadow: 0 0 10px rgba(255, 220, 150, 0.3);
                transition: all 0.3s ease;
            }

            #timer {
                font-size: 18px;
                margin-top: 10px;
                padding: 10px;
                border-radius: 10px;
                display: inline-block;
                min-width: 120px;
            }

            .ok {
                color: #8bcf9b;
            }

            .warning {
                color: #f4c430;
            }

            .danger {
                color: #ff6b6b;
                animation: pulse 1s infinite;
            }

            @keyframes pulse {
                0% { transform: scale(1); }
                50% { transform: scale(1.08); }
                100% { transform: scale(1); }
            }

            .footer {
                margin-top: 20px;
                font-size: 12px;
                opacity: 0.4;
            }

            button {
                margin-top: 20px;
                padding: 10px 20px;
                background: #d6a85f;
                border: none;
                border-radius: 10px;
                color: #2c1b12;
                font-weight: bold;
                cursor: pointer;
            }

            button:hover {
                background: #e5b96c;
            }
        </style>
    </head>

    <body>

    <div class="card">
        <div class="title">Sistema de Caja</div>
        <div class="brand">☕ Coffee Rewards</div>

        <div id="code">----</div>

        <div id="timer" class="ok">Cargando...</div>

        <button onclick="load()">🔄 Actualizar</button>

        <div class="footer">
            Código válido por tiempo limitado
        </div>
    </div>

    <script>
        let seconds = 0;

        async function load(){
            try {
                let r = await fetch('/admin/get_code');
                let d = await r.json();

                document.getElementById("code").innerText = d.code;
                seconds = d.expires_in;
            } catch(e){
                console.error(e);
            }
        }

        function tick(){
            if(seconds <= 0){
                load();
                return;
            }

            seconds--;

            let el = document.getElementById("timer");

            let m = Math.floor(seconds / 60);
            let s = seconds % 60;

            el.innerText = "Expira en " + m + ":" + String(s).padStart(2, "0");

            if(seconds > 20){
                el.className = "ok";
            } else if(seconds > 10){
                el.className = "warning";
            } else {
                el.className = "danger";
            }
        }

        setInterval(tick, 1000);
        setInterval(load, 30000);

        load();
    </script>

    </body>
    </html>
    """)
# -------------------------
# GENERAR CODIGO
# -------------------------
@app.route("/admin/get_code")
def get_code():

    if not session.get("user_id"):
        return jsonify({"error": "unauthorized"}), 403

    branch_id = session["branch_id"]

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute("""
            SELECT * FROM cashier_codes
            WHERE branch_id=%s AND used=0 AND expires_at > NOW()
            ORDER BY id DESC LIMIT 1
        """, (branch_id,))

        code = cursor.fetchone()

        if code:
            remaining = int((code["expires_at"] - datetime.utcnow()).total_seconds())
            return jsonify({"code": code["code"], "expires_in": remaining})

        new_code = str(random.randint(1000, 9999))
        expiry = datetime.utcnow() + timedelta(seconds=60)

        cursor.execute("""
            INSERT INTO cashier_codes (code, branch_id, expires_at, used)
            VALUES (%s, %s, %s, 0)
        """, (new_code, branch_id, expiry))

        conn.commit()

        return jsonify({"code": new_code, "expires_in": 60})

    finally:
        cursor.close()
        conn.close()
# -------------------------
# LOGOUT
# -------------------------
@app.route("/admin/logout")
def logout():
    session.clear()
    return redirect("/")

# -------------------------
# RUN
# -------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)