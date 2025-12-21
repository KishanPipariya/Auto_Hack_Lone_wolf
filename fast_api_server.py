import logging
from logging.handlers import RotatingFileHandler
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse, FileResponse
import json
import asyncio
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from models import Preferences, Itinerary
from agent import TravelAgent
from dotenv import load_dotenv

# Configure Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("travel_agent_server")
handler = RotatingFileHandler("server.log", maxBytes=5*1024*1024, backupCount=3)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)

load_dotenv()

app = FastAPI(title="Travel Planner Agent API")

app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def read_root():
    return FileResponse('static/index.html')

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

agent = TravelAgent()


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.post("/plan", response_model=Itinerary)
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
                detail="High traffic volume. Please try again in a minute. (Quota Exceeded)"
            )
        elif "404" in error_msg:
            raise HTTPException(
                status_code=503, 
                detail="AI Model currently unavailable. Please try again later."
            )
        else:
             # Log the full error for server admins but show simple text to user
            logger.error(f"SERVER ERROR: {error_msg}")
            raise HTTPException(
                status_code=500, 
                detail="An unexpected error occurred while generating your plan."
            )


@app.post("/plan_stream")
async def stream_plan_endpoint(preferences: Preferences):
    """
    Streams status updates and the final itinerary as NDJSON.
    """
    logger.info(f"Received streaming request for city: {preferences.city}, budget: {preferences.budget}")
    
    # Create a new planner instance for each stream to ensure isolation
    # and proper state management for the streaming process.
    agent = TravelAgent() 

    async def event_generator():
        try:
            for item in agent.plan_trip_stream(preferences):
                if isinstance(item, str):
                    yield json.dumps({"type": "status", "message": item}) + "\n"
                else:
                    # It's the Itinerary object
                    yield json.dumps({"type": "result", "data": item.model_dump()}) + "\n"
                
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


@app.post("/pdf")
async def generate_pdf(itinerary: Itinerary):
    # Delegate to utils
    from fpdf_utils import generate_pdf as generate_pdf_util
    return await generate_pdf_util(itinerary)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
