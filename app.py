import os
import json
import pandas as pd
import streamlit as st
import plotly.express as px
from datetime import datetime
from google.cloud import bigquery
from google.oauth2 import service_account
import tempfile

# -------------------------------------------------
# 1️⃣  Secret handling
# -------------------------------------------------
# Project ID from secrets
PROJECT_ID = os.getenv("GCP_PROJECT_ID") or st.secrets.get("gcp_project_id")

# Load service‑account credentials
# Get project ID from secrets
PROJECT_ID = os.getenv("GCP_PROJECT_ID") or st.secrets.get("gcp_project_id")

# Determine path to service‑account JSON
creds_path = os.getenv("GCP_SERVICE_ACCOUNT_PATH") or st.secrets.get(
    "gcp_service_account_path", "service_account.json"
)

# If the secret containing the full JSON is present, write it to a temporary file
if "gcp_service_account_json" in st.secrets:
    # Create a temporary file that persists for the duration of the process
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
    temp_file.write(st.secrets["gcp_service_account_json"].encode("utf-8"))
    temp_file.close()
    creds_path = temp_file.name

# Load credentials and create BigQuery client
credentials = service_account.Credentials.from_service_account_file(creds_path)
client = bigquery.Client(project=PROJECT_ID, credentials=credentials)

# Debug: print secrets (will only show up in Streamlit logs)
st.write("🔐 GCP_PROJECT_ID from secrets:", st.secrets.get("gcp_project_id"))
# Optionally show length of the raw JSON secret (for debugging)
# st.write("🔐 GOOGLE_CREDENTIALS_JSON length:", len(
#     st.secrets.get("google_credentials_json", "")))

# -------------------------------------------------
# 2️⃣  Query the BigQuery table
# -------------------------------------------------
TABLE_REF = f"`resale.public_resale_flat_prices_from_jan_2017`"
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
    FROM {TABLE_REF}
"""

df = client.query(query).to_dataframe()
df["month"] = pd.to_datetime(df["month"])

# Sets the page configuration
# You can set the page title and layout here
st.set_page_config(page_title="HDB Resale Dashboard", layout="wide")

st.title("🏠 Singapore HDB Resale Dashboard")
# st.caption("Code-along: building a usable dashboard from real resale transactions.")

# st.header("Dashboard Overview")
# st.subheader("What this app will show")
# # Use markdown to create bullet points
# st.markdown("""
# - Transaction volume after filtering
# - Average resale price
# - Median floor area
# - Town and flat type trends
# """)

# st.write(f"Rows loaded: {len(df):,} | Columns: {len(df.columns)}")
# st.dataframe(df.head(20), width="stretch")

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
# Make a copy of the original dataframe to apply filters
filtered_df = df.copy()

# If the user has selected any towns, filter the dataframe accordingly
if selected_towns:
    filtered_df = filtered_df[filtered_df["town"].isin(selected_towns)]

# filtered_df["town"] selects the 'town' column from the filtered dataframe
# .isin(selected_towns) checks if each value in the 'town' column is in the list of selected towns
# This returns a boolean mask (Series) of True/False values
# The dataframe is then filtered to include only those rows where the condition is True

# If the user has selected any flat types, filter the dataframe accordingly
if selected_flat_types:
    filtered_df = filtered_df[filtered_df["flat_type"].isin(
        selected_flat_types)]

# Filter the dataframe based on the selected resale price range
filtered_df = filtered_df[filtered_df['resale_price'].between(
    price_range[0], price_range[1])]

# If the user has selected a date range, filter the dataframe accordingly
if len(date_range) == 2:
    # unpack values from date_range tuple
    start_date, end_date = date_range
    filtered_df = filtered_df[filtered_df['month'].between(
        pd.to_datetime(start_date), pd.to_datetime(end_date))]


st.header("Filtered Results")
st.write(
    f"Dataset: Jan 2017 to May 2026 (Last updated: 16 May 2026) | Data source: [Data.gov.sg](https://data.gov.sg/datasets/d_8b84c4ee58e3cfc0ece0d773c8ca6abc/view)\n\n"
    f"Matching rows: {len(filtered_df):,} | Columns: {len(filtered_df.columns)}"
)   # ← closing parenthesis of st.write()
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

# Tells Streamlit to put the following content in the left column
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

# Tells Streamlit to put the following content in the right column
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

# with st.expander("View Filtered Transactions"):
#     st.dataframe(filtered_df, width="stretch", height=350)
#     csv = filtered_df.to_csv(index=False).encode("utf-8")
#     st.download_button(
#         "Download filtered CSV",
#         data=csv,
#         file_name="filtered_resale_data.csv",
#         mime="text/csv",
#     )
