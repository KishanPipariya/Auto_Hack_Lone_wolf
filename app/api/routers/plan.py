import logging
import json
import asyncio
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse, Response
from app.models.domain import Preferences, Itinerary
from app.core.agent import TravelAgent
from app.services.pdf import generate_pdf as generate_pdf_util
from app.services.calendar import generate_ics

logger = logging.getLogger("travel_agent_server")

router = APIRouter(tags=["Planning"])

# Single agent instance (stateless enough for this, but watch out if stateful)
# In original code it was global.
agent = TravelAgent()


@router.post("/plan", response_model=Itinerary)
def generate_plan(preferences: Preferences):
    """
    Generates a travel itinerary based on user preferences.
    """
    try:
        # Check if API key is present for the agent
        if not agent.client:
            raise HTTPException(
                status_code=500, detail="Google API Key not configured on server."
            )

        itinerary = agent.plan_trip(preferences)
        return itinerary
    except Exception as e:
        error_msg = str(e)
        if "429" in error_msg or "RESOURCE_EXHAUSTED" in error_msg:
            raise HTTPException(
                status_code=429,
                detail="High traffic volume. Please try again in a minute. (Quota Exceeded)",
            )
        elif "404" in error_msg:
            raise HTTPException(
                status_code=503,
                detail="AI Model currently unavailable. Please try again later.",
            )
        else:
            # Log the full error for server admins but show simple text to user
            logger.error(f"SERVER ERROR: {error_msg}")
            raise HTTPException(
                status_code=500,
                detail="An unexpected error occurred while generating your plan.",
            )


@router.post("/plan_stream")
async def stream_plan_endpoint(preferences: Preferences):
    """
    Streams status updates and the final itinerary as NDJSON.
    """
    logger.info(
        f"Received streaming request for city: {preferences.city}, budget: {preferences.budget}"
    )

    # Create a new planner instance for each stream to ensure isolation
    # and proper state management for the streaming process.
    stream_agent = TravelAgent()

    async def event_generator():
        try:
            for item in stream_agent.plan_trip_stream(preferences):
                if isinstance(item, str):
                    yield json.dumps({"type": "status", "message": item}) + "\n"
                else:
                    # It's the Itinerary object
                    yield (
                        json.dumps({"type": "result", "data": item.model_dump()}) + "\n"
                    )

                # Small delay to allow client to process events
                await asyncio.sleep(0.05)
        except Exception as e:
            error_msg = str(e)
            logger.error(f"SERVER ERROR: {error_msg}")  # Log full error for admin

            user_msg = "An unexpected error occurred while planning."

            if "429" in error_msg or "RESOURCE_EXHAUSTED" in error_msg:
                user_msg = "High traffic volume. Please try again in a minute. (Quota Exceeded)"
            elif "404" in error_msg:
                user_msg = "AI Model currently unavailable. Please try again later."

            yield json.dumps({"type": "error", "message": user_msg}) + "\n"

    return StreamingResponse(event_generator(), media_type="application/x-ndjson")


@router.post("/pdf")
async def generate_pdf(itinerary: Itinerary):
    # Delegate to utils
    return await generate_pdf_util(itinerary)


@router.post("/calendar")
async def generate_calendar_endpoint(
    itinerary: Itinerary, start_date: str | None = None
):
    try:
        # Generate ICS bytes
        ics_bytes = generate_ics(itinerary, start_date)

        filename = f"Trip_to_{itinerary.city}.ics"
        return Response(
            content=ics_bytes,
            media_type="text/calendar",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except Exception as e:
        logger.exception("Failed to generate calendar file.")
        raise HTTPException(status_code=500, detail=str(e))
