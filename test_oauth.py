#!/usr/bin/env python3
import os
import sys
import json
import threading
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from dataclasses import dataclass

from dotenv import load_dotenv
from supabase import create_client

try:
    import requests  # only used for optional REST call check
except Exception:
    requests = None

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")
REDIRECT_PORT = int(os.getenv("OAUTH_REDIRECT_PORT", "8765"))
REDIRECT_URL = f"http://127.0.0.1:{REDIRECT_PORT}/callback"

if not SUPABASE_URL or not SUPABASE_ANON_KEY:
    print("ERROR: SUPABASE_URL and SUPABASE_ANON_KEY must be set in environment or .env")
    sys.exit(1)

supabase = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

@dataclass
class OAuthResult:
    code: str | None = None
    error: str | None = None
    state: str | None = None

oauth_result = OAuthResult()

class CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path != "/callback":
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not found")
            return

        qs = parse_qs(parsed.query)
        code = qs.get("code", [None])[0]
        error = qs.get("error", [None])[0]
        state = qs.get("state", [None])[0]
        oauth_result.code = code
        oauth_result.error = error
        oauth_result.state = state

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        if code:
            self.wfile.write(b"<h2>Auth complete</h2><p>You can close this tab and return to the terminal.</p>")
        else:
            self.wfile.write(b"<h2>Auth failed</h2><p>Check terminal output.</p>")

    def log_message(self, *args, **kwargs):
        return

def start_server():
    httpd = HTTPServer(("127.0.0.1", REDIRECT_PORT), CallbackHandler)
    httpd.timeout = 300
    httpd.handle_request()

def main():
    print("== Supabase + GitHub OAuth (PKCE) CLI Tester ==")
    print(f"Supabase URL: {SUPABASE_URL}")
    print(f"Redirect URL: {REDIRECT_URL}")
    print()

    print("[1/4] Starting local callback server...")
    t = threading.Thread(target=start_server, daemon=True)
    t.start()

    print("[2/4] Requesting authorization URL (PKCE) from Supabase...")
    res = supabase.auth.sign_in_with_oauth({
        "provider": "github",
        "options": {
            "redirect_to": REDIRECT_URL,
            "flow_type": "pkce"
        }
    })
    auth_url = getattr(res, "url", None) or (res.get("url") if isinstance(res, dict) else None)
    if not auth_url:
        print("ERROR: Could not get auth URL from Supabase")
        sys.exit(2)
    print(f"Auth URL:\n  {auth_url}\n")

    print("[3/4] Opening your browser for GitHub sign-in...")
    print("      If it doesn't open automatically, copy the URL above into a browser.")
    webbrowser.open(auth_url)

    print("      Waiting for the provider to redirect back to the local callback...")
    t.join(timeout=300)
    if oauth_result.error:
        print(f"ERROR returned by provider: {oauth_result.error}")
        sys.exit(3)
    if not oauth_result.code:
        print("ERROR: Did not receive ?code=... on the callback (timeout or wrong redirect URL).")
        sys.exit(4)

    print(f"[Callback] Received code: {oauth_result.code[:8]}... (truncated)")

    print("[4/4] Exchanging code for session tokens with Supabase...")
    data = supabase.auth.exchange_code_for_session({"auth_code": oauth_result.code})
    session_obj = getattr(data, "session", None) or (data.get("session") if isinstance(data, dict) else None)
    if not session_obj:
        print("ERROR: No session returned from exchange. Raw:")
        print(data)
        sys.exit(5)

    access_token = getattr(session_obj, "access_token", None) or session_obj.get("access_token")
    refresh_token = getattr(session_obj, "refresh_token", None) or session_obj.get("refresh_token")
    token_type = getattr(session_obj, "token_type", None) or session_obj.get("token_type")

    print("\n== Session Acquired ==")
    print(json.dumps({
        "token_type": token_type,
        "access_token_preview": (access_token[:20] + "...") if access_token else None,
        "refresh_token_preview": (refresh_token[:12] + "...") if refresh_token else None,
    }, indent=2))

    user = supabase.auth.get_user()
    user_obj = getattr(user, "user", None) or user.get("user") if isinstance(user, dict) else None
    print("\n== Current User ==")
    if user_obj:
        print(json.dumps({
            "id": getattr(user_obj, "id", None) or user_obj.get("id"),
            "email": getattr(user_obj, "email", None) or user_obj.get("email"),
        }, indent=2))
    else:
        print("No user found in session.")

    if requests and access_token:
        print("\n== Optional REST Check ==")
        rest_url = SUPABASE_URL.rstrip("/") + "/rest/v1/"
        headers = {
            "apikey": SUPABASE_ANON_KEY,
            "Authorization": f"Bearer {access_token}",
        }
        try:
            r = requests.get(rest_url, headers=headers, timeout=10)
            print(f"GET {rest_url} -> {r.status_code}")
        except Exception as e:
            print(f"(Skip REST check) {e}")

    print("\nAll good! You can now use these tokens in your Streamlit app via supabase.auth.set_session(...).")

if __name__ == "__main__":
    main()
