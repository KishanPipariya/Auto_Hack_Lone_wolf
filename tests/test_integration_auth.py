
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, StaticPool
from sqlalchemy.orm import sessionmaker
from database import Base, get_db
from fast_api_server import app
import pytest
import os

# Use an in-memory SQLite database for testing
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, 
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def override_get_db():
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db

client = TestClient(app)

@pytest.fixture(scope="module", autouse=True)
def setup_database():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)

def test_register_user():
    response = client.post(
        "/auth/register",
        json={"email": "test@example.com", "password": "password123"},
    )
    assert response.status_code == 200
    assert "access_token" in response.json()
    assert response.json()["token_type"] == "bearer"

def test_register_duplicate_user():
    # Attempt to register the same user again
    response = client.post(
        "/auth/register",
        json={"email": "test@example.com", "password": "password123"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Email already registered"

def test_login_user():
    response = client.post(
        "/auth/token",
        data={"username": "test@example.com", "password": "password123"},
    )
    assert response.status_code == 200
    assert "access_token" in response.json()

def test_login_wrong_password():
    response = client.post(
        "/auth/token",
        data={"username": "test@example.com", "password": "wrongpassword"},
    )
    assert response.status_code == 401

def test_history_flow():
    # 1. Login to get token
    login_res = client.post(
        "/auth/token",
        data={"username": "test@example.com", "password": "password123"},
    )
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 2. Save History
    history_data = {
        "city": "Paris",
        "days": 3,
        "start_date": "2024-01-01",
        "full_json_blob": {"some": "data"}
    }
    save_res = client.post("/history/", json=history_data, headers=headers)
    assert save_res.status_code == 200
    history_id = save_res.json()["id"]

    # 3. Get History List
    list_res = client.get("/history/", headers=headers)
    assert list_res.status_code == 200
    items = list_res.json()
    assert len(items) >= 1
    assert items[0]["city"] == "Paris"
    assert items[0]["id"] == history_id

    # 4. Get History Detail
    detail_res = client.get(f"/history/{history_id}", headers=headers)
    assert detail_res.status_code == 200
    assert detail_res.json() == {"some": "data"}
