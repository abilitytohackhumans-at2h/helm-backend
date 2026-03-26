"""
Authentication & Authorization module for HELM API.
Verifies Supabase JWT tokens and enforces access control.
"""
import logging
from dataclasses import dataclass
from fastapi import Header, HTTPException, Depends
from config import settings
from supabase import create_client

logger = logging.getLogger("helm.auth")

# Use service client only for admin operations (profile lookups)
_sb = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)


@dataclass
class AuthUser:
    """Authenticated user context."""
    user_id: str
    email: str
    is_super_admin: bool = False


async def get_current_user(authorization: str = Header(default="")) -> AuthUser:
    """
    Extract and verify user from Supabase JWT token.
    Returns AuthUser with user_id, email, and super_admin flag.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Token de autenticación requerido")

    token = authorization.replace("Bearer ", "")

    try:
        # Verify token with Supabase Auth API
        user_response = _sb.auth.get_user(token)
        if not user_response or not user_response.user:
            raise HTTPException(401, "Token inválido o expirado")

        user = user_response.user
        user_id = user.id
        email = user.email or ""

    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"Auth failed: {str(e)}")
        raise HTTPException(401, "Token inválido o expirado")

    # Check super_admin status from profile
    is_super_admin = False
    try:
        profile = _sb.table("profiles").select("is_super_admin").eq("id", user_id).single().execute().data
        if profile:
            is_super_admin = profile.get("is_super_admin", False)
    except Exception:
        pass  # Profile may not exist yet (new registration)

    return AuthUser(user_id=user_id, email=email, is_super_admin=is_super_admin)


async def require_super_admin(user: AuthUser = Depends(get_current_user)) -> AuthUser:
    """Require the user to be a super admin."""
    if not user.is_super_admin:
        raise HTTPException(403, "Se requieren permisos de super admin")
    return user


async def require_workspace_access(workspace_id: str, user: AuthUser = Depends(get_current_user)) -> AuthUser:
    """
    Verify that the user has access to the specified workspace.
    Super admins can access all workspaces.
    Regular users must be a member of the workspace.
    """
    if user.is_super_admin:
        return user

    # Check workspace ownership
    ws = _sb.table("workspaces").select("owner_id").eq("id", workspace_id).single().execute().data
    if ws and ws.get("owner_id") == user.user_id:
        return user

    # Check workspace membership
    member = _sb.table("workspace_members").select("id").eq(
        "workspace_id", workspace_id
    ).eq("user_id", user.user_id).execute().data
    if member:
        return user

    raise HTTPException(403, "No tienes acceso a este workspace")
