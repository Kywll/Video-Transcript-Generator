from fastapi import APIRouter, Header, HTTPException
from backend.database.supabase_client import supabase
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter()

@router.post("/save-api-keys")
async def save_api_keys(
    payload: dict,
    authorization: str = Header(None)
):
    logger.info("Save API keys request received")
    if not authorization:
        logger.warning("No authorization header")
        raise HTTPException(401)

    token = authorization.replace("Bearer ", "")
    try:
        user = supabase.auth.get_user(token)
        user_id = user.user.id
        logger.info(f"User ID: {user_id}")
        logger.info(f"Payload: {payload}")

        result = supabase.table("profiles").upsert({
            "id": user_id,
            "elevenlabs_api_key": payload.get("elevenlabs_api_key"),
            "rapidapi_key": payload.get("rapidapi_key")
        }).execute()
        logger.info(f"Supabase result: {result}")
    except Exception as e:
        logger.error(f"Error saving API keys: {e}")
        raise HTTPException(500, detail=str(e))

    return {"success": True}

@router.get("/get-api-keys")
async def get_api_keys(
    authorization: str = Header(None)
):
    logger.info("Get API keys request received")
    if not authorization:
        logger.warning("No authorization header")
        raise HTTPException(401)

    token = authorization.replace("Bearer ", "")
    try:
        user = supabase.auth.get_user(token)
        user_id = user.user.id
        logger.info(f"User ID: {user_id}")

        response = supabase.table("profiles").select("*").eq("id", user_id).execute()
        logger.info(f"Supabase response: {response}")
        profile = response.data[0] if response.data else None
        logger.info(f"Profile: {profile}")

        return {
            "elevenlabs_api_key": profile.get("elevenlabs_api_key") if profile else None,
            "rapidapi_key": profile.get("rapidapi_key") if profile else None
        }
    except Exception as e:
        logger.error(f"Error getting API keys: {e}")
        raise HTTPException(500, detail=str(e))

@router.post("/delete-api-key")
async def delete_api_key(
    payload: dict,
    authorization: str = Header(None)
):
    if not authorization:
        raise HTTPException(401)

    token = authorization.replace("Bearer ", "")
    user = supabase.auth.get_user(token)
    user_id = user.user.id

    key_type = payload.get("key_type")  # "elevenlabs_api_key" or "rapidapi_key"
    if not key_type:
        raise HTTPException(400, detail="key_type is required")

    supabase.table("profiles").upsert({
        "id": user_id,
        key_type: None
    }).execute()

    return {"success": True}