"""Profile router — user profile and role checks."""
from fastapi import APIRouter, Depends
from config import settings
from supabase import create_client
from auth import AuthUser, get_current_user

router = APIRouter()
sb = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)


@router.get("/me")
async def get_profile(user: AuthUser = Depends(get_current_user)):
    """Get user profile with super_admin flag."""
    profile = sb.table("profiles").select("*").eq("id", user.user_id).single().execute().data
    if not profile:
        # Auto-create profile if missing
        try:
            auth_user = sb.auth.admin.get_user_by_id(user.user_id)
            email = auth_user.user.email if auth_user else user.email
        except Exception:
            email = user.email
        profile = sb.table("profiles").insert({
            "id": user.user_id,
            "email": email,
            "is_super_admin": False,
        }).execute().data[0]
    return profile


@router.patch("/me")
async def update_profile(updates: dict, user: AuthUser = Depends(get_current_user)):
    """Update user profile (full_name, avatar_url)."""
    allowed = {"full_name", "avatar_url"}
    filtered = {k: v for k, v in updates.items() if k in allowed}
    if not filtered:
        return {"ok": False, "message": "No valid fields"}
    return sb.table("profiles").update(filtered).eq("id", user.user_id).execute().data


@router.get("/me/workspaces")
async def get_user_workspaces(user: AuthUser = Depends(get_current_user)):
    """Get all workspaces this user has access to."""
    memberships = sb.table("workspace_members").select(
        "role, workspaces(*)"
    ).eq("user_id", user.user_id).execute().data

    result = []
    for m in memberships:
        ws = m.get("workspaces")
        if ws:
            ws["role"] = m["role"]
            result.append(ws)
    return result
