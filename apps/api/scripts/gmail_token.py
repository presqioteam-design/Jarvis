"""
One-time Gmail API sign-in. Prints the three GMAIL_* values for Render and
saves them to apps/api/.env so local runs use the Gmail API too.

    cd apps/api && .venv/bin/python -m scripts.gmail_token ~/Downloads/client_secret_XXXX.json

Sign in with the OUTREACH Gmail account. Google shows "Google hasn't verified
this app": click Advanced → Go to (unsafe). It's your own app.
"""

import base64
import hashlib
import json
import secrets
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

SCOPES = "https://www.googleapis.com/auth/gmail.send https://www.googleapis.com/auth/gmail.readonly"
ENV = Path(__file__).resolve().parent.parent / ".env"


def main(client_file: str) -> None:
    conf = json.loads(Path(client_file).expanduser().read_text())
    conf = conf.get("installed") or conf.get("web") or conf
    client_id, client_secret = conf["client_id"], conf["client_secret"]

    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    result: dict = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            result.update({k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write("<h2>Done. You can close this tab and go back to the terminal.</h2>".encode())

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    redirect = f"http://127.0.0.1:{server.server_port}"
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode({
        "client_id": client_id, "redirect_uri": redirect, "response_type": "code", "scope": SCOPES,
        "access_type": "offline", "prompt": "consent", "code_challenge": challenge, "code_challenge_method": "S256",
    })
    print("Opening the browser. If it doesn't open, visit:\n" + url + "\n")
    webbrowser.open(url)
    while "code" not in result and "error" not in result:
        server.handle_request()
    if "error" in result:
        sys.exit(f"Sign-in failed: {result['error']}")

    r = httpx.post("https://oauth2.googleapis.com/token", data={
        "client_id": client_id, "client_secret": client_secret, "code": result["code"],
        "code_verifier": verifier, "redirect_uri": redirect, "grant_type": "authorization_code",
    })
    r.raise_for_status()
    refresh = r.json().get("refresh_token")
    if not refresh:
        sys.exit("Google didn't return a refresh token. Remove the app's access at myaccount.google.com/permissions and run this again.")

    values = {"GMAIL_CLIENT_ID": client_id, "GMAIL_CLIENT_SECRET": client_secret, "GMAIL_REFRESH_TOKEN": refresh}
    lines = [l for l in (ENV.read_text().splitlines() if ENV.exists() else []) if l.split("=", 1)[0] not in values]
    ENV.write_text("\n".join(lines + [f"{k}={v}" for k, v in values.items()]) + "\n")
    print(f"Saved to {ENV}.\n\nAdd these three to Render → Environment (keep them secret):")
    for k in values:
        print(f"  {k}")
    print("\nThey're in apps/api/.env; copy the values from there.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
