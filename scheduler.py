"""
Cron Scheduler — runs scheduled flows at their cron times.
Runs as a background asyncio task inside the FastAPI process.
Checks every 60 seconds for flows that need to execute.
"""
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from config import settings
from supabase import create_client
from orchestrator import orchestrate

logger = logging.getLogger("helm.scheduler")
sb = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)


def cron_matches(expression: str, now: datetime) -> bool:
    """Check if a cron expression matches the current time (minute-level precision).
    Format: minute hour day-of-month month day-of-week
    Supports: *, specific values, ranges (1-5), steps (*/5), lists (1,3,5)
    """
    if not expression or not expression.strip():
        return False

    parts = expression.strip().split()
    if len(parts) != 5:
        return False

    fields = [now.minute, now.hour, now.day, now.month, now.weekday()]
    # Cron uses 0=Sunday, Python uses 0=Monday — convert
    # Cron: 0=Sun, 1=Mon, ..., 6=Sat
    # Python: 0=Mon, 1=Tue, ..., 6=Sun
    cron_dow = (fields[4] + 1) % 7  # Convert Python weekday to cron weekday

    ranges = [
        (0, 59),   # minute
        (0, 23),   # hour
        (1, 31),   # day of month
        (1, 12),   # month
        (0, 6),    # day of week
    ]

    actual_values = [fields[0], fields[1], fields[2], fields[3], cron_dow]

    for i, (part, value, (lo, hi)) in enumerate(zip(parts, actual_values, ranges)):
        if not _field_matches(part, value, lo, hi):
            return False

    return True


def _field_matches(field: str, value: int, lo: int, hi: int) -> bool:
    """Check if a single cron field matches a value."""
    if field == '*':
        return True

    for item in field.split(','):
        if '/' in item:
            base, step = item.split('/', 1)
            step = int(step)
            if base == '*':
                if value % step == 0:
                    return True
            else:
                start = int(base)
                if value >= start and (value - start) % step == 0:
                    return True
        elif '-' in item:
            start, end = item.split('-', 1)
            if int(start) <= value <= int(end):
                return True
        else:
            if int(item) == value:
                return True

    return False


async def execute_flow(flow: dict):
    """Execute a single scheduled flow."""
    flow_id = flow["id"]
    workspace_id = flow["workspace_id"]
    prompt = flow["prompt"]
    flow_name = flow["name"]

    logger.info(f"⏰ Executing scheduled flow: {flow_name} ({flow_id})")

    try:
        # Create task
        row = sb.table("tasks").insert({
            "workspace_id": workspace_id,
            "user_input": f"[Flujo programado: {flow_name}] {prompt}",
            "status": "running",
        }).execute()
        task = row.data[0]
        task_id = task["id"]

        # Update last_run_at
        sb.table("scheduled_flows").update({
            "last_run_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", flow_id).execute()

        # Orchestrate
        result = await orchestrate(prompt, workspace_id, task_id)

        # Update task result
        sb.table("tasks").update({
            "status": result.get("status", "completed"),
            "plan_json": result.get("plan"),
            "result_json": result.get("results"),
            "assigned_agents": list(result.get("results", {}).keys()) if result.get("results") else [],
            "tokens_used": sum(r.get("tokens_used", 0) for r in result.get("results", {}).values()) if result.get("results") else 0,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", task_id).execute()

        logger.info(f"✅ Flow {flow_name} completed successfully (task: {task_id})")

    except Exception as e:
        logger.error(f"❌ Flow {flow_name} failed: {str(e)}")
        try:
            sb.table("tasks").update({
                "status": "failed",
                "result_json": {"error": str(e)},
            }).eq("id", task_id).execute()
        except Exception:
            pass


async def refresh_expiring_tokens():
    """Refresh Instagram tokens expiring within 5 days."""
    try:
        from services.instagram import refresh_long_lived_token
        from utils.encryption import encrypt_token, decrypt_token

        cutoff = (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()
        rows = sb.table("workspace_integrations").select("*").eq(
            "provider", "instagram"
        ).eq("is_active", True).lt("token_expires_at", cutoff).execute().data

        for row in rows:
            try:
                old_token = decrypt_token(row["access_token_encrypted"])
                result = await refresh_long_lived_token(old_token)
                new_expires = datetime.now(timezone.utc) + timedelta(seconds=result["expires_in"])

                sb.table("workspace_integrations").update({
                    "access_token_encrypted": encrypt_token(result["access_token"]),
                    "token_expires_at": new_expires.isoformat(),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }).eq("id", row["id"]).execute()

                logger.info(f"🔄 Refreshed Instagram token for workspace {row['workspace_id']}")
            except Exception as e:
                logger.error(f"❌ Failed to refresh token for workspace {row['workspace_id']}: {e}")
                # If refresh fails, mark as inactive so user gets notified to reconnect
                if "expired" in str(e).lower() or "invalid" in str(e).lower():
                    sb.table("workspace_integrations").update({
                        "is_active": False,
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    }).eq("id", row["id"]).execute()

    except Exception as e:
        logger.error(f"Token refresh error: {e}")


async def scheduler_loop():
    """Main scheduler loop — checks for due flows every 60 seconds."""
    logger.info("🕐 HELM Scheduler started")
    last_token_refresh = datetime.min.replace(tzinfo=timezone.utc)

    while True:
        try:
            now = datetime.now(timezone.utc)

            # Refresh tokens once per hour
            if (now - last_token_refresh).total_seconds() > 3600:
                await refresh_expiring_tokens()
                last_token_refresh = now

            # Get all active flows with cron expressions
            flows = sb.table("scheduled_flows").select("*").eq(
                "is_active", True
            ).not_.is_("cron_expression", "null").execute().data

            for flow in flows:
                cron_expr = flow.get("cron_expression", "").strip()
                if not cron_expr:
                    continue

                if cron_matches(cron_expr, now):
                    # Prevent double-execution: check last_run_at
                    last_run = flow.get("last_run_at")
                    if last_run:
                        last_run_dt = datetime.fromisoformat(last_run.replace("Z", "+00:00"))
                        diff = (now - last_run_dt).total_seconds()
                        if diff < 120:  # Skip if ran less than 2 minutes ago
                            continue

                    # Execute in background
                    asyncio.create_task(execute_flow(flow))

        except Exception as e:
            logger.error(f"Scheduler error: {str(e)}")

        # Wait 60 seconds before next check
        await asyncio.sleep(60)
