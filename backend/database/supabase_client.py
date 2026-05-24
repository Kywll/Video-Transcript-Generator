from supabase import create_client
import os
from pathlib import Path
from dotenv import load_dotenv

# Try to load .env from backend directory first, then project root
base_dir = Path(__file__).parent.parent  # backend/
project_root = base_dir.parent  # Tiktok Transcript/

print("Loading .env from:", base_dir / ".env", "and", project_root / ".env")
load_dotenv(base_dir / ".env")
load_dotenv(project_root / ".env")

url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_SERVICE_KEY")

print("SUPABASE_URL:", url)
print("SUPABASE_SERVICE_KEY:", "Loaded" if key else "NOT FOUND")

supabase = create_client(url, key)