"""Whale zones — NOAA Fisheries Seasonal Management Areas (SMAs).

Sprint D6.97 #49 (2026-05-25) — Maersk demo asset. Standalone Leaflet
map page at /whale-zones showing the published SMAs from 50 CFR 224.105
where vessels ≥35 ft are restricted to 10 knots seasonally.

This is intentionally a separate route from /chat. The product story:
"we monitor active whale management areas; route awareness for compliance
officers." Future iterations: live DMA (Dynamic Management Area) feed
from NOAA WhaleAlert, vessel-position proximity warnings if GPS opt-in.

Public endpoint — no auth required. The zone polygons are public
regulatory data (50 CFR 224.105) so we don't gate them.
"""

from datetime import date, datetime
from typing import Any

from fastapi import APIRouter

from app.data.whale_sma_zones import get_sma_features

router = APIRouter(prefix="/whale-zones", tags=["whale-zones"])


@router.get("/sma", response_model=dict)
async def get_smas(active_only: bool = False) -> dict[str, Any]:
    """Return NOAA Fisheries Seasonal Management Areas as GeoJSON
    FeatureCollection.

    Args:
        active_only: If true, filter to zones whose seasonal window
                     includes today's date. Default false (return all).

    Each Feature carries properties:
      - name, description (human-readable)
      - season_start, season_end (MM-DD)
      - speed_limit_knots (typically 10)
      - vessel_threshold_ft (typically 35)
      - authority (regulatory citation)
      - zone_type ("SMA")
      - mandatory (bool — SMAs are mandatory; DMAs would be voluntary)
      - active_now (computed: true if today falls in the season window)
    """
    features = get_sma_features()
    today = date.today()

    for feature in features:
        feature["properties"]["active_now"] = _is_active(
            today,
            feature["properties"]["season_start"],
            feature["properties"]["season_end"],
        )

    if active_only:
        features = [f for f in features if f["properties"]["active_now"]]

    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "source": "50 CFR 224.105",
            "authority": "NOAA Fisheries — North Atlantic Right Whale Vessel Speed Rule",
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "note": (
                "Polygons in this endpoint are approximations of the boundaries "
                "published in 50 CFR 224.105. For navigational use consult the "
                "authoritative NOAA Fisheries chart layers."
            ),
        },
    }


def _is_active(today: date, season_start: str, season_end: str) -> bool:
    """Determine whether a date falls within a seasonal window expressed
    as MM-DD strings. Handles wrap-around seasons (Nov 1 to Apr 30 spans
    year-end)."""
    start_month, start_day = map(int, season_start.split("-"))
    end_month, end_day = map(int, season_end.split("-"))

    today_md = (today.month, today.day)
    start_md = (start_month, start_day)
    end_md = (end_month, end_day)

    if start_md <= end_md:
        # Window does not cross year boundary
        return start_md <= today_md <= end_md
    else:
        # Wrap-around: active if today >= start OR today <= end
        return today_md >= start_md or today_md <= end_md
