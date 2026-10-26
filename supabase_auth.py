import json
import os
import urllib.error
import urllib.request

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "")


def verify_token(token):
    """Valida un access token de Supabase GoTrue y devuelve el correo verificado.

    Se consulta /auth/v1/user con la anon key; no se confia en decodificar el
    JWT localmente porque la firma no se puede verificar sin el secreto.
    """
    token = (token or "").strip()
    if not token or not SUPABASE_URL or not SUPABASE_ANON_KEY:
        return None

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
                return None
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError):
        return None

    email = (payload.get("email") or "").strip().lower()
    return email or None
