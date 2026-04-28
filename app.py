from flask import Flask, request, jsonify, render_template_string, session, redirect
import mysql.connector
from datetime import datetime, timedelta
import random
import requests
import os

app = Flask(__name__)
app.secret_key = "secret123"

# 🔐 2CHAT CONFIG
API_KEY_2CHAT = "TU_API_KEY"
URL_2CHAT = "https://api.2chat.co/v1/message/send"

# 🔌 DB CONFIG
DB_CONFIG = {
    "host": "database-1.czao0sewwhuc.us-east-2.rds.amazonaws.com",
    "user": "admin",
    "password": "Motosur2025",
    "database": "loyalty"
}

def get_db():
    return mysql.connector.connect(**DB_CONFIG)

# -------------------------
# 📲 SEND WHATSAPP
# -------------------------
def send_whatsapp(phone, message):
    try:
        payload = {
            "to": phone,
            "message": message
        }

        headers = {
            "Authorization": f"Bearer {API_KEY_2CHAT}",
            "Content-Type": "application/json"
        }

        res = requests.post(URL_2CHAT, json=payload, headers=headers)
        print("📤 WhatsApp:", res.text)

    except Exception as e:
        print("❌ Error WhatsApp:", str(e))

# -------------------------
# HELPERS
# -------------------------

def get_customer(cursor, phone):
    cursor.execute("SELECT * FROM customers WHERE phone=%s", (phone,))
    return cursor.fetchone()

def create_customer(cursor, conn, phone):
    cursor.execute(
        "INSERT INTO customers (phone, created_at) VALUES (%s, %s)",
        (phone, datetime.now())
    )
    conn.commit()
    return cursor.lastrowid

def get_business_by_owner(cursor, phone):
    cursor.execute("SELECT * FROM businesses WHERE owner_phone=%s", (phone,))
    return cursor.fetchone()

def validate_code(cursor, code, branch_id):
    cursor.execute("""
        SELECT id FROM cashier_codes 
        WHERE code=%s AND branch_id=%s AND expires_at > NOW()
    """, (code, branch_id))
    return cursor.fetchone() is not None

def create_purchase(cursor, conn, customer_id, branch_id):
    cursor.execute(
        "INSERT INTO purchases (customer_id, branch_id, created_at) VALUES (%s, %s, %s)",
        (customer_id, branch_id, datetime.now())
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
# 🔐 ACTIVE CODE
# -------------------------

@app.route("/get_active_code")
def get_active_code():
    branch_id = request.args.get("branch")

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

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
        cursor.close()
        conn.close()
        return jsonify({
            "code": result["code"],
            "expires_at": result["expires_at"].strftime("%Y-%m-%dT%H:%M:%S")
        })

    code = str(random.randint(1000, 9999))
    expires_at = datetime.now() + timedelta(seconds=30)

    cursor.execute("""
        INSERT INTO cashier_codes (code, branch_id, expires_at)
        VALUES (%s, %s, %s)
    """, (code, branch_id, expires_at))

    conn.commit()
    cursor.close()
    conn.close()

    return jsonify({
        "code": code,
        "expires_at": expires_at.strftime("%Y-%m-%dT%H:%M:%S")
    })

# -------------------------
# 💻 CASHIER
# -------------------------

@app.route("/cashier")
def cashier():
    branch_id = request.args.get("branch")

    return render_template_string(f"""
    <h1>Código activo</h1>
    <h2 id="code">----</h2>
    <h3 id="countdown"></h3>

    <script>
        let expiresAt = null;

        function fetchCode() {{
            fetch('/get_active_code?branch={branch_id}')
            .then(r => r.json())
            .then(d => {{
                document.getElementById("code").innerText = d.code;
                expiresAt = new Date(d.expires_at);
            }});
        }}

        function tick() {{
            if (!expiresAt) return;

            const diff = Math.floor((expiresAt - new Date())/1000);

            if (diff <= 0) return fetchCode();

            const m = Math.floor(diff/60);
            const s = diff % 60;

            document.getElementById("countdown").innerText =
                m + ":" + String(s).padStart(2,"0");
        }}

        fetchCode();
        setInterval(tick,1000);
        setInterval(fetchCode,30000);
    </script>
    """)

# -------------------------
# 📱 SCAN
# -------------------------

@app.route("/scan")
def scan():
    branch_id = request.args.get("branch")

    return render_template_string(f"""
    <h2>Registrar compra</h2>
    <input id="phone" placeholder="Teléfono"><br><br>
    <input id="code" placeholder="Código"><br><br>

    <button onclick="go()">Registrar</button>
    <p id="r"></p>

    <script>
    function go(){{
        fetch('/register_purchase',{{
            method:'POST',
            headers:{{'Content-Type':'application/json'}},
            body:JSON.stringify({{
                phone:document.getElementById("phone").value,
                code:document.getElementById("code").value,
                branch_id:{branch_id}
            }})
        }}).then(r=>r.json()).then(d=>{{
            document.getElementById("r").innerText =
            d.error || "Compras: "+d.total_purchases;
        }});
    }}
    </script>
    """)

# -------------------------
# 🛒 PURCHASE + WHATSAPP
# -------------------------

@app.route("/register_purchase", methods=["POST"])
def register_purchase():
    data = request.json

    phone = data["phone"]
    branch_id = data["branch_id"]
    code = data["code"]

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    if not validate_code(cursor, code, branch_id):
        return jsonify({"error":"Código inválido"})

    customer = get_customer(cursor, phone)
    customer_id = create_customer(cursor, conn, phone) if not customer else customer["id"]

    create_purchase(cursor, conn, customer_id, branch_id)

    total = count_purchases(cursor, customer_id)

    if total % 9 == 0:
        create_reward(cursor, conn, customer_id)
        send_whatsapp(phone, "🎉 ¡Tienes un café gratis!")
    else:
        send_whatsapp(phone, f"☕ Llevas {total} cafés acumulados")

    cursor.close()
    conn.close()

    return jsonify({"total_purchases": total})

# -------------------------
# 📩 WEBHOOK 2CHAT
# -------------------------

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    print("📩 Incoming:", data)

    try:
        phone = data.get("from")
        text = data.get("text", "").lower()

        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        customer = get_customer(cursor, phone)

        if not customer:
            return jsonify({"reply": "No estás registrado aún 😅"})

        customer_id = customer["id"]
        total = count_purchases(cursor, customer_id)

        if "status" in text or "puntos" in text:
            return jsonify({"reply": f"Tienes {total} cafés ☕"})

        return jsonify({"reply": "Escribe *status* para ver tus cafés ☕"})

    except Exception as e:
        print("❌ Error:", str(e))
        return jsonify({"error": str(e)})

# -------------------------
# 🔐 LOGIN OWNER
# -------------------------

@app.route("/login", methods=["GET","POST"])
def login():

    if request.method == "POST":
        phone = request.form["phone"]

        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        business = get_business_by_owner(cursor, phone)

        if business:
            session["business_id"] = business["id"]
            return redirect("/dashboard")

        return "No existe negocio"

    return """
    <form method="post">
        <input name="phone" placeholder="Tu teléfono"/>
        <button>Entrar</button>
    </form>
    """

# -------------------------
# 📊 DASHBOARD
# -------------------------

@app.route("/dashboard")
def dashboard():

    if "business_id" not in session:
        return redirect("/login")

    business_id = session["business_id"]

    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT COUNT(DISTINCT c.id) as customers
        FROM customers c
        JOIN purchases p ON c.id = p.customer_id
        JOIN branches b ON p.branch_id = b.id
        WHERE b.business_id=%s
    """, (business_id,))
    customers = cursor.fetchone()["customers"]

    cursor.execute("""
        SELECT COUNT(*) as purchases
        FROM purchases p
        JOIN branches b ON p.branch_id = b.id
        WHERE b.business_id=%s
    """, (business_id,))
    purchases = cursor.fetchone()["purchases"]

    cursor.close()
    conn.close()

    return render_template_string(f"""
    <h1>Dashboard</h1>
    <h2>Clientes: {customers}</h2>
    <h2>Compras: {purchases}</h2>
    """)

# -------------------------
# RUN
# -------------------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))