"""Agent 5: Sender - Envia mensajes por email, WhatsApp o Instagram DM."""
import smtplib
import httpx
import json
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone
from config import settings


async def send_email(to_email: str, subject: str, body: str) -> dict:
    """Envia email via SMTP."""
    smtp_host = getattr(settings, 'SMTP_HOST', 'smtp.gmail.com')
    smtp_port = int(getattr(settings, 'SMTP_PORT', 587))
    smtp_user = getattr(settings, 'SMTP_USER', '')
    smtp_pass = getattr(settings, 'SMTP_PASS', '')

    if not smtp_user or not smtp_pass:
        return {"status": "failed", "error": "SMTP no configurado"}

    try:
        msg = MIMEMultipart()
        msg['From'] = smtp_user
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain', 'utf-8'))

        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)

        return {"status": "sent", "sent_at": datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        return {"status": "failed", "error": str(e)}


async def send_whatsapp(phone: str, message: str) -> dict:
    """Envia WhatsApp via Meta Business Cloud API."""
    token = getattr(settings, 'WHATSAPP_TOKEN', '')
    phone_id = getattr(settings, 'WHATSAPP_PHONE_ID', '')

    if not token or not phone_id:
        return {"status": "failed", "error": "WhatsApp Business API no configurado"}

    # Clean phone number
    clean_phone = phone.replace(" ", "").replace("-", "").replace("+", "")
    if not clean_phone.startswith("34"):
        clean_phone = "34" + clean_phone

    url = f"https://graph.facebook.com/v18.0/{phone_id}/messages"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {
        "messaging_product": "whatsapp",
        "to": clean_phone,
        "type": "text",
        "text": {"body": message}
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code == 200:
                return {"status": "sent", "sent_at": datetime.now(timezone.utc).isoformat()}
            else:
                return {"status": "failed", "error": resp.text}
    except Exception as e:
        return {"status": "failed", "error": str(e)}


async def send_instagram_dm(ig_handle: str, message: str, access_token: str = None) -> dict:
    """Envia DM de Instagram via Meta Graph API."""
    token = access_token or getattr(settings, 'INSTAGRAM_ACCESS_TOKEN', '')

    if not token:
        return {"status": "failed", "error": "Instagram access token no configurado"}

    # First get the user ID from handle
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            # Search for user
            search_url = f"https://graph.facebook.com/v18.0/ig_user_search"
            resp = await client.get(search_url, params={"q": ig_handle, "access_token": token})

            if resp.status_code != 200:
                return {"status": "failed", "error": f"No se pudo encontrar @{ig_handle}"}

            # Note: Instagram DM API has restrictions - may need approved messaging
            return {"status": "failed", "error": "Instagram DM requiere aprobacion de Meta Business. Marcado para envio manual."}
    except Exception as e:
        return {"status": "failed", "error": str(e)}


async def send_message(lead: dict, restaurant: dict, message_data: dict, channel: str) -> dict:
    """Dispatch - envia por el canal indicado."""
    result = None

    if channel == "email":
        email = restaurant.get("email")
        if not email:
            return {"status": "failed", "error": "Sin email"}
        subject = message_data.get("subject", "WeNeedToEat - Carta digital")
        body = message_data.get("body", "")
        result = await send_email(email, subject, body)

    elif channel == "whatsapp":
        phone = restaurant.get("whatsapp_number") or restaurant.get("phone")
        if not phone:
            return {"status": "failed", "error": "Sin telefono"}
        message = message_data.get("message", "")
        result = await send_whatsapp(phone, message)

    elif channel == "instagram_dm":
        ig = restaurant.get("instagram_handle")
        if not ig:
            return {"status": "failed", "error": "Sin Instagram"}
        message = message_data.get("message", "")
        result = await send_instagram_dm(ig, message)

    else:
        result = {"status": "failed", "error": f"Canal {channel} no soportado para envio automatico"}

    return result or {"status": "failed", "error": "Sin resultado"}
