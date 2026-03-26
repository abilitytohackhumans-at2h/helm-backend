"""
Image generation tools for HELM agents.
Supports Freepik API and DALL-E (OpenAI) as providers.
Each workspace stores its own API keys in workspace_integrations.
"""
import base64
import httpx
import logging
import uuid
from config import settings
from supabase import create_client

logger = logging.getLogger("helm.tools.image")
sb = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)


async def _get_freepik_key(workspace_id: str) -> str:
    """Get Freepik API key for a workspace from integrations or env."""
    # First try workspace-level key
    try:
        row = sb.table("workspace_integrations").select("*").eq(
            "workspace_id", workspace_id
        ).eq("provider", "freepik").eq("is_active", True).execute().data
        if row:
            from utils.encryption import decrypt_token
            return decrypt_token(row[0]["access_token_encrypted"])
    except Exception:
        pass

    # Fallback to global env key
    key = getattr(settings, "FREEPIK_API_KEY", "")
    if key and len(key) > 5:
        return key

    return ""


async def _get_openai_key(workspace_id: str) -> str:
    """Get OpenAI API key for a workspace from integrations or env."""
    try:
        row = sb.table("workspace_integrations").select("*").eq(
            "workspace_id", workspace_id
        ).eq("provider", "openai").eq("is_active", True).execute().data
        if row:
            from utils.encryption import decrypt_token
            return decrypt_token(row[0]["access_token_encrypted"])
    except Exception:
        pass

    key = getattr(settings, "OPENAI_API_KEY", "")
    if key and len(key) > 5:
        return key

    return ""


async def _upload_to_storage(image_bytes: bytes, filename: str, workspace_id: str) -> str:
    """Upload image to Supabase Storage and return public URL."""
    try:
        path = f"{workspace_id}/{filename}"
        sb.storage.from_("generated-images").upload(
            path,
            image_bytes,
            {"content-type": "image/png", "upsert": "true"},
        )
        public_url = sb.storage.from_("generated-images").get_public_url(path)
        return public_url
    except Exception as e:
        logger.warning(f"Storage upload failed: {e}")
        return ""


# ─── Freepik Image Generation ───────────────────────────────────────

# Model endpoints and info
FREEPIK_MODELS = {
    # ── Classic ──
    "classic": {
        "endpoint": "/v1/ai/text-to-image",
        "async": False,
        "cost": "1 cr",
        "description": "Classic Fast — rapido, estilos artisticos",
        "sizes": ["square_1_1", "landscape_4_3", "landscape_16_9", "portrait_3_4", "portrait_9_16"],
    },
    # ── Mystic (Freepik exclusive) ──
    "mystic": {
        "endpoint": "/v1/ai/mystic",
        "async": True,
        "cost": "3-5 cr",
        "description": "Mystic 2.5 — ultra-realista, LoRA, 1K/2K/4K",
        "sizes": ["square_1_1", "classic_4_3", "traditional_3_4", "widescreen_16_9", "social_story_9_16"],
    },
    # ── Flux family ──
    "flux-kontext-pro": {
        "endpoint": "/v1/ai/text-to-image/flux-kontext-pro",
        "async": True,
        "cost": "5 cr",
        "description": "Flux Kontext Pro — context-aware, imagen de referencia",
        "sizes": ["square_1_1", "classic_4_3", "traditional_3_4", "widescreen_16_9", "social_story_9_16", "standard_3_2"],
    },
    "flux-2-pro": {
        "endpoint": "/v1/ai/text-to-image/flux-2-pro",
        "async": True,
        "cost": "5 cr",
        "description": "Flux 2 Pro — profesional, hasta 4 imagenes input",
        "sizes": ["square_1_1", "classic_4_3", "traditional_3_4", "widescreen_16_9", "social_story_9_16"],
    },
    "flux-2-turbo": {
        "endpoint": "/v1/ai/text-to-image/flux-2-turbo",
        "async": True,
        "cost": "2 cr",
        "description": "Flux 2 Turbo — rapido y economico",
        "sizes": ["square_1_1", "classic_4_3", "traditional_3_4", "widescreen_16_9", "social_story_9_16"],
    },
    "flux-2-klein": {
        "endpoint": "/v1/ai/text-to-image/flux-2-klein",
        "async": True,
        "cost": "1 cr",
        "description": "Flux 2 Klein — sub-segundo, hasta 4 refs",
        "sizes": ["square_1_1", "classic_4_3", "traditional_3_4", "widescreen_16_9", "social_story_9_16"],
    },
    "flux-pro-1.1": {
        "endpoint": "/v1/ai/text-to-image/flux-pro-v1-1",
        "async": True,
        "cost": "5 cr",
        "description": "Flux Pro 1.1 — calidad premium maxima",
        "sizes": ["square_1_1", "classic_4_3", "traditional_3_4", "widescreen_16_9", "social_story_9_16"],
    },
    "flux-dev": {
        "endpoint": "/v1/ai/text-to-image/flux-dev",
        "async": True,
        "cost": "3 cr",
        "description": "Flux Dev — detallado, alta calidad",
        "sizes": ["square_1_1", "classic_4_3", "traditional_3_4", "widescreen_16_9", "social_story_9_16"],
    },
    "hyperflux": {
        "endpoint": "/v1/ai/text-to-image/hyperflux",
        "async": True,
        "cost": "1 cr",
        "description": "HyperFlux — ultra-rapido (el mas rapido)",
        "sizes": ["square_1_1", "classic_4_3", "traditional_3_4", "widescreen_16_9", "social_story_9_16"],
    },
    # ── Seedream family ──
    "seedream-4.5": {
        "endpoint": "/v1/ai/text-to-image/seedream-v4-5",
        "async": True,
        "cost": "2 cr",
        "description": "Seedream 4.5 — tipografia, posters, hasta 4MP",
        "sizes": ["square_1_1", "classic_4_3", "traditional_3_4", "widescreen_16_9", "social_story_9_16"],
    },
    "seedream-4": {
        "endpoint": "/v1/ai/text-to-image/seedream-v4",
        "async": True,
        "cost": "2 cr",
        "description": "Seedream 4 — next-gen, rapido",
        "sizes": ["square_1_1", "classic_4_3", "traditional_3_4", "widescreen_16_9", "social_story_9_16"],
    },
}


async def _poll_async_task(key: str, task_id: str, max_wait: int = 120) -> dict | None:
    """Poll an async Freepik task until completion."""
    import asyncio
    poll_url = f"https://api.freepik.com/v1/ai/tasks/{task_id}"
    headers = {"x-freepik-api-key": key}

    for _ in range(max_wait // 3):
        await asyncio.sleep(3)
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(poll_url, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                status = data.get("status", "")
                if status == "completed":
                    return data
                elif status in ("failed", "error"):
                    return None
    return None


async def freepik_generate(workspace_id: str, inputs: dict) -> str:
    """Generate images using Freepik AI API."""
    key = await _get_freepik_key(workspace_id)
    if not key:
        return "[Freepik no configurado] Ve a Configuracion > Integraciones para añadir tu API key de Freepik."

    prompt = inputs.get("prompt", "")
    if not prompt:
        return "Error: Se requiere un prompt para generar la imagen."

    negative_prompt = inputs.get("negative_prompt", "")
    num_images = min(inputs.get("num_images", 1), 4)
    size = inputs.get("size", "square_1_1")
    style = inputs.get("style", "")
    model = inputs.get("model", "")
    guidance_scale = inputs.get("guidance_scale", 1.0)
    seed = inputs.get("seed", None)
    colors = inputs.get("colors", [])

    body = {
        "prompt": prompt,
        "num_images": num_images,
        "image": {"size": size},
        "guidance_scale": guidance_scale,
        "filter_nsfw": True,
    }
    if negative_prompt:
        body["negative_prompt"] = negative_prompt
    if style:
        body.setdefault("styling", {})["style"] = style
    if colors:
        body.setdefault("styling", {})["colors"] = [{"hex": c, "weight": 0.5} for c in colors[:5]]
    if seed is not None:
        body["seed"] = seed

    # Select model endpoint
    model_info = FREEPIK_MODELS.get(model, FREEPIK_MODELS["classic"])
    endpoint = f"https://api.freepik.com{model_info['endpoint']}"
    is_async = model_info["async"]

    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(
                endpoint,
                json=body,
                headers={
                    "x-freepik-api-key": key,
                    "Content-Type": "application/json",
                },
            )
            resp.raise_for_status()
            data = resp.json()

        # For async models, poll for completion
        if is_async:
            task_id = data.get("task_id") or data.get("id") or data.get("data", {}).get("task_id")
            if task_id:
                poll_result = await _poll_async_task(key, task_id)
                if poll_result:
                    data = poll_result
                else:
                    return f"[Freepik] La generacion con modelo '{model or 'classic'}' tardo demasiado o fallo. Intenta con 'classic' o 'hyperflux' para resultados mas rapidos."

        results = []
        # Handle both sync and async response formats
        images = data.get("data", [])
        if not isinstance(images, list):
            images = [images] if images else []
        for i, img in enumerate(images):
            b64 = img.get("base64", "")
            if b64:
                image_bytes = base64.b64decode(b64)
                filename = f"freepik_{uuid.uuid4().hex[:8]}.png"
                url = await _upload_to_storage(image_bytes, filename, workspace_id)
                if url:
                    results.append(f"Imagen {i+1}: {url}")
                else:
                    results.append(f"Imagen {i+1}: [generada, {len(image_bytes)} bytes, pero no se pudo subir al storage]")

        if not results:
            return "Freepik no devolvio imagenes. Intenta con un prompt diferente."

        meta = data.get("meta", {})
        seed = meta.get("seed", "N/A")
        img_size = meta.get("image", {})

        model_name = model or "classic"
        model_cost = model_info["cost"]
        header = f"✅ IMAGEN GENERADA CON EXITO via Freepik AI\n"
        header += f"Modelo: {model_name} ({model_info['description']}) | Coste: {model_cost}\n"
        header += f"Prompt: {prompt}\n"
        header += f"Tamaño: {img_size.get('width', '?')}x{img_size.get('height', '?')}px | Seed: {seed}\n\n"
        header += "IMPORTANTE: Incluye SIEMPRE las URLs completas de las imagenes en tu respuesta para que el usuario pueda verlas.\n\n"

        return header + "\n".join(results)

    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401:
            return "[Error Freepik] API key invalida. Verifica tu key en Configuracion > Integraciones."
        elif e.response.status_code == 429:
            return "[Error Freepik] Limite de rate excedido. Espera un momento e intenta de nuevo."
        return f"[Error Freepik] HTTP {e.response.status_code}: {e.response.text[:200]}"
    except Exception as e:
        return f"[Error Freepik] {str(e)[:200]}"


# ─── DALL-E Image Generation ────────────────────────────────────────

async def dalle_generate(workspace_id: str, inputs: dict) -> str:
    """Generate images using OpenAI DALL-E API."""
    key = await _get_openai_key(workspace_id)
    if not key:
        return "[DALL-E no configurado] Ve a Configuracion > Integraciones para añadir tu API key de OpenAI."

    prompt = inputs.get("prompt", "")
    if not prompt:
        return "Error: Se requiere un prompt para generar la imagen."

    size = inputs.get("size", "1024x1024")
    quality = inputs.get("quality", "standard")
    n = min(inputs.get("num_images", 1), 4)

    # Map simple sizes to DALL-E format
    size_map = {
        "square": "1024x1024",
        "landscape": "1792x1024",
        "portrait": "1024x1792",
    }
    size = size_map.get(size, size)

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                "https://api.openai.com/v1/images/generations",
                json={
                    "model": "dall-e-3",
                    "prompt": prompt,
                    "n": 1,  # DALL-E 3 only supports n=1
                    "size": size,
                    "quality": quality,
                    "response_format": "b64_json",
                },
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
            )
            resp.raise_for_status()
            data = resp.json()

        results = []
        for i, img in enumerate(data.get("data", [])):
            b64 = img.get("b64_json", "")
            revised_prompt = img.get("revised_prompt", "")
            if b64:
                image_bytes = base64.b64decode(b64)
                filename = f"dalle_{uuid.uuid4().hex[:8]}.png"
                url = await _upload_to_storage(image_bytes, filename, workspace_id)
                if url:
                    results.append(f"Imagen: {url}")
                else:
                    results.append(f"Imagen: [generada, {len(image_bytes)} bytes]")

            if revised_prompt:
                results.append(f"Prompt revisado por DALL-E: {revised_prompt}")

        if not results:
            return "DALL-E no devolvio imagenes. Intenta con un prompt diferente."

        return f"✅ IMAGEN GENERADA CON EXITO via DALL-E 3\nPrompt: {prompt}\nTamaño: {size}\n\nIMPORTANTE: Incluye SIEMPRE las URLs completas de las imagenes en tu respuesta para que el usuario pueda verlas.\n\n" + "\n".join(results)

    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401:
            return "[Error DALL-E] API key invalida. Verifica tu key en Configuracion > Integraciones."
        elif e.response.status_code == 429:
            return "[Error DALL-E] Limite de rate excedido."
        return f"[Error DALL-E] HTTP {e.response.status_code}: {e.response.text[:200]}"
    except Exception as e:
        return f"[Error DALL-E] {str(e)[:200]}"


# ─── Tool Definitions ────────────────────────────────────────────────

FREEPIK_GENERATE_TOOL = {
    "name": "freepik_generate",
    "description": "Genera imagenes con IA usando Freepik. 12 modelos: classic(1cr), hyperflux(1cr,ultra-rapido), flux-2-klein(1cr,sub-segundo), flux-2-turbo(2cr), seedream-4(2cr), seedream-4.5(2cr,tipografia), flux-dev(3cr), mystic(3-5cr,ultra-realista), flux-kontext-pro(5cr,contexto), flux-2-pro(5cr,profesional), flux-pro-1.1(5cr,premium). Formatos: square, landscape 4:3/16:9, portrait 3:4/9:16, standard 3:2.",
    "input_schema": {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "Descripcion detallada de la imagen a generar. Se mas especifico para mejores resultados."
            },
            "model": {
                "type": "string",
                "description": "Modelo de IA. Ordenados por coste: classic/hyperflux/flux-2-klein(1cr), flux-2-turbo/seedream-4/seedream-4.5(2cr), flux-dev(3cr), mystic(3-5cr), flux-kontext-pro/flux-2-pro/flux-pro-1.1(5cr)",
                "enum": ["classic", "mystic", "flux-kontext-pro", "flux-2-pro", "flux-2-turbo", "flux-2-klein", "flux-pro-1.1", "flux-dev", "hyperflux", "seedream-4.5", "seedream-4"],
                "default": "classic"
            },
            "negative_prompt": {
                "type": "string",
                "description": "Elementos a evitar. Ejemplo: 'blurry, low quality, cartoon, text'"
            },
            "num_images": {
                "type": "integer",
                "description": "Imagenes a generar (1-4). Default: 1",
                "default": 1
            },
            "size": {
                "type": "string",
                "description": "Formato/proporcion de la imagen",
                "enum": ["square_1_1", "classic_4_3", "traditional_3_4", "widescreen_16_9", "social_story_9_16", "standard_3_2"],
                "default": "square_1_1"
            },
            "style": {
                "type": "string",
                "description": "Estilo visual (solo modelo classic). photo, anime, digital-art, comic, fantasy, cyberpunk, 3d, watercolor",
                "enum": ["photo", "anime", "digital-art", "comic", "fantasy", "cyberpunk", "3d", "watercolor"]
            },
            "guidance_scale": {
                "type": "number",
                "description": "Fidelidad al prompt (0.0-2.0). Bajo=mas creatividad IA, Alto=mas fiel al prompt. Default: 1.0",
                "default": 1.0
            },
            "seed": {
                "type": "integer",
                "description": "Semilla para reproducir resultados identicos (0-1000000). Omitir para aleatorio."
            },
            "colors": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Colores dominantes en formato hex. Ejemplo: ['#7F77DD', '#3B82F6', '#000000']. Max 5 colores."
            }
        },
        "required": ["prompt"]
    }
}

DALLE_GENERATE_TOOL = {
    "name": "dalle_generate",
    "description": "Genera imagenes con DALL-E 3 de OpenAI. Crea imagenes de alta calidad, arte conceptual, ilustraciones y diseños creativos. Ideal para ideas originales, conceptos artisticos y visuales unicos.",
    "input_schema": {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "Descripcion detallada de la imagen. DALL-E 3 interpreta prompts creativos muy bien. Ejemplo: 'A futuristic office with AI holographic assistants helping creative professionals'"
            },
            "size": {
                "type": "string",
                "description": "Tamaño de la imagen",
                "enum": ["1024x1024", "1792x1024", "1024x1792"],
                "default": "1024x1024"
            },
            "quality": {
                "type": "string",
                "description": "Calidad: standard (rapido) o hd (mayor detalle)",
                "enum": ["standard", "hd"],
                "default": "standard"
            }
        },
        "required": ["prompt"]
    }
}
