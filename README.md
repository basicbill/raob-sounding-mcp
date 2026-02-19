# RAOB Sounding Data MCP Server

A hosted MCP (Model Context Protocol) server that gives Claude direct access to real-time and archived **radiosonde upper air sounding data** via the Iowa State IEM archive — no web searching needed.

## Features

- **Find Station** — Locate a RAOB launch site by name/ID or nearest GPS coordinates
- **Single Sounding** — Fetch the full vertical profile for a station, date, and hour (00Z or 12Z)
- **Date Range** — Pull all soundings across a multi-day period for weather event analysis

## Data Source

All data comes from the **Iowa State University IEM Sounding Archive**, which ingests near real-time data from the Storm Prediction Center (SPC) and backfills from the NCEI Integrated Global Radiosonde Archive. Free, no API key required.

US and Canadian stations available. Soundings released twice daily at **00Z** and **12Z**.

## How It Works

- **FastMCP** (Python) for MCP protocol handling
- **Streamable HTTP** transport for remote access
- **Railway.com** for hosting

Once deployed, add it as a custom connector in Claude Chat and Claude can directly query upper air sounding data.

## Tools Reference

| Tool | Description |
|------|-------------|
| `find_raob_station` | Find a station by name/ID or nearest lat/lon |
| `get_sounding` | Full vertical profile for a specific date/time |
| `get_soundings_range` | All soundings across a date range |

## Deploy to Railway

1. Push this repo to GitHub
2. Create a **New Project** on [railway.com](https://railway.com)
3. Connect to this GitHub repo
4. Railway auto-detects Python via the `Procfile`
5. No environment variables needed

## Add to Claude Chat

1. Go to Claude Chat Settings → Connectors
2. Click "Add custom connector"
3. Enter your Railway URL + `/mcp` (e.g., `https://your-app.up.railway.app/mcp`)
4. Name it "RAOB Soundings"
5. Start asking Claude about upper air data!

## Example Prompts

- "Find the nearest RAOB station to Tucson AZ"
- "Get the 12Z sounding for TUS on December 15, 2025"
- "Pull all soundings for ABQ from February 10-15, 2026"
- "What was the 500mb temperature at Denver for the 00Z sounding yesterday?"

## Development

Run locally:
```bash
pip install -r requirements.txt
python server.py
```

Server starts on `http://localhost:8000/mcp`

## License

MIT

## Author

Built by a retired corporate pilot and weather enthusiast. 🎈
