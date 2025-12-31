
import requests
import json

BASE_URL = "http://localhost:8000"

def run():
    print("1. Registering/Login...")
    s = requests.Session()
    # Register/Login
    email = "debug_user@test.com"
    pwd = "password123"
    
    # Try login first
    res = s.post(f"{BASE_URL}/auth/token", data={"username": email, "password": pwd})
    if res.status_code != 200:
        print("Registering...")
        res = s.post(f"{BASE_URL}/auth/register", json={"email": email, "password": pwd})
        if res.status_code != 200:
            print(f"Registration failed: {res.text}")
            return
        res = s.post(f"{BASE_URL}/auth/token", data={"username": email, "password": pwd})
    
    token = res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    print(f"Got token: {token[:10]}...")

    print("\n2. Saving History...")
    payload = {
        "city": "Debug City",
        "days": 3,
        "start_date": "2024-01-01",
        "full_json_blob": {
            "city": "Debug City",
            "days": [{"day_number": 1, "activities": []}],
            "valid": True
        }
    }
    res = s.post(f"{BASE_URL}/history/", json=payload, headers=headers)
    print(f"Save Status: {res.status_code}")
    print(f"Save Response: {res.text}")
    if res.status_code != 200:
        return
        
    history_id = res.json()["id"]

    print(f"\n3. Fetching History Detail {history_id}...")
    res = s.get(f"{BASE_URL}/history/{history_id}", headers=headers)
    print(f"Get Status: {res.status_code}")
    try:
        data = res.json()
        print("Response Keys:", data.keys())
        print("full_json_blob type:", type(data.get("full_json_blob")))
        print("full_json_blob content:", json.dumps(data.get("full_json_blob"), indent=2))
        
        if data.get("full_json_blob") is None:
            print("ERROR: full_json_blob is None!")
        elif isinstance(data.get("full_json_blob"), str):
            print("ERROR: full_json_blob is STRING! Backend deserialize failed.")
        elif isinstance(data.get("full_json_blob"), dict):
            print("SUCCESS: full_json_blob is DICT.")
    except Exception as e:
        print(f"Failed to parse JSON: {e}")
        print("Raw text:", res.text)

if __name__ == "__main__":
    run()
