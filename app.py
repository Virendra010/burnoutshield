"""
app.py — BurnoutShield Flask Application (Web OAuth Enabled)

Serves:
  GET  /               → Web UI
  POST /analyze        → API endpoint (JSON in/out)
  GET  /health         → Health check
  GET  /login          → Redirects to Google OAuth consent screen
  GET  /oauth/callback → Receives OAuth code, saves token.json
  GET  /auth/status    → UI endpoint to check connection status
  GET  /logout         → Disconnects Google by deleting token.json
  GET  /setup          → Shows exact redirect URI to register in Google Console
"""

import os
import json
import asyncio
import logging
from pathlib import Path

import requests as http_requests
from flask import Flask, request, jsonify, render_template_string, redirect, session, url_for
from dotenv import load_dotenv
from werkzeug.middleware.proxy_fix import ProxyFix

os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

load_dotenv()
logging.basicConfig(level=logging.INFO)

app = Flask(__name__)

# ── CRITICAL: This tells Flask to trust the reverse proxy headers from Cloud Shell ──
# Cloud Shell sends X-Forwarded-Proto, X-Forwarded-Host, X-Forwarded-Port etc.
# Without this, request.url returns http://127.0.0.1:8080 instead of https://...cloudshell.dev
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1, x_prefix=1)

app.secret_key = os.getenv("FLASK_SECRET", "burnoutshield-super-secret-key")
app.config["JSON_SORT_KEYS"] = False

# ── Paths ──
_PROJECT_ROOT = Path(__file__).parent
CREDENTIALS_FILE = _PROJECT_ROOT / "credentials.json"
TOKEN_FILE = _PROJECT_ROOT / "token.json"

SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/gmail.readonly",
]


# ── Helper: Get the real external base URL ────────────────────────────────────

def _get_external_base():
    """
    Returns the real external base URL, handling Cloud Shell reverse proxy.
    Cloud Shell sends X-Forwarded-Host and X-Forwarded-Proto headers.
    After ProxyFix, request.host_url should be correct.
    """
    # After ProxyFix, this should work correctly
    base = request.host_url.rstrip("/")
    logging.info(f"[OAuth] External base URL: {base}")
    return base


# ── Setup page — shows exact redirect URI to register ─────────────────────────

@app.route("/setup")
def setup_page():
    """Shows the exact redirect URI the user needs to add to Google Cloud Console."""
    base = _get_external_base()
    callback_url = f"{base}/oauth/callback"
    has_creds = CREDENTIALS_FILE.exists()
    has_token = TOKEN_FILE.exists()

    return render_template_string(r"""<!DOCTYPE html>
<html><head><title>BurnoutShield Setup</title>
<style>
  body { background: #0a0b0f; color: #e2e5ef; font-family: monospace; padding: 40px; max-width: 800px; margin: auto; }
  h1 { color: #f5a623; }
  .box { background: #1a1d27; border: 1px solid #333; border-radius: 12px; padding: 20px; margin: 20px 0; }
  .url { background: #000; color: #22c55e; padding: 12px; border-radius: 8px; font-size: 14px; word-break: break-all; user-select: all; }
  .status { display: flex; align-items: center; gap: 8px; margin: 8px 0; }
  .dot-green { width: 10px; height: 10px; background: #22c55e; border-radius: 50%; }
  .dot-red { width: 10px; height: 10px; background: #ef4444; border-radius: 50%; }
  ol li { margin-bottom: 12px; line-height: 1.6; }
  a { color: #f5a623; }
</style></head><body>
  <h1>🛡️ BurnoutShield — OAuth Setup</h1>

  <div class="box">
    <h3>Status</h3>
    <div class="status">
      <div class="{{ 'dot-green' if has_creds else 'dot-red' }}"></div>
      credentials.json: {{ 'Found ✓' if has_creds else 'MISSING ✗' }}
    </div>
    <div class="status">
      <div class="{{ 'dot-green' if has_token else 'dot-red' }}"></div>
      token.json: {{ 'Found ✓' if has_token else 'Not yet (login required)' }}
    </div>
  </div>

  <div class="box">
    <h3>Step 1: Copy this Redirect URI</h3>
    <p>Add this <strong>exact URL</strong> to your Google Cloud OAuth Client's <em>Authorized redirect URIs</em>:</p>
    <div class="url">{{ callback_url }}</div>
  </div>

  <div class="box">
    <h3>Step 2: Full Instructions</h3>
    <ol>
      <li>Go to <a href="https://console.cloud.google.com/apis/credentials" target="_blank">Google Cloud Console → APIs & Services → Credentials</a></li>
      <li>Click <strong>+ CREATE CREDENTIALS → OAuth client ID</strong></li>
      <li>Application type: <strong>Web application</strong></li>
      <li>Under <strong>Authorized redirect URIs</strong>, click <strong>+ ADD URI</strong> and paste:<br>
        <code>{{ callback_url }}</code></li>
      <li>Click <strong>CREATE</strong></li>
      <li>Click the <strong>⬇ Download JSON</strong> button on the credentials row</li>
      <li>Rename the downloaded file to <code>credentials.json</code></li>
      <li>Upload it to <code>~/burnoutshield/</code> on Cloud Shell</li>
      <li>Go back to <a href="/">the main page</a> and click <strong>Connect Google</strong></li>
    </ol>
  </div>

  <div class="box">
    <h3>Step 3: Enable APIs</h3>
    <p>Run this in your Cloud Shell terminal:</p>
    <div class="url">gcloud services enable calendar-json.googleapis.com gmail.googleapis.com</div>
  </div>

  <p style="margin-top:30px;"><a href="/">← Back to BurnoutShield</a></p>
</body></html>""", callback_url=callback_url, has_creds=has_creds, has_token=has_token)


# ── Web OAuth Flow ────────────────────────────────────────────────────────────

@app.route("/login")
def login():
    """Initializes the OAuth 2.0 flow."""
    if not CREDENTIALS_FILE.exists():
        return redirect(url_for("setup_page"))

    from google_auth_oauthlib.flow import Flow

    base = _get_external_base()
    callback_url = f"{base}/oauth/callback"

    logging.info(f"[OAuth] Starting flow with redirect_uri={callback_url}")

    flow = Flow.from_client_secrets_file(
        str(CREDENTIALS_FILE),
        scopes=SCOPES,
        redirect_uri=callback_url
    )

    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent"
    )
    session["oauth_state"] = state
    session["oauth_redirect_uri"] = callback_url  # Save to reuse in callback
    
    # CRITICAL: Save the auto-generated code_verifier for PKCE checks
    session["code_verifier"] = getattr(flow, 'code_verifier', None)
    
    return redirect(auth_url)


@app.route("/oauth/callback")
def oauth_callback():
    """Receives the auth code from Google."""
    if "error" in request.args:
        return f"OAuth Error: {request.args.get('error')}<br><a href='/setup'>Go to Setup</a>"

    state = session.get("oauth_state")
    if not state:
        return "Session expired. <a href='/login'>Try again</a>", 400

    from google_auth_oauthlib.flow import Flow

    # Reuse the exact same redirect_uri from the /login step
    callback_url = session.get("oauth_redirect_uri")
    if not callback_url:
        base = _get_external_base()
        callback_url = f"{base}/oauth/callback"

    logging.info(f"[OAuth] Callback with redirect_uri={callback_url}")

    flow = Flow.from_client_secrets_file(
        str(CREDENTIALS_FILE),
        scopes=SCOPES,
        state=state,
        redirect_uri=callback_url
    )
    
    # CRITICAL: Restore the code_verifier for PKCE check compilation
    code_verifier = session.get("code_verifier")
    if code_verifier:
        flow.code_verifier = code_verifier

    # Reconstruct the authorization response URL using the real external URL
    # Cloud Shell proxy may mangle request.url, so rebuild it
    auth_response = request.url
    if auth_response.startswith("http://") and callback_url.startswith("https://"):
        auth_response = "https://" + auth_response[len("http://"):]

    flow.fetch_token(authorization_response=auth_response)

    creds = flow.credentials
    with open(TOKEN_FILE, "w") as token_file:
        token_file.write(creds.to_json())

    logging.info("[OAuth] Successfully saved token.json")
    return redirect(url_for("index"))


@app.route("/auth/status")
def auth_status():
    """Checks if token.json exists and returns user identity if possible."""
    has_creds = CREDENTIALS_FILE.exists()

    if not TOKEN_FILE.exists():
        return jsonify({"connected": False, "email": None, "has_credentials_json": has_creds})

    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request

        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(TOKEN_FILE, "w") as tf:
                tf.write(creds.to_json())

        if creds and creds.valid:
            userinfo = http_requests.get(
                "https://www.googleapis.com/oauth2/v2/userinfo",
                headers={"Authorization": f"Bearer {creds.token}"}
            ).json()
            email = userinfo.get("email", "Google User")
            return jsonify({"connected": True, "email": email, "has_credentials_json": has_creds})
    except Exception as e:
        logging.warning(f"[OAuth] Check failed: {e}")

    return jsonify({"connected": False, "email": None, "has_credentials_json": has_creds})


@app.route("/logout")
def logout():
    """Disconnects Google by deleting token.json."""
    if TOKEN_FILE.exists():
        TOKEN_FILE.unlink()
    return redirect(url_for("index"))


# ── ADK Runner ────────────────────────────────────────────────────────────────

async def _run_agent_async(user_input: str) -> str:
    # Lazy imports — inside the function to let Flask start even if ADK has issues
    try:
        from google.adk.runners import Runner
        from google.adk.sessions import InMemorySessionService
        from google.genai import types as genai_types
    except ImportError as e:
        logging.error(f"[Agent] Failed to import ADK: {e}")
        return f"ADK import error: {e}"

    # Diagnostic: check if the source file actually has root_agent
    agent_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'burnout_agent', 'agent.py')
    try:
        with open(agent_path) as f:
            source = f.read()
        if 'root_agent' not in source:
            logging.error(f"[Diagnostic] The file {agent_path} does NOT contain 'root_agent'!")
            logging.error(f"[Diagnostic] File has {len(source)} chars. Last 200 chars: {source[-200:]}")
            return f"ERROR: Your agent.py file on Cloud Shell is outdated. It does not contain 'root_agent'. Please re-copy the latest agent.py from your local machine."
        else:
            logging.info(f"[Diagnostic] root_agent found in source ({len(source)} chars)")
    except Exception as e:
        logging.error(f"[Diagnostic] Cannot read {agent_path}: {e}")

    try:
        from burnout_agent.agent import root_agent
    except Exception as e:
        logging.error(f"[Agent] Failed to import root_agent: {e}", exc_info=True)
        return f"Agent import error: {e}"

    session_service = InMemorySessionService()
    runner = Runner(
        agent=root_agent,
        app_name="burnoutshield",
        session_service=session_service,
    )

    session_obj = await session_service.create_session(
        app_name="burnoutshield",
        user_id="web_user",
    )

    content = genai_types.Content(
        role="user",
        parts=[genai_types.Part(text=user_input)],
    )

    final_response = ""
    async for event in runner.run_async(
        user_id="web_user",
        session_id=session_obj.id,
        new_message=content,
    ):
        if event.is_final_response() and event.content and event.content.parts:
            final_response = event.content.parts[0].text

    return final_response or "No response generated."


def run_burnout_agent(user_input: str) -> str:
    try:
        return asyncio.run(_run_agent_async(user_input))
    except Exception as e:
        logging.error(f"[Agent] Error: {e}", exc_info=True)
        return f"Agent error: {str(e)}"


# ── HTML Template ─────────────────────────────────────────────────────────────

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>BurnoutShield — AI Chief of Staff</title>
  <style>
    :root {
      --bg: #06070a; --card: rgba(22,25,35,0.75);
      --border: rgba(255,255,255,0.06); --text: #e2e5ef; --text-dim: #8891a5;
      --amber: #f5a623; --green: #22c55e; --red: #ef4444;
    }
    body { background: var(--bg); color: var(--text); font-family: sans-serif; margin: 0; }
    .container { max-width: 880px; margin: 0 auto; padding: 40px 20px; }

    .header { display: flex; justify-content: space-between; align-items: flex-start;
              border-bottom: 1px solid var(--border); padding-bottom: 20px; margin-bottom: 30px; }
    .header-text h1 { margin: 0; font-size: 24px; color: #fff; }
    .header-text p  { margin: 5px 0 0; color: var(--text-dim); font-size: 14px; }

    .status-row { display: flex; gap: 10px; margin-top: 12px; flex-wrap: wrap; }
    .status-pill { border: 1px solid var(--border); border-radius: 20px; padding: 4px 12px;
                   font-size: 11px; background: var(--card); display: flex; align-items: center; gap: 6px; }
    .dot { width: 8px; height: 8px; border-radius: 50%; }
    .dot-gray  { background: #555; }
    .dot-green { background: var(--green); }

    .google-btn { background: #fff; color: #000; padding: 10px 18px; border-radius: 8px;
                  text-decoration: none; font-size: 13px; font-weight: bold; border: none;
                  cursor: pointer; display: inline-block; }
    .google-btn:hover { background: #eee; }
    .setup-link { font-size: 11px; color: var(--amber); text-decoration: underline; display: block; margin-top: 6px; }
    .logout-link { font-size: 11px; color: var(--text-dim); text-decoration: underline; cursor: pointer; }

    textarea { width: 100%; min-height: 120px; background: rgba(0,0,0,0.3); border: 1px solid var(--border);
               color: #fff; padding: 15px; border-radius: 12px; margin-bottom: 15px; font-size: 14px;
               font-family: sans-serif; resize: vertical; box-sizing: border-box; }
    textarea:focus { outline: none; border-color: rgba(245,166,35,0.3); }

    .btn-row { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 20px; }
    .chip { font-size: 12px; color: var(--text-dim); background: rgba(0,0,0,0.3); border: 1px solid var(--border);
            border-radius: 20px; padding: 6px 14px; cursor: pointer; }
    .chip:hover { color: var(--amber); border-color: var(--amber); }

    .analyze-btn { background: var(--amber); color: #000; padding: 14px 32px; font-weight: bold;
                   border-radius: 10px; border: none; cursor: pointer; font-size: 14px; }
    .analyze-btn:disabled { opacity: 0.5; cursor: not-allowed; }
    .analyze-btn:hover:not(:disabled) { filter: brightness(1.1); }

    .output-section { display: none; background: var(--card); padding: 25px; border-radius: 15px;
                      border: 1px solid var(--border); margin-top: 20px; line-height: 1.8; }
    .output-section.visible { display: block; animation: fadeIn 0.4s ease; }
    @keyframes fadeIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }

    .output-body h2 { color: var(--amber); font-size: 18px; margin-top: 20px; }
    .output-body h3 { color: #fff; font-size: 16px; margin-top: 15px; }
    .output-body strong { color: #fff; }
    .output-body li { margin-bottom: 6px; }
    .output-body hr { border: none; height: 1px; background: var(--border); margin: 15px 0; }

    .error-box { display: none; color: var(--red); background: rgba(239,68,68,0.1); border: 1px solid rgba(239,68,68,0.3);
                 padding: 15px; border-radius: 10px; margin-top: 15px; font-size: 13px; }
    .error-box.visible { display: block; }

    .footer { text-align: center; margin-top: 50px; color: #333; font-size: 11px; }
    .footer a { color: var(--amber); text-decoration: none; }
  </style>
</head>
<body>
  <div class="container">
    <header class="header">
      <div class="header-text">
        <h1>🛡️ BurnoutShield</h1>
        <p>AI Chief of Staff — Burnout Detection & Schedule Optimization</p>
        <div class="status-row">
          <span class="status-pill"><div class="dot dot-green"></div>Vertex AI</span>
          <span class="status-pill" id="google-pill">
            <div class="dot dot-gray" id="google-dot"></div>
            <span id="google-text">Checking...</span>
          </span>
        </div>
      </div>
      <div id="auth-container" style="text-align:right;">
        <a href="./login" class="google-btn" id="loginBtn" style="display:none;">🔗 Connect Google</a>
        <a href="./setup" class="setup-link" id="setupLink" style="display:none;">⚙️ Setup Instructions</a>
        <div id="userProfile" style="display:none;">
          <small style="color:var(--green); font-weight:bold;" id="userEmail"></small><br>
          <a href="./logout" class="logout-link">Disconnect</a>
        </div>
      </div>
    </header>

    <textarea id="workloadInput" placeholder="Describe your day... e.g. I have 6 meetings, 2 critical deadlines, 12 tasks, and I'm running on 5 hours of sleep..."></textarea>

    <div class="btn-row">
      <span class="chip" onclick="fill(0)">⚡ Heavy day</span>
      <span class="chip" onclick="fill(1)">🔥 Critical deadline</span>
      <span class="chip" onclick="fill(2)">😰 Overwhelmed</span>
      <span style="flex:1;"></span>
      <button class="analyze-btn" id="analyzeBtn" onclick="analyze()">▶ ANALYZE</button>
    </div>

    <div id="errorBox" class="error-box"></div>

    <div class="output-section" id="outputSection">
      <div class="output-body" id="outputBody"></div>
    </div>

    <div class="footer">
      BurnoutShield — <a href="./setup">Setup</a> | Powered by Google ADK + Vertex AI + Gemini
    </div>
  </div>

  <script>
    const EXAMPLES = [
      "I have 12 tasks today, 6 meetings including a 2-hour planning session, 3 deliverables due by EOD, and 4 urgent emails.",
      "Critical: product demo to investors at 2pm, code still not working. Plus 8 other tasks, 4 meetings. Haven't slept properly in 3 days.",
      "I'm completely overwhelmed. 15 open tasks, sprint deadline tomorrow, manager asking for status updates every hour, and personal commitments tonight."
    ];

    function fill(i) {
      document.getElementById("workloadInput").value = EXAMPLES[i];
    }

    // Check Auth Status
    fetch('./auth/status').then(r => r.json()).then(data => {
      if (data.connected) {
        document.getElementById("userProfile").style.display = "block";
        document.getElementById("userEmail").textContent = "✓ " + data.email;
        document.getElementById("google-dot").className = "dot dot-green";
        document.getElementById("google-text").textContent = "Calendar + Gmail";
      } else {
        document.getElementById("loginBtn").style.display = "inline-block";
        document.getElementById("setupLink").style.display = "block";
        if (!data.has_credentials_json) {
          document.getElementById("google-text").textContent = "Setup needed";
          document.getElementById("loginBtn").textContent = "⚠️ Setup Required";
          document.getElementById("loginBtn").href = "./setup";
        } else {
          document.getElementById("google-text").textContent = "Not connected";
        }
      }
    }).catch(() => {
      document.getElementById("google-text").textContent = "Offline";
      document.getElementById("loginBtn").style.display = "inline-block";
    });

    function renderMarkdown(text) {
      return text
        .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
        .replace(/^### (.+)$/gm, "<h3>$1</h3>")
        .replace(/^## (.+)$/gm, "<h2>$1</h2>")
        .replace(/^# (.+)$/gm, "<h2>$1</h2>")
        .replace(/^---+$/gm, "<hr>")
        .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
        .replace(/\*(.*?)\*/g, "<em>$1</em>")
        .replace(/^[-•]\s(.+)$/gm, "<li>$1</li>")
        .replace(/^\d+\.\s(.+)$/gm, "<li>$1</li>")
        .replace(/\n\n/g, "<br><br>")
        .replace(/\n/g, "<br>");
    }

    async function analyze() {
      const input = document.getElementById("workloadInput").value.trim();
      if (!input) return;
      const btn = document.getElementById("analyzeBtn");
      const errBox = document.getElementById("errorBox");

      errBox.className = "error-box";
      document.getElementById("outputSection").classList.remove("visible");
      btn.textContent = "⏳ ANALYZING...";
      btn.disabled = true;

      try {
        const res = await fetch("./analyze", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ input })
        });
        const data = await res.json();
        if (data.error) throw new Error(data.error);

        document.getElementById("outputBody").innerHTML = renderMarkdown(data.output);
        document.getElementById("outputSection").classList.add("visible");
        document.getElementById("outputSection").scrollIntoView({ behavior: "smooth" });
      } catch (e) {
        errBox.textContent = "⚠️ " + e.message;
        errBox.className = "error-box visible";
      } finally {
        btn.textContent = "▶ ANALYZE";
        btn.disabled = false;
      }
    }

    // Ctrl+Enter shortcut
    document.getElementById("workloadInput").addEventListener("keydown", e => {
      if (e.ctrlKey && e.key === "Enter") { e.preventDefault(); analyze(); }
    });
  </script>
</body>
</html>
"""


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)


@app.route("/analyze", methods=["POST"])
def analyze_route():
    try:
        body = request.get_json(silent=True) or {}
        user_input = (body.get("input") or "").strip()
        if not user_input:
            return jsonify({"error": "No input provided"}), 400
        logging.info(f"[/analyze] Input: {user_input[:80]}...")
        result = run_burnout_agent(user_input)
        return jsonify({"output": result})
    except Exception as e:
        logging.error(f"[/analyze] Error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route("/health")
def health():
    return jsonify({"status": "ok"}), 200


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    logging.info(f"Starting BurnoutShield on port {port}")
    logging.info(f"  credentials.json: {'Found' if CREDENTIALS_FILE.exists() else 'MISSING'}")
    logging.info(f"  token.json: {'Found' if TOKEN_FILE.exists() else 'Not yet'}")
    logging.info(f"  Visit /setup for OAuth configuration help")
    app.run(host="0.0.0.0", port=port, debug=False)
