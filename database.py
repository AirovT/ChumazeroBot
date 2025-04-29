from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, JSON, Boolean
from typing import Dict
from sqlalchemy.orm import sessionmaker, declarative_base
from products import products_data  # Asegúrate de importar products_data
from datetime import datetime

Base = declarative_base()

# Definición de las tablas
class Product(Base):
    __tablename__ = 'products'
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True)
    price = Column(Float)


class Order(Base):
    __tablename__ = 'DEUDORES'
    id = Column(Integer, primary_key=True)
    custom_id = Column(Integer, unique=True)  # Nuevo campo para ID personalizado
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

class Discount(Base):
    __tablename__ = 'discounts'
    id = Column(Integer, primary_key=True)
    code = Column(String(20), unique=True)
    discount_type = Column(String(10))  # 'percent' o 'fixed'
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

# Función para inicializar productos
def initialize_products():
    session = Session()
    Base.metadata.create_all(bind=engine)  # Esto creará todas las tablas
    for product in products_data:
        if not session.query(Product).filter_by(name=product["name"]).first():
            new_product = Product(name=product["name"], price=product["price"],)
            session.add(new_product)
    session.commit()

# Al final del archivo database.py, añade:
if __name__ == "__main__":
    initialize_products()  # <-- Esto ejecutará la inicialización