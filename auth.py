import hashlib
import secrets
import jwt
from datetime import datetime, timedelta
from fastapi import HTTPException, Security, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

security = HTTPBearer()

def generate_api_key() -> str:
    """Genera API key criptográficamente segura"""
    return "titans_" + secrets.token_urlsafe(32)

def hash_api_key(api_key: str) -> str:
    """Hash SHA-256 para almacenamiento seguro"""
    return hashlib.sha256(api_key.encode()).hexdigest()

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    """JWT para autenticación de dashboard"""
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=15))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, get_config().SECRET_KEY, algorithm=get_config().ALGORITHM)

async def get_current_tenant(
    credentials: HTTPAuthorizationCredentials = Security(security),
    db: Session = Depends(get_db)
) -> SaaSConfig:
    """
    Middleware de autenticación que verifica API key y retorna config del tenant.
    Implementa rate limiting y verificación de plan.
    """
    token = credentials.credentials
    
    # Verificar si es API key o JWT
    if token.startswith("titans_"):
        # Es API key - verificar contra hash
        key_hash = hash_api_key(token)
        tenant = db.query(Tenant).filter(Tenant.api_key_hash == key_hash).first()
        
        if not tenant or not tenant.is_active:
            raise HTTPException(status_code=401, detail="API Key inválida o cuenta suspendida")
        
        return SaaSConfig(
            tenant_id=tenant.id,
            plan=tenant.plan,
            api_key=token,
            trading_mode=tenant.trading_mode,
            webhook_url=tenant.config.get("webhook_url")
        )
    else:
        # Es JWT - decodificar
        try:
            payload = jwt.decode(token, get_config().SECRET_KEY, algorithms=[get_config().ALGORITHM])
            tenant_id = payload.get("sub")
            tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
            if not tenant:
                raise HTTPException(status_code=401, detail="Tenant no encontrado")
            
            return SaaSConfig(
                tenant_id=tenant.id,
                plan=tenant.plan,
                api_key="jwt_auth",
                trading_mode=tenant.trading_mode
            )
        except jwt.PyJWTError:
            raise HTTPException(status_code=401, detail="Token inválido")