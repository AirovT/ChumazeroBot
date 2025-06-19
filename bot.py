
from google_sheets import initialize_sheets
import gspread
from gspread import utils
import json
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes, CommandHandler, ConversationHandler
import os
from database import Session, Product, Order, initialize_products,Discount
from products import products_datas
import pytz
from datetime import datetime
import re
from fpdf import FPDF  # Necesitarás instalar esta librería: pip install fpdf
from sqlalchemy import func
from telegram.helpers import escape_markdown  # Añade este import al inicio
import pandas as pd  # Añade esto al inicio de tus imports
import requests  # Añade esto para obtener el clima
from typing import Dict  # Si no está presente
import asyncio
from gspread.utils import rowcol_to_a1  # Asegúrate de tener esta importación
from cachetools import TTLCache

# Cache de inventario (dura 30 segundos)
inventory_cache = TTLCache(maxsize=100, ttl=30)
PEDIDO_CONFIRM = 1

# Configuración
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
# Lee las credenciales desde Railway
# TOKEN = ""
TIMEZONE = pytz.timezone("America/Guayaquil")
# Configuración
PRODUCTION_CHAT_ID = -1002606763522  # ⬅️ Este es el ID correcto
GERENCIA_CHAT_ID =   -4775103529  # ⬅️ Este es el ID correcto
MAIN_GROUP_ID =      -1002366423301  # ⬅️ Este es el ID correcto
INVENTARIO = -4834916229
# ##################CLONES #####################
# PRODUCTION_CHAT_ID = -1002606763522  # ⬅️ Este es el ID correcto
# GERENCIA_CHAT_ID =   -4775103529  # ⬅️ Este es el ID correcto
# MAIN_GROUP_ID =      -4709557559  # ⬅️ Este es el ID correcto

import requests
from datetime import datetime

DESCUENTO_CODE, DESCUENTO_TYPE, DESCUENTO_VALUE, DESCUENTO_DATE, DESCUENTO_USES = range(5)

DESACTIVAR_CODE, CONFIRMAR_ELIMINAR = range(2)

################################################## GOOGLE SHEET #######################################
GSHEETS = initialize_sheets()
DIAS_ESPANOL = {
    'Monday': 'Lunes', 'Tuesday': 'Martes', 'Wednesday': 'Miércoles',
    'Thursday': 'Jueves', 'Friday': 'Viernes', 'Saturday': 'Sábado',
    'Sunday': 'Domingo'
}

MESES_ESPANOL = {
    1: 'Enero', 2: 'Febrero', 3: 'Marzo', 4: 'Abril', 5: 'Mayo', 6: 'Junio',
    7: 'Julio', 8: 'Agosto', 9: 'Septiembre', 10: 'Octubre', 11: 'Noviembre',
    12: 'Diciembre'
}

def normalize_name(name):
    return re.sub(r'\s+', ' ', name).strip().lower()

def get_cached_inventory():
    """Obtiene inventario desde caché o Google Sheets"""
    try:
        # Verificar si hay caché válido
        if 'inventory_data' in inventory_cache:
            return inventory_cache['inventory_data']
        
        # Leer desde Sheets si no hay caché
        inventory_sheet = GSHEETS.worksheet('Inventario')
        inventory_data = inventory_sheet.get_all_records()
        
        # Crear mapa para búsqueda rápida
        inventory_map = {}
        for i, record in enumerate(inventory_data, start=2):
            norm_name = normalize_name(record['Producto'])
            inventory_map[norm_name] = {
                'row': i,
                'stock': record['Stock'],
                'minimo': record['Mínimo'],
                'ultima_alerta': record.get('Ultima_alerta', '')
            }
        
        # Guardar en caché
        inventory_cache['inventory_data'] = (inventory_data, inventory_map)
        return inventory_data, inventory_map
        
    except Exception as e:
        print(f"❌ Error obteniendo inventario: {str(e)}")
        return [], {}

def register_batch_orders_to_sheets(orders, context=None):
    """Registra múltiples pedidos en Google Sheets evitando duplicados"""
    try:
        sheet = GSHEETS.worksheet('EntradaDiaria')
        existing_data = sheet.get_all_values()[1:]
        existing_combinations = set()
        
        for row in existing_data:
            if len(row) >= 3:
                custom_id = row[0]
                fecha = row[1]
                hora = row[2]
                existing_combinations.add(f"{custom_id}|{fecha}|{hora}")
        
        batch_data = []
        inventory_alerts = []
        # Primero: Recopilar todos los productos vendidos
        all_products = []

        for order in orders:
            # Paso 1: Determinar si es naive o aware
            if order.created_at.tzinfo is None:
                # CORRECCIÓN: Ya está en hora local, solo agregar zona horaria
                created_at = TIMEZONE.localize(order.created_at)
            else:
                # Convertir directamente a Guayaquil
                created_at = order.created_at.astimezone(TIMEZONE)
                    
            # Formatear para Sheets
            fecha_str = created_at.strftime('%d/%m/%Y')
            hora_str = created_at.strftime('%H:%M')
            dia_semana = DIAS_ESPANOL[created_at.strftime('%A')]
            semana_iso = created_at.isocalendar()[1]
            nombre_mes = MESES_ESPANOL[created_at.month]

            unique_id = f"{order.custom_id}|{fecha_str}|{hora_str}"
            
            if unique_id in existing_combinations:
                continue
                
            for producto in order.products:
                # Agregar datos a la hoja
                batch_data.append([
                    order.custom_id,
                    fecha_str,
                    hora_str,
                    producto['Tipo'],
                    producto['Nombre_completo'],
                    producto['cantidad'],
                    producto['precio_unitario'] * producto['cantidad'],
                    order.fpago,
                    order.discount_code or "N/A",
                    order.mesero,
                    order.mesa,
                    dia_semana,
                    semana_iso,
                    nombre_mes,
                    producto['Servicio'],
                ])
                
                # Acumular productos para procesamiento posterior
                all_products.append({
                    'name': producto['Nombre_completo'],
                    'quantity': producto['cantidad']
                })
        
        # Segundo: Actualizar inventario con todos los productos juntos
        if all_products:
            # Agrupar productos por nombre y sumar cantidades
            grouped_products = {}
            for product in all_products:
                name = product['name']
                if name in grouped_products:
                    grouped_products[name] += product['quantity']
                else:
                    grouped_products[name] = product['quantity']
            
            # Procesar cada grupo de productos
            if grouped_products:
                # Procesar TODOS los productos en una sola operación
                alert_data = update_inventory_batch(grouped_products)
                if alert_data:
                    inventory_alerts.extend(alert_data)
                    
        # if batch_data:
        #     sheet.append_rows(batch_data)
        #     print(f"✅ Batch: {len(batch_data)} registros insertados")
            if batch_data:
                # SOLUCIÓN CLAVE: Insertar como USER_ENTERED con formato numérico
                sheet.append_rows(batch_data, value_input_option='USER_ENTERED')
                print(f"✅ Batch: {len(batch_data)} registros insertados")

                # Forzar formato de fecha en la columna B
                sheet.format('B2:B', {
                    "numberFormat": {
                        "type": "DATE",
                        "pattern": "dd/MM/yyyy"  # Patrón local
                    }
                })
                
                # Forzar formato de hora en la columna C
                sheet.format('C2:C', {
                    "numberFormat": {
                        "type": "TIME",
                        "pattern": "HH:mm"  # Patrón de 24 horas
                    }
                })

            # Enviar alertas de inventario si hay contexto
            if context and inventory_alerts:
                print(f"📢 Enviando {len(inventory_alerts)} alertas de inventario")
                for alert in inventory_alerts:
                    asyncio.create_task(send_inventory_alert(context, alert))
        
        return True, inventory_alerts
        
    except Exception as e:
        print(f"❌ Error batch Sheets: {str(e)}")
        return False, []

def update_inventory_batch(grouped_products):
    """Actualiza inventario para múltiples productos en una sola operación"""
    try:
        session = Session()
        # 1. Obtener datos de inventario desde caché
        _, inventory_map = get_cached_inventory()
        
        alertas = []
        updates = []
        today = datetime.now(TIMEZONE).strftime('%d/%m/%Y')
        
        # 2. Procesar todos los productos
        for product_name, total_quantity in grouped_products.items():
            # Buscar producto en DB
            product = session.query(Product).filter(
                Product.nombre_completo == product_name
            ).first()
            
            if not product:
                print(f"⚠️ Producto no encontrado en DB: {product_name}")
                continue
            
            # Obtener ingredientes
            try:
                ingredients_dict = product.ingredients
                if isinstance(ingredients_dict, str):
                    ingredients_dict = json.loads(ingredients_dict)
            except (TypeError, json.JSONDecodeError) as e:
                print(f"Error procesando ingredientes: {product.ingredients} - {str(e)}")
                continue
            
            # 3. Procesar cada ingrediente
            for ingrediente, cantidad in ingredients_dict.items():
                norm_ingred = normalize_name(ingrediente)
                
                if norm_ingred not in inventory_map:
                    print(f"⏭️ Ingrediente no registrado: {ingrediente}. Se omite.")
                    continue
                    
                inv_data = inventory_map[norm_ingred]
                cantidad_usada = cantidad * total_quantity
                nuevo_stock = inv_data['stock'] - cantidad_usada
                
                # Preparar actualización
                updates.append({
                    'row': inv_data['row'],
                    'col': 2,  # Columna Stock
                    'value': nuevo_stock
                })
                
                # Verificar alerta
                if nuevo_stock < inv_data['minimo'] and inv_data['ultima_alerta'] != today:
                    updates.append({
                        'row': inv_data['row'],
                        'col': 4,  # Columna Ultima_alerta
                        'value': today
                    })
                    alertas.append({
                        'producto': ingrediente,
                        'nuevo_stock': nuevo_stock,
                        'min_required': inv_data['minimo']
                    })
        
        # 4. Aplicar actualizaciones en lote
        if updates:
            inventory_sheet = GSHEETS.worksheet('Inventario')
            batch_updates = []
            for update in updates:
                cell = rowcol_to_a1(update['row'], update['col'])
                batch_updates.append({
                    'range': cell,
                    'values': [[update['value']]]
                })
            inventory_sheet.batch_update(batch_updates)
            
            # Limpiar caché después de modificar
            inventory_cache.clear()
        
        return alertas
        
    except Exception as e:
        print(f"❌ Error en batch update: {str(e)}")
        import traceback
        traceback.print_exc()
        return []
    finally:
        session.close()

async def reponer_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Añade stock al inventario: /reponer Pilsener 10"""
    try:
        args = context.args
        if len(args) < 2:
            await update.message.reply_text("Formato: /reponer [producto] [cantidad]")
            return

        product_name = " ".join(args[:-1])
        cantidad = int(args[-1])
        
        inventory_sheet = GSHEETS.worksheet('Inventario')
        records = inventory_sheet.get_all_records()
        
        for i, record in enumerate(records, start=2):
            if record['Producto'].lower() == product_name.lower():
                current_stock = record['Stock']
                new_stock = current_stock + cantidad
                inventory_sheet.update_cell(i, 2, new_stock)
                
                await update.message.reply_text(
                    f"✅ Stockizado:\n"
                    f"{product_name}: {current_stock} → {new_stock}"
                )
                # LIMPIAR CACHÉ DESPUÉS DE ACTUALIZAR
                inventory_cache.clear()
                return
        
        await update.message.reply_text(f"❌ Producto no encontrado: {product_name}")
    
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def subirdt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sincroniza manualmente las cantidades en la hoja Ingresos"""
    session = Session()
    inventory_alerts = []  # Para almacenar alertas
    
    try:
        # 1. Obtener pedidos pagados no sincronizados
        pedidos_pagados = session.query(Order).filter(
            Order.status == "pagado",
            Order.synced_to_sheets == False
        ).all()

        if not pedidos_pagados:
            await update.message.reply_text("📭 No hay nuevos pedidos pagados para sincronizar")
            return

        # 2. Registrar en Sheets y actualizar inventario
        success, alerts = register_batch_orders_to_sheets(pedidos_pagados, context)
        inventory_alerts = alerts
        
        if not success:
            await update.message.reply_text("❌ Error al sincronizar con Google Sheets")
            return

        # 3. Actualizar estado de sincronización
        for order in pedidos_pagados:
            order.synced_to_sheets = True
            
        session.commit()
        
        # 4. Enviar confirmación
        msg = f"✅ Sincronizados {len(pedidos_pagados)} pedidos a 'Entrada Diaria en la nube'"
        if inventory_alerts:
            msg += f"\n\n⚠️ Se generaron {len(inventory_alerts)} alertas de inventario bajo"
        await update.message.reply_text(msg)
        
    except Exception as e:
        session.rollback()
        await update.message.reply_text(f"❌ Error al sincronizar: {str(e)}")
    finally:
        session.close()

def get_next_gasto_id():
    try:
        egresos_sheet = GSHEETS.worksheet('Egresos')
        last_row = len(egresos_sheet.col_values(1))  # Cuenta filas en columna ID
        
        if last_row <= 1:  # Solo encabezado
            return 1
            
        # Lee solo el último ID registrado
        last_id = egresos_sheet.cell(last_row, 1).value
        return int(last_id) + 1
        
    except Exception as e:
        print(f"Error: {e}")
        return 1

async def gasto_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Registra un gasto en la hoja Egresos con ID único"""
    try:
        # Si no hay argumentos, mostrar ayuda
        if not context.args:
            await update.message.reply_text(
                "❌ Formato incorrecto. Usa:\n"
                "/gasto [tipo] [descripción] [monto] [método]\n\n"
                "Ejemplo:\n"
                '/gasto Insumos "Papas y snacks" 25.50 contado\n'
                '/gasto Insumos "Compra de cerveza" 80 credito'
            )
            return
        
        # Unir todos los argumentos
        full_text = " ".join(context.args)
        
        # Buscar el monto y método al final usando regex
        import re
        match = re.search(r'(\d+\.?\d*)\s+(contado|credito)$', full_text, re.IGNORECASE)
        
        if not match:
            await update.message.reply_text(
                "❌ No se encontró monto y método. Usa:\n"
                "/gasto [tipo] [descripción] [monto] contado/credito\n\n"
                "Ejemplo:\n"
                '/gasto Insumos "Refrescos" 15.75 contado'
            )
            return
        
        # Extraer componentes
        monto = float(match.group(1))
        metodo = match.group(2).lower()
        texto_restante = full_text[:match.start()].strip()
        
        # Separar tipo y descripción
        parts = texto_restante.split(maxsplit=1)
        if len(parts) < 1:
            await update.message.reply_text("❌ Falta tipo de gasto. Ejemplo: /gasto Insumos ...")
            return
        elif len(parts) < 2:
            tipo = parts[0]
            descripcion = "Sin descripción"
        else:
            tipo = parts[0]
            descripcion = parts[1]
        
        # Validar método de pago
        if metodo not in ["contado", "credito"]:
            await update.message.reply_text("❌ Método inválido. Usa 'contado' o 'credito'")
            return
        
        # Obtener usuario
        user = update.message.from_user.username or update.message.from_user.first_name
        
        # Registrar en Google Sheets
        egresos_sheet = GSHEETS.worksheet('Egresos')
        
        # Obtener próximo ID
        gasto_id = get_next_gasto_id()
        
        # Obtener fecha y hora actual
        now = datetime.now(TIMEZONE)
        
        # Determinar estado según método de pago
        estado = "Pagado" if metodo == "contado" else "Pendiente"
        
        # Calcular campos temporales adicionales
        dia_semana = DIAS_ESPANOL[now.strftime('%A')]
        semana_iso = now.isocalendar()[1]  # Semana ISO
        mes = MESES_ESPANOL[now.month]

        # Crear fila con ID y estructura completa
        row = [
            gasto_id,               # ID único
            tipo,                   # Tipo
            descripcion,            # Descripción
            monto,                  # Costo
            user,                   # Pagado Por
            now.strftime('%d/%m/%Y'),  # Fecha
            now.strftime('%H:%M'),     # Hora
            estado,                 # Estado
            dia_semana,             # Día de la semana (NUEVO)
            semana_iso,             # Semana ISO (NUEVO)
            mes                   # Estado
        ]
        
        # Insertar con interpretación de formato
        egresos_sheet.append_row(row, value_input_option='USER_ENTERED')
        
        # Formatear columnas de fecha y hora después de insertar
        last_row = len(egresos_sheet.col_values(1))  # Obtener última fila insertada
        egresos_sheet.format(f'F{last_row}', {
            "numberFormat": {
                "type": "DATE",
                "pattern": "dd/MM/yyyy"
            }
        })
        egresos_sheet.format(f'G{last_row}', {
            "numberFormat": {
                "type": "TIME",
                "pattern": "HH:mm"
            }
        })
        
        await update.message.reply_text(
            f"✅ Gasto registrado (ID: {gasto_id}):\n"
            f"Tipo: {tipo}\n"
            f"Descripción: {descripcion}\n"
            f"Monto: ${monto:.2f}\n"
            f"Método: {metodo.capitalize()}\n"
            f"Estado: {estado}"
        )
        
    except ValueError:
        await update.message.reply_text("❌ El monto debe ser un número. Ejemplo: 25.50")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def pagar_gasto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Marca un gasto a crédito como pagado usando su ID"""
    try:
        # Validar argumentos
        if not context.args:
            await update.message.reply_text("❌ Debes especificar el ID del gasto. Ejemplo: /pagar_gasto 5")
            return
            
        gasto_id = context.args[0]
        
        # Buscar el gasto en Google Sheets
        egresos_sheet = GSHEETS.worksheet('Egresos')
        all_values = egresos_sheet.get_all_values()
        
        # Verificar si hay datos
        if len(all_values) < 2:
            await update.message.reply_text("❌ No hay gastos registrados")
            return
        
        # Encontrar índices de columnas
        headers = all_values[0]
        try:
            id_col_idx = headers.index("ID")
            estado_col_idx = headers.index("Estado")
        except ValueError:
            # Intentar encontrar columnas con nombres similares
            id_col_idx = next((i for i, h in enumerate(headers) if "id" in h.lower()), -1)
            estado_col_idx = next((i for i, h in enumerate(headers) if "estado" in h.lower()), -1)
            
            if id_col_idx == -1 or estado_col_idx == -1:
                await update.message.reply_text("❌ No se encontraron las columnas necesarias (ID y Estado)")
                return
        
        found = False
        for i in range(1, len(all_values)):
            row = all_values[i]
            if len(row) <= max(id_col_idx, estado_col_idx):
                continue
                
            # Comparar IDs
            current_id = str(row[id_col_idx]).strip()
            if current_id == gasto_id:
                estado = row[estado_col_idx] if len(row) > estado_col_idx else ""
                
                if estado == "Pendiente":
                    # Actualizar estado a "Pagado"
                    egresos_sheet.update_cell(i+1, estado_col_idx+1, "Pagado")
                    found = True
                    break
                else:
                    await update.message.reply_text(f"⚠️ El gasto {gasto_id} no está pendiente de pago (Estado actual: {estado})")
                    return
        
        if found:
            await update.message.reply_text(f"✅ Gasto {gasto_id} marcado como PAGADO")
        else:
            # Obtener todos los IDs para ayudar en la depuración
            existing_ids = [str(row[id_col_idx]).strip() for row in all_values[1:] if len(row) > id_col_idx]
            await update.message.reply_text(
                f"❌ No se encontró un gasto pendiente con ID {gasto_id}\n"
                f"IDs existentes: {', '.join(existing_ids)}"
            )
            
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()

def find_gasto_by_id(gasto_id):
    """Busca un gasto por ID y devuelve (hoja, fila_index, headers)"""
    try:
        egresos_sheet = GSHEETS.worksheet('Egresos')
        all_values = egresos_sheet.get_all_values()
        
        if len(all_values) < 2:
            return None, None, None
        
        headers = all_values[0]
        try:
            id_col_idx = headers.index("ID")
        except ValueError:
            id_col_idx = next((i for i, h in enumerate(headers) if "id" in h.lower()), -1)
            if id_col_idx == -1:
                return None, None, None
        
        for i in range(1, len(all_values)):
            row = all_values[i]
            if len(row) > id_col_idx and str(row[id_col_idx]).strip() == str(gasto_id):
                return egresos_sheet, i+1, headers  # i+1 porque en gspread las filas empiezan en 1
        
        return None, None, None
    except Exception as e:
        print(f"Error buscando gasto: {str(e)}")
        return None, None, None

async def editar_gasto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Edita un campo específico de un gasto"""
    try:
        if len(context.args) < 3:
            await update.message.reply_text(
                "❌ Formato incorrecto. Usa:\n"
                "/editar_gasto [ID] [campo] [nuevo_valor]\n\n"
                "Campos disponibles: tipo, descripción, monto, método\n\n"
                "Ejemplos:\n"
                '/editar_gasto 5 tipo Servicios\n'
                '/editar_gasto 5 monto 150.75\n'
                '/editar_gasto 5 método contado'
            )
            return
            
        gasto_id = context.args[0]
        campo = context.args[1].lower()
        nuevo_valor = " ".join(context.args[2:])
        
        sheet, row_index, headers = find_gasto_by_id(gasto_id)
        
        if not sheet or not row_index:
            await update.message.reply_text(f"❌ No se encontró un gasto con ID {gasto_id}")
            return
        
        # Mapeo de campos a columnas
        campo_map = {
            'tipo': ['tipo', 'categoría', 'categoria'],
            'descripción': ['descripción', 'descripcion', 'detalle', 'nota'],
            'monto': ['monto', 'cantidad', 'valor', 'costo'],
            'método': ['método', 'metodo', 'forma pago', 'pago']
        }
        
        # Encontrar índice de columna
        col_idx = None
        for key, aliases in campo_map.items():
            if campo in key or campo in aliases:
                # Buscar el nombre real en los headers
                for header in headers:
                    if header.lower() in aliases:
                        col_idx = headers.index(header) + 1  # Columna en gspread (1-indexed)
                        break
                if col_idx:
                    break
        
        if not col_idx:
            await update.message.reply_text(
                "❌ Campo inválido. Campos disponibles:\n"
                "- tipo\n- descripción\n- monto\n- método"
            )
            return
        
        # Validaciones específicas por campo
        if campo == 'monto':
            try:
                nuevo_valor = float(nuevo_valor)
            except ValueError:
                await update.message.reply_text("❌ El monto debe ser un número. Ejemplo: 25.50")
                return
        
        if campo == 'método' or campo == 'metodo':
            if nuevo_valor.lower() not in ["contado", "credito"]:
                await update.message.reply_text("❌ Método inválido. Usa 'contado' o 'credito'")
                return
            nuevo_valor = nuevo_valor.capitalize()
            
            # Si cambiamos método, actualizar estado automáticamente
            estado_idx = None
            try:
                estado_idx = headers.index("Estado") + 1
            except ValueError:
                pass
            
            if estado_idx:
                nuevo_estado = "Pagado" if nuevo_valor.lower() == "contado" else "Pendiente"
                sheet.update_cell(row_index, estado_idx, nuevo_estado)
        
        # Actualizar el campo
        sheet.update_cell(row_index, col_idx, nuevo_valor)
        
        await update.message.reply_text(
            f"✅ Gasto ID {gasto_id} actualizado:\n"
            f"Campo '{campo}' cambiado a: {nuevo_valor}"
        )
        
    except ValueError:
        await update.message.reply_text("❌ El monto debe ser un número. Ejemplo: 25.50")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

def update_inventory(product_name, quantity_sold):
    """Actualiza el inventario basado en ingredientes desde SQLite"""
    try:
        session = Session()
        # 1. Buscar el producto en la base de datos SQLite
        product = session.query(Product).filter(
            Product.nombre_completo == product_name
        ).first()
        
        if not product:
            print(f"⚠️ Producto no encontrado en DB: {product_name}")
            return None
        
        # 2. Obtener ingredientes desde la base de datos
        try:
            ingredients_dict = product.ingredients
            if isinstance(ingredients_dict, str):
                ingredients_dict = json.loads(ingredients_dict)
        except (TypeError, json.JSONDecodeError) as e:
            print(f"Error procesando ingredientes: {product.ingredients} - {str(e)}")
            return None
        
        # # 3. Obtener datos de inventario desde Google Sheets
        # inventory_sheet = GSHEETS.worksheet('Inventario')
        # inventory_data = inventory_sheet.get_all_records()

        inventory_data, inventory_map = get_cached_inventory()
        
        # Crear diccionario para búsqueda rápida
        inventory_map = {}
        for i, record in enumerate(inventory_data, start=2):
            norm_name = normalize_name(record['Producto'])
            inventory_map[norm_name] = {
                'row': i,
                'stock': record['Stock'],
                'minimo': record['Mínimo'],
                'ultima_alerta': record.get('Ultima_alerta', '')
            }
        
        alertas = []
        updates = []
        today = datetime.now(TIMEZONE).strftime('%d/%m/%Y')
        
        # 4. Procesar cada ingrediente
        for ingrediente, cantidad in ingredients_dict.items():
            norm_ingred = normalize_name(ingrediente)
            
            if norm_ingred not in inventory_map:
                print(f"⏭️ Ingrediente no registrado: {ingrediente}. Se omite.")
                continue
                
            inv_data = inventory_map[norm_ingred]
            cantidad_usada = cantidad * quantity_sold
            nuevo_stock = inv_data['stock'] - cantidad_usada
            
            # Preparar actualización de stock
            updates.append({
                'row': inv_data['row'],
                'col': 2,  # Columna Stock
                'value': nuevo_stock
            })
            
            # Verificar alerta (SOLO verificación, sin actualizar aún)
            if nuevo_stock < inv_data['minimo']:
                # Guardar alerta potencial
                alertas.append({
                    'ingrediente': ingrediente,
                    'nuevo_stock': nuevo_stock,
                    'min_required': inv_data['minimo'],
                    'needs_alert_update': (inv_data['ultima_alerta'] != today)
                })
        
        # 5. Procesar alertas después de todas las verificaciones
        final_alertas = []
        for alerta in alertas:
            if alerta['needs_alert_update']:
                # Buscar el ingrediente en el mapa para actualizar
                norm_ingred = normalize_name(alerta['ingrediente'])
                if norm_ingred in inventory_map:
                    inv_data = inventory_map[norm_ingred]
                    updates.append({
                        'row': inv_data['row'],
                        'col': 4,  # Columna Ultima_alerta
                        'value': today
                    })
                
                # Añadir a alertas finales
                final_alertas.append({
                    'producto': alerta['ingrediente'],
                    'nuevo_stock': alerta['nuevo_stock'],
                    'min_required': alerta['min_required']
                })
        
        # 6. Aplicar actualizaciones en lote
        if updates:
            inventory_sheet = GSHEETS.worksheet('Inventario')
            batch_updates = []
            for update in updates:
                cell = rowcol_to_a1(update['row'], update['col'])
                batch_updates.append({
                    'range': cell,
                    'values': [[update['value']]]
                })
            inventory_sheet.batch_update(batch_updates)

            # Actualizar caché después de modificar
            inventory_cache.clear()
        
        return final_alertas if final_alertas else None
        
    except Exception as e:
        print(f"❌ Error actualizando inventario: {str(e)}")
        import traceback
        traceback.print_exc()
        return None
    finally:
        session.close()

async def send_inventory_alert(context: ContextTypes.DEFAULT_TYPE, alert_data):
    """Envía alerta de inventario bajo a administradores"""
    try:
        # Asegurarnos que alert_data es un diccionario
        if not isinstance(alert_data, dict):
            print(f"⚠️ Formato inválido de alerta: {type(alert_data)}")
            return
            
        message = (
            f"⚠️ *ALERTA DE INVENTARIO BAJO* ⚠️\n\n"
            f"Producto: {alert_data['producto']}\n"
            f"Stock: {alert_data['nuevo_stock']}\n"
            f"Mínimo requerido: {alert_data['min_required']}\n\n"
            f"¡Es necesario reponer stock inmediatamente!"
        )
        
        try:
            await context.bot.send_message(
                chat_id=INVENTARIO,
                text=message,
                parse_mode='Markdown'
            )
            await asyncio.sleep(0.3)  # Pequeña pausa para evitar bloqueos
        except Exception as e:
            print(f"Error enviando alerta a admin {INVENTARIO}: {str(e)}")
    except Exception as e:
        print(f"❌ Error crítico en send_inventory_alert: {str(e)}")


################################### CODIGO ANTERIOR #########################################
def obtener_temperatura(fecha):
    try:
        latitud = -1.2491
        longitud = -78.6167
        fecha_str = fecha.strftime("%d/%m/%Y")
        
        url = f"https://api.open-meteo.com/v1/forecast?latitude={latitud}&longitude={longitud}&hourly=temperature_2m"
        response = requests.get(url)
        response.raise_for_status()  # Verificar errores HTTP
        data = response.json()
        
        # Verificar si hay datos
        if "hourly" not in data or "temperature_2m" not in data["hourly"]:
            return "N/A"
        
        temperaturas = data["hourly"]["temperature_2m"]
        
        # Filtrar valores None y calcular promedio
        temps_validas = [t for t in temperaturas if t is not None]
        
        if not temps_validas:
            return "N/A"
        
        return round(sum(temps_validas) / len(temps_validas), 1)
    
    except Exception as e:
        print(f"Error Open-Meteo: {str(e)}")
        return "N/A"

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
    if update.message.from_user.username in ["Bastian029", "IngAiro", "Karla181117","Dannytxx"]:
        reset_deudores()
        await update.message.reply_text("✅ Base de datos eliminada, buen incio de trabajo")
    else:
        await update.message.reply_text("❌ No tienes permisos para ejecutar este comando.")

def get_next_order_id():
    """Obtiene el próximo ID persistente (no se reinicia diariamente)"""
    session = Session()
    try:
        # Busca el máximo ID existente
        max_id = session.query(func.max(Order.custom_id)).scalar()
        return (max_id or 0) + 1
    finally:
        session.close()

# Función para procesar pedidos
def process_order(order_text, user, custom_id,discount_code=None,mesa=None):
    session = Session()
    try:
        lines = order_text.split("\n")
        items = [line.strip() for line in lines[1:] if line.strip()]
        
        if not items:
            return "❌ No hay productos en el pedido."
        
        # Obtener ID persistente
        custom_id = get_next_order_id()

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
                "Meser@": user,
                "Tipo":product.tipo,
                "Servicio":product.servicio,
                "Nombre_completo": product.nombre_completo,
                "Descripcion": product.descripcion
            })
            total += product.price * quantity
        
        # Si hay errores, no crear el pedido
        if errores:
            response = "❌ Errores en el ingreso del pedido:\n" + "\n".join(errores)
            return response
        
        discount_amount = 0.0

        if discount_code:
            session = Session()
            discount = session.query(Discount).filter(
                Discount.code == discount_code.upper(),
                Discount.valid_from <= datetime.now(TIMEZONE),
                Discount.valid_to >= datetime.now(TIMEZONE),
                Discount.is_active == True,
                (Discount.max_uses > Discount.current_uses) | (Discount.max_uses.is_(None))
            ).first()

            if discount:
                if discount.discount_type == 'percent':
                    discount_amount = total * (discount.value / 100)
                else:
                    discount_amount = discount.value
                
                total -= discount_amount
                discount.current_uses += 1
                session.commit()
            else:
                session.close()
                return f"❌ Código inválido o expirado: {discount_code}"
            
            session.close()
            
        # Crear pedido solo si no hay errores
        new_order = Order(
            custom_id=custom_id,
            products=products_list,
            total=total,
            status="pendiente",
            created_at=datetime.now(TIMEZONE),
            discount_code=discount_code,
            discount_amount=discount_amount,
            mesero = user,
            mesa = mesa
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
        response += f"📅 Fecha: {order.created_at.strftime('%d/%m/%Y %H:%M')}\n"
        response += f"💵 Total: ${order.total:.2f}\n"
        response += "------------------------\n"
    
    await update.message.reply_text(response)

# Comando para cierre de caja diario
async def cierre_caja(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = Session()
    now = datetime.now(TIMEZONE)

    # 1. Obtener pedidos pagados no sincronizados
    pedidos_pagados = session.query(Order).filter(
        Order.status == "pagado",
        Order.synced_to_sheets == False  # Nueva columna
    ).all()

    # 2. Verificar si hay pedidos para sincronizar
    if not pedidos_pagados:
        await update.message.reply_text("📭 No hay nuevos pedidos pagados para sincronizar")
        # ... (resto del código de reporte)
        return

    # 3. Registrar TODOS los pedidos en Sheets (BATCH)
    try:
        # Función optimizada para registro masivo
        await subirdt(update, context)
        
        # Actualizar estado de sincronización
        for order in pedidos_pagados:
            order.synced_to_sheets = True
        session.commit()
        
        print(f"✅ Sincronizados {len(pedidos_pagados)} pedidos a Google Sheets")
    except Exception as e:
        print(f"❌ Error sincronización Sheets: {str(e)}")
        await update.message.reply_text(f"⚠️ Error sincronizando Sheets: {str(e)}")


    # Obtener todos los pedidos pagados
    pedidos_pagados = session.query(Order).filter(Order.status == "pagado").all()

    if not pedidos_pagados:
        await update.message.reply_text("📭 No hay pedidos pagados para generar reporte")
        session.close()
        return

    # Comprobar pedidos pendientes
    pedidos_pendientes = session.query(Order).filter(Order.status == "pendiente").all()
    
    # Encontrar primer y último pedido
    primer_pedido = min(pedidos_pagados, key=lambda x: x.created_at)
    ultimo_pedido = max(pedidos_pagados, key=lambda x: x.created_at)
    
    # Obtener fecha de referencia (del primer pedido)
    fecha_referencia = primer_pedido.created_at.date()

    # Generar PDF
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    
    respuesta = "📊 **CIERRE DE CAJA**\n\n"
    pdf.cell(200, 10, txt="CIERRE DE CAJA", ln=1, align='C')
    temperaturas_cache = {}  # Inicializar el caché de temperaturas aquí

    
    if pedidos_pendientes:
        respuesta += "⚠️ ¡Atención! Pedidos pendientes:\n"
        pdf.cell(200, 10, txt="¡ATENCIÓN! Hay pedidos pendientes:", ln=1)
        for pedido in pedidos_pendientes:
            respuesta += f"- Pedido {pedido.custom_id} (${pedido.total:.2f})\n"
            pdf.cell(200, 10, txt=f"Pedido {pedido.custom_id} - ${pedido.total:.2f}", ln=1)
    else:
        # Calcular totales
        total_ventas = sum(p.total for p in pedidos_pagados)
        total_efectivo = sum(p.efectivo for p in pedidos_pagados)
        total_transferencia = sum(p.transferencia for p in pedidos_pagados)
        total_pedidos = len(pedidos_pagados)

        # Texto y PDF
        hora_inicio = primer_pedido.created_at.strftime('%d/%m/%Y %H:%M')
        hora_fin = ultimo_pedido.created_at.strftime('%d/%m/%Y %H:%M')
        respuesta += f"🕒 Período: {hora_inicio} - {hora_fin}\n"
        respuesta += f"💰 Total: ${total_ventas:.2f}\n"
        respuesta += f"💵 Efectivo: ${total_efectivo:.2f}\n"
        respuesta += f"📲 Transferencia: ${total_transferencia:.2f}\n"
        respuesta += f"🍺 Total de pedidos: {total_pedidos}\n"
        respuesta += "🍺 Productos vendidos:\n"

        # PDF
        pdf.cell(200, 10, txt=f"Periodo: {hora_inicio} a {hora_fin}", ln=1)
        pdf.cell(200, 10, txt=f"Total: ${total_ventas:.2f}", ln=1)
        pdf.cell(200, 10, txt=f"Efectivo: ${total_efectivo:.2f}", ln=1)
        pdf.cell(200, 10, txt=f"Transferencia: ${total_transferencia:.2f}", ln=1)
        pdf.cell(200, 10, txt="Productos vendidos:", ln=1)

        #Excel data
        excel_data = []
        for pedido in pedidos_pagados:
            # Obtener detalles de fecha/hora
            fecha_completa = pedido.created_at
            fecha = fecha_completa.strftime('%d/%m/%Y')  # Fecha separada
            hora = fecha_completa.strftime('%H:%M')      # Hora separada
            dia_semana = fecha_completa.strftime('%A')   # Día en inglés (ej: Monday)
            
            # Obtener temperatura (solo una vez por fecha para optimizar)
            if fecha not in temperaturas_cache:
                temperaturas_cache[fecha] = obtener_temperatura(fecha_completa)
            temp = temperaturas_cache[fecha]

            if pedido.efectivo > 0 and pedido.transferencia == 0:
                forma_pago= "efectivo"
            elif pedido.transferencia > 0 and  pedido.efectivo == 0:
                forma_pago= "Trasnferencia"
            elif pedido.transferencia > 0 and  pedido.efectivo > 0:
                forma_pago= "Ambos"
            for producto in pedido.products:
                excel_data.append({
                    "Pedido ID": pedido.custom_id,
                    "Fecha": fecha,          # Ej: 01/07/2023
                    "Hora": hora,           # Ej: 14:30
                    "Día Semana": dia_semana,
                    "Temperatura (°C)": temp,
                    "Total": pedido.total,
                    "Efectivo": pedido.efectivo,
                    "Transferencia": pedido.transferencia,
                    "Forma de pago":forma_pago,
                    "Producto": producto["Descripcion"],
                    "Cantidad": producto["cantidad"],
                    "Código Descuento": pedido.discount_code,
                    "Monto Descuento": pedido.discount_amount,
                })
        # Crear DataFrame y guardar como Excel

        # Crear DataFrame
        df = pd.DataFrame(excel_data)
        nombre_excel = f"detalle_pedidos_{now.strftime('%Y%m%d_%H%M')}.xlsx"
        # Traducir días al español (opcional)
        dias_ingles_espanol = {
            "Monday": "Lunes",
            "Tuesday": "Martes",
            "Wednesday": "Miércoles",
            "Thursday": "Jueves",
            "Friday": "Viernes",
            "Saturday": "Sábado",
            "Sunday": "Domingo",

        }
        df["Día Semana"] = df["Día Semana"].map(dias_ingles_espanol)

        # Guardar Excel
        df.to_excel(nombre_excel, index=False)
        
        # Detalle productos ordenados
        productos_vendidos = {}
        for pedido in pedidos_pagados:
            for producto in pedido.products:
                nombre = producto["Nombre_completo"]
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
    try:
        # Enviar Respuesatas de pdf y Excel solo si hay pedidos pagados
        if not pedidos_pendientes and pedidos_pagados:
            # Enviar mensaje principal
            await context.bot.send_message(
                chat_id=GERENCIA_CHAT_ID,
                text=f"📊 **CIERRE DE CAJA**\n\n{respuesta}",
                parse_mode='Markdown'
            )
            
            # Enviar PDF
            with open(nombre_pdf, 'rb') as pdf_file:
                await context.bot.send_document(
                    chat_id=GERENCIA_CHAT_ID,
                    document=pdf_file,
                    filename=nombre_pdf
                )
            
            # Enviar Excel solo si hay pedidos pagados
            if not pedidos_pendientes and pedidos_pagados:
                with open(nombre_excel, 'rb') as excel_file:
                    await context.bot.send_document(
                        chat_id=GERENCIA_CHAT_ID,
                        document=excel_file,
                        filename=nombre_excel
                    )
    except Exception as e:
        print(f"Error al enviar mensaje: {e}")  # Para depurar
        raise  # Opcional: re-lanza el error si quieres ver el traceback completo
    session.close()

#Ver cuanto se vendio hasta ese momento y enviar como mensaje directo
async def info_venta(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = Session()
    respuesta = "📊 **Información de venta**\n\n"

    try:
        # 1. Verificar pedidos pendientes primero
        pedidos_pendientes = session.query(Order).filter(Order.status == "pendiente").all()
        
        if pedidos_pendientes:
            respuesta += "⚠️ ¡Atención! Pedidos pendientes:\n"
            for pedido in pedidos_pendientes:
                respuesta += f"- Pedido {pedido.custom_id} (${pedido.total:.2f})\n"
            # Mensaje adicional de alerta
            await update.message.reply_text("Hay pedidos pendientes. Revisa los detalles en el reporte.")
        else:
            pedidos_pagados = session.query(Order).filter(Order.status == "pagado").all()

            if not pedidos_pagados:
                respuesta += "ℹ️ No hay pedidos pagados hoy."
            else:
                # 3. Calcular tiempos
                primer_pedido = min(pedidos_pagados, key=lambda x: x.created_at)
                ultimo_pedido = max(pedidos_pagados, key=lambda x: x.created_at)
                
                hora_inicio = primer_pedido.created_at.strftime('%d/%m/%Y %H:%M')
                hora_fin = ultimo_pedido.created_at.strftime('%d/%m/%Y %H:%M')

                # 4. Calcular totales
                total_ventas = sum(p.total for p in pedidos_pagados)
                total_efectivo = sum(p.efectivo for p in pedidos_pagados)
                total_transferencia = sum(p.transferencia for p in pedidos_pagados)
                total_pedidos = len(pedidos_pagados)

                # 5. Construir respuesta
                respuesta += f"🕒 Período: {hora_inicio} - {hora_fin}\n"
                respuesta += f"💰 Total: ${total_ventas:.2f}\n"
                respuesta += f"💵 Efectivo: ${total_efectivo:.2f}\n"
                respuesta += f"📲 Transferencia: ${total_transferencia:.2f}\n"
                respuesta += f"🍺 Total de pedidos: {total_pedidos}\n"
        
        # 7. Opcional: Enviar copia a gerencia
        if 'GERENCIA_CHAT_ID' in globals():
            await context.bot.send_message(
                chat_id=GERENCIA_CHAT_ID,
                text=f"Información de venta:\n{respuesta}"
            )

    except Exception as e:
        await update.message.reply_text(f"❌ Error generando el reporte: {str(e)}")
        print(f"Error en info_venta: {e}")  # Log para depuración
    finally:
        session.close()

async def get_chat_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await update.message.reply_text(f"El chat ID es: {chat_id}")

async def handle_pedido(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    # Dividir el texto en líneas
    user = update.message.from_user.username
    
    # Dividir en líneas
    lines = text.split('\n')
    first_line = lines[0].strip() if lines else ""
    
    try:
        # Regex mejorado para capturar código de descuento
        # match = re.match(r"(?i)^(pedido|p)\s*(\d+)(?:\s+([a-zA-Z0-9]+))?", first_line)
        # Regex nuevo para prueba con inclusion de mesa
        match = re.match(r"(?i)^(pedido|p)\s*(\d+)(?:\s+m\s*(\d+))?(?:\s+([a-zA-Z0-9]+))?", first_line)

        if not match:
            await update.message.reply_text("❌ Formato incorrecto. Ejemplo:\nP1 m 4 CLIENTE10\n2 Michelada Club")
            return ConversationHandler.END
        
        custom_id = int(match.group(2))
        mesa = int(match.group(3)) if match.group(3) else None  # Extraer mesa
        # discount_code = match.group(3).upper() if match.group(3) else None  # Inicialización correcta
        discount_code = match.group(4).upper() if match.group(4) else None  # Descuento

        # Si el mensaje es "Pedido X pagado" o "PX pagado", ignóralo
        if re.search(r"(?i)(pedido|p)\s*\d+\s+pagado", text):
            return ConversationHandler.END
        
        # Extraer el ID (ej: "P1" → 1, "Pedido 2" → 2)
        custom_id = int(match.group(2))  # El grupo 2 captura el número
        context.user_data['pending_order'] = {
            'text': text,
            'custom_id': custom_id,
            'mesa': mesa,
            'discount_code': discount_code
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
            response = process_order(text, update.message.from_user.username, custom_id, discount_code, mesa)
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
            was_paid = False

            if existing_order and existing_order.status == "pagado":
                was_paid = True
                # ENVIAR NOTIFICACIÓN DE CANCELACIÓN
                try:
                    msg_cancel = (
                        f"🚨 **PEDIDO CANCELADO**\n\n"
                        f"🆔 Pedido {custom_id} ha sido modificado\n"
                        f"❌ Por favor ignoren el anterior"
                    )
                    await context.bot.send_message(
                        chat_id=PRODUCTION_CHAT_ID,
                        text=msg_cancel,
                        parse_mode='Markdown'
                    )
                except Exception as e:
                    print(f"Error al notificar cancelación: {str(e)}")
            # Procesar nuevo pedido
            response = process_order(pending_data['text'], update.message.from_user.username, custom_id)
            
            # ENVIAR NUEVO PEDIDO SI ES PAGADO
            if was_paid:
                try:
                    new_order = session.query(Order).filter(Order.custom_id == custom_id).first()
                    if new_order:
                        msg_produccion = f"🚨 **PEDIDO ACTUALIZADO**\n\n"
                        msg_produccion += f"🆔 Pedido: {custom_id}\n"
                        for producto in new_order.products:
                            msg_produccion += f"  {producto['cantidad']} x {producto['Descripcion']}\n"
                        
                        await context.bot.send_message(
                            chat_id=PRODUCTION_CHAT_ID,
                            text=msg_produccion
                        )
                except Exception as e:
                    print(f"Error al enviar actualización: {str(e)}")
            
            await update.message.reply_text(f"✅ Pedido {custom_id} actualizado!\n{response}")
            # if existing_order:
            #     session.delete(existing_order)
            #     session.commit()
            
            # response = process_order(pending_data['text'], update.message.from_user.username, custom_id)
            # await update.message.reply_text(f"✅ Pedido {custom_id} actualizado!\n{response}")
        
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
        respuesta += f"👨🏻‍💼 Atendido por: {(pedido.mesero or 'SIN ASIGNAR').upper()}\n"
        if pedido.mesa:
            respuesta += f"🪑 Mesa: {pedido.mesa}\n"
        respuesta += f"👉 Descuento de: {(pedido.discount_code or 'SIN DESCUENTO').upper()}\n"
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
    if update.message.from_user.username not in ["Bastian029", "IngAiro", "Karla181117","Dannytxx"]:
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
            try:
                msg_produccion = (
                    f"🚨 **PEDIDO ELIMINADO**\n\n"
                    f"🆔 Pedido {pedido_id} ha sido eliminado\n"
                    f"❌ Por favor no lo preparen"
                )
                await context.bot.send_message(
                    chat_id=PRODUCTION_CHAT_ID,
                    text=msg_produccion,
                    parse_mode='Markdown'
                )
            except Exception as e:
                print(f"Error al notificar producción: {str(e)}")

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
            metodo_pago = 'Efectivo'
            monto = order.total  # Si no se especifica monto, pagar total
            order.efectivo = monto
            order.transferencia = 0.0

        elif metodo == 't':
            metodo_pago = 'Transferencia'
            monto = order.total  # Transferencias siempre son por el total
            order.transferencia = monto
            order.efectivo = 0.0
        elif metodo == 'p':
            metodo_pago = 'Parcial'
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

            if order.status == "pagado":
                # Determinar forma de pago
                if metodo == 'e':
                    forma_pago = "Efectivo"
                elif metodo == 't':
                    forma_pago = "Transferencia"
                else:  # parcial
                    forma_pago = "Parcial"
            
            # Construir mensaje para producción
            msg_produccion = f"🚨 **NUEVO PEDIDO PAGADO ({metodo_pago.upper()})**\n"
            msg_produccion += f"🆔 Pedido: {order_id}\n"
            if order.mesa:  # Mostrar mesa si existe
                msg_produccion += f"🪑 Mesa: {order.mesa}\n"
            msg_produccion += "🍺 Productos:\n"


            
            for producto in order.products:
                msg_produccion += f"\t\t\t\t\t\t {producto['cantidad']} x {producto['Descripcion']}\n"
            
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
            text=f"📢📢 Anuncio del grupo principal 📢📢:\n\n{pregunta}"
        )

#permisos para crear descuentos
async def nuevo_descuento(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user.username
    if user not in ["IngAiro"]:
        await update.message.reply_text("❌ Solo administradores pueden crear descuentos")
        return ConversationHandler.END
    
    await update.message.reply_text(
        "🛠 Creando nuevo descuento:\n\n"
        "1. Ingresa el código del descuento (ej: VERANO20):"
    )
    return DESCUENTO_CODE

async def recibir_codigo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text.upper()
    session = Session()
    
    # Verificar si el código ya existe
    exists = session.query(Discount).filter(Discount.code == code).first()
    session.close()
    
    if exists:
        await update.message.reply_text("❌ Este código ya existe. Ingresa otro:")
        return DESCUENTO_CODE
    
    context.user_data['nuevo_descuento'] = {'code': code}
    
    await update.message.reply_text(
        "2. Selecciona el tipo de descuento:\n\n"
        "🅿️ Porcentaje (ej: 10%)\n"
        "🔢 Monto fijo (ej: $5)\n\n"
        "Responde con 'p' o 'f':"
    )
    return DESCUENTO_TYPE

async def recibir_tipo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tipo = update.message.text.lower()
    if tipo not in ['p', 'f']:
        await update.message.reply_text("❌ Opción inválida. Usa 'p' o 'f':")
        return DESCUENTO_TYPE
    
    context.user_data['nuevo_descuento']['type'] = 'percent' if tipo == 'p' else 'fixed'
    
    await update.message.reply_text(
        "3. Ingresa el valor del descuento:\n\n"
        "Ejemplos:\n"
        "Para 10% → 10\n"
        "Para $5 → 5"
    )
    return DESCUENTO_VALUE

async def recibir_valor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        value = float(update.message.text)
        discount_type = context.user_data['nuevo_descuento']['type']
        
        if discount_type == 'percent' and (value <= 0 or value > 100):
            raise ValueError("El porcentaje debe ser entre 0 y 100")
            
        context.user_data['nuevo_descuento']['value'] = value
        
        await update.message.reply_text(
            "4. Ingresa la fecha de caducidad (DD/MM/AAAA HH:MM):\n\n"
            "Ejemplo: 31/12/2024 23:59"
        )
        return DESCUENTO_DATE
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}. Ingresa un valor válido:")
        return DESCUENTO_VALUE

async def recibir_fecha(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        fecha_str = update.message.text
        fecha = datetime.strptime(fecha_str, "%d/%m/%Y %H:%M").astimezone(TIMEZONE)
        
        if fecha < datetime.now(TIMEZONE):
            raise ValueError("La fecha debe ser futura")
            
        context.user_data['nuevo_descuento']['valid_to'] = fecha
        
        await update.message.reply_text(
            "5. Ingresa el máximo de usos (o 0 para ilimitados):"
        )
        return DESCUENTO_USES
    except Exception as e:
        await update.message.reply_text(f"❌ Formato incorrecto: {str(e)}. Intenta nuevamente:")
        return DESCUENTO_DATE

async def recibir_usos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        max_uses = int(update.message.text)
        if max_uses < 0:
            raise ValueError
        
        # Crear el descuento
        data = context.user_data['nuevo_descuento']
        session = Session()
        
        new_discount = Discount(
            code=data['code'],
            discount_type=data['type'],
            value=data['value'],
            valid_from=datetime.now(TIMEZONE),
            valid_to=data['valid_to'],
            max_uses=max_uses if max_uses > 0 else None,
            created_by=update.message.from_user.username
        )
        
        session.add(new_discount)
        session.commit()
        
        await update.message.reply_text(
            f"✅ Descuento creado!\n\n"
            f"Código: {data['code']}\n"
            f"Tipo: {data['type']}\n"
            f"Valor: {data['value']}\n"
            f"Válido hasta: {data['valid_to'].strftime('%d/%m/%Y %H:%M')}\n"
            f"Usos máximos: {max_uses if max_uses > 0 else 'Ilimitado'}"
        )
        
        return ConversationHandler.END
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}. Ingresa un número válido:")
        return DESCUENTO_USES

# --- HANDLER DE CANCELACIÓN ---
async def cancelar_operacion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'nuevo_descuento' in context.user_data:
        del context.user_data['nuevo_descuento']
        
    await update.message.reply_text("❌ Operación cancelada")
    return ConversationHandler.END

# --- MODIFICACIÓN DEL CONVERSATION HANDLER ---
conv_handler_descuentos = ConversationHandler(
    entry_points=[CommandHandler('nuevo_descuento', nuevo_descuento)],
    states={
        DESCUENTO_CODE: [
            MessageHandler(filters.Regex(r'^/cancelar$'), cancelar_operacion),
            MessageHandler(filters.TEXT, recibir_codigo)
        ],
        DESCUENTO_TYPE: [
            MessageHandler(filters.Regex(r'^/cancelar$'), cancelar_operacion),
            MessageHandler(filters.TEXT, recibir_tipo)
        ],
        DESCUENTO_VALUE: [
            MessageHandler(filters.Regex(r'^/cancelar$'), cancelar_operacion),
            MessageHandler(filters.TEXT, recibir_valor)
        ],
        DESCUENTO_DATE: [
            MessageHandler(filters.Regex(r'^/cancelar$'), cancelar_operacion),
            MessageHandler(filters.TEXT, recibir_fecha)
        ],
        DESCUENTO_USES: [
            MessageHandler(filters.Regex(r'^/cancelar$'), cancelar_operacion),
            MessageHandler(filters.TEXT, recibir_usos)
        ],
    },
    fallbacks=[
        CommandHandler('cancelar', cancelar_operacion),
        MessageHandler(filters.Regex(r'^/cancelar$'), cancelar_operacion)
    ],
    conversation_timeout=300
)

# 1. Handler para desactivar descuentos
async def desactivar_descuento(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user.username
    if user not in ["IngAiro"]:
        await update.message.reply_text("❌ Solo administradores pueden gestionar descuentos")
        return ConversationHandler.END
    
    await update.message.reply_text(
        "🔒 Ingresa el código del descuento a desactivar/eliminar:"
    )
    return DESACTIVAR_CODE

async def manejar_codigo_descuento(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text.upper()
    session = Session()
    
    discount = session.query(Discount).filter(Discount.code == code).first()
    
    if not discount:
        session.close()
        await update.message.reply_text("❌ Código no encontrado")
        return ConversationHandler.END
    
    context.user_data['discount_action'] = {
        'code': code,
        'discount_id': discount.id
    }
    
    # Mostrar detalles del descuento
    respuesta = (
        f"🔎 Descuento encontrado:\n\n"
        f"Código: {discount.code}\n"
        f"Tipo: {discount.discount_type}\n"
        f"Valor: {discount.value}\n"
        f"Usos: {discount.current_uses}/{discount.max_uses if discount.max_uses else '∞'}\n"
        f"Estado: {'🟢 Activo' if discount.is_active else '🔴 Inactivo'}\n\n"
        "Elige una acción:\n"
        "1. Desactivar/Reactivar\n"
        "2. Eliminar permanentemente\n"
        "3. Cancelar"
    )
    
    session.close()
    
    await update.message.reply_text(respuesta)
    return CONFIRMAR_ELIMINAR

async def confirmar_accion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    choice = update.message.text
    data = context.user_data.get('discount_action')
    
    if not data or 'code' not in data:
        await update.message.reply_text("❌ Error en los datos")
        return ConversationHandler.END
    
    session = Session()
    discount = session.query(Discount).get(data['discount_id'])
    
    try:
        if choice == '1':  # Toggle activo/inactivo
            discount.is_active = not discount.is_active
            session.commit()
            estado = "activado" if discount.is_active else "desactivado"
            await update.message.reply_text(f"✅ Descuento {data['code']} {estado} correctamente")
            
        elif choice == '2':  # Eliminar
            session.delete(discount)
            session.commit()
            await update.message.reply_text(f"🗑️ Descuento {data['code']} eliminado permanentemente")
            
        elif choice == '3':  # Cancelar
            await update.message.reply_text("❌ Operación cancelada")
            
        else:
            await update.message.reply_text("❌ Opción inválida")
            
    except Exception as e:
        session.rollback()
        await update.message.reply_text(f"🚨 Error: {str(e)}")
        
    finally:
        session.close()
        if 'discount_action' in context.user_data:
            del context.user_data['discount_action']
        
    return ConversationHandler.END

# 2. Añade este ConversationHandler
conv_handler_gestion_descuentos = ConversationHandler(
    entry_points=[CommandHandler('gestionar_descuento', desactivar_descuento)],
    states={
        DESACTIVAR_CODE: [MessageHandler(filters.TEXT, manejar_codigo_descuento)],
        CONFIRMAR_ELIMINAR: [MessageHandler(filters.TEXT, confirmar_accion)]
    },
    fallbacks=[],
    conversation_timeout=120
)

async def listar_descuentos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = Session()
    try:
        discounts = session.query(Discount).order_by(Discount.valid_to.desc()).all()
        
        if not discounts:
            await update.message.reply_text("🎫 No hay descuentos registrados")
            return
            
        respuesta = "🎟️ **LISTADO DE DESCUENTOS**\n\n"
        for d in discounts:
            estado = "🟢 ACTIVO" if d.is_active else "🔴 INACTIVO"
            respuesta += (
                f"🔖 Código: {d.code}\n"
                f"📌 Tipo: {d.discount_type} ({d.value}%{'$' if d.discount_type == 'fixed' else ''})\n"
                f"📅 Validez: {d.valid_from.strftime('%d/%m/%y')} - {d.valid_to.strftime('%d/%m/%y %H:%M')}\n"
                f"👨💻 Creado por: @{d.created_by}\n"
                f"🚀 Usos: {d.current_uses}/{d.max_uses if d.max_uses else '∞'} | Estado: {estado}\n"
                "⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯\n"
            )
        
        await update.message.reply_text(respuesta)
        
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")
    finally:
        session.close()


#comando help
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ayuda_texto = """
🆘 **MANUAL DE USO DEL BOT** 🆘

📌 **COMANDOS PRINCIPALES**:
▫️ `/help` - Muestra este mensaje de ayuda
▫️ `/deudores` - Lista pedidos pendientes de pago
▫️ `/reiniciar` - Borra todos los pedidos pendientes (solo admin)
▫️ `/cierrecaja` - Genera reporte diario con PDF y Excel
▫️ `/todos` - Lista completa de pedidos con PDF
▫️ `/infoventa` - Se puede ver la venta hasta ese momento y cantidad de pedidos
🔒 **GESTIÓN DE DESCUENTOS (Admin)**:
▫️ `/gestionar_descuento` - Desactivar o eliminar un descuento @IngAiro
▫️ `/nuevo_descuento` - Crea un codigo de descuento solo lo puede hacer @IngAiro
▫️ `/descuentos` - Muestra lista de descuentos
▫️ `/subirdt` - Sincronizar datos con google sheet
▫️ `/gasto` - Registrar gasto
▫️ `/pagar_gasto` - Comando para pagar gasto
▫️ `/editar_gasto` - Editar el gasto
▫️ `/reponer` - Reponer el stock

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

    application.add_handler(conv_handler_descuentos)
    application.add_handler(conv_handler_gestion_descuentos)

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
    application.add_handler(CommandHandler("infoventa", info_venta))
    application.add_handler(CommandHandler("todos", listar_pedidos))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("descuentos", listar_descuentos))
    application.add_handler(CommandHandler("subirdt", subirdt))
    application.add_handler(CommandHandler("gasto", gasto_command))
    application.add_handler(CommandHandler("pagar_gasto", pagar_gasto))
    application.add_handler(CommandHandler("editar_gasto", editar_gasto))
    application.add_handler(CommandHandler("reponer", reponer_stock))
        # ===== CONFIGURACIÓN WEBHOOK PARA RAILWAY =====
    PORT = int(os.environ.get("PORT", 8443))
    DOMAIN = "chumazerobot-production.up.railway.app"  # Reemplaza con tu dominio real de Railway
    
    # Configuración webhook
    application.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        webhook_url=f"https://{DOMAIN}/{TOKEN}",
        url_path=TOKEN,
        drop_pending_updates=True
    )