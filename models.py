from sqlalchemy import create_engine, Column, String, Float, DateTime, Integer, Boolean, JSON, ForeignKey, Enum as SQLEnum
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
import uuid

Base = declarative_base()

def generate_uuid():
    return str(uuid.uuid4())

class Tenant(Base):
    __tablename__ = "tenants"
    
    id = Column(String, primary_key=True, default=generate_uuid)
    email = Column(String, unique=True, index=True)
    api_key_hash = Column(String, unique=True, index=True)  # SHA-256 hash
    plan = Column(SQLEnum(PlanTier), default=PlanTier.FREE)
    is_active = Column(Boolean, default=True)
    trading_mode = Column(SQLEnum(TradingMode), default=TradingMode.PAPER)
    stripe_customer_id = Column(String, nullable=True)
    stripe_subscription_id = Column(String, nullable=True)
    config = Column(JSON, default=dict)  # Config extra por tenant
    created_at = Column(DateTime, default=datetime.utcnow)
    last_billing_date = Column(DateTime, nullable=True)
    
    # Relaciones
    trades = relationship("Trade", back_populates="tenant")
    api_usage = relationship("ApiUsage", back_populates="tenant")

class Trade(Base):
    __tablename__ = "trades"
    # Optimizado para time-series con TimescaleDB
    __table_args__ = {'postgresql_partition_by': 'RANGE (timestamp)'}
    
    id = Column(String, primary_key=True, default=generate_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"))
    timestamp = Column(DateTime, default=datetime.utcnow, primary_key=True)
    symbol = Column(String, index=True)
    action = Column(String)  # BUY, SELL, HOLD
    price = Column(Float)
    quantity = Column(Float)
    confidence = Column(Float)
    pnl = Column(Float, default=0.0)
    commission = Column(Float, default=0.0)
    metadata_json = Column(JSON, default=dict)  # regime, interval, etc.
    
    tenant = relationship("Tenant", back_populates="trades")

class ApiUsage(Base):
    __tablename__ = "api_usage"
    
    id = Column(String, primary_key=True, default=generate_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"))
    date = Column(DateTime, default=datetime.utcnow)
    predictions_count = Column(Integer, default=0)
    trades_executed = Column(Integer, default=0)
    high_confidence_wins = Column(Integer, default=0)  # Para billing por outcome
    
    tenant = relationship("Tenant", back_populates="api_usage")