from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from database import get_db
from sql_models import ItineraryHistory, User
from auth_routes import get_current_user
from models import Itinerary
import json

router = APIRouter(prefix="/history", tags=["History"])


@router.get("/")
def get_user_history(
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    history = (
        db.query(ItineraryHistory)
        .filter(ItineraryHistory.user_id == current_user.id)
        .order_by(ItineraryHistory.created_at.desc())
        .all()
    )
    # Return simplified list
    return [
        {
            "id": h.id,
            "city": h.city,
            "days": h.days,
            "start_date": h.start_date,
            "created_at": h.created_at,
        }
        for h in history
    ]


@router.get("/{history_id}")
def get_history_detail(
    history_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    import logging

    logger = logging.getLogger("travel_agent_server")
    logger.info(f"GET /history/{history_id} requested by {current_user.email}")

    item = (
        db.query(ItineraryHistory)
        .filter(
            ItineraryHistory.id == history_id,
            ItineraryHistory.user_id == current_user.id,
        )
        .first()
    )
    if not item:
        logger.warning(f"Itinerary {history_id} not found for user {current_user.id}")
        raise HTTPException(status_code=404, detail="Itinerary not found")

    # Check if full_json_blob is a string and parse it, otherwise return as is
    blob = item.full_json_blob
    if isinstance(blob, str):
        try:
            blob = json.loads(blob)
        except Exception as e:
            logger.error(f"Failed to parse JSON blob for {history_id}: {e}")
            blob = {}  # Validation fallback

    logger.info(
        f"Returning history item {history_id} with keys: {list(blob.keys()) if isinstance(blob, dict) else 'NotDict'}"
    )

    return {
        "id": item.id,
        "city": item.city,
        "days": item.days,
        "start_date": item.start_date,
        "full_json_blob": blob,
        "created_at": item.created_at,
    }


class HistoryCreate(BaseModel):
    city: str
    days: int
    start_date: str | None = None
    full_json_blob: dict


@router.post("/")
def save_history(
    item: HistoryCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    import logging

    logger = logging.getLogger("travel_agent_server")
    logger.info(
        f"POST /history received from user {current_user.email} for city {item.city}"
    )
    db_item = ItineraryHistory(
        user_id=current_user.id,
        city=item.city,
        days=item.days,
        start_date=item.start_date,
        full_json_blob=json.dumps(item.full_json_blob),
    )
    db.add(db_item)
    db.commit()
    db.refresh(db_item)
    return {"status": "saved", "id": db_item.id}
