"""OAuth authentication endpoints for MCP providers."""
import os
import json
import secrets
from urllib.parse import urlencode
from flask import Flask, request, redirect, jsonify
import requests

# OAuth configuration
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")
MCP_BRIDGE_URL = os.environ.get("MCP_BRIDGE_URL")
MCP_BRIDGE_SECRET = os.environ.get("MCP_BRIDGE_SECRET")

# OAuth endpoints
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"

# Scopes for different providers
PROVIDER_SCOPES = {
    "google_analytics": [
        "https://www.googleapis.com/auth/analytics.readonly",
    ],
}


def create_auth_app() -> Flask:
    """Create Flask app for OAuth endpoints."""
    app = Flask(__name__)
    
    @app.route("/auth/init", methods=["GET"])
    def auth_init():
        """Initialize OAuth flow for a provider."""
        provider = request.args.get("provider", "google_analytics")
        workspace_id = request.args.get("workspace_id")
        redirect_uri = request.args.get("redirect_uri")
        
        if not workspace_id:
            return jsonify({"error": "workspace_id is required"}), 400
        
        if provider == "google_analytics":
            # Build state with workspace info
            state = json.dumps({
                "provider": provider,
                "workspace_id": workspace_id,
                "redirect_uri": redirect_uri,
                "nonce": secrets.token_urlsafe(16),
            })
            
            # Get the callback URL (this server's callback)
            callback_url = request.url_root.rstrip("/") + "/auth/callback"
            
            # Build OAuth URL
            params = {
                "client_id": GOOGLE_CLIENT_ID,
                "redirect_uri": callback_url,
                "response_type": "code",
                "scope": " ".join(PROVIDER_SCOPES[provider]),
                "access_type": "offline",
                "prompt": "consent",
                "state": state,
            }
            
            auth_url = f"{GOOGLE_AUTH_URL}?{urlencode(params)}"
            return jsonify({"auth_url": auth_url})
        
        return jsonify({"error": f"Unknown provider: {provider}"}), 400
    
    @app.route("/auth/callback", methods=["GET"])
    def auth_callback():
        """Handle OAuth callback."""
        code = request.args.get("code")
        state_str = request.args.get("state")
        error = request.args.get("error")
        
        if error:
            return f"<html><body><h1>Authentication Failed</h1><p>{error}</p></body></html>", 400
        
        if not code or not state_str:
            return "<html><body><h1>Missing parameters</h1></body></html>", 400
        
        try:
            state = json.loads(state_str)
            provider = state.get("provider")
            workspace_id = state.get("workspace_id")
            redirect_uri = state.get("redirect_uri")
        except json.JSONDecodeError:
            return "<html><body><h1>Invalid state</h1></body></html>", 400
        
        # Exchange code for tokens
        callback_url = request.url_root.rstrip("/") + "/auth/callback"
        
        token_response = requests.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": callback_url,
            },
        )
        
        if not token_response.ok:
            return f"<html><body><h1>Token exchange failed</h1><p>{token_response.text}</p></body></html>", 400
        
        tokens = token_response.json()
        
        # Send tokens to mcp-bridge to store in Supabase
        bridge_response = requests.post(
            MCP_BRIDGE_URL,
            headers={
                "Content-Type": "application/json",
                "x-mcp-secret": MCP_BRIDGE_SECRET,
            },
            json={
                "action": "store_oauth_tokens",
                "provider": provider,
                "workspace_id": workspace_id,
                "credentials": {
                    "access_token": tokens.get("access_token"),
                    "refresh_token": tokens.get("refresh_token"),
                    "expires_in": tokens.get("expires_in"),
                    "token_type": tokens.get("token_type"),
                    "scope": tokens.get("scope"),
                    # Include client credentials for token refresh
                    "client_id": GOOGLE_CLIENT_ID,
                    "client_secret": GOOGLE_CLIENT_SECRET,
                },
            },
        )
        
        if not bridge_response.ok:
            print(f"Failed to store tokens: {bridge_response.text}")
            return "<html><body><h1>Failed to save credentials</h1></body></html>", 500
        
        # Redirect back to app
        if redirect_uri:
            return redirect(f"{redirect_uri}?success=true&provider={provider}")
        
        return """
        <html>
        <body>
            <h1>Authentication Successful!</h1>
            <p>You can close this window and return to the application.</p>
            <script>
                if (window.opener) {
                    window.opener.postMessage({ type: 'oauth_success', provider: '%s' }, '*');
                    window.close();
                }
            </script>
        </body>
        </html>
        """ % provider
    
    @app.route("/health", methods=["GET"])
    def health():
        """Health check endpoint."""
        return jsonify({"status": "healthy"})
    
    return app
