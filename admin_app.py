from flask import Flask, request, session, redirect, jsonify, render_template_string
import mysql.connector
from datetime import datetime, timedelta
import random
import requests
import os
import secrets


app = Flask(__name__)
app.secret_key = "super_secret_key_admin"

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
# LOGIN
# -------------------------
@app.route("/", methods=["GET", "POST"])
def login():

    if request.method == "POST":
        username = request.form.get("username").lower().strip()

        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("SELECT * FROM users WHERE username=%s", (username,))
        user = cursor.fetchone()

        if not user:
            cursor.close()
            conn.close()
            return "Usuario no existe", 404

        otp = str(random.randint(1000, 9999))
        expiry = datetime.utcnow() + timedelta(minutes=5)

        cursor.execute("""
            UPDATE users SET reset_code=%s, reset_expires=%s WHERE id=%s
        """, (otp, expiry, user["id"]))
        conn.commit()

        send_whatsapp(user["phone"], f"🔐 Tu código de acceso es: {otp}")

        cursor.close()
        conn.close()

        session["temp_user"] = user["id"]

        return redirect("/verify")

    return """
    <!DOCTYPE html>
    <html>
    <head>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
    :root{
        --bg:#1f1b17;
        --card:#253532;
        --accent:#517f83;
        --soft:#9e8d77;
        --espresso:#583d34;
        --text:#f5f5f5;
    }

    body{
        margin:0;
        font-family: Inter, sans-serif;
        background: radial-gradient(circle at top, var(--card), var(--bg));
        display:flex;
        justify-content:center;
        align-items:center;
        height:100vh;
        color:var(--text);
    }

    .card{
        background:rgba(37,53,50,0.7);
        backdrop-filter:blur(25px);
        padding:50px;
        border-radius:25px;
        text-align:center;
        border:1px solid rgba(255,255,255,0.06);
        animation:fade .6s ease;

        width:min(90vw, 600px);
        box-sizing:border-box;
    }

    @keyframes fade{
        from{opacity:0; transform:translateY(20px)}
        to{opacity:1; transform:translateY(0)}
    }

    .brand{
        text-align:center;
        font-size:22px;
        color:var(--soft);
        margin-bottom:25px;
        letter-spacing:1px;
    }

    input{
        width:100%;
        padding:14px;
        border-radius:12px;
        border:none;
        background:#1a1a1a;
        color:white;
        margin-bottom:20px;
        transition:.3s;
    }

    input:focus{
        outline:none;
        box-shadow:0 0 0 2px var(--accent);
        transform:scale(1.02);
    }

    button{
        width:100%;
        padding:14px;
        border:none;
        border-radius:12px;
        background:linear-gradient(135deg,var(--accent),var(--soft));
        color:#111;
        font-weight:bold;
        cursor:pointer;
        transition:.3s;
    }

    button:hover{
        transform:scale(1.05);
    }
    </style>
    </head>

    <body>
    <form method="POST" class="card">
        <div class="brand">☕ Coffee Admin</div>
        <input name="username" placeholder="Usuario" required>
        <button type="submit">Solicitar acceso</button>
    </form>
    </body>
    </html>
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

        cursor.execute("SELECT * FROM users WHERE id=%s", (session["temp_user"],))
        user = cursor.fetchone()

        if user and user["reset_code"] == otp and user["reset_expires"] > datetime.utcnow():
            cursor.execute("""
                UPDATE users
                SET reset_code=NULL,
                    reset_expires=NULL
                WHERE id=%s
            """, (user["id"],))

            conn.commit()

            session["user_id"] = user["id"]
            session["branch_id"] = user["branch_id"]
            session["cafe_id"] = user["cafe_id"]
            session["role"] = user["role"]

            session.pop("temp_user", None)

            return redirect("/admin/cashier")

        cursor.close()
        conn.close()
        return "OTP incorrecto", 401

    return """
    <!DOCTYPE html>
    <html>
    <head>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
    body{
        margin:0;
        background:#1f1b17;
        display:flex;
        justify-content:center;
        align-items:center;
        height:100vh;
        color:white;
        font-family:Inter;
    }

    .card{
        background:#253532;
        padding:40px;
        border-radius:20px;
        text-align:center;
        animation:fade .5s ease;
    }

    input{
        font-size:32px;
        letter-spacing:12px;
        text-align:center;
        padding:15px;
        border:none;
        border-radius:12px;
        background:#111;
        color:#9e8d77;
        margin-top:20px;
        transition:.3s;
    }

    input:focus{
        outline:none;
        transform:scale(1.08);
    }

    button{
        margin-top:20px;
        padding:12px;
        width:100%;
        border:none;
        border-radius:12px;
        background:#517f83;
        font-weight:bold;
        cursor:pointer;
    }
    </style>
    </head>

    <body>
    <form method="POST" class="card">
        <h2>🔐 Verificación</h2>
        <input name="otp" maxlength="4" required>
        <button>Validar</button>
    </form>
    </body>
    </html>
    """

# -------------------------
# CASHIER
# -------------------------
@app.route("/admin/cashier")
def cashier():
    if not session.get("user_id"):
        return redirect("/")

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT role
        FROM users
        WHERE id=%s
    """, (session["user_id"],))

    user = cursor.fetchone()

    cursor.close()
    conn.close()

    if not user or user["role"] not in ["admin", "cashier", "master"]:
        return "No autorizado", 403

    return render_template_string("""
    <!DOCTYPE html>
    <html>
    <head>
    <meta name="viewport" content="width=device-width, initial-scale=1">

    <style>
    :root{
        --bg:#1f1b17;
        --card:#253532;
        --accent:#517f83;
        --soft:#9e8d77;
        --danger:#ff6b6b;
    }

    body{
        margin:0;
        background:linear-gradient(160deg,#1f1b17,#253532);
        display:flex;
        justify-content:center;
        align-items:center;
        height:100vh;
        font-family:Inter;
        color:white;
    }

    .card{
        background:rgba(37,53,50,0.7);
        backdrop-filter:blur(25px);
        padding:50px;
        border-radius:25px;
        text-align:center;
        border:1px solid rgba(255,255,255,0.06);
        animation:fade .6s ease;
    }

    #code{
        font-size:clamp(32px, 12vw, 90px);
        letter-spacing:clamp(2px, 1vw, 16px);
        margin:30px 0;
        color:#f5f5f5;
        transition:.25s;

        width:100%;
        overflow-wrap:anywhere;
        word-break:break-word;
        text-align:center;
        line-height:1.1;
    }

    #timer{
        opacity:.7;
        transition:.3s;
    }

    .danger{
        color:var(--danger);
        transform:scale(1.1);
    }

    button{
        margin-top:20px;
        padding:12px 20px;
        border:none;
        border-radius:12px;
        background:var(--accent);
        color:white;
        font-weight:bold;
        cursor:pointer;
        transition:.3s;
    }

    button:hover{
        transform:scale(1.05);
    }

    @keyframes fade{
        from{opacity:0; transform:translateY(20px)}
        to{opacity:1; transform:translateY(0)}
    }
    </style>
    </head>

    <body>

    <div class="card">
        <div style="color:#9e8d77;">☕ Coffee Rewards</div>

        <div id="code">----</div>
        <div id="timer">Cargando...</div>

        <button onclick="load()">Actualizar</button>
    </div>

    <script>
    let seconds = 0;

    async function load(){
        let r = await fetch('/admin/get_code');
        let d = await r.json();

        let codeEl = document.getElementById("code");

        codeEl.style.transform="scale(0.7)";
        codeEl.style.opacity="0.4";

        setTimeout(()=>{
            codeEl.innerText = d.code;
            codeEl.style.transform="scale(1)";
            codeEl.style.opacity="1";
        },150);

        seconds = d.expires_in;
    }

    function tick(){

        if(seconds <= 0){
            load();
            return;
        }

        seconds--;

        let el = document.getElementById("timer");

        el.innerText = "Expira en " + seconds + "s";

        if(seconds <= 10){
            el.className = "danger";
        } else {
            el.className = "";
        }
    }

    setInterval(tick,1000);
    setInterval(load,30000);
    load();
    </script>

    </body>
    </html>
    """)

# -------------------------
# GET CODE
# -------------------------
@app.route("/admin/get_code")
def get_code():

    if not session.get("user_id"):
        return jsonify({"error": "unauthorized"}), 403

    branch_id = session.get("branch_id")
    cafe_id = session.get("cafe_id")

    print("SESSION DEBUG:", session)

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute("""
            SELECT * FROM cashier_codes
            WHERE branch_id=%s AND cafe_id=%s AND used=0 AND expires_at > NOW()
            ORDER BY id DESC LIMIT 1
        """, (branch_id, cafe_id))

        code = cursor.fetchone()

        if code:
            remaining = max(
                0,
                int((code["expires_at"].replace(tzinfo=None) - datetime.utcnow()).total_seconds())
            )
            return jsonify({
                "code": code["code"],
                "expires_in": max(0, remaining)
            })

        new_code = secrets.token_hex(4).upper()
        expiry = datetime.utcnow() + timedelta(seconds=60)

        cursor.execute("""
            INSERT INTO cashier_codes (code, branch_id, cafe_id, expires_at, used)
            VALUES (%s, %s, %s, %s, 0)
        """, (new_code, branch_id, cafe_id, expiry))

        conn.commit()

        return jsonify({"code": new_code, "expires_in": 60})

    except Exception as e:
        print("ERROR GET CODE:", e)
        return jsonify({"error": "server_error"}), 500

    finally:
        cursor.close()
        conn.close()

@app.route("/admin/logout")
def logout():
    session.clear()
    return redirect("/")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)