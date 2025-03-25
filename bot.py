import re 
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes, CommandHandler
import os
from database import Session, Product, Order, initialize_products
from products import products_data
import pytz
from datetime import datetime
from telegram.ext import ConversationHandler
import re

# Estados de la conversación
PEDIDO_CONFIRM = 1

# Configuración
TOKEN = "7675712119:AAErbTDe5s_4TBrfjag9iX3HsdutZ_RN6GE"
TIMEZONE = pytz.timezone("America/Guayaquil")
# Configuración
# PRODUCTION_CHAT_ID = -4683968841  # ⬅️ Sin comillas, es un número entero negativo
PRODUCTION_CHAT_ID = -1002606763522  # ⬅️ Este es el ID correcto
MAIN_GROUP_ID = -1002366423301  # ⬅️ Este es el ID correcto
# Función para reiniciar solo los pedidos pendientes (deudores)
def reset_deudores():
    """
    Elimina todos los registros de la tabla Order que estén pendientes,
    pero no afecta la tabla Product ni los pedidos pagados.
    """
    session = Session()
    
    try:
        # Eliminar solo los pedidos pendientes
        session.query(Order).delete()
        
        # Confirmar los cambios
        session.commit()
        
        print("✅ Pedidos reiniciados correctamente.")
        
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
    if update.message.from_user.username == "Bastian029" or "IngAiro":
        reset_deudores()
        await update.message.reply_text("✅ Pedidos pendientes (deudores) reiniciados correctamente.")
    else:
        await update.message.reply_text("❌ No tienes permisos para ejecutar este comando.")

# Función para procesar pedidos
def process_order(order_text, user, custom_id):
    session = Session()
    try:
        lines = order_text.split("\n")
        items = [line.strip() for line in lines[1:] if line.strip()]
        
        if not items:
            return "❌ No hay productos en el pedido."
        
        total = 0.0
        products_list = []
        errores = []
        sugerencias_globales = []
        
        # Validar ID duplicado primero
        if session.query(Order).filter(Order.custom_id == custom_id).first():
            return "❌ Este ID de pedido ya existe."
        
        # Procesar TODOS los productos primero
        for idx, item in enumerate(items, 1):
            # Validar formato "cantidad nombre"
            if not re.match(r"^\d+\s+.+", item):
                errores.append(f"Línea {idx}: Formato incorrecto. Ejemplo: '3 Cerveza'")
                continue
                
            quantity_str, product_name = item.split(" ", 1)
            product_name = product_name.strip().lower()
            
            # Validar cantidad
            if not quantity_str.isdigit():
                errores.append(f"Línea {idx}: Cantidad no es número: '{quantity_str}'")
                continue
            quantity = int(quantity_str)
            
            # Buscar producto EXACTO
            product = session.query(Product).filter(Product.name.ilike(product_name)).first()
            
            if not product:
                # Buscar sugerencias (solo 3)
                sugerencias = (
                    session.query(Product)
                    .filter(Product.name.ilike(f"%{product_name}%"))
                    .limit(3)
                    .all()
                )
                if sugerencias:
                    sugs = ", ".join([s.name for s in sugerencias])
                    errores.append(f"Línea {idx}: '{product_name}' no existe el producto. \nSugerencias:\n {sugs}")
                else:
                    errores.append(f"Línea {idx}: '{product_name}' no existe y no hay sugerencias.")
                continue
            
            # Si todo está bien, agregar a la lista
            products_list.append({
                "nombre": product.name,
                "cantidad": quantity,
                "precio_unitario": product.price,
                "entregado": 0
            })
            total += product.price * quantity
        
        # Si hay errores, no crear el pedido
        if errores:
            response = "❌ Errores en el ingreso del pedido:\n" + "\n".join(errores)
            return response
        
        # Crear pedido solo si no hay errores
        new_order = Order(
            custom_id=custom_id,
            products=products_list,
            total=total,
            status="pendiente",
            created_at=datetime.now(TIMEZONE)
        )
        session.add(new_order)
        session.commit()
        
        return f"📝 Pedido {custom_id} registrado!\nTotal: ${total:.2f}"
        
    except Exception as e:
        session.rollback()
        print(f"Error: {e}")
        return "❌ Error grave al procesar el pedido."
    finally:
        session.close()

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
                order = session.query(Order).filter(Order.custom_id == int(order_id)).first()
                
                if order:
                    order.status = "pagado"  # Cambiar estado a pagado
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
        response += f"🆔 Pedido {order.custom_id}\n"
        response += f"📅 Fecha: {order.created_at.strftime('%Y-%m-%d %H:%M')}\n"
        response += f"💵 Total: ${order.total:.2f}\n"
        response += "------------------------\n"
    
    await update.message.reply_text(response)

# Comando para cierre de caja diario
async def cierre_caja(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = Session()
    hoy = datetime.now(TIMEZONE).date()
    
    # Comprobar si existen pedidos pendientes
    pedidos_pendientes = session.query(Order).filter(Order.status == "pendiente").all()
    if pedidos_pendientes:
        respuesta = "\n⚠️ ¡Atención! Aún faltan por pagar algunos pedidos pendientes.\n"
        await list_deudores(update, context)
    
    else:
        # Obtener pedidos pagados del día
        pedidos_pagados = session.query(Order).filter(
            Order.created_at >= hoy,
            Order.status == "pagado"
        ).all()

        # Obtener pedidos pagados del día
        pedidos_pagados_efectivo = session.query(Order).filter(
            Order.created_at >= hoy,
            Order.fpago == "efectivo"
        ).all()

        # Obtener pedidos pagados del día
        pedidos_pagados_transferencia = session.query(Order).filter(
            Order.created_at >= hoy,
            Order.fpago == "transferencia"
        ).all()
        
        # Calcular totales
        total_ventas = sum(pedido.total for pedido in pedidos_pagados)
        productos_vendidos = {}
        for pedido in pedidos_pagados:
            for producto in pedido.products:
                nombre = producto["nombre"]
                cantidad = producto["cantidad"]
                productos_vendidos[nombre] = productos_vendidos.get(nombre, 0) + cantidad

        # Calcular totales
        total_ventas_efectivo = sum(pedido.total for pedido in pedidos_pagados_efectivo)
        productos_vendidos_efectivo = {}
        for pedido in pedidos_pagados_efectivo:
            for producto in pedido.products:
                nombre = producto["nombre"]
                cantidad = producto["cantidad"]
                productos_vendidos_efectivo[nombre] = productos_vendidos_efectivo.get(nombre, 0) + cantidad

        # Calcular totales
        total_ventas_transferencia = sum(pedido.total for pedido in pedidos_pagados_transferencia)
        productos_vendidos_trans = {}
        for pedido in pedidos_pagados_transferencia:
            for producto in pedido.products:
                nombre = producto["nombre"]
                cantidad = producto["cantidad"]
                productos_vendidos_trans[nombre] = productos_vendidos_trans.get(nombre, 0) + cantidad
        
        # Construir respuesta
        respuesta = "📊 **CIERRE DE CAJA**\n\n"
        respuesta += f"💰 Total vendido hoy: ${total_ventas:.2f}\n"
        respuesta += f"💰 Total vendido efectivo: ${total_ventas_efectivo:.2f}\n"
        respuesta += f"💰 Total vendido transferencia: ${total_ventas_transferencia:.2f}\n"
        respuesta += "🍺 Productos vendidos:\n"
        for producto, cantidad in productos_vendidos.items():
            respuesta += f"- {producto}: {cantidad}\n"
    
    await update.message.reply_text(respuesta)
    session.close()

async def handle_pedido(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    
    # Si el mensaje es "Pedido X pagado" o "PX pagado", ignóralo
    if re.search(r"(?i)(pedido|p)\s*\d+\s+pagado", text):
        return ConversationHandler.END
    
    try:
        # Usar regex para detectar "Pedido X" o "PX"
        match = re.match(r"(?i)^(pedido|p)\s*(\d+)", text.split("\n")[0])
        if not match:
            await update.message.reply_text("❌ Formato incorrecto. Ejemplo:\nP1\n2 Michelada Club")
            return ConversationHandler.END
        
        # Extraer el ID (ej: "P1" → 1, "Pedido 2" → 2)
        custom_id = int(match.group(2))  # El grupo 2 captura el número
        context.user_data['pending_order'] = {
            'text': text,
            'custom_id': custom_id
        }
        
        # Verificar si el ID ya existe
        session = Session()
        existing_order = session.query(Order).filter(Order.custom_id == custom_id).first()
        session.close()
        
        if existing_order:
            await update.message.reply_text(
                f"⚠️ El Pedido {custom_id} ya existe. ¿Qué deseas hacer?\n\n"
                "1. Sobrescribir\n"
                "2. Usar siguiente ID\n"
                "3. Cancelar"
            )
            return PEDIDO_CONFIRM
        else:
            response = process_order(text, update.message.from_user.username, custom_id)
            await update.message.reply_text(response)
            return ConversationHandler.END
            
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")
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
        
        elif choice == '2':  # Siguiente ID disponible (CORREGIDO)
            next_id = custom_id + 1
            while True:
                existing = session.query(Order).filter(Order.custom_id == next_id).first()
                if not existing:
                    break
                next_id += 1
            
            # Crear nuevo texto con el ID actualizado
            new_lines = pending_data['text'].split("\n")
            new_lines[0] = f"Pedido {next_id}"
            new_text = "\n".join(new_lines)
            
            # Procesar el nuevo pedido
            response = process_order(new_text, update.message.from_user.username, next_id)
            if response:
                await update.message.reply_text(f"✅ Usando ID {next_id}:\n{response}")
            else:
                await update.message.reply_text("❌ Error al crear el nuevo pedido.")
        
        elif choice == '3':  # Cancelar
            await update.message.reply_text("❌ Operación cancelada.")
        
        else:
            await update.message.reply_text("❌ Opción no válida. Elige 1, 2 o 3.")
            return PEDIDO_CONFIRM
    
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")
    
    finally:
        session.close()
        if 'pending_order' in context.user_data:
            del context.user_data['pending_order']

# Configura el ConversationHandler
conv_handler = ConversationHandler(
        entry_points=[MessageHandler(
        filters.TEXT & ~filters.COMMAND & ~filters.Regex(r"(?i)^(ver|eliminar)"),  # <-- Excluye otros comandos
        handle_pedido
    )],
    states={
        PEDIDO_CONFIRM: [MessageHandler(filters.TEXT, handle_pedido_confirm)]
    },
    fallbacks=[]
)

# --- COMANDO PARA VER DETALLES DE UN PEDIDO ---
async def ver_pedido(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text.lower()
    
    # Detecta "pedido 2" o "ver pedido 2"
    match = re.search(r"(?:pedido|ver pedido)\s+(\d+)", texto)
    
    if not match:
        await update.message.reply_text("❌ Formato incorrecto. Ejemplo:\nPedido 2\nVer pedido 3")
        return
    
    pedido_id = int(match.group(1))
    
    session = Session()
    try:
        pedido = session.query(Order).filter(Order.custom_id == pedido_id).first()
        
        if not pedido:
            await update.message.reply_text(f"❌ Pedido {pedido_id} no encontrado")
            return
            
        # Construir respuesta detallada
        respuesta = f"📋 **PEDIDO {pedido_id}**\n"
        respuesta += f"📅 Fecha: {pedido.created_at.strftime('%d/%m/%Y %H:%M')}\n"
        respuesta += f"🔄 Estado: {pedido.status.upper()}\n"
        respuesta += "--------------------------------\n"
        
        for producto in pedido.products:
            respuesta += f"➤ {producto['nombre']}\n"
            respuesta += f"   Cantidad: {producto['cantidad']}\n"
            respuesta += f"   Precio: ${producto['precio_unitario']:.2f} c/u\n"
            respuesta += f"   Subtotal: ${producto['cantidad'] * producto['precio_unitario']:.2f}\n\n"
        
        respuesta += f"💵 **TOTAL: ${pedido.total:.2f}**"
        
        await update.message.reply_text(respuesta)
        
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")
    finally:
        session.close()

# --- COMANDO PARA LISTAR TODOS LOS PEDIDOS ---
async def listar_pedidos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = Session()
    try:
        pedidos = session.query(Order).order_by(Order.custom_id).all()
        
        if not pedidos:
            await update.message.reply_text("📭 No hay pedidos registrados")
            return
        
        respuesta = "📦 **LISTA DE TODOS LOS PEDIDOS**\n\n"
        
        for pedido in pedidos:
            respuesta += f"🆔 Pedido {pedido.custom_id}\n"
            respuesta += f"   📅 Fecha: {pedido.created_at.strftime('%d/%m/%y')}\n"
            respuesta += f"   💵 Total: ${pedido.total:.2f}\n"
            respuesta += f"   📌 Estado: {pedido.status.upper()}\n"
            respuesta += "------------------------\n"
        
        await update.message.reply_text(respuesta)
        
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")
    finally:
        session.close()

# --- COMANDO PARA ELIMINAR PEDIDO (EXISTENTE) ---
async def eliminar_pedido(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.username not in ["Bastian029", "IngAiro", "admin2"]:
        await update.message.reply_text("❌ Sin permisos")
        return
    texto = update.message.text
    match = re.search(r"eliminar pedido (\d+)", texto, re.IGNORECASE)
    

    if not match:
        await update.message.reply_text("❌ Formato incorrecto. Ejemplo: Eliminar pedido 2")
        return
        
    pedido_id = int(match.group(1))
    
    session = Session()
    try:
        pedido = session.query(Order).filter(Order.custom_id == pedido_id).first()
        
        if pedido:
            session.delete(pedido)
            session.commit()
            await update.message.reply_text(f"✅ Pedido {pedido_id} eliminado permanentemente")
        else:
            await update.message.reply_text(f"❌ Pedido {pedido_id} no encontrado")
            
    except Exception as e:
        session.rollback()
        await update.message.reply_text(f"❌ Error al eliminar: {str(e)}")
    finally:
        session.close()


# Función para buscar productos por término (por ejemplo, "michelada")
async def ayuda_productos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Se espera que el mensaje sea del tipo "ayuda <palabra>"
    text = update.message.text.strip()
    # Extraemos la palabra después de "ayuda"
    match = re.match(r"(?i)^ayuda\s+(.+)$", text)
    if not match:
        await update.message.reply_text("❌ Formato incorrecto. Usa: 'ayuda <producto>'")
        return

    termino = match.group(1).strip().lower()
    session = Session()
    try:
        # Se buscan productos cuyo nombre contenga el término (sin distinguir mayúsculas/minúsculas)
        productos = session.query(Product).filter(Product.name.ilike(f"%{termino}%")).all()
        
        if not productos:
            await update.message.reply_text(f"❌ No se encontraron productos que coincidan con '{termino}'.")
            return

        respuesta = f"🔎 Productos que coinciden con '{termino}':\n\n"
        for prod in productos:
            respuesta += f"- {prod.name} (${'{:.2f}'.format(prod.price)})\n"
        
        await update.message.reply_text(respuesta)
    
    except Exception as e:
        await update.message.reply_text(f"❌ Error al buscar productos: {str(e)}")
    
    finally:
        session.close()

#Envio de mensaje
async def handle_pedido_pagado(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    try:
        tokens = text.split()
        if len(tokens) < 4:
            await update.message.reply_text("❌ Formato incorrecto. Usa: 'Pedido X pagado <método>'")
            return
            
        session = Session()
        order_id = int(tokens[1])
        metodo_pago = tokens[3].lower()

        if metodo_pago == "e":
            metodo_pago2 = "efectivo"
        elif metodo_pago == "t":
            metodo_pago2 = "transferencia"
        else:
            await update.message.reply_text("❌ Método no válido. Usa 'e' para efectivo o 't' para transferencia.")
            return

        order = session.query(Order).filter(Order.custom_id == order_id).first()
        
        if order:
            order.status = "pagado"
            order.fpago = metodo_pago2
            session.commit()
            
            # Construir mensaje para producción
            msg_produccion = f"🚨 **NUEVO PEDIDO PAGADO ({metodo_pago2.upper()})**\n"
            msg_produccion += f"🆔 Pedido: {order_id}\n"
            msg_produccion += "🍺 Productos:\n"
            
            for producto in order.products:
                msg_produccion += f"- {producto['cantidad']}x {producto['nombre']}\n"
            
            msg_produccion += f"\n💵 Total: ${order.total:.2f}"
            
            # Enviar a grupo de producción (con manejo de errores)
            try:
                await context.bot.send_message(
                    chat_id=PRODUCTION_CHAT_ID,
                    text=msg_produccion
                )
            except Exception as e:
                print(f"Error al enviar a producción: {str(e)}")  # Para debug
                await update.message.reply_text("❌ No se pudo enviar el pedido a producción. Verifica permisos.")
            
            await update.message.reply_text(f"✅ Pedido {order_id} marcado como PAGADO con {metodo_pago2.upper()}.")
        else:
            await update.message.reply_text("❌ Pedido no encontrado.")

    except Exception as e:
        print(f"🚨 ERROR ENVIANDO A PRODUCCIÓN: {str(e)}")  # <-- Esto mostrará el error real
        await update.message.reply_text(f"❌ Error técnico: {str(e)}")

    finally:
        session.close()

#La parte de los anuncios
# Handler para anuncios
async def handle_anuncio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        # Extraer texto después de "anuncio"
        anuncio_text = re.sub(r'(?i)^anuncio\s*', '', update.message.text).strip()
        
        # Formatear con emojis
        formatted_msg = f"🚨⚠️ **{anuncio_text.upper()}** ⚠️🚨"
        
        # Determinar origen
        chat_id = update.message.chat.id
        
        # Si es del grupo principal
        if chat_id == MAIN_GROUP_ID:
            # Enviar al grupo principal
            await context.bot.send_message(
                chat_id=MAIN_GROUP_ID,
                text=formatted_msg,
                parse_mode='Markdown'
            )
            # Reenviar a producción
            await context.bot.send_message(
                chat_id=PRODUCTION_CHAT_ID,
                text=f"📢 ANUNCIO DEL GRUPO PRINCIPAL:\n{formatted_msg}",
                parse_mode='Markdown'
            )
            
        # Si es de producción
        elif chat_id == PRODUCTION_CHAT_ID:
            # Enviar al grupo principal
            await context.bot.send_message(
                chat_id=MAIN_GROUP_ID,
                text=formatted_msg,
                parse_mode='Markdown'
            )

    except Exception as e:
        print(f"Error en anuncio: {e}")

# Handler para preguntas del grupo principal
async def forward_questions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Si es del grupo principal y no es un comando
    if update.message.chat.id == MAIN_GROUP_ID and not update.message.text.startswith('/'):
        pregunta = update.message.text
        # Enviar a producción
        await context.bot.send_message(
            chat_id=PRODUCTION_CHAT_ID,
            text=f"❓ **CONSULTA DEL CLIENTE** ❓\n\n{pregunta}"
        )

# En la sección de handlers del main (dentro de if __name__ == "__main__":)
if __name__ == "__main__":
    initialize_products()
    application = Application.builder().token(TOKEN).build()

    # ===== HANDLERS EN ORDEN CORRECTO =====
    # 1. Handler de anuncios
    application.add_handler(MessageHandler(
        filters.Regex(r'(?i)^anuncio\s.+'),  # <-- Corregido
        handle_anuncio
    ))
    
    # ===== HANDLERS EN ORDEN DE PRIORIDAD =====
    # 1. Comandos CRÍTICOS primero (eliminar, marcar pagado)
    # 2. Eliminar pedido
    application.add_handler(MessageHandler(
        filters.Regex(r'(?i)^eliminar pedido \d+$'),  # <-- Corregido
        eliminar_pedido
    ))
    
    # 3. Marcar como pagado
    application.add_handler(MessageHandler(
        filters.Regex(r'(?i)^(pedido|p)\s*\d+\s+pagado\s+\w+$'),  # <-- Corregido
        handle_pedido_pagado
    ))
    
    # 3. Handler para preguntas del grupo principal (¡NUEVO!)
    application.add_handler(MessageHandler(
        filters.Chat(chat_id=MAIN_GROUP_ID) & ~filters.COMMAND,
        forward_questions
    ))

    # 2. Ver pedido
    application.add_handler(MessageHandler(
        filters.Regex(r"(?i)^(ver\s+pedido|pedido)\s+\d+$"),
        ver_pedido
    ))
    
    # 3. Ayuda por si no sabes como escribir el pedido
    # --- Registrar el handler para el comando "ayuda" ---
    application.add_handler(MessageHandler(
        filters.Regex(r"(?i)^ayuda\s+.+"),
        ayuda_productos
    ))


    # 6. ConversationHandler (CREAR pedidos)
    application.add_handler(conv_handler)
    
    # 7. Comandos restantes
    application.add_handler(CommandHandler("deudores", list_deudores))
    application.add_handler(CommandHandler("reiniciar", reset_db_command))
    application.add_handler(CommandHandler("cierrecaja", cierre_caja))
    application.add_handler(CommandHandler("todos", listar_pedidos))
    
    # ===== INICIAR BOT =====
    application.run_polling()