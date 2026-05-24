from cryptography.fernet import Fernet
import os
from pathlib import Path
from dotenv import load_dotenv

base_dir = Path(__file__).parent.parent
load_dotenv(base_dir / ".env")

ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")
if not ENCRYPTION_KEY:
    # Generate a key if none exists (only for first run)
    key = Fernet.generate_key()
    print("⚠️  ENCRYPTION_KEY not found! Generated a new one. Add this to your backend/.env:")
    print(f"ENCRYPTION_KEY={key.decode()}")
    ENCRYPTION_KEY = key

cipher = Fernet(ENCRYPTION_KEY)

def encrypt_data(data: str | None) -> str | None:
    if not data:
        return None
    return cipher.encrypt(data.encode()).decode()

def decrypt_data(data: str | None) -> str | None:
    if not data:
        return None
    return cipher.decrypt(data.encode()).decode()