from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, JSON
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
    created_at = Column(DateTime, default=datetime.now)

# Configuración de la base de datos
engine = create_engine('sqlite:///chumazero.db')
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)

# Función para inicializar productos
def initialize_products():
    session = Session()
    for product in products_data:
        if not session.query(Product).filter_by(name=product["name"]).first():
            new_product = Product(name=product["name"], price=product["price"])
            session.add(new_product)
    session.commit()