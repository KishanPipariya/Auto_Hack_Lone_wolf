from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from app.core.database import Base
import datetime
from datetime import timezone


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(timezone.utc))

    itineraries = relationship("ItineraryHistory", back_populates="owner")


class ItineraryHistory(Base):
    __tablename__ = "itinerary_history"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    city = Column(String)
    start_date = Column(String, nullable=True)
    days = Column(Integer)
    full_json_blob = Column(Text)  # Storing JSON as string
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(timezone.utc))

    owner = relationship("User", back_populates="itineraries")
