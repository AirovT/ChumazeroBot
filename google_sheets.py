import gspread
from google.oauth2.service_account import Credentials
import os
import json

# Configuración
SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]
# CREDS_FILE = 'controlbotbar-creds.json'  # El archivo que descargaste habilitar para pruebas remotas %%%%%%%%%%%%%%%%%%%%%
SPREADSHEET_NAME = 'ControlBotBar'

# def initialize_sheets(): HABILITAR PREUBAS REMOTAS %%%%%%%%%%%%%%%%%%
#     """Inicializa la conexión y crea hojas si no existen"""
#     try:
#         # Autenticación
#         creds = Credentials.from_service_account_file(CREDS_FILE, scopes=SCOPES)
#         client = gspread.authorize(creds)

#         creds_json = os.environ.get('GOOGLE_CREDENTIALS')
        
#         # Abrir o crear hoja
#         try:
#             spreadsheet = client.open(SPREADSHEET_NAME)
#         except gspread.SpreadsheetNotFound:
#             spreadsheet = client.create(SPREADSHEET_NAME)
        
#         # Crear hojas requeridas
#         required_sheets = {
#             'EntradaDiaria': ['ID', 'Fecha', 'Hora', 'Producto', 'Cantidad', 'Total', 'Forma Pago', 'Descuento', 'Mesero','Cliente'],
#             'Ingresos': ['Tipo','Producto', 'Cantidad', 'Costo', 'Venta', 'Ganancia', 'P Ganancia'],
#             'Egresos': ['Tipo', 'Descripción', 'Costo', 'Pagado Por', 'Fecha', 'Hora','Estado']
#         }
        
#         # Verificar y crear hojas faltantes
#         existing_sheets = [sheet.title for sheet in spreadsheet.worksheets()]
        
#         for sheet_name, headers in required_sheets.items():
#             if sheet_name not in existing_sheets:
#                 new_sheet = spreadsheet.add_worksheet(title=sheet_name, rows=1000, cols=20)
#                 new_sheet.append_row(headers)
#                 print(f"✅ Hoja creada: {sheet_name}")
        
#         print("Google Sheets configurado correctamente")
#         return spreadsheet
        
#     except Exception as e:
#         print(f"Error en Google Sheets: {e}")
#         return None
    
# if __name__ == "__main__":

#     print("Probando conexión con Google Sheets...")
#     sh = initialize_sheets()

#     if sh:
#         print("✅ Conexión exitosa!")
#         print(f"URL de la hoja: https://docs.google.com/spreadsheets/d/{sh.id}")

import gspread
from google.oauth2.service_account import Credentials
import os
import json

# Configuración
SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]

SPREADSHEET_NAME = 'ControlBotBar'

def initialize_sheets():
    """Inicializa la conexión y crea hojas si no existen"""
    try:
        # Obtener credenciales de la variable de entorno
        creds_json = os.environ.get('GOOGLE_CREDENTIALS')
        if not creds_json:
            raise Exception("❌ Error: La variable GOOGLE_CREDENTIALS no está configurada")
        
        # Convertir el JSON string a diccionario
        creds_info = json.loads(creds_json)
        
        # CORRECCIÓN PRINCIPAL: Usar from_service_account_info() en lugar de from_service_account_file()
        creds = Credentials.from_service_account_info(creds_info, scopes=SCOPES)
        client = gspread.authorize(creds)
        
        # Abrir o crear hoja
        try:
            spreadsheet = client.open(SPREADSHEET_NAME)
        except gspread.SpreadsheetNotFound:
            spreadsheet = client.create(SPREADSHEET_NAME)
            # Compartir con el email del service account (opcional pero recomendado)
            spreadsheet.share(creds_info['client_email'], perm_type='user', role='writer')
        
        # Crear hojas requeridas
        required_sheets = {
            'EntradaDiaria': ['ID', 'Fecha', 'Hora', 'Producto', 'Cantidad', 'Total', 'Forma Pago', 'Descuento', 'Mesero','Cliente'],
            'Ingresos': ['Tipo','Producto', 'Cantidad', 'Costo', 'Venta', 'Ganancia', 'P Ganancia'],
            'Egresos': ['Tipo', 'Descripción', 'Costo', 'Pagado Por', 'Fecha', 'Hora','Estado']
        }
        
        # Verificar y crear hojas faltantes
        existing_sheets = [sheet.title for sheet in spreadsheet.worksheets()]
        
        for sheet_name, headers in required_sheets.items():
            if sheet_name not in existing_sheets:
                new_sheet = spreadsheet.add_worksheet(title=sheet_name, rows=1000, cols=20)
                new_sheet.append_row(headers)
                print(f"✅ Hoja creada: {sheet_name}")
        
        print("✅ Google Sheets configurado correctamente")
        return spreadsheet
        
    except Exception as e:
        print(f"❌ Error en Google Sheets: {e}")
        return None
    
if __name__ == "__main__":
    print("🔌 Probando conexión con Google Sheets...")
    sh = initialize_sheets()

    if sh:
        print("✅ Conexión exitosa!")
        print(f"📊 URL de la hoja: https://docs.google.com/spreadsheets/d/{sh.id}")