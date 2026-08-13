#!/usr/bin/env python3
"""
Cloud pipeline: Pull HDB resale data from Data.gov.sg API into BigQuery.

This script is designed to run as a scheduled GitHub Action (or manually).
It is self-contained and does NOT depend on Dagster or Meltano.

Flow:
  1. Connect to BigQuery using a service account (from env var or file).
  2. Get the current row count in the destination table.
  3. Get the total record count from the Data.gov.sg API.
  4. Fetch only the newest records (from the end of the dataset) that are
     not yet in BigQuery.
  5. Load them into BigQuery using a MERGE statement so there are NO duplicates.

Usage:
  python scripts/update_bigquery.py

Environment variables:
  GOOGLE_CREDENTIALS_PATH  - path to the service account JSON file (local)
  GCP_SERVICE_ACCOUNT_JSON - inline service account JSON (GitHub Actions)
  GCP_PROJECT_ID           - GCP project id (defaults to value in credentials)
  GCP_DATASET_ID           - BigQuery dataset (default: resale)
  GCP_TABLE_ID             - BigQuery table (default: public_resale_flat_prices_from_jan_2017)
"""

import io
import json
import os
import sys
import time
from typing import Any, Dict, List

import pandas as pd
import requests
from google.cloud import bigquery
from google.oauth2 import service_account

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DATA_GOV_API_URL = "https://data.gov.sg/api/action/datastore_search"
RESOURCE_ID = "d_8b84c4ee58e3cfc0ece0d773c8ca6abc"
PAGE_SIZE = 100  # Data.gov.sg API hard limit is 100 records per page
MAX_RETRIES = 5
RETRY_DELAY = 1  # seconds, doubles on each retry (exponential backoff)

DATASET_ID = os.getenv("GCP_DATASET_ID", "resale")
TABLE_ID = os.getenv(
    "GCP_TABLE_ID", "public_resale_flat_prices_from_jan_2017")

# Local backup CSV path (fallback for the Streamlit app)
CSV_PATH = os.getenv(
    "CSV_PATH",
    os.path.join(
        os.path.dirname(__file__),
        "..",
        "data",
        "ResaleflatpricesbasedonregistrationdatefromJan2017onwards.csv",
    ),
)


def _get_credentials():
    """Build BigQuery credentials from env var or service account file."""
    # Prefer inline JSON (used in GitHub Actions)
    inline_json = os.getenv("GCP_SERVICE_ACCOUNT_JSON")
    if inline_json:
        try:
            info = json.loads(inline_json)
        except json.JSONDecodeError as e:
            raise ValueError(
                "GCP_SERVICE_ACCOUNT_JSON is not valid JSON") from e
        return service_account.Credentials.from_service_account_info(info)

    # Fall back to a service account file path (used locally)
    creds_path = os.getenv("GOOGLE_CREDENTIALS_PATH")
    if not creds_path:
        raise ValueError(
            "Set either GCP_SERVICE_ACCOUNT_JSON or GOOGLE_CREDENTIALS_PATH "
            "to provide BigQuery credentials."
        )
    if not os.path.exists(creds_path):
        raise FileNotFoundError(
            f"Service account key file not found at: {creds_path}")
    return service_account.Credentials.from_service_account_file(creds_path)


def _get_project_id(credentials) -> str:
    """Resolve the GCP project id."""
    env_project = os.getenv("GCP_PROJECT_ID")
    if env_project:
        return env_project
    # Try to read from the credentials' service account info
    try:
        return credentials.project_id or ""
    except Exception:
        return ""


def _get_table_id(project_id: str) -> str:
    return f"{project_id}.{DATASET_ID}.{TABLE_ID}"


def _get_table_schema(client: bigquery.Client, table_id: str) -> List[bigquery.SchemaField]:
    """Get the existing table schema from BigQuery.

    If the table does not exist, returns an empty list so the caller
    can create it from the API records instead.
    """
    try:
        table = client.get_table(table_id)
        return table.schema
    except Exception as e:
        if "Not found" in str(e) or "404" in str(e):
            print(f"Table {table_id} does not exist yet. Will create it.")
            return []
        raise


def _ensure_table_exists(
    client: bigquery.Client,
    table_id: str,
    records: List[Dict[str, Any]],
) -> List[bigquery.SchemaField]:
    """Create the destination table if it does not exist.

    The schema is inferred from the API records. Returns the table schema.
    """
    schema = _get_table_schema(client, table_id)
    if schema:
        return schema

    if not records:
        raise ValueError(
            "Cannot create table: no records available to infer schema.")

    # Infer schema from the first record
    sample = records[0]
    schema = []
    for key, value in sample.items():
        if key == "_id":
            continue  # skip the API internal id field
        if isinstance(value, bool):
            field_type = "BOOL"
        elif isinstance(value, int):
            field_type = "INTEGER"
        elif isinstance(value, float):
            field_type = "FLOAT"
        elif isinstance(value, str) and len(value) == 7 and "-" in value:
            # e.g. "2017-01" -> likely a date-month field
            field_type = "DATE"
        else:
            field_type = "STRING"
        schema.append(bigquery.SchemaField(key, field_type))

    # Special case: 'month' should be TIMESTAMP (or DATE) for the app
    # The app reads it as a datetime; DATE works for "2017-01-01".
    for field in schema:
        if field.name == "month":
            field = bigquery.SchemaField("month", "DATE")

    print(f"Creating table {table_id} with schema: "
          f"{[f'{f.name}:{f.field_type}' for f in schema]}")
    table_ref = client.dataset(DATASET_ID).table(table_id.split(".")[-1])
    table = bigquery.Table(table_ref, schema=schema)
    client.create_table(table, exists_ok=True)
    print(f"✅ Table created: {table_id}")

    return schema


def _get_bigquery_record_count(client: bigquery.Client, table_id: str) -> int:
    """Get the current count of records in the BigQuery table."""
    query = f"SELECT COUNT(*) as row_count FROM `{table_id}`"
    query_job = client.query(query)
    for row in query_job.result():
        return row.row_count
    return 0


def _fetch_single_page(page: int) -> List[Dict[str, Any]]:
    """Fetch a single page from the Data.gov.sg API with retry logic."""
    api_url = (
        f"{DATA_GOV_API_URL}?resource_id={RESOURCE_ID}"
        f"&page={page}&page_size={PAGE_SIZE}"
    )
    print(f"Fetching page {page}...")

    retries = 0
    retry_delay = RETRY_DELAY
    response = requests.get(api_url, timeout=60)

    while response.status_code == 429 and retries < MAX_RETRIES:
        print(
            f"Rate limited. Retrying in {retry_delay}s "
            f"(attempt {retries + 1}/{MAX_RETRIES})"
        )
        time.sleep(retry_delay)
        retry_delay *= 2
        response = requests.get(api_url, timeout=60)
        retries += 1

    response.raise_for_status()
    data = response.json()
    return data["result"]["records"]


def _filter_records_to_schema(
    records: List[Dict[str, Any]],
    schema: List[bigquery.SchemaField],
) -> List[Dict[str, Any]]:
    """Keep only fields that exist in the destination table schema."""
    allowed_fields = {field.name for field in schema}
    return [
        {k: v for k, v in record.items() if k in allowed_fields}
        for record in records
    ]


def _convert_records_for_bigquery(
    records: List[Dict[str, Any]],
    schema: List[bigquery.SchemaField],
) -> List[Dict[str, Any]]:
    """Convert records to match BigQuery schema types (e.g. month format)."""
    converted = []
    for record in records:
        rec = record.copy()
        if "month" in rec:
            month_value = rec["month"]
            # Convert "2017-01" -> "2017-01-01" for TIMESTAMP compatibility
            if isinstance(month_value, str) and len(month_value) == 7:
                rec["month"] = month_value + "-01"
            else:
                rec["month"] = str(month_value)
        converted.append(rec)
    return converted


def _load_with_bigquery_dedup(
    client: bigquery.Client,
    table_id: str,
    schema: List[bigquery.SchemaField],
    records: List[Dict[str, Any]],
) -> int:
    """Load records into BigQuery using MERGE so there are NO duplicates.

    Returns the number of rows actually inserted.
    """
    if not records:
        print("No records to load.")
        return 0

    # Create a temporary table to stage the new records
    temp_table_id = f"{table_id}_temp_{int(time.time())}"
    temp_table_ref = client.dataset(DATASET_ID).table(
        temp_table_id.split(".")[-1]
    )
    temp_table = bigquery.Table(temp_table_ref, schema=schema)

    print(f"Creating temporary table: {temp_table_id}")
    client.create_table(temp_table, exists_ok=True)

    # Load records into the temp table
    json_lines = "\n".join(json.dumps(record) for record in records)
    job_config = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        schema=schema,
    )
    load_job = client.load_table_from_file(
        io.BytesIO(json_lines.encode("utf-8")),
        temp_table,
        job_config=job_config,
    )
    load_job.result()
    print(f"Loaded {load_job.output_rows} records into temp table")

    # Build MERGE statement matching on all fields (no natural key available)
    join_conditions = [
        f"NEW.`{field.name}` = EXISTING.`{field.name}`"
        for field in schema
    ]
    join_clause = " AND ".join(join_conditions)

    merge_query = f"""
    MERGE `{table_id}` EXISTING
    USING `{temp_table_id}` NEW
    ON {join_clause}
    WHEN NOT MATCHED THEN INSERT ROW
    """

    print("Executing MERGE for deduplication...")
    merge_job = client.query(merge_query)
    merge_job.result()

    rows_inserted = merge_job.num_dml_affected_rows or 0
    print(
        f"MERGE complete: {rows_inserted} new rows inserted "
        f"(duplicates skipped)"
    )

    # Clean up temp table
    client.delete_table(temp_table_id)
    print(f"Dropped temp table: {temp_table_id}")

    return int(rows_inserted)


def _update_local_csv(records: List[Dict[str, Any]]) -> int:
    """Update the local backup CSV with new records (deduplicated).

    The CSV uses 'month' in YYYY-MM format (matching the API), while BigQuery
    uses YYYY-MM-01. We convert back to YYYY-MM for the CSV.

    Returns the number of new rows added to the CSV.
    """
    if not records:
        print("No records to add to CSV.")
        return 0

    csv_path = os.path.abspath(CSV_PATH)
    print(f"Updating local CSV: {csv_path}")

    # Load existing CSV if it exists
    if os.path.exists(csv_path):
        existing_df = pd.read_csv(csv_path)
        print(f"Existing CSV rows: {len(existing_df)}")
    else:
        existing_df = pd.DataFrame()
        print("CSV does not exist yet. Creating new file.")

    # Convert new records to a DataFrame
    new_df = pd.DataFrame(records)

    # Convert month back to YYYY-MM format for the CSV
    if "month" in new_df.columns:
        new_df["month"] = new_df["month"].astype(str).str[:7]

    # Ensure consistent column order matching the CSV schema
    expected_columns = [
        "month",
        "town",
        "flat_type",
        "block",
        "street_name",
        "storey_range",
        "floor_area_sqm",
        "flat_model",
        "lease_commence_date",
        "remaining_lease",
        "resale_price",
    ]
    for col in expected_columns:
        if col not in new_df.columns:
            new_df[col] = ""
    new_df = new_df[expected_columns]

    # Deduplicate against existing CSV rows using pandas drop_duplicates
    # (more robust than tuple comparison, handles NaN and type mismatches)
    if not existing_df.empty:
        # Combine existing + new, then drop rows that already exist
        combined = pd.concat(
            [existing_df[expected_columns], new_df[expected_columns]],
            ignore_index=True,
        )
        # Keep only rows that appear in new_df but NOT in existing_df
        # Strategy: mark existing rows, then keep new rows not already present
        existing_keys = set(
            map(tuple, existing_df[expected_columns].astype(str).values)
        )
        new_rows = []
        for _, row in new_df[expected_columns].astype(str).iterrows():
            key = tuple(row.values)
            if key not in existing_keys:
                existing_keys.add(key)
                new_rows.append(row)
        new_df = pd.DataFrame(new_rows, columns=expected_columns)
    else:
        # No existing CSV, all records are new
        new_df = new_df[expected_columns]

    if new_df.empty:
        print("No new records to add to CSV (all duplicates).")
        return 0

    # Append new records to the CSV
    new_df.to_csv(
        csv_path,
        mode="a",
        header=not os.path.exists(csv_path),
        index=False,
    )

    print(f"✅ Added {len(new_df)} new rows to CSV.")
    return len(new_df)


def main():
    """Main entry point."""
    print("=" * 60)
    print("HDB Resale Data Pipeline (Cloud)")
    print("=" * 60)

    # 1. Connect to BigQuery
    credentials = _get_credentials()
    project_id = _get_project_id(credentials)
    if not project_id:
        raise ValueError("Could not determine GCP project id.")
    table_id = _get_table_id(project_id)

    client = bigquery.Client(credentials=credentials, project=project_id)
    print(f"Connected to BigQuery. Table: {table_id}")

    # 2. Check if the table exists
    existing_schema = _get_table_schema(client, table_id)
    table_exists = bool(existing_schema)
    print(f"Table exists: {table_exists}")

    # 3. Get total records available from the API
    api_url = (
        f"{DATA_GOV_API_URL}?resource_id={RESOURCE_ID}"
        f"&page=1&page_size=1"
    )
    resp = requests.get(api_url, timeout=60)
    resp.raise_for_status()
    total_api_records = resp.json()["result"].get("total", 0)
    print(f"Total records in API: {total_api_records}")

    # 4. Determine how many records to fetch
    if table_exists:
        bq_count = _get_bigquery_record_count(client, table_id)
        print(f"Current records in BigQuery: {bq_count}")
        new_records_needed = total_api_records - bq_count
    else:
        # Table doesn't exist - bootstrap: fetch ALL records
        bq_count = 0
        new_records_needed = total_api_records
        print("Bootstrap mode: table missing, will fetch ALL records")

    print(f"New records to fetch: {new_records_needed}")

    if new_records_needed <= 0:
        print("BigQuery is up to date. Nothing to do.")
        return

    # 5. Fetch the newest records (from the end of the dataset)
    #    Fetch a bit more than needed to account for any gaps.
    pages_needed = (new_records_needed + PAGE_SIZE - 1) // PAGE_SIZE
    pages_to_fetch = int(pages_needed * 1.2) + 1  # 20% buffer
    last_page = (total_api_records + PAGE_SIZE - 1) // PAGE_SIZE
    start_page = max(1, last_page - pages_to_fetch + 1)

    print(
        f"Fetching pages {start_page} to {last_page} "
        f"({pages_to_fetch} pages)"
    )

    all_records = []
    for page in range(start_page, last_page + 1):
        records = _fetch_single_page(page)
        if not records:
            break
        all_records.extend(records)
        print(f"  Page {page}: {len(records)} records (total: {len(all_records)})")

    if not all_records:
        print("No records fetched from API.")
        return

    # 6. Ensure the table exists (create it from records if needed)
    schema = _ensure_table_exists(client, table_id, all_records)
    print(f"Schema ready: {len(schema)} fields")

    # 7. Filter and convert records
    records = _filter_records_to_schema(all_records, schema)
    records = _convert_records_for_bigquery(records, schema)
    print(f"Prepared {len(records)} records for loading")

    # 8. Load with deduplication (MERGE)
    rows_inserted = _load_with_bigquery_dedup(
        client, table_id, schema, records
    )

    # 9. Update the local backup CSV with the same new records (deduplicated)
    #    Use the schema-filtered records (before BigQuery month conversion)
    #    so the CSV keeps the YYYY-MM format.
    csv_records = _filter_records_to_schema(all_records, schema)
    csv_rows_added = _update_local_csv(csv_records)

    print("=" * 60)
    print(f"✅ Done. {rows_inserted} new records loaded to BigQuery.")
    print(f"✅ Done. {csv_rows_added} new records added to local CSV.")
    print("=" * 60)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        sys.exit(1)
