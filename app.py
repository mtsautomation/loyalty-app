from flask import Flask, request, jsonify, render_template_string, session, redirect
import mysql.connector
from datetime import datetime, timedelta
import random
import requests
import os
import socket
import bcrypt
import requests.packages.urllib3.util.connection as urllib3_cn

# -------------------------
# ⚙️ NETWORK FIX
# -------------------------
def allowed_gai_family():
    return socket.AF_INET

urllib3_cn.allowed_gai_family = allowed_gai_family

# -------------------------
# 🚀 APP
# -------------------------
app = Flask(__name__)

# 🔐 SESSION CONFIG (MUY IMPORTANTE)
app.secret_key = os.environ.get("SECRET_KEY", "super_secret_key")
app.config["SESSION_PERMANENT"] = False  # 🔥 se borra al cerrar navegador
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SECURE"] = True  # solo https en producción

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
# 🔐 PASSWORD
# -------------------------
def hash_password(password):
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def verify_password(password, hashed):
    return bcrypt.checkpw(password.encode(), hashed.encode())

def generate_otp():
    return str(random.randint(100000, 999999))

# -------------------------
# 📲 WHATSAPP
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
        print("❌ WhatsApp:", e)

# -------------------------
# 🔐 LOGIN (FASE 1)
# -------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("SELECT * FROM admins WHERE username=%s", (username,))
        admin = cursor.fetchone()

        cursor.close()
        conn.close()

        if admin and verify_password(password, admin["password"]):

            otp = generate_otp()
            expires = datetime.utcnow() + timedelta(minutes=5)

            conn = get_db()
            cursor = conn.cursor()

            cursor.execute("""
                UPDATE admins
                SET reset_code=%s, reset_expires=%s
                WHERE id=%s
            """, (otp, expires, admin["id"]))
            conn.commit()

            cursor.close()
            conn.close()

            send_whatsapp(admin["phone"], f"🔐 Tu código de acceso es: {otp}")

            session.clear()
            session["pending_admin"] = admin["id"]

            return redirect("/verify")

        return render_template_string(LOGIN_HTML, error="Credenciales incorrectas")

    return render_template_string(LOGIN_HTML)

# -------------------------
# 🔐 VERIFY OTP (FASE 2)
# -------------------------
@app.route("/verify", methods=["GET", "POST"])
def verify():

    if not session.get("pending_admin"):
        return redirect("/login")

    if request.method == "POST":
        code = request.form.get("code")

        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT * FROM admins
            WHERE id=%s AND reset_code=%s AND reset_expires > NOW()
        """, (session["pending_admin"], code))

        admin = cursor.fetchone()

        cursor.close()
        conn.close()

        if admin:
            session.clear()
            session["admin_id"] = admin["id"]
            session["branch_id"] = admin["branch_id"]

            return redirect("/cashier")

    return render_template_string(VERIFY_HTML)

# -------------------------
# 🔐 LOGOUT
# -------------------------
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

# -------------------------
# 🔐 PROTECTED ROUTE
# -------------------------
def is_logged():
    return session.get("admin_id")

# -------------------------
# 🔐 GET ACTIVE CODE
# -------------------------
@app.route("/get_active_code")
def get_active_code():

    if not is_logged():
        return jsonify({"error": "unauthorized"}), 403

    branch_id = session.get("branch_id")

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute("""
            DELETE FROM cashier_codes
            WHERE branch_id=%s AND expires_at < NOW()
        """, (branch_id,))

        cursor.execute("""
            SELECT * FROM cashier_codes
            WHERE branch_id=%s AND used=0
            ORDER BY id DESC LIMIT 1
        """, (branch_id,))

        row = cursor.fetchone()

        if row:
            remaining = int((row["expires_at"] - datetime.utcnow()).total_seconds())
            return jsonify({"code": row["code"], "expires_in": max(0, remaining)})

        code = str(random.randint(1000, 9999))
        expires = datetime.utcnow() + timedelta(seconds=60)

        cursor.execute("""
            INSERT INTO cashier_codes (code, branch_id, expires_at, used)
            VALUES (%s, %s, %s, 0)
        """, (code, branch_id, expires))

        conn.commit()

        return jsonify({"code": code, "expires_in": 60})

    finally:
        cursor.close()
        conn.close()

# -------------------------
# 💻 CASHIER UI
# -------------------------
@app.route("/cashier")
def cashier():

    if not is_logged():
        return redirect("/login")

    return render_template_string(CASHIER_HTML)

# -------------------------
# 🎨 LOGIN UI
# -------------------------
LOGIN_HTML = """
<!DOCTYPE html>
<html>
<head>
<title>Login</title>
<style>
body {background:#0f172a;color:white;display:flex;justify-content:center;align-items:center;height:100vh;font-family:sans-serif;}
.card {background:#1e293b;padding:40px;border-radius:20px;width:300px;}
input {display:block;margin:10px 0;padding:12px;width:100%;border-radius:10px;border:none;}
button {padding:12px;width:100%;background:#22c55e;border:none;border-radius:10px;color:white;}
.error {color:#f87171;}
</style>
</head>
<body>
<div class="card">
<h2>☕ Login</h2>
{% if error %}<div class="error">{{error}}</div>{% endif %}
<form method="POST">
<input name="username" placeholder="Usuario">
<input name="password" type="password" placeholder="Password">
<button>Entrar</button>
</form>
</div>
</body>
</html>
"""

# -------------------------
# 🎨 VERIFY UI
# -------------------------
VERIFY_HTML = """
<!DOCTYPE html>
<html>
<head>
<title>Verificación</title>
<style>
body {background:#0f172a;color:white;display:flex;justify-content:center;align-items:center;height:100vh;font-family:sans-serif;}
.card {background:#1e293b;padding:40px;border-radius:20px;width:300px;text-align:center;}
input {margin:10px 0;padding:12px;width:100%;border-radius:10px;border:none;}
button {padding:12px;width:100%;background:#22c55e;border:none;border-radius:10px;color:white;}
</style>
</head>
<body>
<div class="card">
<h2>🔐 Código OTP</h2>
<form method="POST">
<input name="code" placeholder="Código recibido">
<button>Verificar</button>
</form>
</div>
</body>
</html>
"""

# -------------------------
# 🎨 CASHIER UI
# -------------------------
CASHIER_HTML = """
<!DOCTYPE html>
<html>
<head>
<title>Código</title>
<style>
body {background:#0f172a;color:white;display:flex;justify-content:center;align-items:center;height:100vh;font-family:sans-serif;}
.card {background:#1e293b;padding:40px;border-radius:20px;text-align:center;}
#code {font-size:70px;margin:20px;}
</style>
</head>
<body>
<div class="card">
<h2>🔐 Código dinámico</h2>
<div id="code">----</div>
<div id="timer"></div>
<br>
<a href="/logout">Cerrar sesión</a>
</div>

<script>
let t=0;

function fetchCode(){
 fetch('/get_active_code')
 .then(r=>r.json())
 .then(d=>{
   document.getElementById("code").innerText=d.code;
   t=d.expires_in;
 });
}

function tick(){
 if(t<=0){fetchCode();return;}
 t--;
 document.getElementById("timer").innerText="Expira en "+t+"s";
}

fetchCode();
setInterval(tick,1000);
setInterval(fetchCode,30000);
</script>
</body>
</html>
"""

# -------------------------
# 🚀 RUN
# -------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))