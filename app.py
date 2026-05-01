from flask import Flask, request, jsonify, render_template_string, session, redirect
import mysql.connector
from datetime import datetime, timedelta
import random
import requests
import os
import socket
import requests.packages.urllib3.util.connection as urllib3_cn

# -------------------------
# 🔧 APP INIT (FIXED)
# -------------------------
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "super_secret_key")

def allowed_gai_family():
    return socket.AF_INET

urllib3_cn.allowed_gai_family = allowed_gai_family

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
# 🔐 LOGIN (MODERN UI)
# -------------------------
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
            return redirect("/cashier")

        return "❌ Credenciales incorrectas"

    return render_template_string("""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Login</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">

        <style>
            body {
                margin: 0;
                font-family: 'Segoe UI', sans-serif;
                background: linear-gradient(135deg, #0f172a, #1e293b);
                display: flex;
                justify-content: center;
                align-items: center;
                height: 100vh;
                color: white;
            }

            .card {
                background: rgba(255,255,255,0.05);
                backdrop-filter: blur(20px);
                padding: 40px;
                border-radius: 20px;
                width: 320px;
                box-shadow: 0 20px 50px rgba(0,0,0,0.4);
            }

            h2 {
                text-align: center;
                margin-bottom: 25px;
            }

            input {
                width: 100%;
                padding: 12px;
                margin-bottom: 15px;
                border: none;
                border-radius: 10px;
                background: rgba(255,255,255,0.1);
                color: white;
            }

            button {
                width: 100%;
                padding: 12px;
                border: none;
                border-radius: 10px;
                background: #22c55e;
                color: white;
                font-weight: bold;
                cursor: pointer;
                transition: 0.3s;
            }

            button:hover {
                background: #16a34a;
            }
        </style>
    </head>

    <body>
        <div class="card">
            <h2>☕ Acceso Cafetería</h2>
            <form method="POST">
                <input name="username" placeholder="Usuario" required>
                <input name="password" type="password" placeholder="Contraseña" required>
                <button type="submit">Entrar</button>
            </form>
        </div>
    </body>
    </html>
    """)

# -------------------------
# 🔐 ACTIVE CODE API
# -------------------------
@app.route("/get_active_code")
def get_active_code():

    if not session.get("user_id"):
        return jsonify({"error": "unauthorized"}), 403

    branch_id = session.get("branch_id")

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute("DELETE FROM cashier_codes WHERE branch_id=%s AND expires_at < NOW()", (branch_id,))

        cursor.execute("""
            SELECT code, expires_at FROM cashier_codes
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
# 💻 CASHIER (PREMIUM UI)
# -------------------------
@app.route("/cashier")
def cashier():

    if not session.get("user_id"):
        return redirect("/login")

    return render_template_string("""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Código Caja</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">

        <style>
            body {
                margin: 0;
                font-family: 'Segoe UI', sans-serif;
                background: radial-gradient(circle at top, #1e293b, #020617);
                color: white;
                display: flex;
                justify-content: center;
                align-items: center;
                height: 100vh;
            }

            .card {
                text-align: center;
                padding: 40px;
                border-radius: 25px;
                background: rgba(255,255,255,0.05);
                backdrop-filter: blur(25px);
                box-shadow: 0 30px 80px rgba(0,0,0,0.6);
                width: 320px;
            }

            h1 {
                opacity: 0.7;
                margin-bottom: 10px;
            }

            #code {
                font-size: 70px;
                font-weight: bold;
                letter-spacing: 10px;
                margin: 20px 0;
                animation: pulse 1.5s infinite;
            }

            @keyframes pulse {
                0% { transform: scale(1); }
                50% { transform: scale(1.05); }
                100% { transform: scale(1); }
            }

            #countdown {
                font-size: 18px;
                margin-top: 10px;
            }

            .low {
                color: #ef4444;
            }

            .ok {
                color: #22c55e;
            }

            .logout {
                margin-top: 20px;
                font-size: 14px;
                opacity: 0.7;
                cursor: pointer;
            }

            .logout:hover {
                opacity: 1;
            }
        </style>
    </head>

    <body>
        <div class="card">
            <h1>🔐 Código activo</h1>
            <div id="code">----</div>
            <div id="countdown">Cargando...</div>

            <div class="logout" onclick="location.href='/logout'">
                Cerrar sesión
            </div>
        </div>

        <script>
            let secondsLeft = 0;

            function fetchCode() {
                fetch('/get_active_code')
                .then(r => r.json())
                .then(d => {
                    document.getElementById("code").innerText = d.code;
                    secondsLeft = d.expires_in;
                });
            }

            function tick() {
                if (secondsLeft <= 0) {
                    fetchCode();
                    return;
                }

                secondsLeft--;

                const el = document.getElementById("countdown");

                const m = Math.floor(secondsLeft / 60);
                const s = secondsLeft % 60;

                el.innerText = "Expira en: " + m + ":" + String(s).padStart(2, "0");

                el.className = secondsLeft <= 10 ? "low" : "ok";
            }

            fetchCode();
            setInterval(tick, 1000);
            setInterval(fetchCode, 30000);
        </script>
    </body>
    </html>
    """)

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