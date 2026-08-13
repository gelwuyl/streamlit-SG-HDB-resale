# 🏠 Singapore HDB Resale Dashboard

Live app: [https://gel-sg-hdb-resale.streamlit.app/](https://gel-sg-hdb-resale.streamlit.app/)


## 📊 Data Pipeline Architecture

```
┌─────────────────────────────────────────────────────────────┐
│              LOCAL (dev/testing only)                       │
│  • Meltano: Supabase → BigQuery (initial setup)             │
│  • Dagster: Data.gov.sg API → BigQuery (local testing)      │
└─────────────────────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│              CLOUD (production)                             │
│  GitHub Action (weekly)                                     │
│  └── scripts/update_bigquery.py                             │
│        ├── 1. Pull Data.gov.sg API (newest records)         │
│        ├── 2. Load → BigQuery (MERGE dedup, no duplicates)  │
│        └── 3. Update → local CSV (dedup, no duplicates)     │
│              └── Commit CSV back to repo                    │
└─────────────────────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│                  Streamlit Dashboard                        │
│  • 1. Try BigQuery (primary)                                │
│  • 2. Fallback to CSV (if BigQuery fails)                   │
└─────────────────────────────────────────────────────────────┘
```

## 📋 Current Status

| Component | Status | Notes |
|-----------|--------|-------|
| **Meltano Pipeline** | ✅ Local | Initial data setup (dev only) |
| **Dagster Pipeline** | ✅ Local | Local testing (dev only) |
| **GitHub Action** | ✅ Cloud | Weekly scheduled API → BigQuery + CSV |
| **BigQuery Data** | ✅ Available | Table exists |
| **Streamlit App** | ✅ Functional | BigQuery primary, CSV fallback |

## 🚀 Features

- **Interactive Dashboard**: Filter by town, flat type, price range, and date
- **Key Metrics**: Transaction count, average/median prices, floor area
- **Visualizations**: Average resale price by town, transactions by flat type, monthly price trends
- **Data Sources**: BigQuery (primary) → CSV fallback
- **Real-time Updates**: Data refreshes on each app run

## 📁 Project Structure

```
streamlit-SGhdbresale/
├── app.py                 # Main Streamlit application
├── data/                  # Local CSV fallback data
├── scripts/
│   └── update_bigquery.py # Cloud pipeline: API → BigQuery + CSV
├── .github/workflows/
│   └── update_bigquery.yml  # Weekly scheduled GitHub Action
├── dagster-orchestration/ # Dagster pipeline (local dev only)
├── meltano-resale/        # Meltano pipeline (local dev only)
├── .streamlit/            # Streamlit configuration (secrets.toml)
├── requirements.txt       # Python dependencies
└── README.md             # This file
```

## 🛠️ Setup Instructions

1. **Install dependencies**: `pip install -r requirements.txt`
2. **Configure Streamlit secrets**: Add `gcp_service_account`, `dataset_id`, `table_id` to `.streamlit/secrets.toml`
3. **Run locally**: `streamlit run app.py`
4. **Deploy to Streamlit Cloud**: Push to GitHub, connect, configure secrets

## ☁️ Cloud Pipeline (GitHub Action)

Runs **weekly** (Monday 00:30 UTC / 08:30 SGT) to pull the latest HDB resale data from the Data.gov.sg API into BigQuery and update the local backup CSV. Can also be triggered manually from the **Actions** tab.

```
GitHub Action (weekly)
  └── scripts/update_bigquery.py
        ├── 1. Pull Data.gov.sg API (newest records)
        ├── 2. Load → BigQuery (MERGE dedup, no duplicates)
        └── 3. Update → local CSV (dedup, no duplicates)
              └── Commit CSV back to repo
```

### Setup

Add these GitHub Secrets (Settings → Secrets and variables → Actions):

| Secret | Description |
|--------|-------------|
| `GCP_SERVICE_ACCOUNT_JSON` | Full service account JSON (inline) |
| `GCP_PROJECT_ID` | GCP project id |
| `GCP_DATASET_ID` | BigQuery dataset (default: `resale`) |
| `GCP_TABLE_ID` | BigQuery table (default: `public_resale_flat_prices_from_jan_2017`) |

### Local Testing

```bash
export GOOGLE_CREDENTIALS_PATH=/path/to/service-account.json
python scripts/update_bigquery.py
```

The script updates both BigQuery and the local CSV file.
