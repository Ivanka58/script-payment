from flask import Flask, request, jsonify
import psycopg2
import os
from datetime import datetime

app = Flask(__name__)

# ================= КОНФИГУРАЦИЯ =================
# Замени на свои данные из Supabase
DB_URL = "postgresql://postgres.ojircwgpnhcxpwzwjmpw:Trotil11---@aws-1-eu-central-1.pooler.supabase.com:6543/postgres?pgbouncer=true"
# Или используй переменные окружения:
# DB_URL = os.environ.get("DATABASE_URL")

PAYPALYCH_SHOP_ID = "твой_shop_id_из_пайпалича"
PAYPALYCH_API_TOKEN = "твой_api_token_из_пайпалича"

# Соотношение цена → токены
PACKAGES = {
    1: 1,      # 1 рубль = 1 токен (тест)
    100: 500,  # 100 рублей = 500 токенов
    200: 1200, # 200 рублей = 1200 токенов
    500: 3500, # 500 рублей = 3500 токенов
    1000: 8000 # 1000 рублей = 8000 токенов
}

# ================= БАЗА ДАННЫХ =================
def get_db_connection():
    return psycopg2.connect(DB_URL)

def add_tokens_to_user(user_id, tokens):
    """Начисляет токены пользователю в таблице messages"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    # Обновляем баланс (предполагаю, таблица messages, столбец tokens)
    cur.execute("""
        UPDATE messages 
        SET tokens = COALESCE(tokens, 0) + %s 
        WHERE user_id = %s
        RETURNING tokens
    """, (tokens, user_id))
    
    result = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()
    
    return result[0] if result else None

def save_payment(user_id, order_id, amount, tokens, status='pending'):
    """Сохраняет информацию о платеже"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    cur.execute("""
        INSERT INTO payments (user_id, order_id, amount, tokens, status)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (order_id) DO NOTHING
        RETURNING id
    """, (user_id, order_id, amount, tokens, status))
    
    result = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()
    
    return result[0] if result else None

def update_payment_status(order_id, status):
    """Обновляет статус платежа"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    cur.execute("""
        UPDATE payments 
        SET status = %s, paid_at = %s 
        WHERE order_id = %s
        RETURNING user_id, tokens
    """, (status, datetime.now() if status == 'success' else None, order_id))
    
    result = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()
    
    return result  # (user_id, tokens)

def get_payment(order_id):
    """Проверяет существование платежа"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    cur.execute("SELECT status FROM payments WHERE order_id = %s", (order_id,))
    result = cur.fetchone()
    
    cur.close()
    conn.close()
    return result

# ================= ВЕБХУК PAYPALYCH =================
@app.route('/webhook', methods=['POST'])
def paypalych_webhook():
    """
    Обработчик уведомлений от PayPalych
    PayPalych шлёт сюда POST когда платёж успешен/неуспешен
    """
    data = request.json or request.form.to_dict()
    
    print(f"📩 Получен вебхук: {data}")
    
    # Проверка обязательных полей
    if not data or 'order_id' not in data:
        return jsonify({"error": "No order_id"}), 400
    
    order_id = data.get('order_id')
    status = data.get('status')  # 'success', 'failed', 'pending'
    amount = int(data.get('amount', 0))
    
    # Проверяем, не обработали ли уже
    existing = get_payment(order_id)
    if existing and existing[0] == 'success':
        print(f"⚠️ Платёж {order_id} уже обработан")
        return jsonify({"status": "already_processed"}), 200
    
    # Извлекаем user_id из order_id (формат: user_123456_1678901234)
    try:
        user_id = int(order_id.split('_')[1])
    except (IndexError, ValueError):
        return jsonify({"error": "Invalid order_id format"}), 400
    
    # Определяем сколько токенов
    tokens = PACKAGES.get(amount, amount)  # Если сумма не в списке — 1:1
    
    # Если платёж новый — сохраняем
    if not existing:
        save_payment(user_id, order_id, amount, tokens, 'pending')
    
    # Если успешный статус — начисляем токены
    if status == 'success':
        payment_info = update_payment_status(order_id, 'success')
        
        if payment_info:
            user_id, tokens = payment_info
            new_balance = add_tokens_to_user(user_id, tokens)
            print(f"✅ Начислено {tokens} токенов пользователю {user_id}. Новый баланс: {new_balance}")
            
            # Здесь можно добавить отправку уведомления в Telegram
            # send_telegram_notification(user_id, f"💰 Зачислено {tokens} токенов!")
    
    return jsonify({"status": "ok"}), 200

# ================= ПРОВЕРКА =================
@app.route('/')
def health_check():
    return "Webhook server is running!", 200

if __name__ == '__main__':
    # Для локального тестирования
    app.run(host='0.0.0.0', port=5000, debug=True)
