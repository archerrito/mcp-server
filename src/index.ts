import express from 'express';
import cors from 'cors';
import { google } from 'googleapis';

const app = express();
app.use(cors());
app.use(express.json());

// Environment variables (set in Cloud Run)
const GOOGLE_CLIENT_ID = process.env.GOOGLE_CLIENT_ID!;
const GOOGLE_CLIENT_SECRET = process.env.GOOGLE_CLIENT_SECRET!;
const REDIRECT_URI = process.env.REDIRECT_URI!;
const LOVABLE_FUNCTION_URL = process.env.LOVABLE_FUNCTION_URL!;
const MCP_BRIDGE_SECRET = process.env.MCP_BRIDGE_SECRET!;

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
  const { workspace_id, organization_id, redirect_url } = req.query;
  
  if (!workspace_id || !redirect_url) {
    return res.status(400).json({ error: 'Missing workspace_id or redirect_url' });
  }

  const state = Buffer.from(JSON.stringify({ 
    workspace_id, 
    organization_id,
    redirect_url 
  })).toString('base64');
  
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
    const { workspace_id, organization_id, redirect_url } = JSON.parse(
      Buffer.from(state as string, 'base64').toString()
    );

    const { tokens } = await oauth2Client.getToken(code as string);
    
    // Call Lovable edge function to store tokens
    const response = await fetch(LOVABLE_FUNCTION_URL, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'x-mcp-secret': MCP_BRIDGE_SECRET
      },
      body: JSON.stringify({
        workspace_id,
        organization_id,
        tokens: {
          access_token: tokens.access_token,
          refresh_token: tokens.refresh_token,
          expiry_date: tokens.expiry_date
        }
      })
    });

    if (!response.ok) {
      const error = await response.json();
      console.error('Failed to store tokens:', error);
      throw new Error('Failed to store tokens');
    }

    // Redirect back to Lovable app
    res.redirect(`${redirect_url}?success=true`);
  } catch (error) {
    console.error('OAuth callback error:', error);
    const redirect_url = req.query.state 
      ? JSON.parse(Buffer.from(req.query.state as string, 'base64').toString()).redirect_url 
      : '/';
    res.redirect(`${redirect_url}?error=auth_failed`);
  }
});

const PORT = process.env.PORT || 8080;
app.listen(PORT, () => {
  console.log(`MCP Server running on port ${PORT}`);
});
