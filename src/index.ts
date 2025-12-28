import express from 'express';
import cors from 'cors';
import { google } from 'googleapis';
import { createClient } from '@supabase/supabase-js';

const app = express();
app.use(cors());
app.use(express.json());

// Environment variables (set in Cloud Run)
const GOOGLE_CLIENT_ID = process.env.GOOGLE_CLIENT_ID!;
const GOOGLE_CLIENT_SECRET = process.env.GOOGLE_CLIENT_SECRET!;
const SUPABASE_URL = process.env.SUPABASE_URL!;
const SUPABASE_SERVICE_KEY = process.env.SUPABASE_SERVICE_KEY!;
const REDIRECT_URI = process.env.REDIRECT_URI!; // Your Cloud Run URL + /callback

const supabase = createClient(SUPABASE_URL, SUPABASE_SERVICE_KEY);

const oauth2Client = new google.auth.OAuth2(
  GOOGLE_CLIENT_ID,
  GOOGLE_CLIENT_SECRET,
  REDIRECT_URI
);

// Health check
app.get('/', (req, res) => {
  res.json({ status: 'ok', service: 'Google Analytics MCP Server' });
});

// Initiate OAuth flow
app.get('/auth/init', (req, res) => {
  const { workspace_id, redirect_url } = req.query;
  
  if (!workspace_id || !redirect_url) {
    return res.status(400).json({ error: 'Missing workspace_id or redirect_url' });
  }

  const state = Buffer.from(JSON.stringify({ workspace_id, redirect_url })).toString('base64');
  
  const authUrl = oauth2Client.generateAuthUrl({
    access_type: 'offline',
    prompt: 'consent',
    scope: [
      'https://www.googleapis.com/auth/analytics.readonly',
      'https://www.googleapis.com/auth/analytics'
    ],
    state
  });

  res.json({ auth_url: authUrl });
});

// OAuth callback
app.get('/callback', async (req, res) => {
  const { code, state } = req.query;
  
  try {
    const { workspace_id, redirect_url } = JSON.parse(
      Buffer.from(state as string, 'base64').toString()
    );

    const { tokens } = await oauth2Client.getToken(code as string);
    
    // Store tokens in Supabase integrations table
    const { error } = await supabase
      .from('integrations')
      .upsert({
        workspace_id,
        platform: 'google_analytics',
        status: 'connected',
        credentials: {
          access_token: tokens.access_token,
          refresh_token: tokens.refresh_token,
          expiry_date: tokens.expiry_date
        },
        connected_at: new Date().toISOString()
      }, {
        onConflict: 'workspace_id,platform'
      });

    if (error) throw error;

    // Redirect back to Lovable app
    res.redirect(`${redirect_url}?success=true`);
  } catch (error) {
    console.error('OAuth callback error:', error);
    res.redirect(`${req.query.redirect_url || '/'}?error=auth_failed`);
  }
});

// Query Google Analytics
app.post('/query', async (req, res) => {
  const { workspace_id, tool, params } = req.body;

  try {
    // Get stored credentials
    const { data: integration, error } = await supabase
      .from('integrations')
      .select('credentials')
      .eq('workspace_id', workspace_id)
      .eq('platform', 'google_analytics')
      .single();

    if (error || !integration?.credentials) {
      return res.status(401).json({ error: 'Not connected to Google Analytics' });
    }

    const { access_token, refresh_token, expiry_date } = integration.credentials;
    
    oauth2Client.setCredentials({
      access_token,
      refresh_token,
      expiry_date
    });

    // Refresh token if expired
    if (expiry_date && Date.now() > expiry_date) {
      const { credentials } = await oauth2Client.refreshAccessToken();
      oauth2Client.setCredentials(credentials);
      
      // Update stored tokens
      await supabase
        .from('integrations')
        .update({
          credentials: {
            access_token: credentials.access_token,
            refresh_token: credentials.refresh_token || refresh_token,
            expiry_date: credentials.expiry_date
          }
        })
        .eq('workspace_id', workspace_id)
        .eq('platform', 'google_analytics');
    }

    const analyticsData = google.analyticsdata({ version: 'v1beta', auth: oauth2Client });
    
    let result;
    
    switch (tool) {
      case 'get_traffic_overview':
        result = await analyticsData.properties.runReport({
          property: `properties/${params.property_id}`,
          requestBody: {
            dateRanges: [{ startDate: params.start_date || '30daysAgo', endDate: params.end_date || 'today' }],
            metrics: [
              { name: 'sessions' },
              { name: 'activeUsers' },
              { name: 'screenPageViews' },
              { name: 'bounceRate' }
            ],
            dimensions: [{ name: 'date' }]
          }
        });
        break;
        
      case 'get_top_pages':
        result = await analyticsData.properties.runReport({
          property: `properties/${params.property_id}`,
          requestBody: {
            dateRanges: [{ startDate: params.start_date || '30daysAgo', endDate: params.end_date || 'today' }],
            metrics: [{ name: 'screenPageViews' }, { name: 'activeUsers' }],
            dimensions: [{ name: 'pagePath' }],
            limit: params.limit || 10
          }
        });
        break;
        
      case 'get_traffic_sources':
        result = await analyticsData.properties.runReport({
          property: `properties/${params.property_id}`,
          requestBody: {
            dateRanges: [{ startDate: params.start_date || '30daysAgo', endDate: params.end_date || 'today' }],
            metrics: [{ name: 'sessions' }, { name: 'activeUsers' }],
            dimensions: [{ name: 'sessionSource' }, { name: 'sessionMedium' }]
          }
        });
        break;

      case 'list_properties':
        const admin = google.analyticsadmin({ version: 'v1beta', auth: oauth2Client });
        result = await admin.accountSummaries.list();
        break;
        
      default:
        return res.status(400).json({ error: `Unknown tool: ${tool}` });
    }

    res.json({ data: result.data });
  } catch (error: any) {
    console.error('Query error:', error);
    res.status(500).json({ error: error.message });
  }
});

// Disconnect
app.post('/disconnect', async (req, res) => {
  const { workspace_id } = req.body;
  
  try {
    await supabase
      .from('integrations')
      .update({ status: 'disconnected', credentials: null })
      .eq('workspace_id', workspace_id)
      .eq('platform', 'google_analytics');
      
    res.json({ success: true });
  } catch (error: any) {
    res.status(500).json({ error: error.message });
  }
});

const PORT = process.env.PORT || 8080;
app.listen(PORT, () => {
  console.log(`MCP Server running on port ${PORT}`);
});
