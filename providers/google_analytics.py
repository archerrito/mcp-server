"""Google Analytics 4 MCP Provider.

Adapted from the official googleanalytics/google-analytics-mcp server
to support per-user OAuth tokens instead of Application Default Credentials.
"""
from typing import Any, Dict, List, Optional
from dataclasses import dataclass
import json

from google.oauth2.credentials import Credentials
from google.analytics.admin_v1beta import AnalyticsAdminServiceClient
from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    RunReportRequest,
    RunRealtimeReportRequest,
    DateRange,
    Dimension,
    Metric,
)

from .base import MCPProvider, ToolDefinition


class GoogleAnalyticsProvider(MCPProvider):
    """Google Analytics 4 MCP Provider."""
    
    id = "google_analytics"
    name = "Google Analytics"
    description = "Access Google Analytics 4 data and reports"
    auth_type = "oauth2"
    
    SCOPES = ["https://www.googleapis.com/auth/analytics.readonly"]
    
    def __init__(self, access_token: str = None, credentials: Dict[str, Any] = None):
        super().__init__(access_token, credentials)
        self._admin_client = None
        self._data_client = None
    
    def _get_credentials(self) -> Credentials:
    """Build Google credentials from access token."""
    if not self.access_token:
        raise ValueError("No access token provided")
    
    creds = Credentials(
        token=self.access_token,
        refresh_token=self.credentials.get("refresh_token"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=self.credentials.get("client_id"),
        client_secret=self.credentials.get("client_secret"),
    )
    
    # Refresh if expired
    if creds.expired and creds.refresh_token:
        from google.auth.transport.requests import Request
        creds.refresh(Request())
    
    return creds
    
    def _get_admin_client(self) -> AnalyticsAdminServiceClient:
        """Get or create Analytics Admin API client."""
        if not self._admin_client:
            credentials = self._get_credentials()
            self._admin_client = AnalyticsAdminServiceClient(credentials=credentials)
        return self._admin_client
    
    def _get_data_client(self) -> BetaAnalyticsDataClient:
        """Get or create Analytics Data API client."""
        if not self._data_client:
            credentials = self._get_credentials()
            self._data_client = BetaAnalyticsDataClient(credentials=credentials)
        return self._data_client
    
    def get_tools(self) -> List[ToolDefinition]:
        """Return all GA4 tools."""
        return [
            ToolDefinition(
                name="get_account_summaries",
                description="List all Google Analytics 4 accounts and properties the user has access to. Returns account IDs, names, and their associated properties.",
                input_schema={
                    "type": "object",
                    "properties": {},
                    "required": []
                },
                handler=self._get_account_summaries
            ),
            ToolDefinition(
                name="get_property_details",
                description="Get detailed information about a specific GA4 property including its configuration, data retention settings, and linked services.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "property_id": {
                            "type": "string",
                            "description": "The GA4 property ID (e.g., 'properties/123456789')"
                        }
                    },
                    "required": ["property_id"]
                },
                handler=self._get_property_details
            ),
            ToolDefinition(
                name="run_report",
                description="Run a Google Analytics 4 report with custom dimensions, metrics, and date ranges. Use this to get traffic, user behavior, conversions, and other analytics data.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "property_id": {
                            "type": "string",
                            "description": "The GA4 property ID (e.g., 'properties/123456789' or just '123456789')"
                        },
                        "dimensions": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Dimensions to include (e.g., ['date', 'country', 'deviceCategory', 'sessionDefaultChannelGroup'])"
                        },
                        "metrics": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Metrics to include (e.g., ['activeUsers', 'sessions', 'screenPageViews', 'conversions'])"
                        },
                        "date_range": {
                            "type": "string",
                            "description": "Date range: '7d', '30d', '90d', or 'YYYY-MM-DD,YYYY-MM-DD' for custom range"
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of rows to return (default: 100)"
                        }
                    },
                    "required": ["property_id"]
                },
                handler=self._run_report
            ),
            ToolDefinition(
                name="run_realtime_report",
                description="Run a realtime report showing current active users and their activity in the last 30 minutes.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "property_id": {
                            "type": "string",
                            "description": "The GA4 property ID"
                        },
                        "dimensions": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Realtime dimensions (e.g., ['country', 'city', 'unifiedScreenName'])"
                        },
                        "metrics": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Realtime metrics (e.g., ['activeUsers', 'screenPageViews'])"
                        }
                    },
                    "required": ["property_id"]
                },
                handler=self._run_realtime_report
            ),
            ToolDefinition(
                name="get_custom_dimensions_and_metrics",
                description="Get the custom dimensions and metrics configured for a GA4 property.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "property_id": {
                            "type": "string",
                            "description": "The GA4 property ID"
                        }
                    },
                    "required": ["property_id"]
                },
                handler=self._get_custom_dimensions_and_metrics
            ),
            ToolDefinition(
                name="list_google_ads_links",
                description="List Google Ads account links for a GA4 property.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "property_id": {
                            "type": "string",
                            "description": "The GA4 property ID"
                        }
                    },
                    "required": ["property_id"]
                },
                handler=self._list_google_ads_links
            ),
        ]
    
    # ==================== Tool Implementations ====================
    
    async def _get_account_summaries(self, **kwargs) -> Dict[str, Any]:
        """List all GA4 accounts and properties."""
        client = self._get_admin_client()
        
        accounts = []
        for account_summary in client.list_account_summaries():
            properties = []
            for prop in account_summary.property_summaries:
                properties.append({
                    "property_id": prop.property,
                    "display_name": prop.display_name,
                })
            
            accounts.append({
                "account_id": account_summary.account,
                "display_name": account_summary.display_name,
                "properties": properties,
            })
        
        return {"accounts": accounts}
    
    async def _get_property_details(self, property_id: str, **kwargs) -> Dict[str, Any]:
        """Get details about a specific property."""
        client = self._get_admin_client()
        
        # Normalize property ID format
        if not property_id.startswith("properties/"):
            property_id = f"properties/{property_id}"
        
        property_obj = client.get_property(name=property_id)
        
        return {
            "property_id": property_obj.name,
            "display_name": property_obj.display_name,
            "time_zone": property_obj.time_zone,
            "currency_code": property_obj.currency_code,
            "industry_category": str(property_obj.industry_category),
            "create_time": property_obj.create_time.isoformat() if property_obj.create_time else None,
            "update_time": property_obj.update_time.isoformat() if property_obj.update_time else None,
        }
    
    async def _run_report(
        self,
        property_id: str,
        dimensions: Optional[List[str]] = None,
        metrics: Optional[List[str]] = None,
        date_range: str = "30d",
        limit: int = 100,
        **kwargs
    ) -> Dict[str, Any]:
        """Run a GA4 report."""
        client = self._get_data_client()
        
        # Normalize property ID
        if not property_id.startswith("properties/"):
            property_id = f"properties/{property_id}"
        
        # Parse date range
        start_date, end_date = self._parse_date_range(date_range)
        
        # Default dimensions and metrics if not provided
        if not dimensions:
            dimensions = ["date"]
        if not metrics:
            metrics = ["activeUsers", "sessions"]
        
        # Build request
        request = RunReportRequest(
            property=property_id,
            dimensions=[Dimension(name=d) for d in dimensions],
            metrics=[Metric(name=m) for m in metrics],
            date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
            limit=limit,
        )
        
        response = client.run_report(request)
        
        # Format response
        rows = []
        for row in response.rows:
            row_data = {}
            for i, dim_value in enumerate(row.dimension_values):
                row_data[dimensions[i]] = dim_value.value
            for i, metric_value in enumerate(row.metric_values):
                row_data[metrics[i]] = metric_value.value
            rows.append(row_data)
        
        return {
            "property_id": property_id,
            "date_range": {"start": start_date, "end": end_date},
            "row_count": len(rows),
            "rows": rows,
        }
    
    async def _run_realtime_report(
        self,
        property_id: str,
        dimensions: Optional[List[str]] = None,
        metrics: Optional[List[str]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Run a realtime report."""
        client = self._get_data_client()
        
        if not property_id.startswith("properties/"):
            property_id = f"properties/{property_id}"
        
        if not dimensions:
            dimensions = ["country"]
        if not metrics:
            metrics = ["activeUsers"]
        
        request = RunRealtimeReportRequest(
            property=property_id,
            dimensions=[Dimension(name=d) for d in dimensions],
            metrics=[Metric(name=m) for m in metrics],
        )
        
        response = client.run_realtime_report(request)
        
        rows = []
        for row in response.rows:
            row_data = {}
            for i, dim_value in enumerate(row.dimension_values):
                row_data[dimensions[i]] = dim_value.value
            for i, metric_value in enumerate(row.metric_values):
                row_data[metrics[i]] = metric_value.value
            rows.append(row_data)
        
        return {
            "property_id": property_id,
            "row_count": len(rows),
            "rows": rows,
        }
    
    async def _get_custom_dimensions_and_metrics(
        self, property_id: str, **kwargs
    ) -> Dict[str, Any]:
        """Get custom dimensions and metrics for a property."""
        client = self._get_admin_client()
        
        if not property_id.startswith("properties/"):
            property_id = f"properties/{property_id}"
        
        # Get custom dimensions
        custom_dimensions = []
        for cd in client.list_custom_dimensions(parent=property_id):
            custom_dimensions.append({
                "name": cd.parameter_name,
                "display_name": cd.display_name,
                "description": cd.description,
                "scope": str(cd.scope),
            })
        
        # Get custom metrics
        custom_metrics = []
        for cm in client.list_custom_metrics(parent=property_id):
            custom_metrics.append({
                "name": cm.parameter_name,
                "display_name": cm.display_name,
                "description": cm.description,
                "measurement_unit": str(cm.measurement_unit),
                "scope": str(cm.scope),
            })
        
        return {
            "property_id": property_id,
            "custom_dimensions": custom_dimensions,
            "custom_metrics": custom_metrics,
        }
    
    async def _list_google_ads_links(self, property_id: str, **kwargs) -> Dict[str, Any]:
        """List Google Ads links for a property."""
        client = self._get_admin_client()
        
        if not property_id.startswith("properties/"):
            property_id = f"properties/{property_id}"
        
        links = []
        for link in client.list_google_ads_links(parent=property_id):
            links.append({
                "name": link.name,
                "customer_id": link.customer_id,
                "can_manage_clients": link.can_manage_clients,
                "ads_personalization_enabled": link.ads_personalization_enabled,
            })
        
        return {
            "property_id": property_id,
            "google_ads_links": links,
        }
    
    # ==================== Helpers ====================
    
    def _parse_date_range(self, date_range: str) -> tuple[str, str]:
        """Parse date range string into start and end dates."""
        from datetime import datetime, timedelta
        
        today = datetime.now()
        
        if date_range == "7d":
            start = today - timedelta(days=7)
            return start.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")
        elif date_range == "30d":
            start = today - timedelta(days=30)
            return start.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")
        elif date_range == "90d":
            start = today - timedelta(days=90)
            return start.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")
        elif "," in date_range:
            parts = date_range.split(",")
            return parts[0].strip(), parts[1].strip()
        else:
            # Default to last 30 days
            start = today - timedelta(days=30)
            return start.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")
