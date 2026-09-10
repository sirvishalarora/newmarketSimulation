"""BigQuery table names and SQL for Newmarket mall trend pipeline."""

from mall_trends.newmarket_geofence import (
    AUCKLAND_TA_ID,
    GEOHASH_7_SQL,
    LAT_MAX,
    LAT_MIN,
    LON_MAX,
    LON_MIN,
    MAX_ACCURACY_M,
    MIN_PINGS,
    MIN_SPAN_MINUTES,
)

DATASET = "geo-reach.analytics"
AUCKLAND_PANEL = f"`{DATASET}.auckland_panel_daily`"


def daily_visits_table(no_dwell: bool = False) -> str:
    name = "newmarket_daily_visits_no_dwell" if no_dwell else "newmarket_daily_visits"
    return f"`{DATASET}.{name}`"


# backwards compat
DAILY_VISITS = daily_visits_table(False)


def _geofence_where() -> str:
    return f"""
    geohash_7 IN ({GEOHASH_7_SQL})
    AND latitude BETWEEN {LAT_MIN} AND {LAT_MAX}
    AND longitude BETWEEN {LON_MIN} AND {LON_MAX}
    AND horizontal_accuracy <= {MAX_ACCURACY_M}
    AND ta_id = {AUCKLAND_TA_ID}
    """


CREATE_DATASET = f"CREATE SCHEMA IF NOT EXISTS `{DATASET}`"


def create_daily_visits(no_dwell: bool = False) -> str:
    table = daily_visits_table(no_dwell)
    return f"""
CREATE TABLE IF NOT EXISTS {table} (
  local_date DATE NOT NULL,
  maid STRING NOT NULL,
  ping_count INT64 NOT NULL,
  span_minutes INT64 NOT NULL
)
PARTITION BY local_date
CLUSTER BY maid
"""


CREATE_AUCKLAND_PANEL = f"""
CREATE TABLE IF NOT EXISTS {AUCKLAND_PANEL} (
  local_date DATE NOT NULL,
  device_count INT64 NOT NULL
)
PARTITION BY local_date
"""


def delete_daily_visits(start: str, end: str, *, no_dwell: bool = False) -> str:
    table = daily_visits_table(no_dwell)
    return f"""
DELETE FROM {table}
WHERE local_date BETWEEN DATE '{start}' AND DATE '{end}'
"""


DELETE_AUCKLAND_PANEL = f"""
DELETE FROM {AUCKLAND_PANEL}
WHERE local_date BETWEEN DATE '{{start}}' AND DATE '{{end}}'
"""


def insert_daily_visits(start: str, end: str, *, no_dwell: bool = False) -> str:
    table = daily_visits_table(no_dwell)
    having = ""
    if not no_dwell:
        having = f"HAVING ping_count >= {MIN_PINGS} AND span_minutes >= {MIN_SPAN_MINUTES}"
    return f"""
INSERT INTO {table}
SELECT
  local_date,
  maid,
  COUNT(*) AS ping_count,
  TIMESTAMP_DIFF(MAX(date_time), MIN(date_time), MINUTE) AS span_minutes
FROM `geo-reach.pings.fact_ping`
WHERE local_date BETWEEN DATE '{start}' AND DATE '{end}'
  AND {_geofence_where()}
GROUP BY local_date, maid
{having}
"""


def insert_auckland_panel(start: str, end: str) -> str:
    return f"""
INSERT INTO {AUCKLAND_PANEL}
SELECT local_date, COUNT(DISTINCT maid) AS device_count
FROM `geo-reach.pings.fact_ping`
WHERE local_date BETWEEN DATE '{start}' AND DATE '{end}'
  AND ta_id = {AUCKLAND_TA_ID}
GROUP BY local_date
"""
