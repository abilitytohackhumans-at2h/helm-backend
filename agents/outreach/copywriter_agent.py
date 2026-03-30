"""Agent 4: Copywriter - Genera mensajes personalizados por canal."""
import json
import anthropic
from config import settings

EMAIL_SYSTEM = """Eres el agente de outreach de WeNeedToEat, una carta digital para restaurantes.

WeNeedToEat lleva 5 anos validado en restaurantes de Madrid. El producto
digitaliza la carta con soporte multiidioma, QR dinamico y analytics.

Tu mision: escribir un email de primer contacto para un restaurante target.
El restaurante NO sabe que vas a escribirles. No son leads calientes.

REGLAS ABSOLUTAS:
- Maximo 120 palabras en el cuerpo del email.
- NO empieces con "Hola, me llamo..." ni presentaciones genericas.
- Empieza con una observacion especifica del restaurante (rating, zona, tipo).
- Menciona solo un beneficio concreto de WeNeedToEat.
- Termina con UNA sola llamada a accion: demo de 15 minutos.
- Tono: directo, respetuoso, peer-to-peer. No vendedor.
- Idioma: espanol. Si el restaurante tiene senales turisticas altas, anade
  una linea final en ingles.

OUTPUT: JSON con dos campos: "subject" y "body". Solo JSON, sin markdown."""

WHATSAPP_SYSTEM = """Eres el agente de outreach de WeNeedToEat para mensajes WhatsApp.

REGLAS ABSOLUTAS:
- Maximo 3 frases. Literalmente 3.
- Primera frase: quien eres en 5 palabras.
- Segunda frase: beneficio especifico para ese restaurante.
- Tercera frase: pregunta simple de si/no para abrir conversacion.
- Sin emojis excesivos. Maximo 1.
- Tono: como si escribieras a un colega del sector.

OUTPUT: JSON con campo "message". Solo JSON, sin markdown."""

INSTAGRAM_SYSTEM = """Eres el agente de outreach de WeNeedToEat para Instagram Direct.

REGLAS ABSOLUTAS:
- Maximo 2 frases.
- Tono casual pero profesional. Eres fan de su restaurante.
- Menciona algo especifico que podrias haber visto en su perfil.
- No menciones "ventas" ni "demo". Solo curiosidad / conversacion.
- El objetivo es que respondan, no vender en el primer mensaje.

OUTPUT: JSON con campo "message". Solo JSON, sin markdown."""

CHANNEL_PROMPTS = {
    "email": EMAIL_SYSTEM,
    "whatsapp": WHATSAPP_SYSTEM,
    "instagram_dm": INSTAGRAM_SYSTEM,
}


async def generate_message(lead: dict, restaurant: dict, channel: str = None) -> dict:
    """Genera mensaje personalizado para un lead."""
    ch = channel or lead.get("preferred_channel", "email")
    system = CHANNEL_PROMPTS.get(ch, EMAIL_SYSTEM)

    profile = {
        "name": restaurant.get("name"),
        "zone": restaurant.get("zone"),
        "city": restaurant.get("city"),
        "category": restaurant.get("category"),
        "google_rating": restaurant.get("google_rating"),
        "review_count": restaurant.get("review_count"),
        "segment": lead.get("segment"),
        "has_digital_menu": restaurant.get("has_digital_menu"),
        "languages_detected": restaurant.get("languages_detected"),
        "instagram_handle": restaurant.get("instagram_handle"),
    }

    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    response = client.messages.create(
        model=settings.MODEL_NAME,
        max_tokens=500,
        system=system,
        messages=[{"role": "user", "content": json.dumps(profile, ensure_ascii=False)}],
    )

    text = response.content[0].text
    tokens = response.usage.input_tokens + response.usage.output_tokens

    # Parse JSON response
    try:
        message_data = json.loads(text)
    except json.JSONDecodeError:
        # Try to extract JSON from the response
        import re
        json_match = re.search(r'\{.*\}', text, re.DOTALL)
        if json_match:
            message_data = json.loads(json_match.group())
        else:
            message_data = {"body": text} if ch != "email" else {"subject": "WeNeedToEat", "body": text}

    return {
        "channel": ch,
        "message": message_data,
        "tokens_used": tokens,
    }
