"""
One-time Withings OAuth2 setup. Run with:
    uv run python scripts/withings_auth.py

Saves tokens to ~/.palms/withings_tokens.json.
Requires WITHINGS_CLIENT_ID and WITHINGS_CLIENT_SECRET in .env.
"""

import base64
import hashlib
import json
import secrets
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import httpx
from palms.config import settings

TOKEN_PATH = Path.home() / ".palms" / "withings_tokens.json"
REDIRECT_URI = "http://localhost:8080/callback"
AUTH_URL = "https://account.withings.com/oauth2_user/authorize2"
TOKEN_URL = "https://wbsapi.withings.net/v2/oauth2"
SCOPE = "user.metrics"


def _pkce_pair() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    return verifier, challenge


def main() -> None:
    client_id = settings.withings_client_id
    client_secret = settings.withings_client_secret
    if not client_id:
        raise SystemExit("Set WITHINGS_CLIENT_ID in .env first.")

    verifier, challenge = _pkce_pair()
    state = secrets.token_hex(16)

    auth_params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPE,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    url = AUTH_URL + "?" + urllib.parse.urlencode(auth_params)

    code_holder: dict = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed.query)
            if "code" in params:
                code_holder["code"] = params["code"][0]
                code_holder["state"] = params.get("state", [None])[0]
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"<h1>Withings auth complete. You can close this tab.</h1>")

        def log_message(self, *args):
            pass

    print("Opening browser for Withings authorization...")
    webbrowser.open(url)
    server = HTTPServer(("localhost", 8080), Handler)
    server.handle_request()

    if "code" not in code_holder:
        raise SystemExit("No authorization code received.")
    if code_holder.get("state") != state:
        raise SystemExit("State mismatch — possible CSRF.")

    resp = httpx.post(TOKEN_URL, data={
        "action": "requesttoken",
        "grant_type": "authorization_code",
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code_holder["code"],
        "redirect_uri": REDIRECT_URI,
        "code_verifier": verifier,
    })
    resp.raise_for_status()
    body = resp.json()
    if body.get("status") != 0:
        raise SystemExit(f"Token exchange failed: {body}")

    tokens = body["body"]
    tokens["expires_at"] = int(time.time()) + tokens.get("expires_in", 10800)

    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(json.dumps(tokens, indent=2))
    print(f"Tokens saved to {TOKEN_PATH}")


if __name__ == "__main__":
    main()
