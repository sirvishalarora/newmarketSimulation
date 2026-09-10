"""BigQuery client — credentials are read from disk, never stored in this repo."""

from __future__ import annotations

import os
from pathlib import Path

from google.cloud import bigquery
from google.oauth2 import service_account

# ponytail: fixed candidate list; extend via GOOGLE_APPLICATION_CREDENTIALS only
_CREDENTIAL_CANDIDATES = (
    os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"),
    os.path.expanduser("~/.bigquery/geo-reach-2e4493b509c3.json"),
    os.path.expanduser("~/Projects/root/datascience/setup/credentials/geo-reach-dev.json"),
    os.path.expanduser("~/Projects/root/Knooh/.bigquery/geo-reach-67f9b1f6336c.json"),
)


def resolve_credentials_path() -> str:
    for raw in _CREDENTIAL_CANDIDATES:
        if not raw:
            continue
        path = Path(raw).expanduser()
        if path.is_file():
            return str(path)
    raise FileNotFoundError(
        "BigQuery credentials not found. Set GOOGLE_APPLICATION_CREDENTIALS or place "
        "geo-reach-dev.json in ~/Projects/root/datascience/setup/credentials/"
    )


def get_client() -> bigquery.Client:
    path = resolve_credentials_path()
    credentials = service_account.Credentials.from_service_account_file(path)
    return bigquery.Client(credentials=credentials, project=credentials.project_id)


def query(sql: str, *, dry_run: bool = False):
    client = get_client()
    job_config = bigquery.QueryJobConfig(dry_run=dry_run, use_query_cache=not dry_run)
    job = client.query(sql, job_config=job_config)
    if dry_run:
        return job.total_bytes_processed
    return job.result().to_dataframe()


def execute(sql: str) -> None:
    client = get_client()
    job = client.query(sql)
    job.result()
    print(f"OK ({job.total_bytes_processed / 1e9:.2f} GB scanned): {sql.strip().split()[0:3]}...")
