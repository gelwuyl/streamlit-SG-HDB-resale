# 🏠 Singapore HDB Resale Dashboard

Live app: [https://gel-sg-hdb-resale.streamlit.app/](https://gel-sgresalehdb.streamlit.app/)


## 📊 Data Pipeline Architecture

```
┌─────────────────────────────────────────────────────────────┐
│              Initial Setup (Meltano Pipeline)               │
│  ┌──────────────┐    ┌────────────────┐    ┌─────────────┐ │
│  │ tap-postgres │───▶│ target-bigquery│───▶│  BigQuery   │ │
│  │  (Supabase)  │    │   (Meltano)    │    │  Dataset    │ │
│  └──────────────┘    └────────────────┘    └─────────────┘ │
└─────────────────────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│              Production Pipeline (Dagster)                  │
│  ┌──────────────────────────────────────────────────────┐  │
│  │              Dagster Orchestration                   │  │
│  │  Schedule: Daily at 11:59 PM SGT                     │  │
│  └──────────────────────────────────────────────────────┘  │
│                        │                                   │
│                        ▼                                   │
│  ┌──────────────────────────────────────────────────────┐  │
│  │              Asset Selection                         │  │
│  │  • hdb_resale_data_from_csv (manual fallback)        │  │
│  │  • hdb_resale_data_from_api (incremental fetch)      │  │
│  └──────────────────────────────────────────────────────┘  │
│                        │                                   │
│                        ▼                                   │
│  ┌──────────────────────────────────────────────────────┐  │
│  │           Google BigQuery                            │  │
│  │  • Source: Data.gov.sg API                           │  │
│  │  • Features: Deduplication, Rate limiting            │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│                  Streamlit Dashboard                        │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  1. Try BigQuery (primary)                           │  │
│  │  2. Fallback to CSV (if BigQuery fails)              │  │
│  └──────────────────────────────────────────────────────┘  │
│                        │                                   │
│                        ▼                                   │
│  ┌──────────────────────────────────────────────────────┐  │
│  │              Dashboard Components                    │  │
│  │  • Filters, KPIs, Visualizations                     │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

## 🔧 Configuration

```python
# GCP Configuration
PROJECT_ID = "..."
DATASET_ID = "resale"
TABLE_ID = "public_resale_flat_prices_from_jan_2017"
```

## 📋 Current Status

| Component | Status | Notes |
|-----------|--------|-------|
| **Meltano Pipeline** | ✅ Working | Initial data setup |
| **Dagster Pipeline** | ✅ Working | Daily scheduled ingestion |
| **BigQuery Data** | ✅ Available | Table exists |
| **Streamlit BigQuery** | ❌ Failing | Connection issue |
| **Streamlit CSV Fallback** | ✅ Working | Dashboard loads from local CSV |
| **Overall App** | ✅ Functional | Falls back to CSV when BigQuery fails |

## 🚀 Features

- **Interactive Dashboard**: Filter by town, flat type, price range, and date
- **Key Metrics**: Transaction count, average/median prices, floor area
- **Visualizations**: 
  - Average resale price by town (top 10)
  - Transactions by flat type
  - Monthly median resale price trends
- **Data Sources**: 
  - Primary: BigQuery (Dagster pipeline)
  - Fallback: Local CSV file
- **Real-time Updates**: Data refreshes on each app run

## 📁 Project Structure

```
streamlit-SGhdbresale/
├── app.py                 # Main Streamlit application
├── data/                  # Local CSV fallback data
├── dagster-orchestration/ # Dagster pipeline configuration
├── meltano-resale/        # Meltano pipeline configuration
├── .streamlit/            # Streamlit configuration (secrets.toml)
├── requirements.txt       # Python dependencies
└── README.md             # This file
```

## 🛠️ Setup Instructions

1. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure Streamlit secrets** (for BigQuery connection):
   ```bash
   # Create .streamlit/secrets.toml for local testing
   # Add gcp_credentials_b64 and gcp_project_id
   ```

3. **Run locally**:
   ```bash
   streamlit run app.py
   ```

4. **Deploy to Streamlit Cloud**:
   - Push to GitHub repository
   - Connect to Streamlit Cloud
   - Configure secrets in dashboard settings
