from fastapi import APIRouter, Request, Header
from typing import Optional

billing_router = APIRouter()

@billing_router.post("/webhook/stripe")
async def stripe_webhook(
    request: Request,
    x_stripe_signature: Optional[str] = Header(None)
):
    """Webhook para eventos de Stripe"""
    payload = await request.body()
    
    try:
        import stripe
        stripe.api_key = get_config().STRIPE_SECRET_KEY
        
        event = stripe.Webhook.construct_event(
            payload, x_stripe_signature, get_config().STRIPE_WEBHOOK_SECRET
        )
        
        if event['type'] == 'checkout.session.completed':
            session = event['data']['object']
            tenant_id = session['metadata']['tenant_id']
            plan = session['metadata']['plan']
            
            # Actualizar plan en DB
            db = next(get_db())
            tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
            if tenant:
                tenant.plan = PlanTier(plan)
                tenant.stripe_subscription_id = session['subscription']
                db.commit()
                logger.info(f"Tenant {tenant_id} upgraded to {plan}")
        
        elif event['type'] == 'customer.subscription.deleted':
            subscription = event['data']['object']
            tenant_id = subscription['metadata']['tenant_id']
            
            # Downgrade a FREE
            db = next(get_db())
            tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
            if tenant:
                tenant.plan = PlanTier.FREE
                db.commit()
        
        return {"status": "success"}
        
    except Exception as e:
        logger.error(f"Error en webhook: {e}")
        raise HTTPException(status_code=400, detail=str(e))

app.include_router(billing_router, prefix="/billing")