from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, JSON
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime

Base = declarative_base()

# Tabla de Productos (predefinidos)
class Product(Base):
    __tablename__ = 'products'
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True)
    price = Column(Float)

# Tabla de Pedidos
class Order(Base):
    __tablename__ = 'orders'
    id = Column(Integer, primary_key=True)
    products = Column(JSON)  # Ej: [{"name": "Michelada Club", "quantity": 2}]
    total = Column(Float)
    status = Column(String, default="pendiente")  # "pendiente" o "pagado"
    created_at = Column(DateTime, default=datetime.now)

# Inicializar la base de datos
engine = create_engine('sqlite:///chumazero.db')
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)