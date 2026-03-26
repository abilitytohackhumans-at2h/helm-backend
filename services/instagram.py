"""
Instagram Graph API service layer.
Handles all Instagram API calls: OAuth, publishing, insights, comments.
"""
import httpx
import logging
from config import settings

logger = logging.getLogger("helm.instagram")

GRAPH_API_BASE = "https://graph.facebook.com/v21.0"
GRAPH_IG_BASE = "https://graph.instagram.com/v21.0"


# ─── OAuth & Token Management ───────────────────────────────────

async def exchange_code_for_token(code: str, redirect_uri: str) -> dict:
    """Exchange OAuth authorization code for a long-lived access token.

    Flow: code → short-lived token → long-lived token (60 days)
    """
    async with httpx.AsyncClient(timeout=15.0) as client:
        # Step 1: Exchange code for short-lived token
        resp = await client.get(
            f"{GRAPH_API_BASE}/oauth/access_token",
            params={
                "client_id": settings.FACEBOOK_APP_ID,
                "client_secret": settings.FACEBOOK_APP_SECRET,
                "redirect_uri": redirect_uri,
                "code": code,
            },
        )
        resp.raise_for_status()
        short_lived = resp.json()

        # Step 2: Exchange for long-lived token
        resp2 = await client.get(
            f"{GRAPH_API_BASE}/oauth/access_token",
            params={
                "grant_type": "fb_exchange_token",
                "client_id": settings.FACEBOOK_APP_ID,
                "client_secret": settings.FACEBOOK_APP_SECRET,
                "fb_exchange_token": short_lived["access_token"],
            },
        )
        resp2.raise_for_status()
        long_lived = resp2.json()

        return {
            "access_token": long_lived["access_token"],
            "expires_in": long_lived.get("expires_in", 5184000),  # 60 days default
        }


async def refresh_long_lived_token(token: str) -> dict:
    """Refresh a long-lived Instagram token (must be >24h old and <60 days)."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f"{GRAPH_IG_BASE}/refresh_access_token",
            params={
                "grant_type": "ig_refresh_token",
                "access_token": token,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return {
            "access_token": data["access_token"],
            "expires_in": data.get("expires_in", 5184000),
        }


async def get_instagram_account(access_token: str) -> dict:
    """Get the Instagram Business Account ID and username from the Facebook token.

    Flow: token → /me/accounts (Facebook Pages) → page.instagram_business_account
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        # Get Facebook Pages
        resp = await client.get(
            f"{GRAPH_API_BASE}/me/accounts",
            params={"access_token": access_token, "fields": "id,name,instagram_business_account"},
        )
        resp.raise_for_status()
        pages = resp.json().get("data", [])

        if not pages:
            raise ValueError("No se encontraron páginas de Facebook. Necesitas una página conectada a tu cuenta de Instagram Business.")

        # Find the first page with an Instagram Business Account
        ig_account = None
        page_id = None
        for page in pages:
            if "instagram_business_account" in page:
                ig_account = page["instagram_business_account"]["id"]
                page_id = page["id"]
                break

        if not ig_account:
            raise ValueError("Ninguna página tiene una cuenta de Instagram Business conectada. Ve a la configuración de tu página de Facebook y conecta tu cuenta de Instagram.")

        # Get Instagram username
        resp2 = await client.get(
            f"{GRAPH_API_BASE}/{ig_account}",
            params={"access_token": access_token, "fields": "id,username,profile_picture_url,followers_count,media_count"},
        )
        resp2.raise_for_status()
        ig_data = resp2.json()

        return {
            "ig_user_id": ig_account,
            "username": ig_data.get("username", ""),
            "profile_picture_url": ig_data.get("profile_picture_url", ""),
            "followers_count": ig_data.get("followers_count", 0),
            "media_count": ig_data.get("media_count", 0),
            "page_id": page_id,
        }


# ─── Publishing ──────────────────────────────────────────────────

async def publish_single_image(token: str, ig_user_id: str, image_url: str, caption: str) -> dict:
    """Publish a single image to Instagram.

    Two-step process: create container → publish container.
    Image must be JPEG, max 30MB.
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        # Step 1: Create media container
        resp = await client.post(
            f"{GRAPH_API_BASE}/{ig_user_id}/media",
            params={
                "image_url": image_url,
                "caption": caption,
                "access_token": token,
            },
        )
        resp.raise_for_status()
        container_id = resp.json()["id"]

        # Step 2: Publish
        resp2 = await client.post(
            f"{GRAPH_API_BASE}/{ig_user_id}/media_publish",
            params={
                "creation_id": container_id,
                "access_token": token,
            },
        )
        resp2.raise_for_status()
        media_id = resp2.json()["id"]

        # Get permalink
        resp3 = await client.get(
            f"{GRAPH_API_BASE}/{media_id}",
            params={"fields": "id,permalink", "access_token": token},
        )
        permalink = resp3.json().get("permalink", f"https://instagram.com/p/{media_id}")

        return {"media_id": media_id, "permalink": permalink}


async def publish_carousel(token: str, ig_user_id: str, items: list[dict], caption: str) -> dict:
    """Publish a carousel post to Instagram.

    Three-step process: create children → create parent container → publish.
    Items: list of {"image_url": str, "alt_text"?: str}
    Max 10 items. All must be same aspect ratio.
    """
    if len(items) < 2 or len(items) > 10:
        raise ValueError("Un carrusel necesita entre 2 y 10 imágenes.")

    async with httpx.AsyncClient(timeout=60.0) as client:
        # Step 1: Create child containers
        children_ids = []
        for item in items:
            params = {
                "image_url": item["image_url"],
                "is_carousel_item": "true",
                "access_token": token,
            }
            if item.get("alt_text"):
                params["alt_text"] = item["alt_text"]

            resp = await client.post(
                f"{GRAPH_API_BASE}/{ig_user_id}/media",
                params=params,
            )
            resp.raise_for_status()
            children_ids.append(resp.json()["id"])

        # Step 2: Create carousel container
        resp2 = await client.post(
            f"{GRAPH_API_BASE}/{ig_user_id}/media",
            params={
                "caption": caption,
                "media_type": "CAROUSEL",
                "children": ",".join(children_ids),
                "access_token": token,
            },
        )
        resp2.raise_for_status()
        container_id = resp2.json()["id"]

        # Step 3: Publish
        resp3 = await client.post(
            f"{GRAPH_API_BASE}/{ig_user_id}/media_publish",
            params={
                "creation_id": container_id,
                "access_token": token,
            },
        )
        resp3.raise_for_status()
        media_id = resp3.json()["id"]

        # Get permalink
        resp4 = await client.get(
            f"{GRAPH_API_BASE}/{media_id}",
            params={"fields": "id,permalink", "access_token": token},
        )
        permalink = resp4.json().get("permalink", f"https://instagram.com/p/{media_id}")

        return {"media_id": media_id, "permalink": permalink}


# ─── Insights & Analytics ────────────────────────────────────────

async def get_account_insights(token: str, ig_user_id: str, metrics: list[str] | None = None, period: str = "day") -> dict:
    """Get account-level insights.

    Default metrics: impressions, reach, profile_views, accounts_engaged
    Period: day, week, days_28
    """
    if not metrics:
        metrics = ["impressions", "reach", "profile_views", "accounts_engaged"]

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f"{GRAPH_API_BASE}/{ig_user_id}/insights",
            params={
                "metric": ",".join(metrics),
                "period": period,
                "access_token": token,
            },
        )
        resp.raise_for_status()
        return resp.json()


async def get_media_insights(token: str, media_id: str, metrics: list[str] | None = None) -> dict:
    """Get insights for a specific post."""
    if not metrics:
        metrics = ["impressions", "reach", "saved", "likes", "comments", "shares"]

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f"{GRAPH_API_BASE}/{media_id}/insights",
            params={
                "metric": ",".join(metrics),
                "access_token": token,
            },
        )
        resp.raise_for_status()
        return resp.json()


async def get_media_list(token: str, ig_user_id: str, limit: int = 10) -> list:
    """Get recent media posts."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f"{GRAPH_API_BASE}/{ig_user_id}/media",
            params={
                "fields": "id,caption,media_type,media_url,thumbnail_url,permalink,timestamp,like_count,comments_count",
                "limit": limit,
                "access_token": token,
            },
        )
        resp.raise_for_status()
        return resp.json().get("data", [])


# ─── Comments ────────────────────────────────────────────────────

async def get_comments(token: str, media_id: str) -> list:
    """Get comments on a specific post."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f"{GRAPH_API_BASE}/{media_id}/comments",
            params={
                "fields": "id,text,username,timestamp,like_count,replies{id,text,username,timestamp}",
                "access_token": token,
            },
        )
        resp.raise_for_status()
        return resp.json().get("data", [])


async def reply_to_comment(token: str, comment_id: str, message: str) -> dict:
    """Reply to a comment."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{GRAPH_API_BASE}/{comment_id}/replies",
            params={
                "message": message,
                "access_token": token,
            },
        )
        resp.raise_for_status()
        return resp.json()


async def delete_comment(token: str, comment_id: str) -> dict:
    """Delete a comment."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.delete(
            f"{GRAPH_API_BASE}/{comment_id}",
            params={"access_token": token},
        )
        resp.raise_for_status()
        return {"deleted": True}
