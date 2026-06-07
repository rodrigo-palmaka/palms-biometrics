"""
One-time Oura OAuth2 setup. Run with:
    uv run python scripts/oura_auth.py

Saves tokens to ~/.palms/oura_tokens.json.
Requires OURA_CLIENT_ID and OURA_CLIENT_SECRET in .env (or env vars).
"""

import base64
import hashlib
import json
import os
import secrets
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import httpx
from palms.config import settings

TOKEN_PATH = Path.home() / ".palms" / "oura_tokens.json"
REDIRECT_URI = "http://localhost:8080/callback"
AUTH_URL = "https://cloud.ouraring.com/oauth/authorize"
TOKEN_URL = "https://api.ouraring.com/oauth/token"
SCOPES = "email personal daily heartrate workout session"


def _pkce_pair() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    return verifier, challenge


def main() -> None:
    client_id = settings.oura_client_id
    client_secret = settings.oura_client_secret
    if not client_id:
        raise SystemExit("Set OURA_CLIENT_ID in .env first.")

    verifier, challenge = _pkce_pair()
    state = secrets.token_hex(16)

    auth_params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
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
            self.wfile.write(b"<h1>Auth complete. You can close this tab.</h1>")

        def log_message(self, *args):
            pass

    print(f"Opening browser for Oura authorization...")
    webbrowser.open(url)
    server = HTTPServer(("localhost", 8080), Handler)
    server.handle_request()

    if "code" not in code_holder:
        raise SystemExit("No authorization code received.")
    if code_holder.get("state") != state:
        raise SystemExit("State mismatch — possible CSRF.")

    resp = httpx.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code_holder["code"],
            "redirect_uri": REDIRECT_URI,
            "client_id": client_id,
            "client_secret": client_secret,
            "code_verifier": verifier,
        },
    )
    resp.raise_for_status()
    tokens = resp.json()
    tokens["expires_at"] = int(time.time()) + tokens.get("expires_in", 86400)

    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(json.dumps(tokens, indent=2))
    print(f"Tokens saved to {TOKEN_PATH}")


if __name__ == "__main__":
    main()
