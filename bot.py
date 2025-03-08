import os
from telegram.ext import Application, MessageHandler, filters
from database import Session, Product, Order
from products import products_data
from datetime import datetime
import pytz

# Configuración
TOKEN = os.getenv("7553810124:AAEnfkfQekmzmc5LAXQxWathpFcnMXoUR9w")  # Usa variables de entorno
TIMEZONE = pytz.timezone("America/Quito")  # Ajusta según tu zona horaria

# Cargar productos predefinidos en la base de datos
def initialize_products():
    session = Session()
    for product in products_data:
        if not session.query(Product).filter_by(name=product["name"]).first():
            new_product = Product(name=product["name"], price=product["price"])
            session.add(new_product)
    session.commit()

# Procesar un nuevo pedido
def process_order(order_text, user):
    lines = order_text.split("\n")
    order_id = lines[0].split()[1]  # "Pedido 1" -> id=1
    items = [line.strip() for line in lines[1:] if line.strip()]
    
    session = Session()
    total = 0.0
    products_list = []
    
    for item in items:
        quantity, product_name = item.split(" ", 1)
        product = session.query(Product).filter_by(name=product_name).first()
        if product:
            total += product.price * int(quantity)
            products_list.append({"name": product.name, "quantity": int(quantity)})
    
    new_order = Order(
        products=products_list,
        total=total,
        status="pendiente",
        created_at=datetime.now(TIMEZONE)
    )
    session.add(new_order)
    session.commit()
    
    return f"✅ Pedido {order_id} registrado! Total: S/{total:.2f}"

# Manejador de mensajes
def handle_message(update, context):
    text = update.message.text
    user = update.message.from_user.username
    
    if text.lower().startswith("pedido"):
        response = process_order(text, user)
        update.message.reply_text(response)
    
    elif "cancelado" in text.lower():
        order_id = text.split()[1]
        session = Session()
        order = session.query(Order).get(int(order_id))
        if order:
            order.status = "pagado"
            session.commit()
            update.message.reply_text(f"✅ Pedido {order_id} marcado como pagado.")
        else:
            update.message.reply_text("❌ Pedido no encontrado.")

# Inicializar el bot
if __name__ == "__main__":
    initialize_products()  # Asegurar que los productos existan
    updater = Updater(TOKEN, use_context=True)
    dispatcher = updater.dispatcher
    application.add_handler(MessageHandler(filters.TEXT, handle_message))
    updater.start_polling()
    updater.idle()