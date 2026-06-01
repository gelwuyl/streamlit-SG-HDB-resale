import os
import re
import json
import pandas as pd
import streamlit as st
import plotly.express as px
from google.cloud import bigquery
from google.oauth2 import service_account

# Set the page configuration before any Streamlit rendering or messages.
st.set_page_config(page_title="HDB Resale Dashboard", layout="wide")

# -------------------------------------------------
# 1️⃣  GCP Configuration (matches Meltano setup)
# -------------------------------------------------
PROJECT_ID = "gen-lang-client-0767762328"
DATASET_ID = "resale"
TABLE_ID = "public_resale_flat_prices_from_jan_2017"

# -------------------------------------------------
# 2️⃣  Load Data - Try BigQuery first, fallback to CSV
# -------------------------------------------------


def _normalize_service_account_json(raw_text: str) -> str:
    """Convert raw newlines in the private_key field into escaped \n for JSON parsing."""
    if '"private_key"' not in raw_text:
        return raw_text

    def _escape_private_key(match):
        text = match.group(2)
        escaped = text.replace("\n", "\\n")
        return f"{match.group(1)}{escaped}{match.group(3)}"

    return re.sub(
        r'("private_key"\s*:\s*")(.+?)(")',
        _escape_private_key,
        raw_text,
        flags=re.DOTALL,
    )


def get_bigquery_client():
    """Return a BigQuery client and dataset/table config from Streamlit secrets."""
    if "gcp_service_account" not in st.secrets:
        raise KeyError(
            "Missing gcp_service_account. Add the inline service account JSON secret to Streamlit Cloud settings."
        )

    creds_raw = st.secrets["gcp_service_account"]
    if isinstance(creds_raw, str):
        try:
            creds_info = json.loads(creds_raw)
        except json.JSONDecodeError:
            normalized = _normalize_service_account_json(creds_raw)
            try:
                creds_info = json.loads(normalized)
            except json.JSONDecodeError as err:
                raise ValueError(
                    "Invalid JSON in gcp_service_account. "
                    "Use a valid JSON string or store gcp_service_account as a TOML object in Streamlit secrets."
                ) from err
    elif isinstance(creds_raw, dict):
        creds_info = creds_raw
    else:
        raise ValueError(
            "gcp_service_account must be a JSON string or object in Streamlit secrets"
        )

    private_key = creds_info.get("private_key")
    if not private_key or "BEGIN PRIVATE KEY" not in private_key:
        raise ValueError(
            "Invalid gcp_service_account private_key. "
            "Paste the full PEM private key text into the secret, not a placeholder or truncated value."
        )
    if "..." in private_key:
        raise ValueError(
            "The gcp_service_account private_key contains placeholder text '...'. "
            "Use the full service account private key from your JSON file."
        )

    credentials = service_account.Credentials.from_service_account_info(
        creds_info)
    project_id = (
        creds_info.get("project_id")
        or st.secrets.get("gcp_project_id")
        or PROJECT_ID
    )
    dataset_id = st.secrets.get("dataset_id") or DATASET_ID
    table_id = st.secrets.get("table_id") or TABLE_ID
    return bigquery.Client(credentials=credentials, project=project_id), project_id, dataset_id, table_id


def _normalize_bigquery_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize BigQuery results to the same schema and dtype expectations as the CSV fallback."""
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

    df = df.copy()
    for col in expected_columns:
        if col not in df.columns:
            df[col] = pd.NA

    df["month"] = pd.to_datetime(df["month"], errors="coerce")

    for numeric_col in ["resale_price", "floor_area_sqm", "remaining_lease"]:
        df[numeric_col] = pd.to_numeric(df[numeric_col], errors="coerce")

    if "lease_commence_date" in df.columns:
        df["lease_commence_date"] = df["lease_commence_date"].astype("string")

    return df[expected_columns]


@st.cache_data
def load_data():
    """
    Load HDB resale data from BigQuery or CSV fallback.
    Priority: BigQuery > CSV file
    """

    # Try to load from BigQuery first
    try:
        client, project_id, dataset_id, table_id = get_bigquery_client()

        # 6. Build table reference and query
        table_ref = f"{project_id}.{dataset_id}.{table_id}"
        query = f"""
            SELECT
                month,
                town,
                flat_type,
                block,
                street_name,
                storey_range,
                floor_area_sqm,
                flat_model,
                lease_commence_date,
                remaining_lease,
                resale_price
            FROM `{table_ref}`
        """

        df = client.query(query).to_dataframe()
        df = _normalize_bigquery_dataframe(df)

        st.info("✅ Data loaded from BigQuery (Meltano pipeline)")
        return df

    except KeyError as ke:
        # Missing secrets
        st.warning(f"⚠️ Missing secret configuration: {ke}")
        st.info("📄 Falling back to local CSV data file...")

    # Fallback: Load from CSV file
    try:
        csv_path = os.path.join(
            os.path.dirname(__file__),
            "data",
            "ResaleflatpricesbasedonregistrationdatefromJan2017onwards.csv"
        )

        if not os.path.exists(csv_path):
            st.error(f"❌ CSV file not found: {csv_path}")
            st.stop()

        df = pd.read_csv(csv_path)

        # Convert month to datetime
        if 'month' in df.columns:
            df["month"] = pd.to_datetime(df["month"])

        st.info("✅ Data loaded from local CSV file")
        return df

    except Exception as csv_error:
        st.error(f"❌ Failed to load CSV: {csv_error}")
        st.stop()


# Load data (BigQuery or CSV)
df = load_data()


# -------------------------------------------------
# 4️⃣  Dashboard Setup
# -------------------------------------------------
# Page config is already set above; this section focuses on title and dashboard layout.
st.title("🏠 Singapore HDB Resale Dashboard")

# Optional: Uncomment the lines below to display a data summary header.
# st.header("Dataset Summary")
# st.write(f"Rows loaded: {len(df):,} | Columns: {len(df.columns)}")

st.sidebar.header("Filters")

# Get unique towns and flat types for the multi-select widgets
unique_towns = sorted(df["town"].dropna().unique())
unique_flat_types = sorted(df["flat_type"].dropna().unique())

# Get min and max resale prices for the slider
min_price = int(df["resale_price"].min())
max_price = int(df["resale_price"].max())

# Get min and max dates for the date input
date_min = df["month"].min().date()
date_max = df["month"].max().date()

# Create filter widgets
selected_towns = st.sidebar.multiselect("Town", unique_towns, default=[])
selected_flat_types = st.sidebar.multiselect(
    "Flat Type", unique_flat_types, default=[]
)
price_range = st.sidebar.slider(
    "Resale Price Range",
    min_value=min_price,
    max_value=max_price,
    value=(min_price, max_price),
    step=10000,
)
date_range = st.sidebar.date_input("Month Range", value=(date_min, date_max))
# Keep the original dataset intact and apply filters to a working copy.
filtered_df = df.copy()

# Filter by selected towns if any are chosen.
if selected_towns:
    filtered_df = filtered_df[filtered_df["town"].isin(selected_towns)]

# The .isin() call returns a boolean mask for rows whose town is in the selected list.

# Filter by selected flat types when present.
if selected_flat_types:
    filtered_df = filtered_df[filtered_df["flat_type"].isin(
        selected_flat_types)]

# Filter by resale price range using numeric bounds.
filtered_df = filtered_df[filtered_df["resale_price"].between(
    price_range[0], price_range[1])]

# Apply month range filtering when a valid two-date range is selected.
if len(date_range) == 2:
    start_date, end_date = date_range
    filtered_df = filtered_df[filtered_df["month"].between(
        pd.to_datetime(start_date), pd.to_datetime(end_date))]

st.header("Filtered Results")
st.write(
    f"Dataset: Jan 2017 to May 2026 (Last updated: 16 May 2026) | Data source: [Data.gov.sg](https://data.gov.sg/datasets/d_8b84c4ee58e3cfc0ece0d773c8ca6abc/view)\n\n"
    f"Matching rows: {len(filtered_df):,} | Columns: {len(filtered_df.columns)}"
)
st.dataframe(filtered_df, width="stretch")


# KPI Rows
st.header("Key Metrics")
col1, col2, col3, col4 = st.columns(4)

col1.metric("Transactions", f"{len(filtered_df):,}")
col2.metric("Average Price", f"${filtered_df['resale_price'].mean():,.0f}")
col3.metric("Median Price", f"${filtered_df['resale_price'].median():,.0f}")
col4.metric("Median Floor Area",
            f"{filtered_df['floor_area_sqm'].median():.1f} sqm")

st.header("Visual Analysis")

col_left, col_right = st.columns(2)

# Place the town pricing chart in the left column for side-by-side layout.
with col_left:
    st.subheader("Average Resale Price by Town")
    avg_price_by_town = (
        filtered_df.groupby("town", as_index=False)["resale_price"]
        .mean()
        .sort_values("resale_price", ascending=False)
        .head(10)  # Top 10 towns only for clarity
    )
    fig_town = px.bar(avg_price_by_town, x="town", y="resale_price")
    st.plotly_chart(fig_town, width="stretch")

# Display flat type transaction breakdown in the right column.
with col_right:
    st.subheader("Transactions by Flat Type")
    tx_by_flat = (
        filtered_df.groupby("flat_type", as_index=False)
        .size()
        .rename(columns={"size": "transactions"})
        .sort_values("transactions", ascending=False)
    )
    fig_flat = px.bar(tx_by_flat, x="flat_type", y="transactions")
    st.plotly_chart(fig_flat, width="stretch")


st.subheader("Monthly Median Resale Price")
trend = (
    filtered_df.groupby("month", as_index=False)["resale_price"]
    .median()
    .sort_values("month")
)
fig_trend = px.line(trend, x="month", y="resale_price", markers=True)
st.plotly_chart(fig_trend, width="stretch")


# Optional: Uncomment below to add an expandable section for viewing and downloading filtered transaction data.
with st.expander("View Filtered Transactions"):
    st.dataframe(filtered_df, width="stretch", height=350)
    csv = filtered_df.to_csv(index=False).encode("utf-8")
    st.download_button(
        "Download filtered CSV",
        data=csv,
        file_name="filtered_resale_data.csv",
        mime="text/csv",
    )