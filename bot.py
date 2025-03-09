from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes, CommandHandler
import os
from database import Session, Product, Order, initialize_products
from products import products_data
import pytz
from datetime import datetime

# Configuración
TOKEN = "7675712119:AAFQobgdRBko6_k4dZhZoxSbRVXOQBo12a4"
TIMEZONE = pytz.timezone("America/Guayaquil")

# Función para procesar pedidos
def process_order(order_text, user):
    try:
        lines = order_text.split("\n")
        order_id = lines[0].split()[1].strip()  # Extrae el número de pedido
        items = [line.strip() for line in lines[1:] if line.strip()]
        
        session = Session()
        total = 0.0
        products_list = []
        
        for item in items:
            parts = item.split(" ", 1)
            if len(parts) != 2:
                continue
                
            quantity, product_name = parts
            product = session.query(Product).filter(Product.name.ilike(f"%{product_name}%")).first()
            
            if product:
                total += product.price * int(quantity)
                products_list.append({
                    "nombre": product.name,
                    "cantidad": int(quantity),
                    "precio_unitario": product.price
                })
        
        new_order = Order(
            products=products_list,
            total=total,
            status="pendiente",
            created_at=datetime.now(TIMEZONE)
        )
        session.add(new_order)
        session.commit()
        
        return f"📝 Pedido {order_id} registrado!\nTotal: ${total:.2f}"
        
    except Exception as e:
        print(f"Error: {e}")
        return "❌ Error al procesar el pedido. Verifica el formato."

# Manejador de mensajes
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user = update.message.from_user.username
    
    if text.lower().startswith("pedido"):
        if "pagado" in text.lower():
            # Marcar pedido como pagado
            try:
                order_id = text.split()[1]
                session = Session()
                order = session.query(Order).get(int(order_id))
                
                if order:
                    order.status = "pagado"
                    session.commit()
                    await update.message.reply_text(f"✅ Pedido {order_id} marcado como PAGADO.")
                else:
                    await update.message.reply_text("❌ Pedido no encontrado.")
                    
            except Exception as e:
                await update.message.reply_text("❌ Error en el formato. Usa: 'Pedido X pagado'")
        else:
            # Nuevo pedido
            response = process_order(text, user)
            await update.message.reply_text(response)

# Comando para listar deudores
async def list_deudores(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = Session()
    pendientes = session.query(Order).filter(Order.status == "pendiente").all()
    
    if not pendientes:
        await update.message.reply_text("🎉 ¡No hay pedidos pendientes!")
        return
    
    response = "📋 Lista de Pedidos Pendientes:\n\n"
    for order in pendientes:
        response += f"🆔 Pedido {order.id}\n"
        response += f"📅 Fecha: {order.created_at.strftime('%Y-%m-%d %H:%M')}\n"
        response += f"💵 Total: ${order.total:.2f}\n"
        response += "------------------------\n"
    
    await update.message.reply_text(response)

# Comando para cierre de caja diario
async def cierre_caja(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = Session()
    hoy = datetime.now(TIMEZONE).date()
    
    # Obtener pedidos del día
    pedidos = session.query(Order).filter(
        Order.created_at >= hoy,
        Order.status == "pagado"  # Solo considerar pagados
    ).all()
    
    # Calcular totales
    total_ventas = sum(pedido.total for pedido in pedidos)
    productos_vendidos = {}
    
    for pedido in pedidos:
        for producto in pedido.products:
            nombre = producto["nombre"]
            cantidad = producto["cantidad"]
            productos_vendidos[nombre] = productos_vendidos.get(nombre, 0) + cantidad
    
    # Construir respuesta
    respuesta = "📊 **CIERRE DE CAJA**\n\n"
    respuesta += f"💰 Total vendido hoy: ${total_ventas:.2f}\n"
    respuesta += "🍺 Productos vendidos:\n"
    
    for producto, cantidad in productos_vendidos.items():
        respuesta += f"- {producto}: {cantidad}\n"
    
    await update.message.reply_text(respuesta)

# Añade el handler al bot (en el main)


if __name__ == "__main__":
    initialize_products()
    application = Application.builder().token(TOKEN).build()
    
    # Handlers
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CommandHandler("deudores", list_deudores))
    application.add_handler(CommandHandler("cierrecaja", cierre_caja))
    
    application.run_polling()