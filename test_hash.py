
from auth_utils import get_password_hash, verify_password

try:
    pwd = "testpassword"
    print(f"Hashing '{pwd}'...")
    hashed = get_password_hash(pwd)
    print(f"Hashed: {hashed}")
    
    print("Verifying...")
    match = verify_password(pwd, hashed)
    print(f"Match: {match}")
    
    assert match is True
    print("SUCCESS")
except Exception as e:
    print(f"FAILED: {e}")
