import os
from dataclasses import dataclass, field
from typing import Optional, List
from enum import Enum
from datetime import datetime
from functools import lru_cache

class PlanTier(Enum):
    FREE = "free"
    PRO = "pro"
    ENTERPRISE = "enterprise"

class TradingMode(Enum):
    PAPER = "paper"
    LIVE = "live"

@dataclass
class SaaSConfig:
    """Configuración multi-tenant"""
    tenant_id: str
    plan: PlanTier
    api_key: str
    trading_mode: TradingMode = TradingMode.PAPER
    max_trades_per_day: int = 10
    max_concurrent_strategies: int = 1
    allowed_exchanges: List[str] = field(default_factory=lambda: ["binance"])
    enable_live_trading: bool = False
    webhook_url: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    
    def __post_init__(self):
        if self.plan == PlanTier.FREE:
            self.max_trades_per_day = 10
            self.max_concurrent_strategies = 1
            self.enable_live_trading = False
            self.allowed_exchanges = ["binance"]
        elif self.plan == PlanTier.PRO:
            self.max_trades_per_day = 1000
            self.max_concurrent_strategies = 5
            self.enable_live_trading = True
            self.allowed_exchanges = ["binance", "coinbase", "kraken"]
        elif self.plan == PlanTier.ENTERPRISE:
            self.max_trades_per_day = 10000
            self.max_concurrent_strategies = 20
            self.enable_live_trading = True

@dataclass 
class AppConfig:
    """Configuración global de la aplicación"""
    # Seguridad
    SECRET_KEY: str = os.getenv("SECRET_KEY", "your-secret-key-change-in-production")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    
    # Base de datos
    DATABASE_URL: str = os.getenv("DATABASE_URL", "postgresql://user:pass@localhost/titans")
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    
    # Stripe
    STRIPE_SECRET_KEY: str = os.getenv("STRIPE_SECRET_KEY", "")
    STRIPE_WEBHOOK_SECRET: str = os.getenv("STRIPE_WEBHOOK_SECRET", "")
    STRIPE_API_VERSION: str = "2024-12-18.acacia"
    
    # Trading
    DEFAULT_INITIAL_BALANCE: float = 10000.0
    RISK_PER_TRADE: float = 0.02
    
    # GPU/Performance
    DEVICE: str = "cuda" if os.getenv("CUDA_AVAILABLE", "false").lower() == "true" else "cpu"

@lru_cache()
def get_config() -> AppConfig:
    return AppConfig()