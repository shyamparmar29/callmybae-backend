from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime

# ── AUTH ──
class RegisterRequest(BaseModel):
    name: str
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    password: str

class LoginRequest(BaseModel):
    email: Optional[str] = None
    phone: Optional[str] = None
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    name: Optional[str]
    plan: str

# ── COMPANION ──
class CompanionCreate(BaseModel):
    name: str
    companion_type: str          # her | him | them
    personalities: List[str] = []
    description: Optional[str] = None
    language: str = "en"

class CompanionResponse(BaseModel):
    id: str
    name: str
    companion_type: str
    personalities: List[str]
    description: Optional[str]
    language: str
    created_at: datetime

    class Config:
        from_attributes = True

# ── CALLS ──
class InitiateCallRequest(BaseModel):
    phone: str                    # caller's phone e.g. +919876543210
    companion_name: str
    companion_type: str
    personalities: List[str] = []
    description: Optional[str] = None
    language: str = "en"
    companion_id: Optional[str] = None   # if user is logged in

class InitiateCallResponse(BaseModel):
    call_session_id: str
    companion_id: str
    status: str
    message: str

class CallStatusResponse(BaseModel):
    call_session_id: str
    status: str
    duration_secs: int
    is_free_call: bool

# ── PAYMENTS ──
class CreateOrderRequest(BaseModel):
    plan: str    # spark | soulmate

class CreateOrderResponse(BaseModel):
    order_id: str
    amount: int
    currency: str = "INR"
    key_id: str

class VerifyPaymentRequest(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str
    plan: str
