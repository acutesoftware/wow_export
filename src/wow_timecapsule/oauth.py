from __future__ import annotations

import base64
import hashlib
import json
import secrets
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import httpx


class OAuthError(RuntimeError):
    pass


def authorize(region: str, client_id: str, client_secret: str, timeout: int = 180) -> dict:
    """Run browser authorization-code + PKCE flow; tokens are returned in memory only."""
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(24)
    outcome: dict[str, str] = {}
    done = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            query = parse_qs(urlparse(self.path).query)
            if query.get("state", [""])[0] != state:
                outcome["error"] = "OAuth state mismatch"
            elif "error" in query:
                outcome["error"] = query["error"][0]
            else:
                outcome["code"] = query.get("code", [""])[0]
            body = b"Authorization received. You may close this tab."
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            done.set()

        def log_message(self, *_args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    redirect_uri = f"http://127.0.0.1:{server.server_port}/callback"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    params = urlencode({
        "client_id": client_id, "redirect_uri": redirect_uri, "response_type": "code",
        "scope": "openid wow.profile", "state": state, "code_challenge": challenge,
        "code_challenge_method": "S256",
    })
    webbrowser.open(f"https://{region}.battle.net/oauth/authorize?{params}")
    done.wait(timeout)
    server.shutdown()
    server.server_close()
    if not outcome.get("code"):
        raise OAuthError(outcome.get("error", "Authorization timed out"))
    response = httpx.post(
        f"https://{region}.battle.net/oauth/token",
        data={"grant_type": "authorization_code", "code": outcome["code"],
              "redirect_uri": redirect_uri, "code_verifier": verifier},
        auth=(client_id, client_secret), timeout=30,
    )
    response.raise_for_status()
    token = response.json()
    token["expires_at"] = int(time.time()) + int(token.get("expires_in", 0))
    return token

