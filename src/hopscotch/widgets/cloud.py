"""Supabase cloud storage for widget states."""
import json
import urllib.request
import urllib.parse

_SUPABASE_URL = "https://etvrevhilqtzxrlemdnu.supabase.co"
_SUPABASE_ANON_KEY = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
    ".eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImV0dnJldmhpbHF0enhybGVtZG51Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3Mzc0NzQxNDEsImV4cCI6MjA1MzA1MDE0MX0"
    ".3eHnxnU02sYnwq9Dc3ZtevmzXRHYdeXea4KTOLLZ4xE"
)
_TABLE = "widget_states"
_TIMEOUT = 10


def _user_id_from_token(token: str) -> str:
    import base64
    part = token.split(".")[1]
    part += "=" * (4 - len(part) % 4)
    return json.loads(base64.urlsafe_b64decode(part))["sub"]


def save(token: str, file_name: str, widget_type: str, state: dict) -> None:
    url = f"{_SUPABASE_URL}/rest/v1/{_TABLE}?on_conflict=user_id,object_name"
    payload = json.dumps({
        "user_id":     _user_id_from_token(token),
        "object_name": file_name,
        "widget_type": widget_type,
        "state": state,
    }).encode()
    req = urllib.request.Request(url, data=payload, method="POST")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("apikey", _SUPABASE_ANON_KEY)
    req.add_header("Content-Type", "application/json")
    req.add_header("Prefer", "resolution=merge-duplicates,return=minimal")
    with urllib.request.urlopen(req, timeout=_TIMEOUT):
        pass


def exists(token: str, file_name: str) -> bool:
    """Return True if a saved state with this name exists for the authenticated user."""
    params = urllib.parse.urlencode({
        "object_name": f"eq.{file_name}",
        "select": "object_name",
        "limit": "1",
    })
    url = f"{_SUPABASE_URL}/rest/v1/{_TABLE}?{params}"
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("apikey", _SUPABASE_ANON_KEY)
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        data = json.loads(resp.read().decode())
        return len(data) > 0


def load(token: str, file_name: str) -> dict | None:
    params = urllib.parse.urlencode({
        "object_name": f"eq.{file_name}",
        "select": "state",
        "limit": "1",
    })
    url = f"{_SUPABASE_URL}/rest/v1/{_TABLE}?{params}"
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("apikey", _SUPABASE_ANON_KEY)
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        data = json.loads(resp.read().decode())
        return data[0]["state"] if data else None
