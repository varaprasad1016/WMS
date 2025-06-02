from flask import Flask, render_template, request, jsonify
import sqlite3
import re

app = Flask(__name__)

# --- DATABASE FUNCTION ---

def fetch_order_status(order_id):
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute('SELECT status FROM sales_orders WHERE id = ?', (order_id,))
    result = cursor.fetchone()
    conn.close()

    if result:
        return f"The status of your order {order_id} is: {result[0]}"
    else:
        return f"Order ID {order_id} not found in our system."

# --- CHATBOT FUNCTION ---

def generate_response(message):
    message = message.lower()
    words = set(re.findall(r'\w+', message))

    # Extract numeric order ID if mentioned
    number_match = re.search(r"\b\d{1,10}\b", message)  # match order numbers like 4, 123, 999999
    contains_status_keywords = words & {"status", "track", "where", "check"}

    if contains_status_keywords and number_match:
        return fetch_order_status(number_match.group())

    # Basic numeric ID detection fallback
    if number_match and "order" in words:
        return fetch_order_status(number_match.group())

    # Greeting
    if words & {"hi", "hello", "hey"}:
        return "Hello! 👋 How can I assist you with your order today?"

    # Asking how to order
    if words & {"order", "buy", "purchase"} and words & {"how", "want", "place"}:
        return "To place an order, browse products, add items to your cart, and click 'Checkout'."

    # Delivery time
    if words & {"delivery", "arrive", "receive", "ship", "reach"}:
        return "Delivery usually takes 3 to 5 business days depending on your location."

    # Cancel order
    if "cancel" in words:
        return "To cancel your order, please provide your order ID (e.g., 12345)."

    # Check status (without number yet)
    if contains_status_keywords:
        return "Sure! Just provide your numeric order ID (e.g., 12345) so I can check the status for you."

    # Help
    if words & {"help", "can", "do"}:
        return "I can help you place orders, check order status, cancel orders, and answer delivery-related questions."

    # Default fallback
    return (
        "I'm not quite sure I got that 🤔 Try asking things like:\n"
        "- How do I place an order?\n"
        "- What's the status of my order 12345?\n"
        "- Cancel my order\n"
        "- When will my order arrive?\n"
        "- How do I get a refund?"
    )

# --- ROUTES ---

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/index", methods=["POST"])
def chat():
    user_input = request.json["message"]
    response = generate_response(user_input)
    return jsonify({"response": response})

if __name__ == "__main__":
    app.run(debug=True)