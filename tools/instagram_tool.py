"""
Instagram tools for HELM agents.
Each tool fetches the workspace's encrypted token, decrypts it,
and calls the Instagram service layer.
"""
import logging
from config import settings
from supabase import create_client
from utils.encryption import decrypt_token

logger = logging.getLogger("helm.tools.instagram")
sb = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)


async def _get_ig_credentials(workspace_id: str) -> tuple[str, str]:
    """Get decrypted Instagram token and IG user ID for a workspace."""
    row = sb.table("workspace_integrations").select("*").eq(
        "workspace_id", workspace_id
    ).eq("provider", "instagram").eq("is_active", True).execute().data

    if not row:
        raise ValueError(
            "Instagram no conectado. Ve a Configuracion > Integraciones para conectar tu cuenta de Instagram Business."
        )

    integration = row[0]
    token = decrypt_token(integration["access_token_encrypted"])
    ig_user_id = integration["provider_user_id"]

    if not ig_user_id:
        raise ValueError("No se encontro el ID de la cuenta de Instagram. Reconecta tu cuenta.")

    return token, ig_user_id


# ─── Tool 1: Publish ────────────────────────────────────────────

async def instagram_publish(workspace_id: str, inputs: dict) -> str:
    """Publish an image or carousel to Instagram."""
    from services.instagram import publish_single_image, publish_carousel

    token, ig_user_id = await _get_ig_credentials(workspace_id)
    caption = inputs.get("caption", "")
    items = inputs.get("items")
    image_url = inputs.get("image_url")

    try:
        if items and len(items) >= 2:
            # Carousel
            result = await publish_carousel(token, ig_user_id, items, caption)
            return f"Carrusel publicado exitosamente en Instagram.\nURL: {result['permalink']}\nMedia ID: {result['media_id']}"
        elif image_url:
            # Single image
            result = await publish_single_image(token, ig_user_id, image_url, caption)
            return f"Imagen publicada exitosamente en Instagram.\nURL: {result['permalink']}\nMedia ID: {result['media_id']}"
        else:
            return "Error: Debes proporcionar image_url para una imagen, o items (lista de 2-10 imagenes) para un carrusel."
    except Exception as e:
        logger.error(f"Instagram publish error: {e}")
        return f"Error al publicar en Instagram: {str(e)}"


INSTAGRAM_PUBLISH_TOOL = {
    "name": "instagram_publish",
    "description": "Publica una imagen o carrusel en Instagram Business. Para imagen sola usa image_url + caption. Para carrusel usa items (lista de 2-10 imagenes) + caption. Las imagenes deben ser URLs publicas en formato JPEG.",
    "input_schema": {
        "type": "object",
        "properties": {
            "image_url": {
                "type": "string",
                "description": "URL publica de la imagen JPEG (para post de imagen sola)"
            },
            "caption": {
                "type": "string",
                "description": "Texto del post de Instagram (max 2200 caracteres). Incluye hashtags relevantes."
            },
            "items": {
                "type": "array",
                "description": "Para carrusel: lista de 2-10 objetos con image_url y opcionalmente alt_text",
                "items": {
                    "type": "object",
                    "properties": {
                        "image_url": {"type": "string", "description": "URL publica de la imagen JPEG"},
                        "alt_text": {"type": "string", "description": "Texto alternativo para accesibilidad"}
                    },
                    "required": ["image_url"]
                }
            }
        },
        "required": ["caption"]
    }
}


# ─── Tool 2: Get Insights ───────────────────────────────────────

async def instagram_get_insights(workspace_id: str, inputs: dict) -> str:
    """Get Instagram account or post insights."""
    from services.instagram import get_account_insights, get_media_insights, get_media_list

    token, ig_user_id = await _get_ig_credentials(workspace_id)
    level = inputs.get("level", "account")
    media_id = inputs.get("media_id")

    try:
        if level == "media" and media_id:
            data = await get_media_insights(token, media_id)
            metrics = data.get("data", [])
            lines = [f"📊 Insights del post {media_id}:"]
            for m in metrics:
                lines.append(f"  - {m['name']}: {m['values'][0]['value'] if m.get('values') else 'N/A'}")
            return "\n".join(lines)

        elif level == "recent_posts":
            posts = await get_media_list(token, ig_user_id, limit=inputs.get("limit", 5))
            lines = [f"📱 Ultimos {len(posts)} posts de Instagram:"]
            for p in posts:
                caption_preview = (p.get("caption", "") or "")[:80]
                lines.append(f"  - [{p['media_type']}] {caption_preview}...")
                lines.append(f"    ❤️ {p.get('like_count', 0)} likes · 💬 {p.get('comments_count', 0)} comments")
                lines.append(f"    🔗 {p.get('permalink', '')}")
                lines.append(f"    ID: {p['id']}")
            return "\n".join(lines)

        else:
            # Account insights
            data = await get_account_insights(
                token, ig_user_id,
                metrics=inputs.get("metrics"),
                period=inputs.get("period", "day"),
            )
            metrics = data.get("data", [])
            lines = ["📊 Insights de la cuenta de Instagram:"]
            for m in metrics:
                values = m.get("values", [])
                if values:
                    lines.append(f"  - {m['name']} ({m.get('period', '')}): {values[-1]['value']}")
            return "\n".join(lines) if len(lines) > 1 else "No se encontraron metricas. Es posible que la cuenta tenga menos de 100 seguidores."

    except Exception as e:
        logger.error(f"Instagram insights error: {e}")
        return f"Error al obtener insights: {str(e)}"


INSTAGRAM_GET_INSIGHTS_TOOL = {
    "name": "instagram_get_insights",
    "description": "Obtiene metricas y analytics de Instagram Business. Puede mostrar insights de la cuenta (alcance, impresiones, engagement), listar posts recientes, o ver metricas de un post especifico.",
    "input_schema": {
        "type": "object",
        "properties": {
            "level": {
                "type": "string",
                "enum": ["account", "media", "recent_posts"],
                "description": "Tipo de insights: 'account' para metricas globales, 'media' para un post especifico, 'recent_posts' para listar los ultimos posts"
            },
            "media_id": {
                "type": "string",
                "description": "ID del post (requerido cuando level='media')"
            },
            "metrics": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Metricas especificas a consultar (opcional, por defecto: impressions, reach, profile_views)"
            },
            "period": {
                "type": "string",
                "enum": ["day", "week", "days_28"],
                "description": "Periodo de tiempo para metricas de cuenta"
            },
            "limit": {
                "type": "integer",
                "description": "Numero de posts recientes a mostrar (default 5)"
            }
        },
        "required": []
    }
}


# ─── Tool 3: Read Comments ──────────────────────────────────────

async def instagram_read_comments(workspace_id: str, inputs: dict) -> str:
    """Read comments from an Instagram post."""
    from services.instagram import get_comments, get_media_list

    token, ig_user_id = await _get_ig_credentials(workspace_id)
    media_id = inputs.get("media_id")

    try:
        # If no media_id, get latest post
        if not media_id:
            posts = await get_media_list(token, ig_user_id, limit=1)
            if not posts:
                return "No se encontraron posts en esta cuenta."
            media_id = posts[0]["id"]

        comments = await get_comments(token, media_id)

        if not comments:
            return f"No hay comentarios en el post {media_id}."

        lines = [f"💬 Comentarios del post {media_id} ({len(comments)} total):"]
        for c in comments:
            lines.append(f"  @{c.get('username', '?')}: {c['text']}")
            lines.append(f"    ❤️ {c.get('like_count', 0)} likes | ID: {c['id']}")

            # Show replies
            replies = c.get("replies", {}).get("data", [])
            for r in replies:
                lines.append(f"      ↳ @{r.get('username', '?')}: {r['text']}")

        return "\n".join(lines)

    except Exception as e:
        logger.error(f"Instagram read comments error: {e}")
        return f"Error al leer comentarios: {str(e)}"


INSTAGRAM_READ_COMMENTS_TOOL = {
    "name": "instagram_read_comments",
    "description": "Lee los comentarios de un post de Instagram. Si no se especifica media_id, muestra los comentarios del post mas reciente.",
    "input_schema": {
        "type": "object",
        "properties": {
            "media_id": {
                "type": "string",
                "description": "ID del post de Instagram. Si se omite, usa el post mas reciente."
            }
        },
        "required": []
    }
}


# ─── Tool 4: Reply to Comment ───────────────────────────────────

async def instagram_reply_comment(workspace_id: str, inputs: dict) -> str:
    """Reply to a comment on Instagram."""
    from services.instagram import reply_to_comment

    token, _ = await _get_ig_credentials(workspace_id)
    comment_id = inputs.get("comment_id")
    message = inputs.get("message")

    if not comment_id or not message:
        return "Error: Se requiere comment_id y message para responder a un comentario."

    try:
        result = await reply_to_comment(token, comment_id, message)
        return f"Respuesta enviada exitosamente al comentario {comment_id}.\nReply ID: {result.get('id', 'N/A')}"
    except Exception as e:
        logger.error(f"Instagram reply error: {e}")
        return f"Error al responder comentario: {str(e)}"


INSTAGRAM_REPLY_COMMENT_TOOL = {
    "name": "instagram_reply_comment",
    "description": "Responde a un comentario en un post de Instagram. Necesitas el comment_id (usa instagram_read_comments para obtenerlo) y el mensaje de respuesta.",
    "input_schema": {
        "type": "object",
        "properties": {
            "comment_id": {
                "type": "string",
                "description": "ID del comentario al que responder"
            },
            "message": {
                "type": "string",
                "description": "Texto de la respuesta"
            }
        },
        "required": ["comment_id", "message"]
    }
}
