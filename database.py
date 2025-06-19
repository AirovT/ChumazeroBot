from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, JSON, Boolean
from sqlalchemy.orm import sessionmaker, declarative_base
from datetime import datetime
import pandas as pd
import json

Base = declarative_base()

# Definición de las tablas (actualizada con nuevos campos)
class Product(Base):
    __tablename__ = 'products'
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True)
    price = Column(Float)
    tipo = Column(String)  
    nombre_completo = Column(String)  
    descripcion = Column(String)  
    ingredients = Column(JSON)
    servicio = Column(String)

class Order(Base):
    __tablename__ = 'Ordenes'
    id = Column(Integer, primary_key=True)
    custom_id = Column(Integer, unique=True)
    products = Column(JSON)
    total = Column(Float)
    status = Column(String, default="pendiente")
    fpago = Column(String, default="vacio")
    efectivo = Column(Float, default=0.0)
    transferencia = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.now)
    discount_code = Column(String, nullable=True)
    discount_amount = Column(Float, default=0.0)
    mesero = Column(String, default="no")
    synced_to_sheets = Column(Boolean, default=False)
    mesa = Column(Integer, nullable=True)  # Nuevo campo para el número de mesa

class Discount(Base):
    __tablename__ = 'discounts'
    id = Column(Integer, primary_key=True)
    code = Column(String(20), unique=True)
    discount_type = Column(String(10))
    value = Column(Float)
    valid_from = Column(DateTime)
    valid_to = Column(DateTime)
    max_uses = Column(Integer, default=1)
    current_uses = Column(Integer, default=0)
    created_by = Column(String(50))
    is_active = Column(Boolean, default=True)

# Configuración de la base de datos
engine = create_engine('sqlite:///chumazero.db')
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)

def excel_to_json_and_db(excel_path):
    # Leer el archivo Excel
    df = pd.read_excel(excel_path, engine='openpyxl')
    
    # Convertir decimales con coma a float
    df['price'] = df['price'].astype(str).str.replace(',', '.').astype(float)
    
    # Generar JSON
    json_data = df.to_json(orient='records', indent=4, force_ascii=False)
    with open('productos.json', 'w', encoding='utf-8') as f:
        f.write(json_data)
    
    return df.to_dict('records')

def initialize_products():
    session = Session()
    
    try:
        # Cargar datos desde Excel
        productos = excel_to_json_and_db('productosV2.xlsx')
        
        for producto in productos:
            # Verificar si ya existe
            if not session.query(Product).filter_by(name=producto['name']).first():
                new_product = Product(
                    name=producto['name'],
                    price=producto['price'],
                    tipo=producto.get('Tipo', ''),
                    nombre_completo=producto.get('Nombre completo', ''),
                    descripcion=producto.get('Descripcion', ''),
                    ingredients=producto.get("ingredientes", {}),
                    servicio = producto.get('Servicio','')
                )
                session.add(new_product)
        
        session.commit()
        print("✅ Base de datos actualizada exitosamente!")
        print(f"📦 Total productos insertados: {len(productos)}")
    
    except FileNotFoundError:
        print("❌ Error: Archivo Excel no encontrado")
    except KeyError as e:
        print(f"❌ Error: Columna faltante en el Excel - {str(e)}")
    except Exception as e:
        session.rollback()
        print(f"❌ Error inesperado: {str(e)}")
    finally:
        session.close()

if __name__ == "__main__":
    initialize_products()