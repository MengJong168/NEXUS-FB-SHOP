from flask import Flask, render_template, redirect, url_for, session, request, jsonify
from authlib.integrations.flask_client import OAuth
from datetime import timedelta, datetime
import requests
import time
import base64
from io import BytesIO
import qrcode
from bakong_khqr import KHQR
import os
import csv
import json
from yandex_api import YandexMailClient
from functools import wraps
import pyotp
from zoneinfo import ZoneInfo

app = Flask(__name__)

# ==============================
# BASIC CONFIG
# ==============================
app.secret_key = 'supersecretkey123'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=30)

# API Configuration
API_BASE_URL = 'https://mengtopup.shop'
current_time = datetime.now(ZoneInfo("Asia/Phnom_Penh"))
TELEGRAM_BOT_TOKEN = "8685202927:AAFKAY-2QcYeEH_bIiJp7kGTjaw9l1OpPSk"
TELEGRAM_CHAT_ID = "-5106824805"
# ==============================
# HELPER FUNCTIONS
# ==============================

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            if request.is_json:
                return jsonify({"error": "Authentication required"}), 401
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def api_request(method, endpoint, data=None, params=None, user_id=None, is_admin=False):
    """Make API requests to the backend"""
    url = f"{API_BASE_URL}{endpoint}"
    
    headers = {'Content-Type': 'application/json'}
    
    # Add user authentication if available
    if user_id:
        headers['X-User-ID'] = user_id
    
    # Add admin authentication if this is an admin request
    if is_admin and 'user' in session:
        headers['X-Admin-Email'] = session['user']['email']
        headers['X-User-ID'] = session['user']['id']
    
    try:
        if method.upper() == 'GET':
            response = requests.get(url, headers=headers, params=params, timeout=10)
        elif method.upper() == 'POST':
            response = requests.post(url, headers=headers, json=data, timeout=10)
        elif method.upper() == 'PUT':
            response = requests.put(url, headers=headers, json=data, timeout=10)
        elif method.upper() == 'DELETE':
            response = requests.delete(url, headers=headers, timeout=10)
        else:
            return {"success": False, "error": "Invalid method"}
        
        response.raise_for_status()
        return response.json()
    except requests.exceptions.Timeout:
        return {"success": False, "error": "Request timeout"}
    except requests.exceptions.ConnectionError:
        return {"success": False, "error": "Connection error"}
    except requests.exceptions.HTTPError as e:
        print(f"HTTP Error {e.response.status_code}: {e.response.text}")  # Debug print
        return {"success": False, "error": f"HTTP error: {e.response.status_code}"}
    except Exception as e:
        return {"success": False, "error": str(e)}

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
# ROUTES
# ==============================


@app.route('/')
def index():
    # Get stock counts from API
    kh_stock, us_stock = get_stock_counts()
    
    # Get user's orders and balance if logged in
    orders = []
    user_balance = 0
    if 'user' in session:
        # Get user balance from API
        balance_response = api_request('GET', f'/api/users/{session["user"]["id"]}/balance', 
                                      user_id=session['user']['id'])
        user_balance = balance_response.get('balance', 0) if balance_response.get('success') else 0
        
        # Get user orders from API
        orders_response = api_request('GET', f'/api/users/{session["user"]["id"]}/orders',
                                     user_id=session['user']['id'])
        raw_orders = orders_response.get('orders', []) if orders_response.get('success') else []
        
        # Format orders for template display
        orders = []
        for order in raw_orders:
            # Parse account details if it's a JSON string
            account_details = order.get('account_details', '[]')
            if isinstance(account_details, str):
                try:
                    account_list = json.loads(account_details)
                except:
                    account_list = []
            else:
                account_list = account_details or []
            
            # Create preview and full account text
            if account_list and len(account_list) > 0:
                # Join all accounts with line breaks for full view
                full_account = '\n'.join(account_list)
                # Create preview (first account, truncated)
                preview = account_list[0][:50] + '...' if len(account_list[0]) > 50 else account_list[0]
            else:
                full_account = 'No account details'
                preview = 'No account details'
            
            # Calculate per-item price
            quantity = order.get('quantity', 1)
            total_price = order.get('total_price', 0)
            per_item_price = total_price / quantity if quantity > 0 else total_price
            
            orders.append({
                'order_id': order.get('id', 'N/A'),
                'account': preview,
                'full_account': full_account,
                'all_accounts': account_list,
                'service': order.get('service', 'Unknown'),
                'amount': per_item_price,
                'total_price': total_price,
                'quantity': quantity,
                'status': order.get('status', 'completed').capitalize(),
                'order_date': order.get('created_at', '')[:16] if order.get('created_at') else 'N/A'
            })
    
    return render_template(
        "index.html",
        user=session.get('user'),
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
    
    # Register or get user from API
    user_data = {
        'id': user_id,
        'email': userinfo['email'],
        'name': userinfo.get('name', ''),
        'picture': userinfo.get('picture', '')
    }
    
    # Register user via API
    api_response = api_request('POST', '/api/users/register', data=user_data)
    
    if not api_response.get('success'):
        return f"Failed to register user: {api_response.get('error', 'Unknown error')}"
    
    # Check if user is banned
    if api_response.get('user', {}).get('banned') == 1:
        return "Your account has been banned."

    session['user'] = user_data
    session.permanent = True
    return redirect(url_for('index'))

@app.route('/account')
@login_required
def account():
    user_id = session['user']['id']
    user_email = session['user']['email']

    # Get user balance from API
    balance_response = api_request('GET', f'/api/users/{user_id}/balance', user_id=user_id)
    balance = balance_response.get('balance', 0) if balance_response.get('success') else 0
    
    # Get user transactions from API
    transactions_response = api_request('GET', f'/api/users/{user_id}/transactions', user_id=user_id)
    transactions = transactions_response.get('transactions', []) if transactions_response.get('success') else []
    
    # Get user orders from API
    orders_response = api_request('GET', f'/api/users/{user_id}/orders', user_id=user_id)
    raw_orders = orders_response.get('orders', []) if orders_response.get('success') else []
    
    # Format orders for template display
    orders = []
    for order in raw_orders:
        # Parse account details if it's a JSON string
        account_details = order.get('account_details', '[]')
        if isinstance(account_details, str):
            try:
                account_list = json.loads(account_details)
            except:
                account_list = []
        else:
            account_list = account_details or []
        
        # Create preview and full account text
        if account_list and len(account_list) > 0:
            full_account = '\n'.join(account_list)
            preview = account_list[0][:50] + '...' if len(account_list[0]) > 50 else account_list[0]
        else:
            full_account = 'No account details'
            preview = 'No account details'
        
        quantity = order.get('quantity', 1)
        total_price = order.get('total_price', 0)
        per_item_price = total_price / quantity if quantity > 0 else total_price
        
        orders.append({
            'order_id': order.get('id', 'N/A'),
            'account': preview,
            'full_account': full_account,
            'all_accounts': account_list,
            'service': order.get('service', 'Unknown'),
            'amount': per_item_price,
            'total_price': total_price,
            'quantity': quantity,
            'status': order.get('status', 'completed').capitalize(),
            'order_date': order.get('created_at', '')[:16] if order.get('created_at') else 'N/A'
        })

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
@login_required
def generate_qr():
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

    # Create transaction via API
    transaction_data = {
        'transaction_id': transaction_id,
        'amount': amount,
        'md5_hash': md5_hash,
        'status': 'PENDING'
    }
    
    api_response = api_request('POST', f'/api/users/{session["user"]["id"]}/transactions', 
                              data=transaction_data, user_id=session['user']['id'])
    
    if not api_response.get('success'):
        return jsonify({'error': 'Failed to create transaction'}), 500

    khqr_image = khqr.qr_image(qr=qr_data, format="base64")
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
@login_required
def check_payment():
    transaction_id = request.form.get("transaction_id")

    # Get transaction from API
    transaction_response = api_request(
        'GET',
        f'/api/users/{session["user"]["id"]}/transactions/{transaction_id}',
        user_id=session['user']['id']
    )

    if not transaction_response.get('success'):
        return jsonify({'error': 'Transaction not found'}), 404

    transaction = transaction_response.get('transaction', {})
    status = transaction.get('status')
    md5 = transaction.get('md5_hash')
    amount = transaction.get('amount')

    if status == "PAID":
        return jsonify({"status": "PAID"})

    # Check payment status via external API
    response = requests.get(
        f"https://mengtopup.shop/api/check_payment?md5={md5}"
    )

    if response.status_code != 200:
        return jsonify({"status": "ERROR"})

    new_status = response.json().get("status")

    if new_status == "PAID":

        # Update transaction status via API
        update_response = api_request(
            'POST',
            f'/api/users/{session["user"]["id"]}/transactions/{transaction_id}/paid',
            user_id=session['user']['id']
        )

        if update_response.get('success'):

            print(f"Payment credited via API for transaction: {transaction_id}")

            message = f"""
💰 <b>New Deposit Received</b>

👤 User: {session['user']['email']}
💵 Amount: ${amount}
🧾 Transaction: {transaction_id}
🕒 Time: {datetime.now(ZoneInfo("Asia/Phnom_Penh")).strftime('%Y-%m-%d %H:%M:%S')}
"""

            send_telegram_message(message)

    return jsonify({"status": new_status})

# ==============================
# BUY ACCOUNT
# ==============================

@app.route('/buy_account', methods=['POST'])
@login_required
def buy_account():
    data = request.get_json()
    service = data.get("service")
    quantity = data.get("quantity", 1)

    # Define prices
    prices = {
        "Facebook KH Account": 0.50,
        "Facebook US Account": 0.50
    }
    price_per_unit = prices.get(service)
    if price_per_unit is None:
        return jsonify({"error": "Invalid service"}), 400

    total_price = price_per_unit * quantity

    # Check user balance via API
    balance_response = api_request('GET', f'/api/users/{session["user"]["id"]}/balance', 
                                  user_id=session['user']['id'])
    
    if not balance_response.get('success'):
        return jsonify({"error": "Failed to check balance"}), 500
    
    balance = balance_response.get('balance', 0)
    if balance < total_price:
        return jsonify({"error": "Insufficient balance"}), 400

    # Generate order ID
    order_id = f"ORD{int(time.time())}{session['user']['id'][:5]}"
    
    # Purchase accounts via API - NO ADMIN FLAG NEEDED
    purchase_response = api_request('POST', '/api/stock/purchase', data={
        'service': service,
        'quantity': quantity,
        'buyer_email': session['user']['email'],
        'order_id': order_id,
        'total_price': total_price
    })
    
    if not purchase_response.get('success'):
        return jsonify({"error": purchase_response.get('error', 'Failed to purchase accounts')}), 400
    
    purchased_accounts = purchase_response.get('accounts', [])
    
    # Create order via API
    order_data = {
        'order_id': order_id,
        'service': service,
        'quantity': quantity,
        'total_price': total_price,
        'account_details': json.dumps([a['pipe_format'] for a in purchased_accounts]),
        'user_email': session['user']['email'],
        'status': 'completed'
    }
    
    api_response = api_request('POST', f'/api/users/{session["user"]["id"]}/orders', 
                              data=order_data, user_id=session['user']['id'])
    
    if not api_response.get('success'):
        return jsonify({"error": "Failed to create order"}), 500

    # Deduct balance via API
    deduct_response = api_request('POST', f'/api/users/{session["user"]["id"]}/deduct', 
                                 data={'amount': total_price}, user_id=session['user']['id'])

    # Get updated balance
    new_balance_response = api_request('GET', f'/api/users/{session["user"]["id"]}/balance', 
                                      user_id=session['user']['id'])
    new_balance = new_balance_response.get('balance', balance - total_price)

    return jsonify({
        "success": True,
        "accounts": purchased_accounts,
        "service": service,
        "quantity": quantity,
        "total_price": total_price,
        "buyer": session['user']['email'],
        "sold_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "new_balance": new_balance,
        "order_id": order_id
    })

@app.route('/get_balance')
@login_required
def get_balance():
    balance_response = api_request('GET', f'/api/users/{session["user"]["id"]}/balance', 
                                  user_id=session['user']['id'])
    
    balance = balance_response.get('balance', 0) if balance_response.get('success') else 0
    return jsonify({'balance': balance})

# ==============================
# API ORDER DETAILS
# ==============================

@app.route('/api/order/<order_id>')
@login_required
def get_order_details(order_id):
    order_response = api_request('GET', f'/api/users/{session["user"]["id"]}/orders/{order_id}',
                                user_id=session['user']['id'])
    
    if not order_response.get('success'):
        return jsonify({"error": "Order not found"}), 404
    
    return jsonify(order_response.get('order', {}))

# ==============================
# ADMIN PANEL - UPDATED FOR API
# ==============================

ADMIN_EMAIL = "nexusdevteam55@gmail.com"

@app.route('/admin')
def admin_panel():
    if 'user' not in session or session['user']['email'] != ADMIN_EMAIL:
        return "Access Denied", 403

    # Get all users from API - with admin flag
    users_response = api_request('GET', '/api/admin/users', is_admin=True)
    users = users_response.get('users', []) if users_response.get('success') else []

    # Get all transactions from API - with admin flag
    transactions_response = api_request('GET', '/api/admin/transactions', is_admin=True)
    transactions = transactions_response.get('transactions', []) if transactions_response.get('success') else []

    # Get stats from API - with admin flag
    stats_response = api_request('GET', '/api/admin/stats', is_admin=True)
    stats = stats_response if stats_response.get('success') else {}
    
    total_balance = stats.get('total_balance', 0)
    
    # Get stock counts
    stock_response = api_request('GET', '/api/stock/counts')
    kh_stock = 0
    us_stock = 0
    if stock_response.get('success'):
        kh_stock = stock_response.get('kh_stock', 0)
        us_stock = stock_response.get('us_stock', 0)

    print(f"Users response: {users_response}")  # Debug
    print(f"Transactions response: {transactions_response}")  # Debug
    print(f"Stats response: {stats_response}")  # Debug

    return render_template(
        "admin.html",
        users=users,
        transactions=transactions,
        total_balance=total_balance,
        kh_stock=kh_stock,
        us_stock=us_stock
    )


@app.route('/ban_user/<user_id>')
def ban_user(user_id):
    if 'user' not in session or session['user']['email'] != ADMIN_EMAIL:
        return "Access Denied", 403

    api_request('POST', f'/api/admin/users/{user_id}/ban', is_admin=True)
    return redirect(url_for('admin_panel'))

@app.route('/unban_user/<user_id>')
def unban_user(user_id):
    if 'user' not in session or session['user']['email'] != ADMIN_EMAIL:
        return "Access Denied", 403

    api_request('POST', f'/api/admin/users/{user_id}/unban', is_admin=True)
    return redirect(url_for('admin_panel'))

@app.route('/add_balance/<user_id>', methods=['POST'])
def add_balance(user_id):
    if 'user' not in session or session['user']['email'] != ADMIN_EMAIL:
        return "Access Denied", 403

    amount = float(request.form.get("amount", 0))
    api_request('POST', f'/api/admin/users/{user_id}/balance/add', data={'amount': amount}, is_admin=True)
    return redirect(url_for('admin_panel'))

@app.route('/cut_balance/<user_id>', methods=['POST'])
def cut_balance(user_id):
    if 'user' not in session or session['user']['email'] != ADMIN_EMAIL:
        return "Access Denied", 403

    amount = float(request.form.get("amount", 0))
    api_request('POST', f'/api/admin/users/{user_id}/balance/cut', data={'amount': amount}, is_admin=True)
    return redirect(url_for('admin_panel'))

@app.route('/admin_orders')
def admin_orders():
    if 'user' not in session or session['user']['email'] != ADMIN_EMAIL:
        return "Access Denied", 403

    orders_response = api_request('GET', '/api/admin/orders', is_admin=True)
    orders = orders_response.get('orders', []) if orders_response.get('success') else []

    return render_template("admin_orders.html", orders=orders)

@app.route('/admin_order/<order_id>')
def admin_order_detail(order_id):
    if 'user' not in session or session['user']['email'] != ADMIN_EMAIL:
        return "Access Denied", 403

    order_response = api_request('GET', f'/api/admin/orders/{order_id}', is_admin=True)
    
    if not order_response.get('success'):
        return "Order not found", 404
    
    order = order_response.get('order', {})
    items = order_response.get('items', [])

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
    api_request('POST', f'/api/admin/orders/{order_id}/status', data={'status': new_status}, is_admin=True)
    return redirect(url_for('admin_orders'))

@app.route('/delete_order/<order_id>')
def delete_order(order_id):
    if 'user' not in session or session['user']['email'] != ADMIN_EMAIL:
        return "Access Denied", 403

    api_request('DELETE', f'/api/admin/orders/{order_id}', is_admin=True)
    return redirect(url_for('admin_orders'))

# ==============================
# YANDEX EMAIL READER
# ==============================

@app.get("/quickread/yandex")
def quickread_yandex_get():
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

# Add to your frontend app.py helper functions

def get_stock_counts():
    """Get stock counts from API"""
    response = api_request('GET', '/api/stock/counts')
    if response.get('success'):
        return response.get('kh_stock', 0), response.get('us_stock', 0)
    return 0, 0

@app.route("/", methods=["GET", "POST"])
@app.route("/2fa", methods=["GET", "POST"])
def twofa():

    results = ""
    keys = ""
    result_title = ""
    result_message = ""

    if request.method == "POST":

        keys = request.form.get("keys")

        if keys:

            key_list = keys.splitlines()
            output = []

            for key in key_list:

                # remove spaces
                clean_key = key.strip().replace(" ", "")

                if clean_key:

                    try:
                        totp = pyotp.TOTP(clean_key)
                        code = totp.now()

                        output.append(code)

                    except Exception:
                        output.append("invalid key")

            results = "\n".join(output)

            result_title = "2FA Authentication"
            result_message = "Code generated successfully"

        else:
            result_title = "Error"
            result_message = "No key entered"

    return render_template(
        "2fa.html",
        results=results,
        keys=keys,
        result_title=result_title,
        result_message=result_message
    )

def send_telegram_message(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML"
        }
        requests.post(url, data=data, timeout=10)
    except Exception as e:
        print("Telegram Error:", e)
        
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
    
    app.run(debug=True)
