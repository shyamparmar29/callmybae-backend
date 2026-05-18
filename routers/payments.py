from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timedelta, timezone
import razorpay
import hmac, hashlib

from database import get_db
from models import User, Subscription
from schemas import CreateOrderRequest, CreateOrderResponse, VerifyPaymentRequest
from auth_utils import get_current_user
from config import settings

router = APIRouter()

PLAN_PRICES = {
    "spark":    settings.PLAN_SPARK_PRICE,
    "soulmate": settings.PLAN_SOULMATE_PRICE,
}

def get_razorpay_client():
    return razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))

@router.post("/create-order", response_model=CreateOrderResponse)
async def create_order(
    body: CreateOrderRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user)
):
    if body.plan not in PLAN_PRICES:
        raise HTTPException(400, "Invalid plan")

    amount = PLAN_PRICES[body.plan]

    rz = get_razorpay_client()
    order = rz.order.create({
        "amount": amount,
        "currency": "INR",
        "receipt": f"cmb_{user.id[:8]}_{body.plan}",
        "notes": {"user_id": user.id, "plan": body.plan}
    })

    # Save pending subscription
    sub = Subscription(
        user_id=user.id,
        plan=body.plan,
        razorpay_order_id=order["id"],
        status="pending"
    )
    db.add(sub)

    return CreateOrderResponse(
        order_id=order["id"],
        amount=amount,
        currency="INR",
        key_id=settings.RAZORPAY_KEY_ID
    )

@router.post("/verify")
async def verify_payment(
    body: VerifyPaymentRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user)
):
    # Verify signature
    msg = f"{body.razorpay_order_id}|{body.razorpay_payment_id}"
    expected_sig = hmac.new(
        settings.RAZORPAY_KEY_SECRET.encode(),
        msg.encode(),
        hashlib.sha256
    ).hexdigest()

    if expected_sig != body.razorpay_signature:
        raise HTTPException(400, "Invalid payment signature")

    # Activate subscription
    result = await db.execute(
        select(Subscription).where(
            Subscription.razorpay_order_id == body.razorpay_order_id,
            Subscription.user_id == user.id
        )
    )
    sub = result.scalar_one_or_none()
    if not sub:
        raise HTTPException(404, "Subscription not found")

    sub.razorpay_payment_id = body.razorpay_payment_id
    sub.status = "active"
    sub.started_at = datetime.now(timezone.utc)
    sub.expires_at = datetime.now(timezone.utc) + timedelta(days=30)

    # Upgrade user plan
    user.plan = body.plan
    await db.flush()

    return {"success": True, "plan": body.plan, "expires_at": sub.expires_at}

@router.get("/plans")
async def get_plans():
    return {
        "plans": [
            {"id": "spark",    "name": "Spark",    "price_inr": 499,  "price_paise": 49900,  "features": ["60 mins calls/month", "WhatsApp companion", "Full personality builder", "Persistent memory"]},
            {"id": "soulmate", "name": "Soulmate", "price_inr": 1499, "price_paise": 149900, "features": ["Unlimited calls & chat", "WhatsApp + voice notes", "AI selfies & photos", "Scheduled morning calls", "Deep emotional memory"]},
        ]
    }
