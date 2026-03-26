"""
Notifications router — in-app notifications for super admins.
Tracks events like new client registrations, task completions, etc.
"""
from fastapi import APIRouter
from config import settings
from supabase import create_client

router = APIRouter()
sb = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)


@router.get("")
async def list_notifications(user_id: str, limit: int = 20):
    """Get notifications for a user (most recent first)."""
    return sb.table("notifications").select("*").eq(
        "user_id", user_id
    ).order("created_at", desc=True).limit(limit).execute().data


@router.get("/unread-count")
async def unread_count(user_id: str):
    """Count unread notifications."""
    result = sb.table("notifications").select("id", count="exact").eq(
        "user_id", user_id
    ).eq("read", False).execute()
    return {"count": result.count or 0}


@router.patch("/{notification_id}/read")
async def mark_read(notification_id: str):
    """Mark a notification as read."""
    sb.table("notifications").update({"read": True}).eq("id", notification_id).execute()
    return {"ok": True}


@router.post("/mark-all-read")
async def mark_all_read(user_id: str):
    """Mark all notifications as read for a user."""
    sb.table("notifications").update({"read": True}).eq("user_id", user_id).eq("read", False).execute()
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
        pass  # Don't break flow if notification fails


def notify_super_admins(title: str, message: str, type: str = "info", link: str | None = None):
    """Send notification to all super admins."""
    try:
        admins = sb.table("profiles").select("id").eq("is_super_admin", True).execute().data
        for admin in admins:
            create_notification(admin["id"], title, message, type, link)
    except Exception:
        pass
