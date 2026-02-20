"""
RAOB Sounding Data MCP Server
Provides access to radiosonde (weather balloon) upper air sounding data
via the Iowa State IEM archive. Free, no API key required.
"""

import json
import math
import logging
import os
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict

import httpx
import uvicorn
from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Server init
# ---------------------------------------------------------------------------

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from mcp.server.transport_security import TransportSecuritySettings

mcp = FastMCP(
    "raob_sounding_mcp",
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=False
    )
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

IEM_BASE_URL = "https://mesonet.agron.iastate.edu"
IEM_SOUNDING_URL = f"{IEM_BASE_URL}/json/raob.py"
IEM_NETWORK_URL = f"{IEM_BASE_URL}/api/1/network/RAOB.json"
TIMEOUT = 30.0

VALID_HOURS = {0, 12}   # Standard sounding times (UTC)

# ---------------------------------------------------------------------------
# Shared HTTP helpers
# ---------------------------------------------------------------------------

async def _iem_get(url: str, params: dict) -> dict:
    """Shared GET helper for IEM API calls."""
    headers = {"User-Agent": "raob-sounding-mcp/1.0"}
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await client.get(url, params=params, headers=headers)
        resp.raise_for_status()
        return resp.json()


def _handle_error(e: Exception) -> str:
    """Consistent error formatting across all tools."""
    if isinstance(e, httpx.HTTPStatusError):
        if e.response.status_code == 404:
            return "Error: Sounding data not found. Check station ID, date, and hour."
        elif e.response.status_code == 429:
            return "Error: Rate limit exceeded. Please wait before retrying."
        return f"Error: IEM API returned status {e.response.status_code}."
    elif isinstance(e, httpx.TimeoutException):
        return "Error: Request timed out. IEM may be slow — try again."
    return f"Error: {type(e).__name__}: {str(e)}"


# ---------------------------------------------------------------------------
# Input models
# ---------------------------------------------------------------------------

class FindStationInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    query: Optional[str] = Field(
        default=None,
        description="Station name or ID to search for (e.g. 'Tucson', 'TUS', 'KTUS')"
    )
    lat: Optional[float] = Field(
        default=None,
        description="Latitude for nearest-station search (e.g. 32.12)",
        ge=-90, le=90
    )
    lon: Optional[float] = Field(
        default=None,
        description="Longitude for nearest-station search (e.g. -110.93)",
        ge=-180, le=180
    )


class GetSoundingInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    station: str = Field(
        ...,
        description="Station ID — 3-letter (e.g. 'TUS') or WMO number. Use find_raob_station to look up IDs.",
        min_length=2,
        max_length=6
    )
    date: str = Field(
        ...,
        description="Date in YYYY-MM-DD format (e.g. '2025-12-15')",
        pattern=r"^\d{4}-\d{2}-\d{2}$"
    )
    hour: int = Field(
        default=0,
        description="Sounding hour in UTC: 0 (midnight) or 12 (noon). Soundings are released twice daily.",
        ge=0,
        le=23
    )


class GetRecentSoundingsInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    station: str = Field(
        ...,
        description="Station ID — 3-letter (e.g. 'TUS') or WMO number.",
        min_length=2,
        max_length=6
    )
    start_date: str = Field(
        ...,
        description="Start date in YYYY-MM-DD format",
        pattern=r"^\d{4}-\d{2}-\d{2}$"
    )
    end_date: str = Field(
        ...,
        description="End date in YYYY-MM-DD format",
        pattern=r"^\d{4}-\d{2}-\d{2}$"
    )


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool(
    name="find_raob_station",
    annotations={
        "title": "Find RAOB Launch Station",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
async def find_raob_station(params: FindStationInput) -> str:
    """Find a radiosonde (weather balloon) launch station by name/ID or nearest GPS coordinates.

    Use this first to get the correct station ID before calling get_sounding.
    Returns station name, ID, latitude, longitude, and elevation.

    Args:
        params (FindStationInput): Search parameters containing:
            - query (Optional[str]): Station name or ID to search for
            - lat (Optional[float]): Latitude for nearest-station lookup
            - lon (Optional[float]): Longitude for nearest-station lookup

    Returns:
        str: JSON with matching stations or the single nearest station.
    """
    if not params.query and (params.lat is None or params.lon is None):
        return "Error: Provide either a 'query' (name/ID) or both 'lat' and 'lon' coordinates."

    try:
        data = await _iem_get(IEM_NETWORK_URL, {})
        stations = data.get("data", [])

        if params.query:
            q = params.query.upper()
            matches = [
                s for s in stations
                if q in s.get("id", "").upper() or q in s.get("name", "").upper()
            ]
            return json.dumps({"matches": matches[:8]}, indent=2)

        # Nearest by Pythagorean approximation (fine for proximity search)
        closest = min(
            stations,
            key=lambda s: math.sqrt(
                (params.lat - s["lat"]) ** 2 + (params.lon - s["lon"]) ** 2
            )
        )
        return json.dumps({"closest_station": closest}, indent=2)

    except Exception as e:
        return _handle_error(e)


@mcp.tool(
    name="get_sounding",
    annotations={
        "title": "Get RAOB Sounding Profile",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
async def get_sounding(params: GetSoundingInput) -> str:
    """Fetch a single radiosonde upper air sounding (RAOB) for a station, date, and hour.

    Returns the complete vertical profile: pressure, height, temperature, dewpoint,
    wind direction/speed at each mandatory and significant level from surface to
    stratosphere. Also includes computed stability indices.

    Soundings are taken twice daily at 00Z (midnight UTC) and 12Z (noon UTC).
    Use find_raob_station to look up station IDs.

    Args:
        params (GetSoundingInput): Query parameters containing:
            - station (str): 3-letter station ID (e.g. 'TUS', 'ABQ', 'DNR')
            - date (str): Date in YYYY-MM-DD format
            - hour (int): 0 or 12 UTC

    Returns:
        str: JSON with sounding levels (pressure, height, temp, dewpoint, wind)
             and station metadata.
    """
    try:
        ts = f"{params.date.replace('-', '')}{params.hour:02d}00"
        query_params = {
            "station": params.station.upper(),
            "ts": ts,
        }
        data = await _iem_get(IEM_SOUNDING_URL, query_params)

        if not data.get("profiles"):
            return f"Sounding data not found for {params.station} on {params.date} {params.hour:02d}Z."

        return json.dumps(data, indent=2)

    except Exception as e:
        return _handle_error(e)


@mcp.tool(
    name="get_soundings_range",
    annotations={
        "title": "Get Soundings Over a Date Range",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
async def get_soundings_range(params: GetRecentSoundingsInput) -> str:
    """Fetch all available soundings for a station over a date range (both 00Z and 12Z).

    Useful for tracking atmospheric changes during weather events, or reviewing
    multiple days of upper air data for forecast verification.

    Args:
        params (GetRecentSoundingsInput): Query parameters containing:
            - station (str): 3-letter station ID
            - start_date (str): Start date in YYYY-MM-DD format
            - end_date (str): End date in YYYY-MM-DD format

    Returns:
        str: JSON with list of available soundings across the date range.
             Each sounding includes full vertical profile data.
    """
    try:
        from datetime import date, timedelta
        start = date.fromisoformat(params.start_date)
        end = date.fromisoformat(params.end_date)
        all_profiles = []

        current = start
        while current <= end:
            for hour in [0, 12]:
                ts = f"{current.strftime('%Y%m%d')}{hour:02d}00"
                query_params = {"station": params.station.upper(), "ts": ts}
                data = await _iem_get(IEM_SOUNDING_URL, query_params)
                all_profiles.extend(data.get("profiles", []))
            current += timedelta(days=1)

        return json.dumps({"profiles": all_profiles}, indent=2)

    except Exception as e:
        return _handle_error(e)


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

from starlette.middleware.trustedhost import TrustedHostMiddleware

if __name__ == "__main__":
    logger.info("Starting RAOB Sounding Data MCP server")
    port = int(os.environ.get("PORT", 8000))
    app = mcp.streamable_http_app()
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["*"])
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        proxy_headers=True,
        forwarded_allow_ips="*"
    )
