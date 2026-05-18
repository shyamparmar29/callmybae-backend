from sqlalchemy import Column, String, Integer, Boolean, DateTime, Text, ForeignKey, JSON
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
    plan          = Column(String(20), default="free")   # free | spark | soulmate
    is_active     = Column(Boolean, default=True)
    created_at    = Column(DateTime(timezone=True), server_default=func.now())
    companions    = relationship("Companion", back_populates="user", lazy="select")
    subscriptions = relationship("Subscription", back_populates="user", lazy="select")

class Companion(Base):
    __tablename__ = "companions"
    id               = Column(String, primary_key=True, default=gen_uuid)
    user_id          = Column(String, ForeignKey("users.id"), nullable=True)  # null = guest
    name             = Column(String(50), nullable=False)
    companion_type   = Column(String(10), nullable=False)   # her | him | them
    personalities    = Column(JSON, default=[])             # list of trait strings
    description      = Column(Text, nullable=True)          # free-text personality
    language         = Column(String(10), default="en")     # en | hi | en-hi
    voice_id         = Column(String(100), nullable=True)   # ElevenLabs voice ID
    memory           = Column(JSON, default=[])             # conversation memory
    created_at       = Column(DateTime(timezone=True), server_default=func.now())
    user             = relationship("User", back_populates="companions")
    call_sessions    = relationship("CallSession", back_populates="companion", lazy="select")

class CallSession(Base):
    __tablename__ = "call_sessions"
    id             = Column(String, primary_key=True, default=gen_uuid)
    companion_id   = Column(String, ForeignKey("companions.id"), nullable=False)
    caller_phone   = Column(String(20), nullable=False)
    plivo_call_uuid= Column(String(100), nullable=True, index=True)
    status         = Column(String(20), default="initiated")  # initiated|ringing|connected|ended
    duration_secs  = Column(Integer, default=0)
    is_free_call   = Column(Boolean, default=True)
    transcript     = Column(JSON, default=[])   # list of {role, content, timestamp}
    created_at     = Column(DateTime(timezone=True), server_default=func.now())
    ended_at       = Column(DateTime(timezone=True), nullable=True)
    companion      = relationship("Companion", back_populates="call_sessions")

class Subscription(Base):
    __tablename__ = "subscriptions"
    id                 = Column(String, primary_key=True, default=gen_uuid)
    user_id            = Column(String, ForeignKey("users.id"), nullable=False)
    plan               = Column(String(20), nullable=False)   # spark | soulmate
    razorpay_order_id  = Column(String(100), nullable=True)
    razorpay_payment_id= Column(String(100), nullable=True)
    status             = Column(String(20), default="pending")  # pending | active | cancelled
    started_at         = Column(DateTime(timezone=True), nullable=True)
    expires_at         = Column(DateTime(timezone=True), nullable=True)
    created_at         = Column(DateTime(timezone=True), server_default=func.now())
    user               = relationship("User", back_populates="subscriptions")
