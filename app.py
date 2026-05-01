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
# ⚙️ FIX NETWORK
# -------------------------
def allowed_gai_family():
    return socket.AF_INET

urllib3_cn.allowed_gai_family = allowed_gai_family

# -------------------------
# 🚀 APP
# -------------------------
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "super_secret_key")

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
# 🔐 PASSWORD HELPERS
# -------------------------
def hash_password(password):
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def verify_password(password, hashed):
    return bcrypt.checkpw(password.encode(), hashed.encode())

def generate_reset_code():
    return str(random.randint(100000, 999999))

# -------------------------
# 🔐 LOGIN
# -------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("SELECT * FROM users WHERE username=%s", (username,))
        user = cursor.fetchone()

        cursor.close()
        conn.close()

        if user and verify_password(password, user["password"]):
            session["user_id"] = user["id"]
            session["branch_id"] = user["branch_id"]
            return redirect("/cashier")

        return render_template_string(LOGIN_HTML, error="Credenciales incorrectas")

    return render_template_string(LOGIN_HTML)

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

# -------------------------
# 🔐 ACTIVE CODE
# -------------------------
@app.route("/get_active_code")
def get_active_code():

    if not session.get("user_id"):
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
# 💻 CASHIER UI
# -------------------------
@app.route("/cashier")
def cashier():
    if not session.get("user_id"):
        return redirect("/login")
    return render_template_string(CASHIER_HTML)

# -------------------------
# 📱 PHONE
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
        print("❌ WhatsApp error:", e)

# -------------------------
# 📩 WEBHOOK (BOT + RESET PASSWORD)
# -------------------------
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()

    phone = normalize_phone(data.get("remote_phone_number"))
    text = data.get("message", {}).get("text", "").strip().lower()

    if not phone:
        return jsonify({"status": "no phone"}), 200

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:
        # Buscar usuario (para reset)
        cursor.execute("SELECT * FROM users WHERE phone=%s", (phone,))
        user = cursor.fetchone()

        state = user.get("state") if user else None
        response = ""

        # -------------------------
        # 🔑 INICIAR RESET
        # -------------------------
        if text == "cambiar contraseña":

            if not user:
                response = "❌ Este número no está autorizado"
            else:
                code = generate_reset_code()
                expires = datetime.utcnow() + timedelta(minutes=5)

                cursor.execute("""
                    UPDATE users 
                    SET reset_code=%s, reset_expires=%s, state=%s
                    WHERE id=%s
                """, (code, expires, "await_code", user["id"]))
                conn.commit()

                response = f"🔐 Código: {code}\nVálido por 5 minutos"

        # -------------------------
        # ✅ VALIDAR CODIGO
        # -------------------------
        elif state == "await_code" and text.isdigit():

            cursor.execute("""
                SELECT * FROM users 
                WHERE phone=%s AND reset_code=%s AND reset_expires > NOW()
            """, (phone, text))

            valid = cursor.fetchone()

            if not valid:
                response = "❌ Código inválido"
            else:
                cursor.execute("""
                    UPDATE users SET state='await_pass' WHERE id=%s
                """, (valid["id"],))
                conn.commit()

                response = "✏️ Envía:\nnueva: tupassword"

        # -------------------------
        # 🔐 NUEVA PASSWORD
        # -------------------------
        elif state == "await_pass" and text.startswith("nueva:"):

            new_pass = text.replace("nueva:", "").strip()
            hashed = hash_password(new_pass)

            cursor.execute("""
                UPDATE users 
                SET password=%s, reset_code=NULL, reset_expires=NULL, state=NULL
                WHERE phone=%s
            """, (hashed, phone))
            conn.commit()

            response = "✅ Contraseña actualizada"

        else:
            response = "👋 Escribe *cambiar contraseña* para actualizar tu acceso"

        send_whatsapp(phone, response)
        return jsonify({"status": "ok"}), 200

    except Exception as e:
        print("❌ ERROR:", e)
        return jsonify({"status": "error"}), 500

    finally:
        cursor.close()
        conn.close()

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
.card {background:#1e293b;padding:40px;border-radius:20px;}
input {display:block;margin:10px 0;padding:10px;width:100%;border-radius:10px;border:none;}
button {padding:10px;width:100%;background:#22c55e;border:none;border-radius:10px;color:white;}
</style>
</head>
<body>
<div class="card">
<h2>☕ Login</h2>
{% if error %}<p>{{error}}</p>{% endif %}
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
<h2>🔐 Código</h2>
<div id="code">----</div>
<div id="timer"></div>
<br>
<a href="/logout" style="color:#94a3b8;">Cerrar sesión</a>
</div>

<script>
let t=0;
function fetchCode(){
 fetch('/get_active_code').then(r=>r.json()).then(d=>{
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
</script>
</body>
</html>
"""

# -------------------------
# 🚀 RUN
# -------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))