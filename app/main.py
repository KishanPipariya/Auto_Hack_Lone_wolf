import logging
from logging.handlers import RotatingFileHandler
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from contextlib import asynccontextmanager

from app.core.database import engine, Base
from app.api.routers import auth, history, plan

# Configure Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("travel_agent_server")
handler = RotatingFileHandler("server.log", maxBytes=5 * 1024 * 1024, backupCount=3)
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    logger.info("Database initialized.")
    yield


app = FastAPI(title="Travel Planner Agent API", lifespan=lifespan)

# Mount routers
app.include_router(auth.router)
app.include_router(history.router)
app.include_router(plan.router)

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def read_root():
    return FileResponse("static/index.html")


app.add_middleware(
    CORSMiddleware,  # type: ignore
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health_check():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
