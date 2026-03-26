"""Profile router — user profile and role checks."""
from fastapi import APIRouter
from config import settings
from supabase import create_client

router = APIRouter()
sb = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)


@router.get("/me")
async def get_profile(user_id: str):
    """Get user profile with super_admin flag."""
    profile = sb.table("profiles").select("*").eq("id", user_id).single().execute().data
    if not profile:
        # Auto-create profile if missing
        user = sb.auth.admin.get_user_by_id(user_id)
        profile = sb.table("profiles").insert({
            "id": user_id,
            "email": user.user.email if user else "",
            "is_super_admin": False,
        }).execute().data[0]
    return profile


@router.patch("/me")
async def update_profile(user_id: str, updates: dict):
    """Update user profile (full_name, avatar_url)."""
    allowed = {"full_name", "avatar_url"}
    filtered = {k: v for k, v in updates.items() if k in allowed}
    if not filtered:
        return {"ok": False, "message": "No valid fields"}
    return sb.table("profiles").update(filtered).eq("id", user_id).execute().data


@router.get("/me/workspaces")
async def get_user_workspaces(user_id: str):
    """Get all workspaces this user has access to."""
    memberships = sb.table("workspace_members").select(
        "role, workspaces(*)"
    ).eq("user_id", user_id).execute().data

    result = []
    for m in memberships:
        ws = m.get("workspaces")
        if ws:
            ws["role"] = m["role"]
            result.append(ws)
    return result
