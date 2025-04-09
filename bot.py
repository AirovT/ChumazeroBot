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
from fpdf import FPDF  # Necesitarás instalar esta librería: pip install fpdf
from sqlalchemy import func

# Estados de la conversación
PEDIDO_CONFIRM = 1

# Configuración
TOKEN = "7872872117:AAGi4620wTN6_ri1yI6oh652SShyHcMPHM8"
TIMEZONE = pytz.timezone("America/Guayaquil")
# Configuración
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
    # Usa "in" en lugar de "or"
    if update.message.from_user.username in ["Bastian029", "IngAiro", "Karla181117"]:
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
    now = datetime.now(TIMEZONE)

    # Calcular rango de tiempo (6 AM a 5 AM del día siguiente)
    if now.hour < 5:  # Si es antes de las 5 AM
        inicio_jornada = datetime(now.year, now.month, now.day - 1, 6, 0, tzinfo=TIMEZONE)  # 6 AM del día anterior
        fin_jornada = datetime(now.year, now.month, now.day, 5, 0, tzinfo=TIMEZONE)  # 5 AM del día actual
    else:  # Si es 5 AM o después
        inicio_jornada = datetime(now.year, now.month, now.day, 6, 0, tzinfo=TIMEZONE)  # 6 AM del día actual
        fin_jornada = datetime(now.year, now.month, now.day + 1, 5, 0, tzinfo=TIMEZONE)  # 5 AM del día siguiente

    # Comprobar pedidos pendientes
    pedidos_pendientes = session.query(Order).filter(Order.status == "pendiente").all()
    
    # Generar PDF
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    
    respuesta = "📊 **CIERRE DE CAJA**\n\n"
    pdf.cell(200, 10, txt="CIERRE DE CAJA", ln=1, align='C')
    
    if pedidos_pendientes:
        respuesta += "⚠️ ¡Atención! Pedidos pendientes:\n"
        pdf.cell(200, 10, txt="¡ATENCIÓN! Hay pedidos pendientes:", ln=1)
        for pedido in pedidos_pendientes:
            respuesta += f"- Pedido {pedido.custom_id} (${pedido.total:.2f})\n"
            pdf.cell(200, 10, txt=f"Pedido {pedido.custom_id} - ${pedido.total:.2f}", ln=1)
    else:
        # Obtener todos los pedidos pagados en el rango horario
        pedidos_pagados = session.query(Order).filter(
            Order.created_at.between(inicio_jornada, fin_jornada),
            Order.status == "pagado"
        ).all()

        # Calcular totales
        total_ventas = sum(p.total for p in pedidos_pagados)
        total_efectivo = sum(p.efectivo for p in pedidos_pagados)
        total_transferencia = sum(p.transferencia for p in pedidos_pagados)

        # Texto y PDF
        respuesta += f"🕒 Período: {inicio_jornada.strftime('%d/%m %H:%M')} - {fin_jornada.strftime('%d/%m %H:%M')}\n"
        respuesta += f"💰 Total: ${total_ventas:.2f}\n"
        respuesta += f"💵 Efectivo: ${total_efectivo:.2f}\n"
        respuesta += f"📲 Transferencia: ${total_transferencia:.2f}\n"
        respuesta += "🍺 Productos vendidos:\n"

        # PDF
        pdf.cell(200, 10, txt=f"Periodo: {inicio_jornada.strftime('%d/%m %H:%M')} a {fin_jornada.strftime('%d/%m %H:%M')}", ln=1)
        pdf.cell(200, 10, txt=f"Total: ${total_ventas:.2f}", ln=1)
        pdf.cell(200, 10, txt=f"Efectivo: ${total_efectivo:.2f}", ln=1)
        pdf.cell(200, 10, txt=f"Transferencia: ${total_transferencia:.2f}", ln=1)
        pdf.cell(200, 10, txt="Productos vendidos:", ln=1)

        # Detalle productos ordenados
        productos_vendidos = {}
        for pedido in pedidos_pagados:
            for producto in pedido.products:
                nombre = producto["nombre"]
                cantidad = producto["cantidad"]
                productos_vendidos[nombre] = productos_vendidos.get(nombre, 0) + cantidad

        # Ordenar los productos por cantidad descendente
        productos_ordenados = sorted(
            productos_vendidos.items(),
            key=lambda item: item[1], 
            reverse=True
        )

        # Generar respuesta y PDF con el orden correcto
        for producto, cantidad in productos_ordenados:
            respuesta += f"- {producto}: {cantidad}\n"
            pdf.cell(200, 10, txt=f"{producto}: {cantidad}", ln=1)

    # Guardar y enviar PDF
    nombre_pdf = f"cierre_{now.strftime('%Y%m%d_%H%M')}.pdf"
    pdf.output(nombre_pdf)
    
    # Enviar respuestas
    await update.message.reply_text(respuesta, parse_mode='Markdown')
    await update.message.reply_document(document=open(nombre_pdf, 'rb'))
    
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
    if 'pending_order' not in context.user_data:  # <-- Nueva validación
        await update.message.reply_text("❌ No hay pedido en proceso. Usa 'P1' para empezar.")
        return ConversationHandler.END
    
    choice = update.message.text
    pending_data = context.user_data.get('pending_order')
    
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
    entry_points=[
        MessageHandler(
            filters.Regex(r"(?i)^(pedido|p)\s*\d+") & ~filters.COMMAND,
            handle_pedido
        )
    ],
    states={
        PEDIDO_CONFIRM: [
            MessageHandler(filters.TEXT, handle_pedido_confirm)
        ]
    },
    fallbacks=[],  # Sin manejador de timeout
    conversation_timeout=300  # 5 minutos (solo cierra la conversación en silencio)
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
        
        # Limitar a 15 pedidos en el texto
        max_pedidos_texto = 15
        respuesta = "📦 **PRIMEROS 15 PEDIDOS**\n\n"
        
        # Generar texto con primeros 15 pedidos
        for pedido in pedidos[:max_pedidos_texto]:
            respuesta += f"🆔 Pedido {pedido.custom_id}\n"
            respuesta += f"   📅 Fecha: {pedido.created_at.strftime('%d/%m/%y')}\n"
            respuesta += f"   💵 Total: ${pedido.total:.2f}\n"
            respuesta += f"   📌 Estado: {pedido.status.upper()}\n"
            respuesta += "------------------------\n"
        
        # Si hay más de 15, generar PDF
        if len(pedidos) > max_pedidos_texto:
            respuesta += "\n⚠️ **Hay más de 15 pedidos. Revisa el PDF adjunto.**"
            
            # Crear PDF con todos los pedidos
            pdf = FPDF()
            pdf.add_page()
            pdf.set_font("Arial", size=12)
            pdf.cell(200, 10, txt="LISTA COMPLETA DE PEDIDOS", ln=1, align='C')
            
            for pedido in pedidos:
                pdf.cell(200, 10, txt=f"Pedido #{pedido.custom_id}", ln=1)
                pdf.cell(200, 10, txt=f"Fecha: {pedido.created_at.strftime('%d/%m/%y %H:%M')}", ln=1)
                pdf.cell(200, 10, txt=f"Total: ${pedido.total:.2f}", ln=1)
                pdf.cell(200, 10, txt=f"Estado: {pedido.status.upper()}", ln=1)
                pdf.cell(200, 10, txt="-"*50, ln=1)
            
            # Guardar y enviar PDF
            nombre_archivo = f"Pedidos_{datetime.now(TIMEZONE).strftime('%Y%m%d')}.pdf"
            pdf.output(nombre_archivo)
            await update.message.reply_document(document=open(nombre_archivo, 'rb'))
        
        await update.message.reply_text(respuesta, parse_mode='Markdown')
        
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
        # Usar regex para capturar todos los componentes
        match = re.match(r"(?i)^(pedido|p)\s*(\d+)\s+pagado\s+(\w+)\s*(\d*\.?\d+)?$", text)
        if not match:
            await update.message.reply_text("❌ Formato incorrecto. Usa: 'Pedido X pagado [e/t] [monto]'")
            return

        order_id = int(match.group(2))
        metodo = match.group(3).lower()
        monto = float(match.group(4)) if match.group(4) else None

        session = Session()
        order = session.query(Order).filter(Order.custom_id == order_id).first()
            
        if not order:
            await update.message.reply_text("❌ Pedido no encontrado.")
            return

        # Validar método de pago
        if metodo == 'e':
            metodo_pago = 'efectivo'
            monto = order.total  # Si no se especifica monto, pagar total
            order.efectivo = monto
            order.transferencia = 0.0
        elif metodo == 't':
            metodo_pago = 'transferencia'
            monto = order.total  # Transferencias siempre son por el total
            order.transferencia = monto
            order.efectivo = 0.0
        elif metodo == 'p':
            metodo_pago = 'parcial'
            if monto <= 0 or None:
                await update.message.reply_text("❌ El monto debe ser mayor a 0 en pagos parciales")
                return
            if monto > 0:
                order.efectivo = monto
                order.transferencia = order.total - order.efectivo
                msg_estado = f"💵 Pago parcial: ${monto:.2f} | Restante: ${order.transferencia:.2f}"
        else:
            await update.message.reply_text("❌ Método no válido. Usa 'e', 't' o 'p'")
            return

        session.commit()
        order = session.query(Order).filter(Order.custom_id == order_id).first()
        
        if order:
            order.status = "pagado"
            order.fpago = metodo_pago
            session.commit()
            
            # Construir mensaje para producción
            msg_produccion = f"🚨 **NUEVO PEDIDO PAGADO ({metodo_pago.upper()})**\n"
            msg_produccion += f"🆔 Pedido: {order_id}\n"
            msg_produccion += "🍺 Productos:\n"
            
            for producto in order.products:
                msg_produccion += f"\t\t\t\t\t\t {producto['cantidad']} x {producto['nombre']}\n"
            
            # Enviar a grupo de producción (con manejo de errores)
            try:
                await context.bot.send_message(
                    chat_id=PRODUCTION_CHAT_ID,
                    text=msg_produccion
                )
            except Exception as e:
                print(f"Error al enviar a producción: {str(e)}")  # Para debug
                await update.message.reply_text("❌ No se pudo enviar el pedido a producción. Verifica permisos.")

            await update.message.reply_text(f"✅ Pedido {order_id} marcado como PAGADO con {metodo_pago.upper()}.\n Efectivo: {order.efectivo}\n Trasnferencia: {order.transferencia}")
        else:
            await update.message.reply_text("❌ Pedido no encontrado.")

    except Exception as e:
        print(f"🚨 ERROR ENVIANDO A PRODUCCIÓN: {str(e)}")  # <-- Esto mostrará el error real
        await update.message.reply_text("❌ El monto debe ser mayor a 0 en pagos parciales\n Ejemplo \nPedido 1 pagado p '3 (valor pagado en efectivo)'")

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
    # Filtro mejorado: excluye comandos y palabras clave
    if (
        update.message.chat.id == MAIN_GROUP_ID 
        and not update.message.text.startswith('/')
        and not re.match(r"(?i)^(pedido|p|ver|eliminar|ayuda|anuncio)", update.message.text)
    ):
        pregunta = update.message.text
        await context.bot.send_message(
            chat_id=PRODUCTION_CHAT_ID,
            text=f"❓ **PREGUNTAS** ❓\n\n{pregunta}"
        )

#comando help
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ayuda_texto = """
🆘 **MANUAL DE USO DEL BOT** 🆘

📌 **COMANDOS PRINCIPALES**:
▫️ `/help` - Muestra este mensaje de ayuda
▫️ `/deudores` - Lista pedidos pendientes de pago
▫️ `/reiniciar` - Borra todos los pedidos pendientes (solo admin)
▫️ `/cierrecaja` - Genera reporte diario con PDF
▫️ `/todos` - Lista completa de pedidos con PDF

📦 **GESTIÓN DE PEDIDOS**:
▫️ `P1` + productos (ejemplo:
P1
2 Cerveza 
3 Snacks - Crear nuevo pedido)
▫️ `Pedido 1 pagado e/t/p` - Marcar como pagado (e=efectivo, t=transferencia, p=parcial y se debe especificar solo el monto en efectivo)
▫️ `Ver pedido 1` - Ver detalles de un pedido
▫️ `Eliminar pedido 1` - Elimina un pedido (solo admin)

🔍 **BUSQUEDA Y OTROS**:
▫️ `Ayuda cerveza` - Busca productos similares
▫️ `Anuncio OFERTA ESPECIAL` - Envía anuncio a ambos grupos

⏰ **HORARIO DE CIERRE**:
El cierre diario considera pedidos desde las 6 AM hasta las 5 AM del día siguiente.

📄 **NOTAS**:
- Los IDs de pedido deben ser secuenciales
- Usa el formato exacto para cada comando
- Reporta errores a @IngAiro
"""

    await update.message.reply_text(ayuda_texto, parse_mode='Markdown')

# En la sección de handlers del main (dentro de if __name__ == "__main__":)
if __name__ == "__main__":
    initialize_products()
    application = Application.builder().token(TOKEN).build()

    # ===== HANDLERS EN ORDEN DE PRIORIDAD =====
    # 1. Comandos CRÍTICOS primero (eliminar, marcar pagado)
    application.add_handler(MessageHandler(
        filters.Regex(r'(?i)^eliminar pedido \d+$'),
        eliminar_pedido
    ))
    
    application.add_handler(MessageHandler(
    filters.Regex(r'(?i)^(pedido|p)\s*\d+\s+pagado\s+(\w+)\s*(\d*\.?\d+)?$'),
    handle_pedido_pagado
    ))

    # 2. Handler de anuncios
    application.add_handler(MessageHandler(
        filters.Regex(r'(?i)^anuncio\s.+'),
        handle_anuncio
    ))

    # 3. Ver pedido
    application.add_handler(MessageHandler(
        filters.Regex(r"(?i)^(ver\s+pedido|pedido)\s+\d+$"),
        ver_pedido
    ))
    
    # 4. Ayuda
    application.add_handler(MessageHandler(
        filters.Regex(r"(?i)^ayuda\s+.+"),
        ayuda_productos
    ))

    # 5. ConversationHandler (CREAR pedidos) - ¡Ahora está ANTES de forward_questions!
    application.add_handler(conv_handler)

    # 6. Handler para preguntas (solo si no coincide con nada más)
    application.add_handler(MessageHandler(
        filters.Chat(chat_id=MAIN_GROUP_ID) 
        & ~filters.COMMAND 
        & ~filters.Regex(r"(?i)^(pedido|p|ver|eliminar|ayuda|anuncio)"),  # <-- Excluye comandos
        forward_questions
    ))
    
    # 7. Comandos restantes (deudores, reiniciar, etc.)
    application.add_handler(CommandHandler("deudores", list_deudores))
    application.add_handler(CommandHandler("reiniciar", reset_db_command))
    application.add_handler(CommandHandler("cierrecaja", cierre_caja))
    application.add_handler(CommandHandler("todos", listar_pedidos))
    application.add_handler(CommandHandler("help", help_command))
    
    application.run_polling()