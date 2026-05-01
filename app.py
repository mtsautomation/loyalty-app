from flask import Flask, request, jsonify, render_template_string, session, redirect
import mysql.connector
from datetime import datetime, timedelta
import random
import requests
import os
import hashlib

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "super_secret_key")

app.config.update(
    SESSION_PERMANENT=False,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=True
)

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
# 🔐 SECURITY
# -------------------------
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def generate_otp():
    return str(random.randint(100000, 999999))

# -------------------------
# 📲 WHATSAPP
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

        requests.post(
            "https://api.p.2chat.io/open/whatsapp/send-message",
            json=payload,
            headers=headers,
            timeout=10
        )
    except Exception as e:
        print("WhatsApp error:", e)

# -------------------------
# 🔐 LOGIN
# -------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = request.form.get("username")
        password = hash_password(request.form.get("password"))

        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("SELECT * FROM users WHERE username=%s AND password=%s", (user, password))
        admin = cursor.fetchone()

        cursor.close()
        conn.close()

        if admin:
            session["admin"] = True
            session["phone"] = admin["phone"]
            session["branch_id"] = admin["branch_id"]
            return redirect("/cashier")

        return "Login incorrecto", 401

    return """
    <style>
    body {background:#0f172a;color:white;font-family:sans-serif;text-align:center;margin-top:100px}
    input{padding:10px;margin:10px;border-radius:8px;border:none;width:200px}
    button{padding:10px 20px;border:none;border-radius:10px;background:#22c55e;color:white}
    </style>

    <h2>☕ Admin Login</h2>
    <form method="POST">
        <input name="username" placeholder="Usuario"><br>
        <input type="password" name="password" placeholder="Password"><br>
        <button>Entrar</button>
    </form>

    <br><br>
    <a href="/reset_password" style="color:#38bdf8">¿Olvidaste tu contraseña?</a>
    """

# -------------------------
# 🔐 OTP RESET PASSWORD
# -------------------------
@app.route("/reset_password", methods=["GET", "POST"])
def reset_password():
    if request.method == "POST":
        username = request.form.get("username")

        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("SELECT * FROM users WHERE username=%s", (username,))
        user = cursor.fetchone()

        if not user:
            return "Usuario no encontrado", 404

        otp = generate_otp()

        cursor.execute("""
            UPDATE users SET otp=%s, otp_expire=%s
            WHERE id=%s
        """, (otp, datetime.utcnow() + timedelta(minutes=5), user["id"]))

        conn.commit()

        send_whatsapp(user["phone"], f"🔐 Tu código de recuperación es: {otp}")

        cursor.close()
        conn.close()

        return redirect(f"/verify_otp?user={username}")

    return """
    <h2>Recuperar contraseña</h2>
    <form method="POST">
        Usuario: <input name="username"><br><br>
        <button>Enviar código</button>
    </form>
    """

@app.route("/verify_otp", methods=["GET", "POST"])
def verify_otp():
    username = request.args.get("user")

    if request.method == "POST":
        otp = request.form.get("otp")
        new_pass = hash_password(request.form.get("password"))

        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT * FROM users 
            WHERE username=%s AND otp=%s AND otp_expire > %s
        """, (username, otp, datetime.utcnow()))

        user = cursor.fetchone()

        if not user:
            return "OTP inválido o expirado", 400

        cursor.execute("""
            UPDATE users SET password=%s, otp=NULL, otp_expire=NULL
            WHERE id=%s
        """, (new_pass, user["id"]))

        conn.commit()

        cursor.close()
        conn.close()

        return "✅ Contraseña actualizada. <a href='/login'>Login</a>"

    return f"""
    <h2>Verificar código</h2>
    <form method="POST">
        Código OTP: <input name="otp"><br><br>
        Nueva contraseña: <input type="password" name="password"><br><br>
        <button>Cambiar contraseña</button>
    </form>
    """

# -------------------------
# 💻 CASHIER (PROTECTED)
# -------------------------
@app.route("/cashier")
def cashier():
    if not session.get("admin"):
        return redirect("/login")

    return render_template_string("""
    <html>
    <head>
        <style>
        body {background:#0f172a;color:white;text-align:center;font-family:sans-serif}
        .card{background:#1e293b;padding:30px;border-radius:20px;margin-top:100px}
        #code{font-size:60px;margin:20px}
        </style>
    </head>

    <body>
        <div class="card">
            <h2>🔐 Código activo</h2>
            <div id="code">----</div>
            <div id="timer"></div>
        </div>

        <script>
        let t = 0;

        function getCode(){
            fetch("/get_active_code")
            .then(r=>r.json())
            .then(d=>{
                document.getElementById("code").innerText = d.code;
                t = d.expires_in;
            })
        }

        function tick(){
            if(t<=0){getCode();return;}
            t--;
            document.getElementById("timer").innerText = "Expira en: "+t+"s";
        }

        getCode();
        setInterval(tick,1000);
        </script>
    </body>
    </html>
    """)

# -------------------------
# 🔐 CODE GENERATION
# -------------------------
@app.route("/get_active_code")
def get_code():
    if not session.get("admin"):
        return jsonify({"error":"unauthorized"}),403

    branch_id = session.get("branch_id")

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT code, expires_at FROM cashier_codes
        WHERE branch_id=%s AND used=0 AND expires_at > NOW()
        ORDER BY id DESC LIMIT 1
    """, (branch_id,))

    r = cursor.fetchone()

    if r:
        seconds = int((r["expires_at"] - datetime.utcnow()).total_seconds())
        return jsonify({"code": r["code"], "expires_in": seconds})

    code = str(random.randint(1000,9999))
    exp = datetime.utcnow() + timedelta(seconds=60)

    cursor.execute("""
        INSERT INTO cashier_codes (code, branch_id, expires_at, used)
        VALUES (%s,%s,%s,0)
    """,(code,branch_id,exp))

    conn.commit()

    return jsonify({"code":code,"expires_in":60})

# -------------------------
# LOGOUT
# -------------------------
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

# -------------------------
# RUN
# -------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))