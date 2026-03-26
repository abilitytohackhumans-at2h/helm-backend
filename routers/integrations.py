"""
Integration router — OAuth flows for external services (Instagram, etc.)
"""
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from config import settings
from auth import get_current_user, require_workspace_access, AuthUser
from utils.encryption import encrypt_token, decrypt_token
from services.instagram import exchange_code_for_token, get_instagram_account
from supabase import create_client

router = APIRouter()
sb = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)


# ─── Instagram OAuth ─────────────────────────────────────────────

class InstagramCallbackRequest(BaseModel):
    code: str
    workspace_id: str
    redirect_uri: str


@router.get("/instagram/auth-url")
async def get_instagram_auth_url(
    workspace_id: str,
    redirect_uri: str,
    user: AuthUser = Depends(get_current_user),
):
    """Generate the Facebook OAuth URL for Instagram Business login."""
    await require_workspace_access(workspace_id, user)

    scopes = ",".join([
        "instagram_business_basic",
        "instagram_business_content_publish",
        "instagram_business_manage_comments",
        "instagram_business_manage_insights",
        "pages_show_list",
        "pages_read_engagement",
    ])

    auth_url = (
        f"https://www.facebook.com/v21.0/dialog/oauth"
        f"?client_id={settings.FACEBOOK_APP_ID}"
        f"&redirect_uri={redirect_uri}"
        f"&scope={scopes}"
        f"&state={workspace_id}"
        f"&response_type=code"
    )

    return {"auth_url": auth_url}


@router.post("/instagram/callback")
async def instagram_oauth_callback(
    body: InstagramCallbackRequest,
    user: AuthUser = Depends(get_current_user),
):
    """Exchange OAuth code for token and store encrypted."""
    await require_workspace_access(body.workspace_id, user)

    try:
        # 1. Exchange code for long-lived token
        token_data = await exchange_code_for_token(body.code, body.redirect_uri)
        access_token = token_data["access_token"]
        expires_in = token_data["expires_in"]

        # 2. Get Instagram Business Account info
        ig_info = await get_instagram_account(access_token)

        # 3. Calculate expiration
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

        # 4. Encrypt token
        encrypted_token = encrypt_token(access_token)

        # 5. Upsert into workspace_integrations
        existing = sb.table("workspace_integrations").select("id").eq(
            "workspace_id", body.workspace_id
        ).eq("provider", "instagram").execute().data

        integration_data = {
            "workspace_id": body.workspace_id,
            "provider": "instagram",
            "access_token_encrypted": encrypted_token,
            "token_expires_at": expires_at.isoformat(),
            "provider_user_id": ig_info["ig_user_id"],
            "provider_username": ig_info["username"],
            "scopes": [
                "instagram_business_basic",
                "instagram_business_content_publish",
                "instagram_business_manage_comments",
                "instagram_business_manage_insights",
            ],
            "metadata": {
                "page_id": ig_info.get("page_id"),
                "profile_picture_url": ig_info.get("profile_picture_url"),
                "followers_count": ig_info.get("followers_count"),
                "media_count": ig_info.get("media_count"),
            },
            "is_active": True,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        if existing:
            sb.table("workspace_integrations").update(
                integration_data
            ).eq("id", existing[0]["id"]).execute()
        else:
            sb.table("workspace_integrations").insert(integration_data).execute()

        return {
            "connected": True,
            "username": ig_info["username"],
            "profile_picture_url": ig_info.get("profile_picture_url"),
            "followers_count": ig_info.get("followers_count"),
        }

    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error conectando Instagram: {str(e)}")


@router.delete("/instagram")
async def disconnect_instagram(
    workspace_id: str,
    user: AuthUser = Depends(get_current_user),
):
    """Disconnect Instagram for a workspace."""
    await require_workspace_access(workspace_id, user)

    sb.table("workspace_integrations").delete().eq(
        "workspace_id", workspace_id
    ).eq("provider", "instagram").execute()

    return {"disconnected": True}


# ─── Status (generic for all providers) ──────────────────────────

@router.get("/status")
async def get_integration_status(
    workspace_id: str,
    user: AuthUser = Depends(get_current_user),
):
    """Get connection status for all integrations. Never returns tokens."""
    await require_workspace_access(workspace_id, user)

    integrations = sb.table("workspace_integrations").select(
        "provider, provider_username, provider_user_id, is_active, token_expires_at, metadata, updated_at"
    ).eq("workspace_id", workspace_id).execute().data

    status = {}
    for i in integrations:
        status[i["provider"]] = {
            "connected": i["is_active"],
            "username": i.get("provider_username"),
            "user_id": i.get("provider_user_id"),
            "expires_at": i.get("token_expires_at"),
            "metadata": i.get("metadata", {}),
            "updated_at": i.get("updated_at"),
        }

    return status
