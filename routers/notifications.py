"""
Notifications router — in-app notifications for super admins.
Tracks events like new client registrations, task completions, etc.
"""
from fastapi import APIRouter, Depends
from config import settings
from supabase import create_client
from auth import AuthUser, get_current_user

router = APIRouter()
sb = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)


@router.get("")
async def list_notifications(user: AuthUser = Depends(get_current_user), limit: int = 20):
    """Get notifications for the authenticated user."""
    return sb.table("notifications").select("*").eq(
        "user_id", user.user_id
    ).order("created_at", desc=True).limit(limit).execute().data


@router.get("/unread-count")
async def unread_count(user: AuthUser = Depends(get_current_user)):
    """Count unread notifications for the authenticated user."""
    result = sb.table("notifications").select("id", count="exact").eq(
        "user_id", user.user_id
    ).eq("read", False).execute()
    return {"count": result.count or 0}


@router.patch("/{notification_id}/read")
async def mark_read(notification_id: str, user: AuthUser = Depends(get_current_user)):
    """Mark a notification as read (only if it belongs to the user)."""
    sb.table("notifications").update({"read": True}).eq(
        "id", notification_id
    ).eq("user_id", user.user_id).execute()
    return {"ok": True}


@router.post("/mark-all-read")
async def mark_all_read(user: AuthUser = Depends(get_current_user)):
    """Mark all notifications as read for the authenticated user."""
    sb.table("notifications").update({"read": True}).eq(
        "user_id", user.user_id
    ).eq("read", False).execute()
    return {"ok": True}


def create_notification(user_id: str, title: str, message: str, type: str = "info", link: str | None = None):
    """Helper to create a notification (called from other routers)."""
    try:
        sb.table("notifications").insert({
            "user_id": user_id,
            "title": title,
            "message": message,
            "type": type,
            "link": link,
            "read": False,
        }).execute()
    except Exception:
        pass


def notify_super_admins(title: str, message: str, type: str = "info", link: str | None = None):
    """Send notification to all super admins."""
    try:
        admins = sb.table("profiles").select("id").eq("is_super_admin", True).execute().data
        for admin in admins:
            create_notification(admin["id"], title, message, type, link)
    except Exception:
        pass
