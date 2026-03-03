from flask import Flask, render_template, redirect, url_for, session, request, jsonify
from authlib.integrations.flask_client import OAuth
from datetime import timedelta, datetime
import requests
import time
import base64
from io import BytesIO
import qrcode
from bakong_khqr import KHQR
import sqlite3
import os
import csv
import json
from yandex_api import YandexMailClient

app = Flask(__name__)

# ==============================
# BASIC CONFIG
# ==============================
app.secret_key = 'supersecretkey123'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=30)

DATABASE = "nexus.db"

# ==============================
# INIT DATABASE - UPDATED
# ==============================
def init_db():
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()

    # Users table
    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        email TEXT,
        name TEXT,
        picture TEXT,
        balance REAL DEFAULT 0,
        banned INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # Transactions table (for payments)
    c.execute("""
    CREATE TABLE IF NOT EXISTS transactions (
        id TEXT PRIMARY KEY,
        user_id TEXT,
        amount REAL,
        md5 TEXT,
        status TEXT,
        created_at TEXT,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )
    """)

    # NEW: Orders table - for purchase history
    c.execute("""
    CREATE TABLE IF NOT EXISTS orders (
        id TEXT PRIMARY KEY,
        user_id TEXT,
        user_email TEXT,
        service TEXT,
        quantity INTEGER,
        total_price REAL,
        account_details TEXT,
        status TEXT DEFAULT 'completed',
        created_at TEXT,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )
    """)

    # NEW: Order items table - individual accounts in each order
    c.execute("""
    CREATE TABLE IF NOT EXISTS order_items (
        id TEXT PRIMARY KEY,
        order_id TEXT,
        account_data TEXT,
        account_pipe TEXT,
        created_at TEXT,
        FOREIGN KEY (order_id) REFERENCES orders(id)
    )
    """)

    conn.commit()
    conn.close()

init_db()

# ==============================
# GOOGLE OAUTH
# ==============================
oauth = OAuth(app)

google = oauth.register(
    name='google',
    client_id='880026408317-6r4v93qm2eagk4pv6vqva6f4fcg9f1on.apps.googleusercontent.com',
    client_secret='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',
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'}
)

# ==============================
# BAKONG CONFIG
# ==============================
api_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJkYXRhIjp7ImlkIjoiMmEyMDE3MzUxMGU4NDZhMiJ9LCJpYXQiOjE3NTk3MjIzNjAsImV4cCI6MTc2NzQ5ODM2MH0._d3PWPYi-N_mPyt-Ntxj5qbtHghOdtZhka2LbdJlKRw"
khqr = KHQR(api_token)

# ==============================
# HELPER FUNCTIONS
# ==============================

def get_stock_count(stock_file):
    """Get count of available accounts in stock file"""
    if not os.path.exists(stock_file):
        return 0
    try:
        with open(stock_file, newline='', encoding='utf-8') as f:
            reader = csv.reader(f)
            next(reader, None)  # skip header
            return sum(1 for _ in reader)
    except:
        return 0

def get_user_orders(user_email):
    """Get orders for specific user from database"""
    orders = []
    
    try:
        conn = sqlite3.connect(DATABASE)
        c = conn.cursor()
        
        # Get orders from database
        c.execute("""
        SELECT id, service, quantity, total_price, account_details, created_at, status
        FROM orders 
        WHERE user_email=?
        ORDER BY created_at DESC
        LIMIT 50
        """, (user_email,))
        
        db_orders = c.fetchall()
        
        for order in db_orders:
            order_id, service, quantity, total_price, account_details_json, created_at, status = order
            
            # Parse account details
            try:
                account_details = json.loads(account_details_json) if account_details_json else []
            except:
                account_details = []
            
            # Format for display
            if account_details and len(account_details) > 0:
                # Show first account as preview
                preview = account_details[0][:50] + '...' if len(account_details[0]) > 50 else account_details[0]
                
                orders.append({
                    'order_id': order_id,
                    'account': preview,
                    'full_account': ' | '.join(account_details),  # Join all accounts
                    'all_accounts': account_details,  # List of all accounts
                    'service': service,
                    'amount': total_price / quantity if quantity > 0 else total_price,
                    'total_price': total_price,
                    'quantity': quantity,
                    'status': status.capitalize() if status else 'Completed',
                    'order_date': created_at
                })
            else:
                orders.append({
                    'order_id': order_id,
                    'account': 'Account details not available',
                    'full_account': '',
                    'all_accounts': [],
                    'service': service,
                    'amount': total_price / quantity if quantity > 0 else total_price,
                    'total_price': total_price,
                    'quantity': quantity,
                    'status': status.capitalize() if status else 'Completed',
                    'order_date': created_at
                })
        
        conn.close()
        
    except Exception as e:
        print(f"Error reading orders from database: {e}")
        # Fallback to CSV if database fails
        orders = get_user_orders_from_csv(user_email)
    
    return orders

# Fallback function to read from CSV
def get_user_orders_from_csv(user_email):
    """Fallback function to get orders from CSV"""
    orders = []
    sold_file = "stock/account_sold.csv"
    
    if os.path.exists(sold_file):
        try:
            with open(sold_file, 'r', encoding='utf-8') as f:
                reader = csv.reader(f)
                header = next(reader, None)  # Skip header
                for row in reader:
                    if len(row) >= 8 and row[7] == user_email:  # Buyer Email column
                        # Format: Account details in pipe format
                        account_pipe = f"{row[0]}|{row[1]}|{row[2]}|{row[3]}|{row[4]}|{row[5]}|{row[6]}"
                        
                        orders.append({
                            'order_id': row[11] if len(row) > 11 else f"CSV{len(orders)}",
                            'account': account_pipe[:50] + '...' if len(account_pipe) > 50 else account_pipe,
                            'full_account': account_pipe,
                            'all_accounts': [account_pipe],
                            'service': row[8] if len(row) > 8 else 'Facebook Account',
                            'amount': row[9] if len(row) > 9 else '0.01',
                            'total_price': float(row[9] if len(row) > 9 else '0.01'),
                            'quantity': 1,
                            'status': 'Completed',
                            'order_date': row[10] if len(row) > 10 else datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        })
        except Exception as e:
            print(f"Error reading orders from CSV: {e}")
    
    return orders

# ==============================
# ROUTES
# ==============================

@app.route('/')
def index():
    kh_stock = get_stock_count("stock/kh_account_stock.csv")
    us_stock = get_stock_count("stock/us_account_stock.csv")
    
    # Get user's orders if logged in
    orders = []
    user_balance = 0
    if 'user' in session:
        orders = get_user_orders(session['user']['email'])
        
        # Get user balance
        conn = sqlite3.connect(DATABASE)
        c = conn.cursor()
        c.execute("SELECT balance FROM users WHERE id=?", (session['user']['id'],))
        balance_row = c.fetchone()
        user_balance = balance_row[0] if balance_row else 0
        conn.close()
    
    return render_template(
        "index.html",
        user=session.get('user'),  # This is passed to template
        balance=user_balance,
        kh_stock=kh_stock,
        us_stock=us_stock,
        orders=orders
    )

@app.route('/login')
def login():
    return render_template("login.html")

@app.route('/auth/google')
def google_login():
    redirect_uri = url_for('auth_callback', _external=True)
    return google.authorize_redirect(redirect_uri)

@app.route('/auth/callback')
def auth_callback():
    token = google.authorize_access_token()

    userinfo = requests.get(
        'https://www.googleapis.com/oauth2/v3/userinfo',
        headers={'Authorization': f'Bearer {token["access_token"]}'}
    ).json()

    user_id = userinfo['sub']

    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()

    # Insert if not exists
    c.execute("""
    INSERT OR IGNORE INTO users (id, email, name, picture)
    VALUES (?, ?, ?, ?)
    """, (
        user_id,
        userinfo['email'],
        userinfo.get('name', ''),
        userinfo.get('picture', '')
    ))

    # Check banned
    c.execute("SELECT banned FROM users WHERE id=?", (user_id,))
    banned = c.fetchone()[0]

    conn.commit()
    conn.close()

    if banned == 1:
        return "Your account has been banned."

    session['user'] = {
        'id': user_id,
        'email': userinfo['email'],
        'name': userinfo.get('name', ''),
        'picture': userinfo.get('picture', '')
    }

    session.permanent = True
    return redirect(url_for('index'))

@app.route('/account')
def account():
    if 'user' not in session:
        return redirect(url_for('login'))

    user_id = session['user']['id']
    user_email = session['user']['email']

    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()

    # Get user balance
    c.execute("SELECT balance FROM users WHERE id=?", (user_id,))
    balance = c.fetchone()[0]

    # Get user transactions (payments)
    c.execute("""
        SELECT id, user_id, amount, status, created_at
        FROM transactions
        WHERE user_id=?
        ORDER BY created_at DESC
        LIMIT 20
    """, (user_id,))
    transactions = c.fetchall()
    
    # Get user orders from database (purchases)
    c.execute("""
        SELECT id, service, quantity, total_price, account_details, created_at, status
        FROM orders
        WHERE user_id=?
        ORDER BY created_at DESC
        LIMIT 50
    """, (user_id,))
    
    db_orders = c.fetchall()
    
    # Format orders for template
    orders = []
    for order in db_orders:
        order_id, service, quantity, total_price, account_details_json, created_at, status = order
        
        try:
            account_details = json.loads(account_details_json) if account_details_json else []
        except:
            account_details = []
        
        # Create preview
        if account_details and len(account_details) > 0:
            preview = account_details[0][:50] + '...' if len(account_details[0]) > 50 else account_details[0]
            full_account = ' | '.join(account_details)
        else:
            preview = 'Account details not available'
            full_account = ''
        
        orders.append({
            'order_id': order_id,
            'account': preview,
            'full_account': full_account,
            'all_accounts': account_details,
            'service': service,
            'amount': total_price / quantity if quantity > 0 else total_price,
            'total_price': total_price,
            'quantity': quantity,
            'status': status.capitalize() if status else 'Completed',
            'order_date': created_at
        })

    conn.close()

    return render_template(
        "account.html",
        user=session['user'],
        balance=balance,
        transactions=transactions,
        orders=orders
    )

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

# ==============================
# GENERATE QR
# ==============================

@app.route('/generate_qr', methods=['POST'])
def generate_qr():
    if 'user' not in session:
        return jsonify({'error': 'Login required'}), 401

    try:
        amount = float(request.form['amount'])
    except:
        return jsonify({'error': 'Invalid amount'}), 400

    if amount <= 0:
        return jsonify({'error': 'Amount must be greater than 0'}), 400

    transaction_id = f"TRX{int(time.time())}"

    qr_data = khqr.create_qr(
        bank_account='meng_topup@aclb',
        merchant_name='NEXUS FB SHOP',
        merchant_city='Phnom Penh',
        amount=amount,
        currency='USD',
        store_label='NEXUS',
        phone_number='855976666666',
        bill_number=transaction_id,
        terminal_label='Cashier-01',
        static=False
    )

    md5_hash = khqr.generate_md5(qr_data)

    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("""
    INSERT INTO transactions (id, user_id, amount, md5, status, created_at)
    VALUES (?, ?, ?, ?, ?, ?)
    """, (
        transaction_id,
        session['user']['id'],
        amount,
        md5_hash,
        "PENDING",
        datetime.now().isoformat()
    ))
    conn.commit()
    conn.close()

    qr_img = qrcode.make(qr_data)
    img_io = BytesIO()
    qr_img.save(img_io, 'PNG')
    img_io.seek(0)
    khqr_image = khqr.qr_image(
        qr=qr_data,
        format="base64"
        )
    print("QR:", khqr_image)


    return jsonify({
        "success": True,
        "qr_image": khqr_image,
        "transaction_id": transaction_id
    })

# ==============================
# CHECK PAYMENT
# ==============================

@app.route('/check_payment', methods=['POST'])
def check_payment():
    if 'user' not in session:
        return jsonify({'error': 'Login required'}), 401

    transaction_id = request.form.get("transaction_id")

    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()

    c.execute("SELECT md5, status, user_id, amount FROM transactions WHERE id=?", (transaction_id,))
    row = c.fetchone()

    if not row:
        conn.close()
        return jsonify({'error': 'Transaction not found'}), 404

    md5, status, user_id, amount = row

    if status == "PAID":
        conn.close()
        return jsonify({"status": "PAID"})

    response = requests.get(
        f"http://127.0.0.1:5003/api/check_payment?md5={md5}"
    )

    if response.status_code != 200:
        conn.close()
        return jsonify({"status": "ERROR"})

    new_status = response.json().get("status")

    if new_status == "PAID":
        c.execute("UPDATE transactions SET status='PAID' WHERE id=?", (transaction_id,))
        c.execute("UPDATE users SET balance = balance + ? WHERE id=?", (amount, user_id))
        conn.commit()

    conn.close()

    return jsonify({"status": new_status})

# ==============================
# BUY ACCOUNT
# ==============================

@app.route('/buy_account', methods=['POST'])
def buy_account():
    if 'user' not in session:
        return jsonify({"error": "Login required"}), 401

    data = request.get_json()
    service = data.get("service")
    quantity = data.get("quantity", 1)

    # Define prices
    prices = {
        "Facebook KH Account": 0.01,
        "Facebook US Account": 0.01
    }
    price_per_unit = prices.get(service)
    if price_per_unit is None:
        return jsonify({"error": "Invalid service"}), 400

    total_price = price_per_unit * quantity

    stock_file = ""
    if service == "Facebook KH Account":
        stock_file = "stock/kh_account_stock.csv"
    elif service == "Facebook US Account":
        stock_file = "stock/us_account_stock.csv"

    sold_file = "stock/account_sold.csv"

    # Check if stock file exists
    if not os.path.exists(stock_file):
        return jsonify({"error": "Stock file not found"}), 500

    # Connect to DB
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()

    # Check user balance
    c.execute("SELECT balance FROM users WHERE id=?", (session['user']['id'],))
    balance_row = c.fetchone()
    if not balance_row:
        conn.close()
        return jsonify({"error": "User not found"}), 404
    
    balance = balance_row[0]
    if balance < total_price:
        conn.close()
        return jsonify({"error": "Insufficient balance"}), 400

    # Read stock file
    with open(stock_file, newline='', encoding='utf-8') as f:
        reader = csv.reader(f)
        header = next(reader)  # Get header
        all_accounts = list(reader)

    if len(all_accounts) < quantity:
        conn.close()
        return jsonify({"error": f"Only {len(all_accounts)} accounts available"}), 400

    # Get requested number of accounts
    purchased_accounts = all_accounts[:quantity]
    remaining_accounts = all_accounts[quantity:]

    # Deduct balance
    new_balance = balance - total_price
    c.execute("UPDATE users SET balance=? WHERE id=?", (new_balance, session['user']['id']))
    
    # Generate order ID
    order_id = f"ORD{int(time.time())}{session['user']['id'][:5]}"
    created_at = datetime.now().isoformat()
    
    # Prepare account details for storage
    account_details_list = []
    for account in purchased_accounts:
        account_pipe = "|".join(account[:6])  # Name|User ID|Password|Cookies|Phone|Email|DOB
        account_details_list.append(account_pipe)
    
    account_details_json = json.dumps(account_details_list)
    
    # Insert order into database
    c.execute("""
    INSERT INTO orders (id, user_id, user_email, service, quantity, total_price, account_details, status, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        order_id,
        session['user']['id'],
        session['user']['email'],
        service,
        quantity,
        total_price,
        account_details_json,
        'completed',
        created_at
    ))
    
    # Insert individual order items
    for i, account in enumerate(purchased_accounts):
        item_id = f"{order_id}_ITEM{i+1}"
        account_pipe = "|".join(account[:7])
        c.execute("""
        INSERT INTO order_items (id, order_id, account_data, account_pipe, created_at)
        VALUES (?, ?, ?, ?, ?)
        """, (
            item_id,
            order_id,
            json.dumps(account[:7]),  # Store as JSON
            account_pipe,
            created_at
        ))
    
    conn.commit()
    conn.close()

    # Write sold accounts to account_sold.csv
    file_exists = os.path.exists(sold_file)
    with open(sold_file, 'a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(header + ["Service", "Buyer Email", "Sold At", "Quantity", "Total Price", "Order ID"])
        
        for account in purchased_accounts:
            writer.writerow(account + [service, session['user']['email'], 
                                      datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 
                                      quantity, total_price, order_id])

    # Update stock file
    with open(stock_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(remaining_accounts)

    # Format purchased accounts for response
    formatted_accounts = [] 
    for account in purchased_accounts:
        account_pipe = "|".join(account[:6])  # Name|User ID|Password|Cookies|Phone|Email|DOB
        formatted_accounts.append({
            'pipe_format': account_pipe,
            'details': {
                'Name': account[0] if len(account) > 0 else 'N/A',
                'User ID': account[1] if len(account) > 1 else 'N/A',
                'Password': account[2] if len(account) > 2 else 'N/A',
                '2fa': account[4] if len(account) > 4 else 'N/A',
                'Email': account[5] if len(account) > 5 else 'N/A',
                'Passmail': account[6] if len(account) > 6 else 'N/A'
            }
        })

    return jsonify({
        "success": True,
        "accounts": formatted_accounts,
        "service": service,
        "quantity": quantity,
        "total_price": total_price,
        "buyer": session['user']['email'],
        "sold_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "new_balance": new_balance,
        "order_id": order_id  # Return order ID for reference
    })

@app.route('/get_balance')
def get_balance():
    if 'user' not in session:
        return jsonify({'error': 'Login required'}), 401

    user_id = session['user']['id']

    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT balance FROM users WHERE id=?", (user_id,))
    row = c.fetchone()
    conn.close()

    balance = row[0] if row else 0.0

    return jsonify({'balance': balance})

# ==============================
# ADMIN PANEL
# ==============================

ADMIN_EMAIL = "nexusdevteam55@gmail.com"

@app.route('/admin')
def admin_panel():
    if 'user' not in session or session['user']['email'] != ADMIN_EMAIL:
        return "Access Denied", 403

    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()

    c.execute("SELECT id, email, balance, banned FROM users")
    users = c.fetchall()

    c.execute("SELECT id, user_id, amount, status, created_at FROM transactions ORDER BY created_at DESC")
    transactions = c.fetchall()

    c.execute("SELECT SUM(balance) FROM users")
    total_balance = c.fetchone()[0] or 0

    conn.close()

    return render_template(
        "admin.html",
        users=users,
        transactions=transactions,
        total_balance=total_balance
    )

@app.route('/api/order/<order_id>')
def get_order_details(order_id):
    if 'user' not in session:
        return jsonify({"error": "Login required"}), 401
    
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    
    # Get order details
    c.execute("""
    SELECT id, user_id, user_email, service, quantity, total_price, account_details, created_at, status
    FROM orders
    WHERE id=? AND user_id=?
    """, (order_id, session['user']['id']))
    
    order = c.fetchone()
    
    if not order:
        conn.close()
        return jsonify({"error": "Order not found"}), 404
    
    # Get individual order items
    c.execute("""
    SELECT account_data, account_pipe
    FROM order_items
    WHERE order_id=?
    """, (order_id,))
    
    items = c.fetchall()
    conn.close()
    
    # Format response
    order_data = {
        'order_id': order[0],
        'service': order[3],
        'quantity': order[4],
        'total_price': order[5],
        'created_at': order[7],
        'status': order[8],
        'accounts': [item[1] for item in items]  # List of pipe-formatted accounts
    }
    
    return jsonify(order_data)

# ==============================
# ADMIN ACTIONS
# ==============================

@app.route('/ban_user/<user_id>')
def ban_user(user_id):
    if 'user' not in session or session['user']['email'] != ADMIN_EMAIL:
        return "Access Denied", 403

    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("UPDATE users SET banned=1 WHERE id=?", (user_id,))
    conn.commit()
    conn.close()

    return redirect(url_for('admin_panel'))


@app.route('/unban_user/<user_id>')
def unban_user(user_id):
    if 'user' not in session or session['user']['email'] != ADMIN_EMAIL:
        return "Access Denied", 403

    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("UPDATE users SET banned=0 WHERE id=?", (user_id,))
    conn.commit()
    conn.close()

    return redirect(url_for('admin_panel'))


@app.route('/add_balance/<user_id>', methods=['POST'])
def add_balance(user_id):
    if 'user' not in session or session['user']['email'] != ADMIN_EMAIL:
        return "Access Denied", 403

    amount = float(request.form.get("amount", 0))

    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("UPDATE users SET balance = balance + ? WHERE id=?", (amount, user_id))
    conn.commit()
    conn.close()

    return redirect(url_for('admin_panel'))


@app.route('/cut_balance/<user_id>', methods=['POST'])
def cut_balance(user_id):
    if 'user' not in session or session['user']['email'] != ADMIN_EMAIL:
        return "Access Denied", 403

    amount = float(request.form.get("amount", 0))

    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("UPDATE users SET balance = balance - ? WHERE id=?", (amount, user_id))
    conn.commit()
    conn.close()

    return redirect(url_for('admin_panel'))

@app.route('/admin_stock')
def admin_stock():
    if 'user' not in session or session['user']['email'] != ADMIN_EMAIL:
        return "Access Denied", 403

    kh_stock = get_stock_count("stock/kh_account_stock.csv")
    us_stock = get_stock_count("stock/us_account_stock.csv")

    return f"""
    <h2>Facebook Stock</h2>
    <p>KH Accounts: {kh_stock}</p>
    <p>US Accounts: {us_stock}</p>
    <a href='/admin'>Back</a>
    """
# ==============================
# ADMIN ORDER MANAGEMENT
# ==============================

@app.route('/admin_orders')
def admin_orders():
    if 'user' not in session or session['user']['email'] != ADMIN_EMAIL:
        return "Access Denied", 403

    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()

    c.execute("""
        SELECT id, user_email, service, quantity, total_price, status, created_at
        FROM orders
        ORDER BY created_at DESC
    """)
    orders = c.fetchall()

    conn.close()

    return render_template("admin_orders.html", orders=orders)


@app.route('/admin_order/<order_id>')
def admin_order_detail(order_id):
    if 'user' not in session or session['user']['email'] != ADMIN_EMAIL:
        return "Access Denied", 403

    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()

    c.execute("""
        SELECT id, user_email, service, quantity, total_price, status, created_at
        FROM orders
        WHERE id=?
    """, (order_id,))
    order = c.fetchone()

    c.execute("""
        SELECT account_pipe
        FROM order_items
        WHERE order_id=?
    """, (order_id,))
    items = c.fetchall()

    conn.close()

    return render_template(
        "admin_order_detail.html",
        order=order,
        items=items
    )


@app.route('/update_order_status/<order_id>', methods=['POST'])
def update_order_status(order_id):
    if 'user' not in session or session['user']['email'] != ADMIN_EMAIL:
        return "Access Denied", 403

    new_status = request.form.get("status")

    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("UPDATE orders SET status=? WHERE id=?", (new_status, order_id))
    conn.commit()
    conn.close()

    return redirect(url_for('admin_orders'))


@app.route('/delete_order/<order_id>')
def delete_order(order_id):
    if 'user' not in session or session['user']['email'] != ADMIN_EMAIL:
        return "Access Denied", 403

    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()

    c.execute("DELETE FROM order_items WHERE order_id=?", (order_id,))
    c.execute("DELETE FROM orders WHERE id=?", (order_id,))

    conn.commit()
    conn.close()

    return redirect(url_for('admin_orders'))

@app.get("/quickread/yandex")
def quickread_yandex_get():
    # Default state (no POST yet)
    return render_template(
        "quickread_yandex.html",
        result_title="No Emails Yet",
        result_message="Enter your credentials above to read your emails",
        code=None,
        username="",
        target_email=""
    )

@app.post("/quickread/yandex")
def quickread_yandex_post():
    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""
    target_email = (request.form.get("target_email") or "").strip()

    # Basic validation (keep it simple)
    if not username or not password or not target_email:
        return render_template(
            "quickread_yandex.html",
            result_title="Missing Fields",
            result_message="Please fill in username, password, and target email.",
            code=None,
            username=username,
            target_email=target_email
        ), 400

    client = YandexMailClient(username, password, target_email)
    code = client.get_code()

    if code:
        return render_template(
            "quickread_yandex.html",
            result_title="Code Found",
            result_message="Latest code from your inbox:",
            code=code,
            username=username,
            target_email=target_email
        )
    else:
        return render_template(
            "quickread_yandex.html",
            result_title="No Emails Yet",
            result_message="Enter your credentials above to read your emails",
            code=None,
            username=username,
            target_email=target_email
        )

# ==============================
# RUN
# ==============================
if __name__ == "__main__":
    # Create stock directory if it doesn't exist
    os.makedirs("stock", exist_ok=True)
    
    # Test stock counts
    kh_stock_count = get_stock_count("stock/kh_account_stock.csv")
    print("KH Account Stock:", kh_stock_count)
    
    us_stock_count = get_stock_count("stock/us_account_stock.csv")
    print("US Account Stock:", us_stock_count)
    
    app.run()
