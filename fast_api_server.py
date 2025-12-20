import logging
from logging.handlers import RotatingFileHandler
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse, FileResponse
import json
import asyncio
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from models import Preferences, Itinerary
from agent import TravelPlanner
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
    allow_origins=["http://localhost:8081", "http://127.0.0.1:8081"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

planner = TravelPlanner()


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
        if not planner.client:
            raise HTTPException(
                status_code=500, detail="Google API Key not configured on server."
            )

        itinerary = planner.plan_trip(preferences)
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
    agent = TravelPlanner() 

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


from fpdf import FPDF
from fastapi import Response
import io
import urllib.request
import aiohttp
import asyncio

class ItineraryPDF(FPDF):
    def header(self):
        # Header with colored bar
        self.set_fill_color(37, 99, 235) # Blue-600
        self.rect(0, 0, 210, 20, 'F')
        self.set_font('helvetica', 'B', 15)
        self.set_text_color(255, 255, 255)
        self.cell(0, 10, 'Travel Planner Agent', border=0, align='R')
        self.ln(25)

    def footer(self):
        self.set_y(-15)
        self.set_font('helvetica', 'I', 8)
        self.set_text_color(128, 128, 128)
        self.cell(0, 10, f'Page {self.page_no()}', align='C')

@app.post("/pdf")
async def generate_pdf(itinerary: Itinerary):
    # 1. Fetch all images concurrently
    image_tasks = []
    image_map = {} # url -> bytes

    # Add User-Agent to avoid 403s
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
    
    async with aiohttp.ClientSession(headers=headers) as session:
        for day in itinerary.days:
            for activity in day.activities:
                if activity.image_url:
                    # Create a task for each image
                    async def fetch_image(url):
                        try:
                            async with session.get(url, timeout=10) as resp:
                                if resp.status == 200:
                                    return url, await resp.read()
                        except Exception:
                            pass
                        return url, None
                    
                    image_tasks.append(fetch_image(activity.image_url))
        
        # Run all tasks
        if image_tasks:
            results = await asyncio.gather(*image_tasks)
            for url, data in results:
                if data:
                    image_map[url] = data

    # 2. Generate PDF
    pdf = ItineraryPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    
    # Title
    pdf.set_font("helvetica", "B", 24)
    pdf.set_text_color(31, 41, 55) # Gray-800
    pdf.cell(0, 10, f"Trip to {itinerary.city}", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(5)
    
    # Summary Badge
    pdf.set_fill_color(5, 150, 105) # Emerald-600
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("helvetica", "B", 12)
    # Estimate width of text
    total_str = f" Total Estimated Cost: ${itinerary.total_cost} "
    width = pdf.get_string_width(total_str) + 10
    pdf.set_x((210 - width) / 2) # Center
    pdf.cell(width, 8, total_str, fill=True, align='C', new_x="LMARGIN", new_y="NEXT", border=0)
    pdf.ln(10)
    
    # Reset Colors
    pdf.set_text_color(0, 0, 0)

    # Days
    for day in itinerary.days:
        # Smart Break for Header: Ensure space for Header (15mm) + 1 Activity (~50mm)
        if 297 - pdf.get_y() - 15 < 65:
            pdf.add_page()

        # Day Header
        pdf.set_fill_color(239, 246, 255) # Blue-50
        pdf.rect(10, pdf.get_y(), 190, 8, 'F')
        
        pdf.set_font("helvetica", "B", 16)
        pdf.set_text_color(37, 99, 235) # Blue-600
        pdf.cell(100, 8, f" Day {day.day_number}", border=0)
        
        pdf.set_text_color(75, 85, 99) # Gray-600
        pdf.set_font("helvetica", "", 12)
        day_cost = sum(a.cost for a in day.activities if a.cost)
        pdf.cell(90, 8, f"${day_cost}   ", align='R', new_x="LMARGIN", new_y="NEXT", border=0)
        pdf.ln(5)
        
        for activity in day.activities:
            # Smart Page Break for Activity
            # A4 Height (297) - Bottom Margin (15) - Current Y < Needed (50mm for img)
            if 297 - pdf.get_y() - 15 < 50:
                pdf.add_page()

            # Layout: Image Left (60mm), Text Right
            start_y = pdf.get_y()
            
            # Content Box (Right - starts at 80mm from left margin)
            pdf.set_left_margin(80) 
            pdf.set_font("helvetica", "B", 12)
            pdf.set_text_color(0, 0, 0)
            pdf.cell(0, 6, activity.name, new_x="LMARGIN", new_y="NEXT")
            
            pdf.set_font("helvetica", "", 10)
            pdf.set_text_color(55, 65, 81)
            pdf.multi_cell(0, 5, activity.description)
            pdf.ln(2)
            
            # Meta tags
            pdf.set_font("helvetica", "B", 9)
            pdf.set_text_color(5, 150, 105) # Green
            if activity.cost:
                 pdf.cell(20, 5, f"${activity.cost}")
            pdf.set_text_color(107, 114, 128) # Gray
            if activity.duration_str:
                 pdf.cell(30, 5, f" {activity.duration_str}")
            
            # Record height
            end_y = pdf.get_y()
            
            # Render Image (Left)
            pdf.set_left_margin(10)
            pdf.set_y(start_y)
            
            if activity.image_url and activity.image_url in image_map:
                try:
                    img_data = io.BytesIO(image_map[activity.image_url])
                    # Fixed size 60x45 (Smaller)
                    pdf.image(img_data, x=10, y=start_y, w=60, h=45)
                except Exception:
                     pdf.set_font("helvetica", "I", 8)
                     pdf.cell(60, 45, "(Image Error)", border=1, align='C')
            else:
                 # Placeholder if no image
                 pdf.set_font("helvetica", "I", 8)
                 pdf.set_text_color(156, 163, 175)
                 pdf.cell(60, 45, "(No Image)", border=1, align='C')
            
            # Move cursor to bottom of section
            max_y = max(start_y + 45, end_y)
            pdf.set_y(max_y + 8) # 8mm gap

            # Add separator
            pdf.set_draw_color(229, 231, 235)
            pdf.line(10, max_y + 4, 200, max_y + 4)
            
    # Output
    pdf_bytes = bytes(pdf.output())
    
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=Trip_to_{itinerary.city}.pdf"}
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
