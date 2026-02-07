from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional, List
import json

app = FastAPI(
    title="Titans AI Trading API",
    description="API de trading algorítmico con memoria histórica neural",
    version="2.0.0-saas"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configurar para producción
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Health check
@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "version": "2.0.0-saas",
        "device": str(DEVICE),
        "gpu": torch.cuda.get_device_name(0) if DEVICE.type == "cuda" else None
    }

# Modelos Pydantic
class SignalRequest(BaseModel):
    symbol: str = "BTC/USDT"
    execute: bool = False  # False = solo señal, True = ejecutar trade
    
class TradeResponse(BaseModel):
    timestamp: str
    signal: str
    confidence: float
    price: float
    executed: bool
    regime: Optional[str] = None
    
class PortfolioResponse(BaseModel):
    balance: float
    total_pnl: float
    win_rate: float
    total_trades: int
    current_position: float
    daily_trades_used: int
    daily_trades_limit: int
    plan: str

# Endpoints
@app.post("/api/v1/signal", response_model=TradeResponse)
async def get_signal(
    request: SignalRequest,
    tenant: SaaSConfig = Depends(get_current_tenant),
    background_tasks: BackgroundTasks = None
):
    """
    Obtiene señal de trading. Si execute=True y el plan permite, ejecuta el trade.
    """
    # Rate limiting por API
    if not check_api_rate_limit(tenant.tenant_id):
        raise HTTPException(status_code=429, detail="Rate limit excedido")
    
    # Para operaciones de escritura, usar Celery
    if request.execute:
        task = execute_signal_task.delay(
            tenant.tenant_id,
            request.symbol,
            execute=True
        )
        return {
            "task_id": task.id,
            "status": "processing",
            "message": "Trade en proceso. Use /task/{task_id} para consultar estado."
        }
    
    # Solo lectura: respuesta inmediata
    bot = get_bot_for_tenant(tenant.tenant_id)
    df = bot.data_manager.fetch_recent(limit=168)
    
    if df is None:
        raise HTTPException(status_code=503, detail="Datos no disponibles")
    
    result = bot.predict_and_trade(df, execute=False)
    return result

@app.get("/api/v1/portfolio", response_model=PortfolioResponse)
async def get_portfolio(tenant: SaaSConfig = Depends(get_current_tenant)):
    """Obtiene estado del portfolio"""
    bot = get_bot_for_tenant(tenant.tenant_id)
    metrics = bot.get_metrics()
    
    return {
        "balance": metrics['balance'],
        "total_pnl": metrics['total_pnl'],
        "win_rate": metrics['win_rate'],
        "total_trades": metrics['total_trades'],
        "current_position": bot.position,
        "daily_trades_used": metrics['daily_trades_used'],
        "daily_trades_limit": metrics['daily_trades_limit'],
        "plan": metrics['plan']
    }

@app.get("/api/v1/historical-status")
async def historical_status(tenant: SaaSConfig = Depends(get_current_tenant)):
    """Estado de carga de memoria histórica"""
    bot = get_bot_for_tenant(tenant.tenant_id)
    return {
        "loaded": bot.historical_loaded,
        "records": len(bot.history_analyzer.data) if bot.historical_loaded else 0,
        "crashes_detected": len(bot.history_analyzer.crashes) if bot.historical_loaded else 0,
        "bull_runs_detected": len(bot.history_analyzer.bulls) if bot.historical_loaded else 0
    }

@app.get("/api/v1/usage")
async def get_usage(tenant: SaaSConfig = Depends(get_current_tenant)):
    """Obtiene uso actual para billing"""
    redis_client = redis.Redis.from_url(get_config().REDIS_URL)
    today = datetime.now().strftime('%Y-%m-%d')
    
    usage = redis_client.hgetall(f"usage:{tenant.tenant_id}:{today}")
    
    return {
        "date": today,
        "predictions": int(usage.get(b"predictions", 0)),
        "trades_executed": int(usage.get(b"trades", 0)),
        "high_confidence_wins": int(usage.get(b"high_conf_wins", 0)),
        "plan_limits": {
            "max_trades_per_day": tenant.max_trades_per_day,
            "max_strategies": tenant.max_concurrent_strategies
        }
    }

@app.post("/api/v1/upgrade")
async def upgrade_plan(
    plan: PlanTier,
    tenant: SaaSConfig = Depends(get_current_tenant)
):
    """Inicia proceso de upgrade (integración con Stripe)"""
    if not get_config().STRIPE_SECRET_KEY:
        raise HTTPException(status_code=501, detail="Billing no configurado")
    
    # Crear checkout session en Stripe
    try:
        import stripe
        stripe.api_key = get_config().STRIPE_SECRET_KEY
        
        price_id = os.getenv(f"STRIPE_PRICE_{plan.value.upper()}")
        if not price_id:
            raise HTTPException(status_code=400, detail="Plan no disponible")
        
        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=f"{os.getenv('APP_URL')}/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{os.getenv('APP_URL')}/cancel",
            metadata={"tenant_id": tenant.tenant_id, "plan": plan.value}
        )
        
        return {"checkout_url": session.url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# WebSocket para streaming en tiempo real
@app.websocket("/ws/{tenant_id}")
async def websocket_endpoint(websocket: WebSocket, tenant_id: str):
    await websocket.accept()
    
    try:
        bot = get_bot_for_tenant(tenant_id)
        
        while True:
            df = bot.data_manager.fetch_recent(limit=1)
            if df is not None:
                result = bot.predict_and_trade(df, execute=False)
                await websocket.send_json(result)
            
            await asyncio.sleep(5)  # 5 segundos entre actualizaciones
            
    except WebSocketDisconnect:
        pass
    except Exception as e:
        await websocket.close(code=1011, reason=str(e))

# Admin endpoints
@app.get("/admin/metrics")
async def admin_metrics():
    """Métricas Prometheus para monitoreo"""
    from prometheus_client import Counter, Histogram, generate_latest
    
    return generate_latest()

# Helper functions
def check_api_rate_limit(tenant_id: str) -> bool:
    """Rate limiting simple por tenant"""
    redis_client = redis.Redis.from_url(get_config().REDIS_URL)
    key = f"ratelimit:{tenant_id}:{datetime.now().minute}"
    current = redis_client.incr(key)
    if current == 1:
        redis_client.expire(key, 60)
    return current <= 60  # 60 requests por minuto

def get_db():
    """Dependency para DB sessions"""
    engine = create_engine(get_config().DATABASE_URL)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()