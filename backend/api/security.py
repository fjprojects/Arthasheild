import hashlib
from typing import Tuple, Optional
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from .models import SecureSession


def extract_session_token(request) -> Optional[str]:
    """
    Extracts the session secret token from HTTP headers or secure cookies.
    Checks:
    1. X-Session-Token header (standard for ArthaShield API client)
    2. Authorization header (Bearer or Session scheme)
    3. arthashield_session_token cookie
    """
    # 1. Custom Header
    token = request.headers.get("X-Session-Token")
    if not token and hasattr(request, "META"):
        token = request.META.get("HTTP_X_SESSION_TOKEN")
    if token:
        return token.strip()

    # 2. Authorization Header
    auth_header = request.headers.get("Authorization") or (
        request.META.get("HTTP_AUTHORIZATION") if hasattr(request, "META") else None
    )
    if auth_header:
        parts = auth_header.strip().split()
        if len(parts) == 2 and parts[0].lower() in ("bearer", "session", "token"):
            return parts[1].strip()

    # 3. Cookie fallback
    cookie_token = request.COOKIES.get("arthashield_session_token")
    if cookie_token:
        return cookie_token.strip()

    return None


def authenticate_request_session(
    request, required: bool = True
) -> Tuple[Optional[SecureSession], Optional[Response]]:
    """
    Authenticates the request against server-issued SecureSession records.
    Guarantees:
    - Verifies token hash against database.
    - Rejects expired or revoked sessions.
    - Checks for Cross-Session IDOR: Rejects if the request body or parameters
      attempt to substitute another session ID.
    - Attaches auth_session and auth_session_id to the request.
    """
    token = extract_session_token(request)

    if not token:
        if required:
            return None, Response(
                {
                    "error": "Authentication required. A valid session token must be provided via X-Session-Token header or cookie.",
                    "code": "AUTH_REQUIRED",
                },
                status=status.HTTP_401_UNAUTHORIZED,
            )
        return None, None

    token_hash = SecureSession.hash_token(token)
    session = (
        SecureSession.objects.filter(token_hash=token_hash, is_revoked=False)
        .first()
    )

    if not session:
        return None, Response(
            {
                "error": "Invalid or revoked session credentials.",
                "code": "INVALID_SESSION",
            },
            status=status.HTTP_401_UNAUTHORIZED,
        )

    if session.is_expired:
        return None, Response(
            {
                "error": "Session has expired. Please re-authenticate.",
                "code": "EXPIRED_SESSION",
            },
            status=status.HTTP_401_UNAUTHORIZED,
        )

    # Touch last_active_at periodically (e.g. rolling activity)
    now = timezone.now()
    if (now - session.last_active_at).total_seconds() > 300:
        session.last_active_at = now
        session.save(update_fields=["last_active_at"])

    # Cross-Session IDOR Prevention:
    # If the client sent a session_id in payload, body, or query parameters,
    # it MUST strictly match the authenticated session.
    client_session_id = None
    if hasattr(request, "data") and isinstance(request.data, dict):
        client_session_id = request.data.get("session_id")
    if not client_session_id and hasattr(request, "query_params"):
        client_session_id = request.query_params.get("session_id")
    if not client_session_id and hasattr(request, "GET"):
        client_session_id = request.GET.get("session_id")

    if client_session_id:
        client_session_id = str(client_session_id).strip()
        if client_session_id != session.session_id:
            return None, Response(
                {
                    "error": "Session substitution forbidden. You cannot access or modify another user's session data.",
                    "code": "SESSION_MISMATCH",
                    "authenticated_session": session.session_id,
                },
                status=status.HTTP_403_FORBIDDEN,
            )

    # Attach verified session to request
    request.auth_session = session
    request.auth_session_id = session.session_id

    return session, None


class SecureSessionAuthentication(BaseAuthentication):
    """
    DRF Authentication scheme for SecureSession.
    """

    def authenticate_header(self, request):
        return 'Session realm="api"'

    def authenticate(self, request):
        token = extract_session_token(request)
        if not token:
            return None

        token_hash = SecureSession.hash_token(token)
        session = (
            SecureSession.objects.filter(token_hash=token_hash, is_revoked=False)
            .first()
        )

        if not session or session.is_expired:
            raise AuthenticationFailed("Invalid or expired session token.")

        request.auth_session = session
        request.auth_session_id = session.session_id
        return (None, session)
