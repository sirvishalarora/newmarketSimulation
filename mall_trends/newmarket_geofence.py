"""Tight Westfield Newmarket geofence (topology bbox + geohash_7)."""

GEOHASH_7 = ("rckq1p7", "rckq1pg", "rckq1pm", "rckq1ps", "rckq1pv")
LAT_MIN, LAT_MAX = -36.8735, -36.8695
LON_MIN, LON_MAX = 174.7740, 174.7795
MAX_ACCURACY_M = 50
MIN_PINGS = 3
MIN_SPAN_MINUTES = 10
AUCKLAND_TA_ID = 76
SCENTRE_ANNUAL_VISITS = 12_700_000

GEOHASH_7_SQL = ", ".join(f"'{g}'" for g in GEOHASH_7)
