import json
import os
import urllib.error
import urllib.request

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "")


def verify_token_user(token):
    """Valida un access token de Supabase GoTrue y devuelve (email, user_id)."""
    token = (token or "").strip()
    if not token or not SUPABASE_URL or not SUPABASE_ANON_KEY:
        return None, None

    request = urllib.request.Request(
        SUPABASE_URL + "/auth/v1/user",
        headers={
            "Authorization": "Bearer " + token,
            "apikey": SUPABASE_ANON_KEY,
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            if response.status != 200:
                return None, None
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError):
        return None, None

    email = (payload.get("email") or "").strip().lower() or None
    user_id = (payload.get("id") or "").strip() or None
    return email, user_id


def verify_token(token):
    """Valida un access token de Supabase GoTrue y devuelve el correo verificado.

    Se consulta /auth/v1/user con la anon key; no se confia en decodificar el
    JWT localmente porque la firma no se puede verificar sin el secreto.
    """
    email, _ = verify_token_user(token)
    return email


def is_supabase_staff(token, user_id):
    """Consulta el rol en public.profiles usando el propio token del usuario."""
    if not token or not user_id or not SUPABASE_URL or not SUPABASE_ANON_KEY:
        return False
    url = (
        f"{SUPABASE_URL}/rest/v1/profiles"
        f"?id=eq.{urllib.request.quote(user_id, safe='')}&select=role"
    )
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": "Bearer " + token,
            "apikey": SUPABASE_ANON_KEY,
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            if response.status != 200:
                return False
            rows = json.loads(response.read().decode("utf-8"))
            if isinstance(rows, list) and rows:
                role = (rows[0].get("role") or "").strip().upper()
                return role in ("ADMIN", "RESELLER")
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError):
        return False
    return False
