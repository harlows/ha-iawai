
"""Constants for the IAWAI Water integration."""

from datetime import date

from aiohttp import ClientTimeout

DOMAIN = "iawai"
NAME = "IAWAI Water"

# IAWAI API endpoints
API_BASE_URL = "https://iawai.oplex.nz"
LOGIN_PATH = "/api/account/createtoken"
WATER_DATA_PATH = (
    "/api/WaterData/{owner_id}/{project_id}/{site_group_id}/{site_id}"
    "/PulseTimeSeries"
)

# API request settings
API_INTERVAL_SECONDS = 3600
API_AGGREGATION = 1
REQUEST_TIMEOUT = ClientTimeout(total=60)
CHUNK_DAYS = 7

# Data and timezone settings
TIME_ZONE = "Pacific/Auckland"
HISTORY_START = date(2026, 3, 26)

# IAWAI publishes in two daily batches (~10am and ~10pm NZ).
POLL_HOURS = (10, 22)
POLL_MINUTE = 30

# Config-entry keys
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_OWNER_ID = "owner_id"
CONF_PROJECT_ID = "project_id"
CONF_SITE_GROUP_ID = "site_group_id"
CONF_SITE_ID = "site_id"
