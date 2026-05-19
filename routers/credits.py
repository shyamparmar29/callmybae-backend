from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timezone
import razorpay, hmac, hashlib

from database import get_db
from models import User, UserCredits, CreditTransaction
from auth_utils import get_current_user
from config import settings

router = APIRouter()

CREDITS_PER_RUPEE = 1.0       # ₹1 = 1 credit
CREDITS_PER_MINUTE = 2.0      # 2 credits/min = ₹2/min
MIN_TOPUP = 50                 # Minimum ₹50 top-up
FREE_CREDITS_ON_SIGNUP = 10    # 5 free minutes on signup


async def get_or_create_credits(user_id: str, db: AsyncSession) -> UserCredits:
    result = await db.execute(select(UserCredits).where(UserCredits.user_id == user_id))
    credits = result.scalar_one_or_none()
    if not credits:
        credits = UserCredits(user_id=user_id, balance=FREE_CREDITS_ON_SIGNUP)
        db.add(credits)
        await db.flush()
        # Log free bonus
        tx = CreditTransaction(
            credits_id=credits.id,
            amount=FREE_CREDITS_ON_SIGNUP,
            type="free_bonus",
            description=f"Welcome bonus — {int(FREE_CREDITS_ON_SIGNUP/CREDITS_PER_MINUTE)} free minutes"
        )
        db.add(tx)
        await db.flush()
    return credits


async def deduct_credits_for_call(user_id: str, duration_secs: int,
                                   call_session_id: str, db: AsyncSession) -> float:
    """Deduct credits after a call. Returns credits used."""
    credits = await get_or_create_credits(user_id, db)
    minutes = duration_secs / 60.0
    credits_used = round(minutes * CREDITS_PER_MINUTE, 2)
    
    if credits_used <= 0:
        return 0
    
    credits.balance = max(0, credits.balance - credits_used)
    tx = CreditTransaction(
        credits_id=credits.id,
        amount=-credits_used,
        type="call_usage",
        description=f"Call — {int(minutes)}m {int((minutes%1)*60)}s",
        call_session_id=call_session_id
    )
    db.add(tx)
    await db.flush()
    return credits_used


@router.get("/balance")
async def get_balance(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    credits = await get_or_create_credits(user.id, db)
    minutes_left = credits.balance / CREDITS_PER_MINUTE
    return {
        "balance": credits.balance,
        "minutes_left": round(minutes_left, 1),
        "rate": f"₹{CREDITS_PER_MINUTE}/min",
        "low_balance": credits.balance < 10,
    }


@router.get("/transactions")
async def get_transactions(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    credits = await get_or_create_credits(user.id, db)
    result = await db.execute(
        select(CreditTransaction)
        .where(CreditTransaction.credits_id == credits.id)
        .order_by(CreditTransaction.created_at.desc())
        .limit(50)
    )
    txns = result.scalars().all()
    return {
        "balance": credits.balance,
        "transactions": [
            {
                "id": t.id[:8],
                "amount": t.amount,
                "type": t.type,
                "description": t.description,
                "date": t.created_at.isoformat() if t.created_at else "",
            }
            for t in txns
        ]
    }


@router.post("/create-order")
async def create_topup_order(
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    amount_inr = int(body.get("amount", 0))
    if amount_inr < MIN_TOPUP:
        raise HTTPException(400, f"Minimum top-up is ₹{MIN_TOPUP}")
    if amount_inr > 10000:
        raise HTTPException(400, "Maximum top-up is ₹10,000 per transaction")

    rz = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
    order = rz.order.create({
        "amount": amount_inr * 100,  # paise
        "currency": "INR",
        "receipt": f"cmb_credits_{user.id[:8]}",
        "notes": {"user_id": user.id, "type": "credits", "inr_amount": amount_inr}
    })
    return {
        "order_id": order["id"],
        "amount": amount_inr * 100,
        "currency": "INR",
        "key_id": settings.RAZORPAY_KEY_ID,
        "credits_to_add": amount_inr,  # ₹1 = 1 credit
        "minutes": amount_inr / CREDITS_PER_MINUTE,
    }


@router.post("/verify-topup")
async def verify_topup(
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    order_id = body.get("razorpay_order_id")
    payment_id = body.get("razorpay_payment_id")
    signature = body.get("razorpay_signature")
    amount_inr = int(body.get("amount_inr", 0))

    if not all([order_id, payment_id, signature, amount_inr]):
        raise HTTPException(400, "Missing payment details")

    # Verify signature
    msg = f"{order_id}|{payment_id}"
    expected = hmac.new(
        settings.RAZORPAY_KEY_SECRET.encode(),
        msg.encode(), hashlib.sha256
    ).hexdigest()
    if expected != signature:
        raise HTTPException(400, "Invalid payment signature")

    # Add credits
    credits = await get_or_create_credits(user.id, db)
    credits_to_add = float(amount_inr)
    credits.balance += credits_to_add

    tx = CreditTransaction(
        credits_id=credits.id,
        amount=credits_to_add,
        type="purchase",
        description=f"Top-up ₹{amount_inr} → {credits_to_add} credits",
        razorpay_order_id=order_id,
        razorpay_payment_id=payment_id
    )
    db.add(tx)
    await db.flush()

    return {
        "success": True,
        "credits_added": credits_to_add,
        "new_balance": credits.balance,
        "minutes_left": round(credits.balance / CREDITS_PER_MINUTE, 1),
    }
