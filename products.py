import pandas as pd
import json

# Definir la ruta del archivo de Excel
ruta_excel = r"C:\Users\dstc2\Downloads\Precios.xlsx"

# Leer el archivo de Excel
df = pd.read_excel(ruta_excel)

# Convertir el DataFrame a una lista de diccionarios
products_data = df.to_dict(orient="records")

# Guardar la lista en un archivo JSON
with open("products.json", "w", encoding="utf-8") as json_file:
    json.dump(products_data, json_file, indent=4, ensure_ascii=False)

print("Archivo JSON generado exitosamente.")