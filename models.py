from sqlalchemy import Column, String, Integer, Boolean, DateTime, Text, ForeignKey, JSON, Float
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base
import uuid

def gen_uuid():
    return str(uuid.uuid4())

class User(Base):
    __tablename__ = "users"
    id            = Column(String, primary_key=True, default=gen_uuid)
    name          = Column(String(100), nullable=True)
    email         = Column(String(255), unique=True, nullable=True, index=True)
    phone         = Column(String(20), unique=True, nullable=True, index=True)
    password_hash = Column(String(255), nullable=True)
    google_id     = Column(String(100), unique=True, nullable=True, index=True)
    avatar_url    = Column(String(500), nullable=True)
    plan          = Column(String(20), default="free")
    is_active     = Column(Boolean, default=True)
    created_at    = Column(DateTime(timezone=True), server_default=func.now())
    companions    = relationship("Companion", back_populates="user", lazy="select")
    subscriptions = relationship("Subscription", back_populates="user", lazy="select")
    profile       = relationship("UserProfile", back_populates="user", uselist=False, lazy="select")
    credits       = relationship("UserCredits", back_populates="user", uselist=False, lazy="select")

class UserProfile(Base):
    __tablename__ = "user_profiles"
    id                  = Column(String, primary_key=True, default=gen_uuid)
    user_id             = Column(String, ForeignKey("users.id"), unique=True, nullable=False)
    first_name          = Column(String(50), nullable=True)
    age                 = Column(Integer, nullable=True)
    city                = Column(String(100), nullable=True)
    occupation          = Column(String(100), nullable=True)
    about               = Column(Text, nullable=True)           # user bio in their words
    interests           = Column(JSON, default=[])              # ["cricket","music","startups"]
    # Companion preferences
    companion_name      = Column(String(50), nullable=True)
    companion_type      = Column(String(10), default="her")
    companion_language  = Column(String(10), default="hi")
    companion_personalities = Column(JSON, default=["warm"])
    companion_description = Column(Text, nullable=True)
    # Scheduled calls
    scheduled_calls     = Column(JSON, default=[])
    # Memory bank — structured facts extracted from conversations
    memory_bank         = Column(JSON, default={})
    # AI personality evolution — learned over time
    interaction_style   = Column(JSON, default={})
    total_call_minutes  = Column(Float, default=0.0)
    last_call_at        = Column(DateTime(timezone=True), nullable=True)
    created_at          = Column(DateTime(timezone=True), server_default=func.now())
    updated_at          = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    user                = relationship("User", back_populates="profile")

class UserCredits(Base):
    __tablename__ = "user_credits"
    id         = Column(String, primary_key=True, default=gen_uuid)
    user_id    = Column(String, ForeignKey("users.id"), unique=True, nullable=False)
    balance    = Column(Float, default=0.0)   # credits (1 credit = ₹1)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    user       = relationship("User", back_populates="credits")
    transactions = relationship("CreditTransaction", back_populates="credits_account", lazy="select")

class CreditTransaction(Base):
    __tablename__ = "credit_transactions"
    id              = Column(String, primary_key=True, default=gen_uuid)
    credits_id      = Column(String, ForeignKey("user_credits.id"), nullable=False)
    amount          = Column(Float, nullable=False)  # positive=credit, negative=debit
    type            = Column(String(20), nullable=False)  # purchase|call_usage|wa_usage|free_bonus
    description     = Column(String(200), nullable=True)
    call_session_id = Column(String, nullable=True)
    razorpay_order_id = Column(String(100), nullable=True)
    razorpay_payment_id = Column(String(100), nullable=True)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())
    credits_account = relationship("UserCredits", back_populates="transactions")

class Companion(Base):
    __tablename__ = "companions"
    id               = Column(String, primary_key=True, default=gen_uuid)
    user_id          = Column(String, ForeignKey("users.id"), nullable=True)
    name             = Column(String(50), nullable=False)
    companion_type   = Column(String(10), nullable=False)
    personalities    = Column(JSON, default=[])
    description      = Column(Text, nullable=True)
    language         = Column(String(10), default="en")
    voice_id         = Column(String(100), nullable=True)
    memory           = Column(JSON, default=[])
    wa_history       = Column(JSON, default=[])
    created_at       = Column(DateTime(timezone=True), server_default=func.now())
    user             = relationship("User", back_populates="companions")
    call_sessions    = relationship("CallSession", back_populates="companion", lazy="select")

class CallSession(Base):
    __tablename__ = "call_sessions"
    id              = Column(String, primary_key=True, default=gen_uuid)
    companion_id    = Column(String, ForeignKey("companions.id"), nullable=False)
    caller_phone    = Column(String(20), nullable=False)
    plivo_call_uuid = Column(String(100), nullable=True, index=True)
    status          = Column(String(20), default="initiated")
    duration_secs   = Column(Integer, default=0)
    is_free_call    = Column(Boolean, default=True)
    credits_used    = Column(Float, default=0.0)
    transcript      = Column(JSON, default=[])
    recording_url   = Column(String(500), nullable=True)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())
    ended_at        = Column(DateTime(timezone=True), nullable=True)
    companion       = relationship("Companion", back_populates="call_sessions")

class Subscription(Base):
    __tablename__ = "subscriptions"
    id                  = Column(String, primary_key=True, default=gen_uuid)
    user_id             = Column(String, ForeignKey("users.id"), nullable=False)
    plan                = Column(String(20), nullable=False)
    razorpay_order_id   = Column(String(100), nullable=True)
    razorpay_payment_id = Column(String(100), nullable=True)
    status              = Column(String(20), default="pending")
    started_at          = Column(DateTime(timezone=True), nullable=True)
    expires_at          = Column(DateTime(timezone=True), nullable=True)
    created_at          = Column(DateTime(timezone=True), server_default=func.now())
    user                = relationship("User", back_populates="subscriptions")

class WhatsAppSession(Base):
    __tablename__ = "whatsapp_sessions"
    id           = Column(String, primary_key=True, default=gen_uuid)
    user_phone   = Column(String(20), nullable=False, index=True)
    companion_id = Column(String, ForeignKey("companions.id"), nullable=True)
    history      = Column(JSON, default=[])
    created_at   = Column(DateTime(timezone=True), server_default=func.now())
    updated_at   = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
