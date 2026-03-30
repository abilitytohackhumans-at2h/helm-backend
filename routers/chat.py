"""Chat router — Real-time conversation with individual agents."""
import json
import anthropic
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from config import settings
from auth import AuthUser, get_current_user, require_workspace_access
from supabase import create_client

router = APIRouter()
sb = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)


class ChatMessage(BaseModel):
    workspace_id: str
    agent_slug: str
    message: str
    conversation_id: str | None = None  # None = new conversation


class ConversationMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str


@router.post("/send")
async def chat_send(req: ChatMessage, user: AuthUser = Depends(get_current_user)):
    """Send a message to an agent and get a streaming response."""
    await require_workspace_access(req.workspace_id, user)

    # Load agent
    agent = sb.table("agents").select("*").eq(
        "workspace_id", req.workspace_id
    ).eq("slug", req.agent_slug).single().execute()
    if not agent.data:
        raise HTTPException(404, f"Agente '{req.agent_slug}' no encontrado")

    agent_data = agent.data

    # Load workspace briefing
    ws = sb.table("workspaces").select("briefing").eq("id", req.workspace_id).single().execute()
    briefing = (ws.data or {}).get("briefing") or {}

    # Build system prompt with briefing
    system_prompt = agent_data["system_prompt"]
    if briefing and any(briefing.values()):
        lines = ["\n\n## Contexto del cliente"]
        if briefing.get("industry"):
            lines.append(f"- Sector: {briefing['industry']}")
        if briefing.get("target_audience"):
            lines.append(f"- Publico objetivo: {briefing['target_audience']}")
        if briefing.get("brand_tone"):
            lines.append(f"- Tono de marca: {briefing['brand_tone']}")
        if briefing.get("brand_values"):
            vals = briefing["brand_values"] if isinstance(briefing["brand_values"], list) else [briefing["brand_values"]]
            lines.append(f"- Valores: {', '.join(vals)}")
        if briefing.get("products_services"):
            lines.append(f"- Productos/servicios: {briefing['products_services']}")
        if briefing.get("preferred_language"):
            lines.append(f"- Idioma preferido: {briefing['preferred_language']}")
        if briefing.get("extra_context"):
            lines.append(f"- Info adicional: {briefing['extra_context']}")
        lines.append("\nUSA este contexto para personalizar todas tus respuestas.")
        system_prompt += "\n".join(lines)

    # Get or create conversation
    conv_id = req.conversation_id
    messages = []

    if conv_id:
        # Load existing messages
        existing = sb.table("chat_messages").select("role, content").eq(
            "conversation_id", conv_id
        ).order("created_at").execute()
        messages = [{"role": m["role"], "content": m["content"]} for m in (existing.data or [])]
    else:
        # Create new conversation
        conv = sb.table("chat_conversations").insert({
            "workspace_id": req.workspace_id,
            "agent_slug": req.agent_slug,
            "agent_name": agent_data["name"],
            "user_id": user.user_id,
            "title": req.message[:80],
        }).execute()
        conv_id = conv.data[0]["id"]

    # Add user message
    messages.append({"role": "user", "content": req.message})
    sb.table("chat_messages").insert({
        "conversation_id": conv_id,
        "role": "user",
        "content": req.message,
    }).execute()

    # Stream response from Claude
    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    async def generate():
        full_response = ""
        tokens_used = 0

        # Send conversation_id first
        yield f"data: {json.dumps({'type': 'conversation_id', 'id': conv_id})}\n\n"

        with client.messages.stream(
            model=settings.MODEL_NAME,
            max_tokens=4096,
            system=system_prompt,
            messages=messages,
        ) as stream:
            for text in stream.text_stream:
                full_response += text
                yield f"data: {json.dumps({'type': 'text', 'content': text})}\n\n"

            # Get final message for token count
            final = stream.get_final_message()
            tokens_used = final.usage.input_tokens + final.usage.output_tokens

        # Save assistant message
        sb.table("chat_messages").insert({
            "conversation_id": conv_id,
            "role": "assistant",
            "content": full_response,
            "tokens_used": tokens_used,
        }).execute()

        # Update conversation timestamp
        sb.table("chat_conversations").update({
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", conv_id).execute()

        # Send done event
        yield f"data: {json.dumps({'type': 'done', 'tokens_used': tokens_used})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.get("/conversations")
async def list_conversations(workspace_id: str, user: AuthUser = Depends(get_current_user)):
    """List all conversations for a workspace."""
    await require_workspace_access(workspace_id, user)

    convs = sb.table("chat_conversations").select("*").eq(
        "workspace_id", workspace_id
    ).order("updated_at", desc=True).limit(50).execute()

    return {"conversations": convs.data or []}


@router.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: str, user: AuthUser = Depends(get_current_user)):
    """Get all messages in a conversation."""
    conv = sb.table("chat_conversations").select("*").eq("id", conversation_id).single().execute()
    if not conv.data:
        raise HTTPException(404, "Conversacion no encontrada")

    await require_workspace_access(conv.data["workspace_id"], user)

    messages = sb.table("chat_messages").select("*").eq(
        "conversation_id", conversation_id
    ).order("created_at").execute()

    return {
        "conversation": conv.data,
        "messages": messages.data or [],
    }


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str, user: AuthUser = Depends(get_current_user)):
    """Delete a conversation and its messages."""
    conv = sb.table("chat_conversations").select("workspace_id").eq("id", conversation_id).single().execute()
    if not conv.data:
        raise HTTPException(404, "Conversacion no encontrada")

    await require_workspace_access(conv.data["workspace_id"], user)

    sb.table("chat_messages").delete().eq("conversation_id", conversation_id).execute()
    sb.table("chat_conversations").delete().eq("id", conversation_id).execute()

    return {"ok": True}
