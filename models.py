from sqlalchemy import (
    Column, String, Integer, Float, Boolean, Text, DateTime, ForeignKey,
    JSON, UniqueConstraint
)
from sqlalchemy.orm import relationship, declarative_base
from datetime import datetime, timezone
import uuid

Base = declarative_base()


def _uuid():
    return str(uuid.uuid4())


def _utcnow():
    return datetime.utcnow()  # naive UTC — matches TIMESTAMP WITHOUT TIME ZONE in Postgres


class User(Base):
    __tablename__ = "users"
    id = Column(String, primary_key=True, default=_uuid)
    email = Column(String(255), unique=True, nullable=False, index=True)
    name = Column(String(255))
    phone = Column(String(30))
    password_hash = Column(String(255))
    google_id = Column(String(100), unique=True)
    avatar_url = Column(String(500))
    created_at = Column(DateTime, default=_utcnow)


class UserProfile(Base):
    __tablename__ = "user_profiles"
    id = Column(String, primary_key=True, default=_uuid)
    user_id = Column(String, ForeignKey("users.id"), unique=True, nullable=False)
    first_name = Column(String(100))
    companion_name = Column(String(50))
    companion_type = Column(String(10), default="her")
    companion_personalities = Column(JSON, default=list)
    companion_language = Column(String(10), default="en")
    companion_description = Column(Text)
    memory_bank = Column(JSON, default=dict)
    interaction_style = Column(JSON, default=dict)
    scheduled_calls = Column(JSON, default=list)
    total_call_minutes = Column(Float, default=0)
    last_call_at = Column(DateTime)
    created_at = Column(DateTime, default=_utcnow)


class UserCredits(Base):
    __tablename__ = "user_credits"
    id = Column(String, primary_key=True, default=_uuid)
    user_id = Column(String, ForeignKey("users.id"), unique=True, nullable=False)
    balance = Column(Float, default=10.0)
    updated_at = Column(DateTime, default=_utcnow)


class CreditTransaction(Base):
    __tablename__ = "credit_transactions"
    id = Column(String, primary_key=True, default=_uuid)
    credits_id = Column(String, ForeignKey("user_credits.id"))
    amount = Column(Float)
    type = Column(String(20))
    description = Column(String(255))
    call_session_id = Column(String)
    razorpay_order_id = Column(String(100))
    razorpay_payment_id = Column(String(100))
    created_at = Column(DateTime, default=_utcnow)


class Companion(Base):
    __tablename__ = "companions"
    id = Column(String, primary_key=True, default=_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=True)
    name = Column(String(50))
    companion_type = Column(String(10))
    personalities = Column(JSON, default=list)
    description = Column(Text)
    language = Column(String(10), default="en")
    voice_id = Column(String(100))
    wa_history = Column(JSON, default=list)
    created_at = Column(DateTime, default=_utcnow)


class CallSession(Base):
    __tablename__ = "call_sessions"
    id = Column(String, primary_key=True, default=_uuid)
    companion_id = Column(String, ForeignKey("companions.id"))
    character_id = Column(String, ForeignKey("characters.id"), nullable=True)
    caller_phone = Column(String(30))
    plivo_call_uuid = Column(String(100))
    status = Column(String(20), default="initiated")
    duration_secs = Column(Integer, default=0)
    transcript = Column(JSON, default=list)
    recording_url = Column(String(500))
    is_free_call = Column(Boolean, default=False)
    credits_used = Column(Float, default=0)
    created_at = Column(DateTime, default=_utcnow)
    ended_at = Column(DateTime)


class Subscription(Base):
    __tablename__ = "subscriptions"
    id = Column(String, primary_key=True, default=_uuid)
    user_id = Column(String, ForeignKey("users.id"))
    plan = Column(String(50))
    status = Column(String(20))
    razorpay_subscription_id = Column(String(100))
    started_at = Column(DateTime, default=_utcnow)
    expires_at = Column(DateTime)


class WhatsAppSession(Base):
    __tablename__ = "whatsapp_sessions"
    id = Column(String, primary_key=True, default=_uuid)
    user_id = Column(String, ForeignKey("users.id"))
    companion_id = Column(String, ForeignKey("companions.id"))
    last_message_at = Column(DateTime, default=_utcnow)


class Character(Base):
    """Pre-built character with personality and evolving life."""
    __tablename__ = "characters"
    id = Column(String, primary_key=True)
    name = Column(String(50), nullable=False)
    tagline = Column(String(200))
    avatar_emoji = Column(String(10))
    age = Column(Integer)
    location = Column(String(100))
    occupation = Column(String(200))
    backstory = Column(Text)
    personality = Column(Text)
    speaking_style = Column(Text)
    voice_id = Column(String(100))
    language = Column(String(10), default="hi")
    gender = Column(String(20))
    personalities = Column(JSON, default=list)
    initial_life_state = Column(JSON, default=dict)
    is_active = Column(Boolean, default=True)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=_utcnow)


class UserCharacterRelationship(Base):
    """Each user has their own version of each character's life + memory."""
    __tablename__ = "user_character_relationships"
    id = Column(String, primary_key=True, default=_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    character_id = Column(String, ForeignKey("characters.id"), nullable=False)
    conversation_memory = Column(JSON, default=dict)
    character_life_state = Column(JSON, default=dict)
    call_count = Column(Integer, default=0)
    total_call_minutes = Column(Float, default=0)
    relationship_depth = Column(Integer, default=0)
    last_call_at = Column(DateTime)
    created_at = Column(DateTime, default=_utcnow)
    __table_args__ = (UniqueConstraint("user_id", "character_id", name="uq_user_character"),)
