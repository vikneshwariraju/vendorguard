# VendorGuard - Vendor Renewal & Risk Tracker
Claude reads contracts and calls MCP tools. VendorGuard stores vendors, computes the
"Act by" date (contract end - notice days), shows the dashboard and lets people edit.
No AI inside, no AI keys anywhere.

## Run locally
    python -m venv .venv && . .venv/bin/activate
    pip install -r requirements.txt
    python seed.py            # optional demo data
    MCP_KEY=mysecret uvicorn main:app --reload
    # app: http://localhost:8000   MCP: http://localhost:8000/mcp/?key=mysecret

## Deploy (Render)
1. Push this folder to a GitHub repo.
2. Render > New > PostgreSQL. Copy the Internal database URL.
3. Render > New > Web Service > your repo > Runtime: Docker.
4. Env vars: DATABASE_URL = (the Postgres URL), MCP_KEY = (a long random string).
5. Deploy. Open the URL.

## Connect to Claude
Claude.ai > Settings > Connectors > Add custom connector
- Name: VendorGuard
- URL: https://YOUR-APP.onrender.com/mcp/?key=YOUR_MCP_KEY
Then in a new chat enable the connector and try:
"Read this contract and create a vendor record in VendorGuard."

## Tools
create_vendor, update_vendor, list_vendors
