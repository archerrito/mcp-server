"""
MCP Gateway Server for Cloud Run.

This server exposes MCP tools via HTTP transport using JSON-RPC 2.0 protocol.
It aggregates tools from multiple providers (GA4, Shopify, Klaviyo, etc.)
and handles per-user OAuth tokens passed from mcp-bridge.
"""
import os
import asyncio
import json
from typing import Any, Dict, List
from threading import Thread

from flask import Flask, request, jsonify
from dotenv import load_dotenv

from providers import PROVIDERS
from auth import create_auth_app

# Load environment variables
load_dotenv()

PORT = int(os.environ.get("PORT", 8080))
MCP_BRIDGE_SECRET = os.environ.get("MCP_BRIDGE_SECRET")


def create_mcp_app() -> Flask:
    """Create Flask app for MCP JSON-RPC endpoint."""
    app = Flask(__name__)
    
    # Merge auth routes
    auth_app = create_auth_app()
    for rule in auth_app.url_map.iter_rules():
        if rule.endpoint != 'static':
            app.add_url_rule(
                rule.rule,
                endpoint=rule.endpoint,
                view_func=auth_app.view_functions[rule.endpoint],
                methods=rule.methods - {'OPTIONS', 'HEAD'}
            )
    
    @app.route("/", methods=["GET"])
    def root():
        """Root endpoint with server info."""
        return jsonify({
            "name": "MCP Gateway",
            "version": "1.0.0",
            "protocol": "JSON-RPC 2.0",
            "endpoints": {
                "mcp": "/mcp (POST)",
                "auth_init": "/auth/init (GET)",
                "auth_callback": "/auth/callback (GET)",
                "health": "/health (GET)",
            },
            "providers": list(PROVIDERS.keys()),
        })
    
    @app.route("/mcp", methods=["POST", "OPTIONS"])
    def mcp_endpoint():
        """
        MCP JSON-RPC 2.0 endpoint.
        
        Supports methods:
        - tools/list: List all available tools from all providers
        - tools/call: Execute a tool with given arguments
        """
        # Handle CORS preflight
        if request.method == "OPTIONS":
            response = jsonify({})
            response.headers["Access-Control-Allow-Origin"] = "*"
            response.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
            return response
        
        try:
            body = request.get_json()
        except Exception as e:
            return _jsonrpc_error(-32700, "Parse error", str(e), None)
        
        jsonrpc = body.get("jsonrpc")
        method = body.get("method")
        params = body.get("params", {})
        request_id = body.get("id")
        
        # Validate JSON-RPC format
        if jsonrpc != "2.0":
            return _jsonrpc_error(-32600, "Invalid Request", "jsonrpc must be '2.0'", request_id)
        
        if not method:
            return _jsonrpc_error(-32600, "Invalid Request", "method is required", request_id)
        
        # Verify authorization (optional but recommended)
        auth_header = request.headers.get("Authorization", "")
        if MCP_BRIDGE_SECRET and not auth_header.endswith(MCP_BRIDGE_SECRET):
            # For now, just log - don't block (for easier testing)
            print("[mcp] Warning: Missing or invalid authorization")
        
        # Route to appropriate handler
        if method == "tools/list":
            result = handle_tools_list(params)
        elif method == "tools/call":
            result = handle_tools_call(params)
        else:
            return _jsonrpc_error(-32601, "Method not found", f"Unknown method: {method}", request_id)
        
        response = jsonify({
            "jsonrpc": "2.0",
            "result": result,
            "id": request_id,
        })
        response.headers["Access-Control-Allow-Origin"] = "*"
        return response
    
    return app


def handle_tools_list(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handle tools/list method.
    Returns all available tools from all registered providers.
    """
    tools = []
    
    for provider_id, provider_class in PROVIDERS.items():
        # Create provider instance (no credentials needed for listing)
        provider = provider_class()
        
        for tool in provider.get_tools():
            # Namespace tool name with provider ID
            namespaced_name = f"{provider_id}__{tool.name}"
            
            tools.append({
                "name": namespaced_name,
                "description": f"[{provider.name}] {tool.description}",
                "inputSchema": tool.input_schema,
            })
    
    return {"tools": tools}


def handle_tools_call(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handle tools/call method.
    Routes to the appropriate provider and executes the tool.
    """
    tool_name = params.get("name")
    arguments = params.get("arguments", {})
    credentials = params.get("_credentials", {})
    
    if not tool_name:
        raise ValueError("Tool name is required")
    
    # Parse namespaced tool name
    if "__" not in tool_name:
        raise ValueError(f"Invalid tool name format: {tool_name}. Expected 'provider__tool_name'")
    
    provider_id, actual_tool_name = tool_name.split("__", 1)
    
    # Get provider class
    provider_class = PROVIDERS.get(provider_id)
    if not provider_class:
        raise ValueError(f"Unknown provider: {provider_id}")
    
    # Extract credentials
    access_token = credentials.get("access_token")
    if not access_token:
        raise ValueError(f"No access_token provided for {provider_id}")
    
    # Create provider instance with credentials
    provider = provider_class(
        access_token=access_token,
        credentials=credentials,
    )
    
    # Find and execute tool
    tool = provider.get_tool_by_name(actual_tool_name)
    if not tool:
        raise ValueError(f"Unknown tool: {actual_tool_name} for provider {provider_id}")
    
    # Execute tool handler
    result = asyncio.run(tool.handler(**arguments))
    
    return result


def _jsonrpc_error(code: int, message: str, data: str = None, request_id: Any = None):
    """Create a JSON-RPC error response."""
    error = {"code": code, "message": message}
    if data:
        error["data"] = data
    
    response = jsonify({
        "jsonrpc": "2.0",
        "error": error,
        "id": request_id,
    })
    response.headers["Access-Control-Allow-Origin"] = "*"
    return response


if __name__ == "__main__":
    app = create_mcp_app()
    print(f"🚀 MCP Gateway starting on port {PORT}")
    print(f"📦 Registered providers: {list(PROVIDERS.keys())}")
    app.run(host="0.0.0.0", port=PORT, debug=False)
