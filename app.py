from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_file, flash
import sqlite3
import csv
from io import BytesIO
import os
import barcode
from barcode import Code128
from barcode.writer import ImageWriter
from flask import make_response
from functools import wraps
import json

app = Flask(__name__)
app.secret_key = 'your_secret_key'  # change this for security!

# Initialize the database
def init_db():
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            barcode TEXT UNIQUE NOT NULL,
            quantity INTEGER DEFAULT 0,
            location TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS stock (
            tracker_id INTEGER PRIMARY KEY AUTOINCREMENT,
            barcode TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            FOREIGN KEY (barcode) REFERENCES products(barcode)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sales_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER,
            order_data TEXT,
            status TEXT DEFAULT 'Pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(customer_id) REFERENCES users(id)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS vendors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            phone TEXT,
            address TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS purchase_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vendor_id INTEGER,
            sales_order_id INTEGER,
            product_barcode TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            status TEXT DEFAULT 'Pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(vendor_id) REFERENCES vendors(id),
            FOREIGN KEY(sales_order_id) REFERENCES sales_orders(id),
            FOREIGN KEY(product_barcode) REFERENCES products(barcode)
        )
    ''')
    conn.commit()

    cursor.execute('SELECT * FROM users WHERE username = ?', ('admin',))
    if cursor.fetchone() is None:
        cursor.execute('INSERT INTO users (username, password, role) VALUES (?, ?, ?)',
                       ('admin', 'admin123', 'admin'))
        conn.commit()
    conn.close()

def no_cache(view):
    @wraps(view)
    def no_cache_wrapper(*args, **kwargs):
        response = make_response(view(*args, **kwargs))
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response
    return no_cache_wrapper

def generate_barcode_image(barcode_number):
    # Ensure the directory exists
    if not os.path.exists(os.path.join('static', 'barcodes')):
        os.makedirs(os.path.join('static', 'barcodes'))
        
    filepath = os.path.join('static', 'barcodes', f'{barcode_number}.png')
    if not os.path.exists(filepath):
        code128 = barcode.get('code128', barcode_number, writer=ImageWriter())
        code128.save(filepath[:-4])
    return filepath

def get_db_connection():
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    return conn

@app.route('/')
def home():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        role = request.form['role']
        conn = get_db_connection()
        try:
            conn.execute('INSERT INTO users (username, password, role) VALUES (?, ?, ?)',
                         (username, password, role))
            conn.commit()
        except sqlite3.IntegrityError:
            return 'Username already exists!'
        conn.close()
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        role = request.form['role']
        conn = get_db_connection()
        user = conn.execute('SELECT * FROM users WHERE username = ? AND password = ? AND role = ?',
                            (username, password, role)).fetchone()
        conn.close()
        if user:
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role']
            return redirect(url_for('customer_dashboard') if role == 'customer' else 'dashboard')
        else:
            return "Invalid Credentials!"
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    if session.get('role') == 'admin':
        conn = get_db_connection()
        orders = conn.execute('''
            SELECT sales_orders.*, users.username 
            FROM sales_orders
            LEFT JOIN users ON sales_orders.customer_id = users.id
            ORDER BY sales_orders.created_at DESC
        ''').fetchall()
        conn.close()
        return render_template('dashboard.html', orders=orders)
    else:
        return redirect(url_for('customer_dashboard'))

@app.route('/scan')
def scan():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template('scan.html')

@app.route('/api/scan', methods=['POST'])
def scan_barcode():
    data = request.get_json()
    barcode_value = data.get('barcode')
    conn = get_db_connection()
    product = conn.execute('SELECT * FROM products WHERE barcode = ?', (barcode_value,)).fetchone()
    conn.close()
    return jsonify({'status': 'found', 'product': dict(product)}) if product else jsonify({'status': 'not_found'})

@app.route('/products')
def products():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db_connection()
    products = conn.execute('SELECT * FROM products').fetchall()
    conn.close()
    for product in products:
        generate_barcode_image(product['barcode'])
    return render_template('products.html', products=products)

@app.route('/add-product', methods=['GET', 'POST'])
def add_product():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    if request.method == 'POST':
        name = request.form['name']
        barcode_number = request.form['barcode']
        quantity = int(request.form['quantity'])
        location = request.form['location']
        conn = get_db_connection()
        try:
            conn.execute('INSERT INTO products (name, barcode, quantity, location) VALUES (?, ?, ?, ?)',
                         (name, barcode_number, quantity, location))
            conn.commit()
        except sqlite3.IntegrityError:
            return 'Barcode already exists!'
        conn.close()
        generate_barcode_image(barcode_number)
        return redirect(url_for('products'))
    return render_template('add_product.html')

@app.route('/sales-orders')
def view_sales_orders():
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect(url_for('login'))

    conn = get_db_connection()
    orders = conn.execute('''
        SELECT sales_orders.*, users.username 
        FROM sales_orders
        LEFT JOIN users ON sales_orders.customer_id = users.id
        ORDER BY sales_orders.created_at DESC
    ''').fetchall()
    conn.close()

    # Process orders to extract items from JSON data for easier display
    processed_orders = []
    for order in orders:
        order_dict = dict(order)
        try:
            # Parse the JSON data to get the items
            order_items = json.loads(order['order_data'])
            items = []
            # Process the items based on the structure
            for barcode, details in order_items.items():
                items.append({
                    'barcode': barcode,
                    'quantity': details['quantity']
                })
            order_dict['items'] = items
            processed_orders.append(order_dict)
        except:
            # If there's an error parsing, just add the original order
            processed_orders.append(order_dict)

    return render_template('sales_orders.html', orders=processed_orders)

@app.route('/update-order-status/<int:order_id>', methods=['POST'])
def update_order_status(order_id):
    if 'user_id' not in session or session['role'] != 'admin':
        return redirect(url_for('login'))
    
    new_status = request.form['status']
    conn = get_db_connection()
    
    # First, check if the status is being changed to an approval status
    # We'll consider both "Order Accepted" and "Approved" as approval statuses
    approval_statuses = ['Order Accepted', 'Approved']
    
    # Get the current status before updating
    current_status = conn.execute('SELECT status FROM sales_orders WHERE id = ?', (order_id,)).fetchone()
    
    # Store items with insufficient stock for potential vendor notification
    insufficient_stock_items = []
    
    # Only update product quantities if:
    # 1. The new status is in our approval list
    # 2. The current status was not already an approved status (to prevent double deduction)
    if new_status in approval_statuses and (not current_status or current_status['status'] not in approval_statuses):
        try:
            # Get the order data
            order = conn.execute('SELECT * FROM sales_orders WHERE id = ?', (order_id,)).fetchone()
            
            if order:
                # Parse the order data JSON
                order_data = json.loads(order['order_data'])
                
                # Check stock for each item in the order first
                has_insufficient_stock = False
                
                for barcode, details in order_data.items():
                    qty = details['quantity']
                    
                    # Check if there's enough stock
                    current_stock = conn.execute('SELECT * FROM products WHERE barcode = ?', 
                                              (barcode,)).fetchone()
                    
                    if not current_stock or current_stock['quantity'] < qty:
                        has_insufficient_stock = True
                        # Calculate how many more units we need
                        shortage = qty - (current_stock['quantity'] if current_stock else 0)
                        
                        # Add to our list of items with insufficient stock
                        insufficient_stock_items.append({
                            'barcode': barcode,
                            'name': current_stock['name'] if current_stock else "Unknown Product",
                            'requested': qty,
                            'available': current_stock['quantity'] if current_stock else 0,
                            'shortage': shortage
                        })
                
                # If there are items with insufficient stock, let the admin handle it via vendors
                if has_insufficient_stock:
                    session['insufficient_stock'] = {
                        'order_id': order_id,
                        'new_status': new_status,
                        'items': insufficient_stock_items
                    }
                    session.modified = True
                    
                    flash("Order has items with insufficient stock. Please review and notify vendors if needed.", "warning")
                    conn.close()
                    return redirect(url_for('insufficient_stock_dialog', order_id=order_id))
                
                # If we have enough stock for everything, proceed with the update
                else:
                    # Update the order status
                    conn.execute('UPDATE sales_orders SET status = ? WHERE id = ?', (new_status, order_id))
                    
                    # Update stock for each item
                    for barcode, details in order_data.items():
                        qty = details['quantity']
                        
                        # Update product quantities
                        conn.execute('UPDATE products SET quantity = quantity - ? WHERE barcode = ?', 
                                   (qty, barcode))
                        
                        # Record this stock movement in the stock table
                        conn.execute('INSERT INTO stock (barcode, quantity) VALUES (?, ?)', 
                                   (barcode, -qty))  # Negative quantity indicates stock reduction
                    
                    flash("Order has been successfully approved and stock updated!", "success")
        
        except Exception as e:
            print(f"Error processing order data: {e}")
            flash(f"Error updating stock: {str(e)}", "error")
    else:
        # Just update the status if it's not an approval status
        conn.execute('UPDATE sales_orders SET status = ? WHERE id = ?', (new_status, order_id))
    
    conn.commit()
    conn.close()
    return redirect(url_for('view_sales_orders'))
    
@app.route('/customer-dashboard')
def customer_dashboard():
    if 'user_id' not in session or session.get('role') != 'customer':
        return redirect(url_for('login'))
    
    # Get search query parameter (if any)
    search_query = request.args.get('search', '')
    
    conn = get_db_connection()
    
    if search_query:
        # If there's a search query, filter products
        products = conn.execute('''
            SELECT * FROM products 
            WHERE name LIKE ? OR barcode LIKE ?
            ORDER BY name
        ''', (f'%{search_query}%', f'%{search_query}%')).fetchall()
    else:
        # Otherwise get all available products
        products = conn.execute('SELECT * FROM products').fetchall()
    
    # Get user's orders
    orders = conn.execute('''
        SELECT * FROM sales_orders 
        WHERE customer_id = ? 
        ORDER BY created_at DESC
    ''', (session['user_id'],)).fetchall()
    
    # Process orders to extract items from JSON data
    processed_orders = []
    for order in orders:
        try:
            order_items = json.loads(order['order_data'])
            items = []
            for barcode, details in order_items.items():
                # Get product name for display
                product = conn.execute('SELECT name FROM products WHERE barcode = ?', (barcode,)).fetchone()
                product_name = product['name'] if product else "Unknown Product"
                
                items.append({
                    'barcode': barcode,
                    'name': product_name,
                    'quantity': details['quantity']
                })
            
            processed_orders.append({
                'id': order['id'],
                'status': order['status'],
                'created_at': order['created_at'],
                'items': items
            })
        except:
            # Handle any JSON parsing errors
            continue
    
    conn.close()
    
    # Calculate cart count for display
    cart_count = sum(item['quantity'] for item in session.get('cart', {}).values())
    
    return render_template('customer_dashboard.html', 
                          products=products, 
                          orders=processed_orders, 
                          cart_count=cart_count,
                          search_query=search_query)

@app.route('/add-to-cart', methods=['POST'])
def add_to_cart():
    if 'user_id' not in session or session.get('role') != 'customer':
        return jsonify({'success': False})
    data = request.get_json()
    barcode = data['barcode']
    quantity = int(data['quantity'])
    cart = session.get('cart', {})
    if barcode in cart:
        cart[barcode]['quantity'] += quantity
    else:
        cart[barcode] = {'quantity': quantity}
    session['cart'] = cart
    session.modified = True
    total_items = sum(item['quantity'] for item in cart.values())
    return jsonify({'success': True, 'cart_count': total_items})

@app.route('/cart')
def view_cart():
    if 'user_id' not in session or session.get('role') != 'customer':
        return redirect(url_for('login'))
    cart = session.get('cart', {})
    conn = get_db_connection()
    products = []
    for barcode, item in cart.items():
        product = conn.execute('SELECT * FROM products WHERE barcode = ?', (barcode,)).fetchone()
        if product:
            products.append({
                'name': product['name'],
                'barcode': barcode,
                'quantity': item['quantity'],
                'available': product['quantity']  # Keep this for information purposes
            })
    conn.close()
    cart_count = sum(item['quantity'] for item in cart.values())
    return render_template('cart.html', products=products, cart_count=cart_count)

@app.route('/checkout', methods=['POST'])
def checkout():
    if 'user_id' not in session or session.get('role') != 'customer':
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': 'Please log in'}), 401
        return redirect(url_for('login'))

    cart = session.get('cart', {})
    if not cart:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': 'Your cart is empty'}), 400
        return redirect(url_for('customer_dashboard'))

    # REMOVED: We no longer check if stock is sufficient here
    # Instead, we just process the order regardless of stock availability

    order_data = json.dumps(cart)
    customer_id = session['user_id']

    conn = get_db_connection()
    conn.execute('INSERT INTO sales_orders (customer_id, order_data, status) VALUES (?, ?, ?)',
                 (customer_id, order_data, 'Pending'))
    conn.commit()
    conn.close()
    
    session['cart'] = {}

    # If AJAX request, return JSON instead of redirect
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'success': True, 'message': 'Order placed successfully!'})

    flash('Order has been successfully placed!', 'success')
    return redirect(url_for('customer_dashboard'))

@app.route('/report')
def report():
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect(url_for('login'))
    conn = get_db_connection()
    products = conn.execute('SELECT * FROM products').fetchall()
    conn.close()
    return render_template('report.html', products=products)

@app.route('/download-csv')
def download_csv():
    if 'user_id' not in session or session.get('role') != 'admin':
        return redirect(url_for('login'))
        
    conn = get_db_connection()
    products = conn.execute('SELECT * FROM products').fetchall()
    conn.close()
    output = BytesIO()
    writer = csv.writer(output)
    writer.writerow(['ID', 'Name', 'Barcode', 'Quantity', 'Location'])
    for product in products:
        writer.writerow([product['id'], product['name'], product['barcode'], product['quantity'], product['location']])
    output.seek(0)
    return send_file(output, mimetype='text/csv', download_name='inventory.csv', as_attachment=True)

@app.route('/your-orders')
def your_orders():
    if 'user_id' not in session or session.get('role') != 'customer':
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    
    # Get user's orders
    orders = conn.execute('''
        SELECT * FROM sales_orders 
        WHERE customer_id = ? 
        ORDER BY created_at DESC
    ''', (session['user_id'],)).fetchall()
    
    # Process orders to extract items from JSON data
    processed_orders = []
    for order in orders:
        try:
            order_items = json.loads(order['order_data'])
            items = []
            for barcode, details in order_items.items():
                # Get product name for display
                product = conn.execute('SELECT name FROM products WHERE barcode = ?', (barcode,)).fetchone()
                product_name = product['name'] if product else "Unknown Product"
                
                items.append({
                    'barcode': barcode,
                    'name': product_name,
                    'quantity': details['quantity']
                })
            
            processed_orders.append({
                'id': order['id'],
                'status': order['status'],
                'created_at': order['created_at'],
                'items': items
            })
        except:
            # Handle any JSON parsing errors
            continue
    
    conn.close()
    
    # Calculate cart count for display
    cart_count = sum(item['quantity'] for item in session.get('cart', {}).values())
    
    return render_template('your_orders.html', orders=processed_orders, cart_count=cart_count)

@app.route('/print-barcode/<barcode>')
@no_cache
def print_barcode(barcode):
    image_path = generate_barcode_image(barcode)
    return render_template('print_barcode.html', barcode=barcode)

@app.route('/insufficient-stock/<int:order_id>')
def insufficient_stock_dialog(order_id):
    if 'user_id' not in session or session['role'] != 'admin':
        return redirect(url_for('login'))
    
    # Get the insufficient stock info from the session
    insufficient_stock = session.get('insufficient_stock', {})
    
    # Make sure it's for the right order
    if not insufficient_stock or insufficient_stock.get('order_id') != order_id:
        flash("Invalid request or session expired", "error")
        return redirect(url_for('view_sales_orders'))
    
    # Get vendors for the dropdown
    conn = get_db_connection()
    vendors = conn.execute('SELECT * FROM vendors').fetchall()
    conn.close()
    
    # If no vendors yet, suggest adding one
    if not vendors:
        flash("You need to add vendors first before you can create purchase orders", "warning")
    
    return render_template('insufficient_stock_dialog.html', 
                          order_id=order_id,
                          items=insufficient_stock.get('items', []),
                          vendors=vendors)

@app.route('/process-insufficient-stock/<int:order_id>', methods=['POST'])
def process_insufficient_stock(order_id):
    if 'user_id' not in session or session['role'] != 'admin':
        return redirect(url_for('login'))
    
    # Get the insufficient stock info from the session
    insufficient_stock = session.get('insufficient_stock', {})
    
    # Make sure it's for the right order
    if not insufficient_stock or insufficient_stock.get('order_id') != order_id:
        flash("Invalid request or session expired", "error")
        return redirect(url_for('view_sales_orders'))
    
    # Get the form data
    action = request.form.get('action')
    
    conn = get_db_connection()
    
    if action == 'notify_vendor':
        # Create purchase orders for the items with insufficient stock
        vendor_id = request.form.get('vendor_id')
        
        if not vendor_id:
            flash("Please select a vendor", "error")
            conn.close()
            return redirect(url_for('insufficient_stock_dialog', order_id=order_id))
        
        # Create a purchase order for each item
        for item in insufficient_stock.get('items', []):
            conn.execute('''
                INSERT INTO purchase_orders 
                (vendor_id, sales_order_id, product_barcode, quantity, status) 
                VALUES (?, ?, ?, ?, ?)
            ''', (vendor_id, order_id, item['barcode'], item['shortage'], 'Pending'))
        
        # Update the order status - we're approving it even with insufficient stock because we've notified vendors
        conn.execute('UPDATE sales_orders SET status = ? WHERE id = ?', 
                   (insufficient_stock.get('new_status'), order_id))
        
        # Update stock for the available quantities
        order = conn.execute('SELECT * FROM sales_orders WHERE id = ?', (order_id,)).fetchone()
        if order:
            order_data = json.loads(order['order_data'])
            
            for barcode, details in order_data.items():
                qty_requested = details['quantity']
                
                # Get current stock
                product = conn.execute('SELECT * FROM products WHERE barcode = ?', (barcode,)).fetchone()
                if product:
                    # Use what we have
                    qty_to_deduct = min(qty_requested, product['quantity'])
                    if qty_to_deduct > 0:
                        conn.execute('UPDATE products SET quantity = quantity - ? WHERE barcode = ?', 
                                   (qty_to_deduct, barcode))
                        conn.execute('INSERT INTO stock (barcode, quantity) VALUES (?, ?)', 
                                   (barcode, -qty_to_deduct))
        
        flash("Purchase orders have been created and vendors will be notified. Order has been approved with partial fulfillment.", "success")
    
    elif action == 'fulfill_later':
        # Just update the status but don't deduct stock
        conn.execute('UPDATE sales_orders SET status = ? WHERE id = ?', 
                   (insufficient_stock.get('new_status'), order_id))
        flash("Order has been approved but will be fulfilled later when stock is available.", "info")
    
    elif action == 'cancel':
        # Don't update the status, just go back
        flash("Order status update cancelled.", "info")
    
    # Clear the session data
    if 'insufficient_stock' in session:
        del session['insufficient_stock']
        session.modified = True
    
    conn.commit()
    conn.close()
    return redirect(url_for('view_sales_orders'))

@app.route('/vendors')
def vendors():
    if 'user_id' not in session or session['role'] != 'admin':
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    vendors_list = conn.execute('SELECT * FROM vendors').fetchall()
    conn.close()
    
    return render_template('vendors.html', vendors=vendors_list)

@app.route('/add-vendor', methods=['GET', 'POST'])
def add_vendor():
    if 'user_id' not in session or session['role'] != 'admin':
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        phone = request.form['phone']
        address = request.form['address']
        
        conn = get_db_connection()
        try:
            conn.execute('''
                INSERT INTO vendors (name, email, phone, address) 
                VALUES (?, ?, ?, ?)
            ''', (name, email, phone, address))
            conn.commit()
            flash("Vendor added successfully!", "success")
        except sqlite3.IntegrityError:
            flash("Email already exists for another vendor!", "error")
        finally:
            conn.close()
        
        return redirect(url_for('vendors'))
    
    return render_template('add_vendor.html')

@app.route('/purchase-orders')
def purchase_orders():
    if 'user_id' not in session or session['role'] != 'admin':
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    orders = conn.execute('''
        SELECT po.*, v.name as vendor_name, p.name as product_name 
        FROM purchase_orders po
        JOIN vendors v ON po.vendor_id = v.id
        JOIN products p ON po.product_barcode = p.barcode
        ORDER BY po.created_at DESC
    ''').fetchall()
    conn.close()
    
    return render_template('purchase_orders.html', orders=orders)

@app.route('/update-purchase-order/<int:po_id>', methods=['POST'])
def update_purchase_order(po_id):
    if 'user_id' not in session or session['role'] != 'admin':
        return redirect(url_for('login'))
    
    new_status = request.form['status']
    conn = get_db_connection()
    
    # Update the PO status
    conn.execute('UPDATE purchase_orders SET status = ? WHERE id = ?', (new_status, po_id))
    
    # If the status is "Received", update inventory
    if new_status == 'Received':
        po = conn.execute('SELECT * FROM purchase_orders WHERE id = ?', (po_id,)).fetchone()
        if po:
            # Update product quantities
            conn.execute('UPDATE products SET quantity = quantity + ? WHERE barcode = ?', 
                      (po['quantity'], po['product_barcode']))
            
            # Record this stock movement
            conn.execute('INSERT INTO stock (barcode, quantity) VALUES (?, ?)', 
                      (po['product_barcode'], po['quantity']))
            
            flash("Purchase order marked as received. Stock has been updated.", "success")
    
    conn.commit()
    conn.close()
    
    return redirect(url_for('purchase_orders'))

if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=5000, debug=True)