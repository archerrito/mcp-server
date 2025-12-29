"""MCP Provider registry."""
from .google_analytics import GoogleAnalyticsProvider

# Registry of all available providers
PROVIDERS = {
    "google_analytics": GoogleAnalyticsProvider,
}

__all__ = ["PROVIDERS", "GoogleAnalyticsProvider"]
