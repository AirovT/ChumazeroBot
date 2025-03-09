from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes, CommandHandler
import os
from database import Session, Product, Order, initialize_products
from products import products_data
import pytz
from datetime import datetime
from telegram.ext import ConversationHandler

# Estados de la conversación
PEDIDO_CONFIRM = 1

# Configuración
TOKEN = "7675712119:AAFQobgdRBko6_k4dZhZoxSbRVXOQBo12a4"
TIMEZONE = pytz.timezone("America/Guayaquil")

# Función para reiniciar solo los pedidos pendientes (deudores)
def reset_deudores():
    """
    Elimina todos los registros de la tabla Order que estén pendientes,
    pero no afecta la tabla Product ni los pedidos pagados.
    """
    session = Session()
    
    try:
        # Eliminar solo los pedidos pendientes
        session.query(Order).filter(Order.status == "pendiente").delete()
        
        # Confirmar los cambios
        session.commit()
        
        print("✅ Pedidos pendientes (deudores) reiniciados correctamente.")
        
    except Exception as e:
        # Revertir cambios en caso de error
        session.rollback()
        print(f"❌ Error al reiniciar los pedidos pendientes: {e}")
        
    finally:
        # Cerrar la sesión
        session.close()

# Comando para reiniciar solo los pedidos pendientes
async def reset_db_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Verificar si el usuario es un administrador
    if update.message.from_user.username == "Bastian029":
        reset_deudores()
        await update.message.reply_text("✅ Pedidos pendientes (deudores) reiniciados correctamente.")
    else:
        await update.message.reply_text("❌ No tienes permisos para ejecutar este comando.")

# Función para procesar pedidos
def process_order(order_text, user, custom_id):
    try:
        lines = order_text.split("\n")
        items = [line.strip() for line in lines[1:] if line.strip()]
        
        # Validar si hay productos en el pedido
        if not items:
            return "❌ No hay productos en el pedido."
        
        session = Session()
        total = 0.0
        products_list = []
        productos_no_encontrados = []
        
        # Verificar si el ID ya existe
        existing_order = session.query(Order).filter(Order.custom_id == custom_id).first()
        if existing_order:
            return None  # Indica que hay un duplicado
        
        # Procesar productos
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
            else:
                productos_no_encontrados.append(product_name)
        
        # Validar si no se encontraron productos válidos
        if not products_list:
            return "❌ No se encontraron productos válidos en el pedido."
        
        # Crear el pedido
        new_order = Order(
            custom_id=custom_id,  # Usamos el ID personalizado
            products=products_list,
            total=total,
            status="pendiente",
            created_at=datetime.now(TIMEZONE)
        )
        session.add(new_order)
        session.commit()
        
        # Construir respuesta
        response = f"📝 Pedido {custom_id} registrado!\nTotal: ${total:.2f}\n"
        if productos_no_encontrados:
            response += "❌ Productos no encontrados:\n"
            for producto in productos_no_encontrados:
                response += f"- {producto}\n"
        
        return response
        
    except Exception as e:
        print(f"Error: {e}")
        return "❌ Error al procesar el pedido."

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

async def handle_pedido(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user = update.message.from_user.username
    
    try:
        lines = text.split("\n")
        custom_id = int(lines[0].split()[1].strip())
        
        # Procesar pedido
        response = process_order(text, user, custom_id)
        
        if response is None:
            context.user_data['pending_order'] = {
                'text': text,
                'custom_id': custom_id
            }
            await update.message.reply_text(
                f"⚠️ El Pedido {custom_id} ya existe. ¿Qué deseas hacer?\n\n"
                "1. Sobrescribir\n"
                "2. Usar siguiente ID disponible\n"
                "3. Cancelar"
            )
            return PEDIDO_CONFIRM
        else:
            await update.message.reply_text(response)
            return ConversationHandler.END
            
    except Exception as e:
        await update.message.reply_text("❌ Formato incorrecto. Ejemplo:\nPedido 1\n2 Michelada Club")
        return ConversationHandler.END

async def handle_pedido_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    choice = update.message.text
    pending_data = context.user_data.get('pending_order')
    
    if not pending_data:
        await update.message.reply_text("❌ Error. Inicia un nuevo pedido.")
        return ConversationHandler.END
    
    custom_id = pending_data['custom_id']
    session = Session()
    
    try:
        if choice == '1':  # Sobrescribir
            existing_order = session.query(Order).filter(Order.custom_id == custom_id).first()
            if existing_order:
                session.delete(existing_order)
                session.commit()
            
            response = process_order(pending_data['text'], update.message.from_user.username, custom_id)
            await update.message.reply_text(f"✅ Pedido {custom_id} actualizado!\n{response}")
        
        elif choice == '2':  # Siguiente ID disponible
            next_id = custom_id + 1
            while session.query(Order).filter(Order.custom_id == next_id).first():
                next_id += 1
            
            new_text = pending_data['text'].replace(str(custom_id), str(next_id))
            response = process_order(new_text, update.message.from_user.username, next_id)
            await update.message.reply_text(f"✅ Usando ID {next_id}:\n{response}")
        
        elif choice == '3':  # Cancelar
            await update.message.reply_text("❌ Operación cancelada.")
        
        else:
            await update.message.reply_text("❌ Opción no válida. Elige 1, 2 o 3.")
            return PEDIDO_CONFIRM
    
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")
    
    finally:
        if 'pending_order' in context.user_data:           del context.user_data['pending_order']
        session.close()
    
    return ConversationHandler.END

# Configura el ConversationHandler
conv_handler = ConversationHandler(
    entry_points=[MessageHandler(filters.TEXT & ~filters.COMMAND, handle_pedido)],
    states={
        PEDIDO_CONFIRM: [MessageHandler(filters.TEXT, handle_pedido_confirm)]
    },
    fallbacks=[]
)

if __name__ == "__main__":
    initialize_products()
    application = Application.builder().token(TOKEN).build()
    
    # Handlers
    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("deudores", list_deudores))
    application.add_handler(CommandHandler("resetdb", reset_db_command))
    application.add_handler(CommandHandler("cierrecaja", cierre_caja))
    
    application.run_polling()