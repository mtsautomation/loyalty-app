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
        password = request.form.get("password")

        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT * FROM users 
            WHERE username=%s AND password=%s
        """, (username, password))

        user = cursor.fetchone()

        if not user:
            return "❌ Credenciales incorrectas"

        # generar OTP
        otp = str(random.randint(1000, 9999))
        expiry = datetime.utcnow() + timedelta(minutes=5)

        cursor.execute("""
            UPDATE users 
            SET otp_code=%s, otp_expiry=%s
            WHERE id=%s
        """, (otp, expiry, user["id"]))
        conn.commit()

        send_whatsapp(user["phone"], f"🔐 Tu código OTP es: {otp}")

        session["tmp_user"] = user["id"]

        cursor.close()
        conn.close()

        return redirect("/verify")

    return """
    <h2>Login Administrador</h2>
    <form method="POST">
        Usuario:<br><input name="username"><br><br>
        Password:<br><input type="password" name="password"><br><br>
        <button>Solicitar acceso</button>
    </form>
    """

# -------------------------
# VERIFY OTP
# -------------------------
@app.route("/verify", methods=["GET", "POST"])
def verify():

    if "tmp_user" not in session:
        return redirect("/")

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

        return "❌ OTP inválido o expirado"

    return """
    <h2>Verificación OTP</h2>
    <form method="POST">
        Código:<br><input name="otp"><br><br>
        <button>Entrar</button>
    </form>
    """

# -------------------------
# CASHIER
# -------------------------
@app.route("/cashier")
def cashier():

    if not session.get("user_id"):
        return redirect("/")

    return render_template_string("""
    <h1>🔐 Código dinámico</h1>
    <div id="code">----</div>
    <div id="timer"></div>

    <script>
        let seconds = 0;

        async function load(){
            let r = await fetch('/get_code')
            let d = await r.json()
            document.getElementById("code").innerText = d.code
            seconds = d.expires_in
        }

        function tick(){
            seconds--
            document.getElementById("timer").innerText = "Expira en: " + seconds
            if(seconds <= 0){
                load()
            }
        }

        setInterval(tick, 1000)
        setInterval(load, 30000)
        load()
    </script>
    """)

# -------------------------
# GENERAR CODIGO
# -------------------------
@app.route("/get_code")
def get_code():

    if not session.get("user_id"):
        return jsonify({"error": "unauthorized"}), 403

    branch_id = session["branch_id"]

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

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

# -------------------------
# LOGOUT
# -------------------------
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

# -------------------------
# RUN
# -------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)