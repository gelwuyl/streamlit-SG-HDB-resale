# 🏠 Singapore HDB Resale Dashboard

Live demo: [https://gel-sgresalehdb.streamlit.app/](https://gel-sgresalehdb.streamlit.app/)

## 📊 Data Pipeline Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Meltano Pipeline (Local)                 │
│  ┌──────────────┐    ┌────────────────┐    ┌─────────────┐ │
│  │ tap-postgres │───▶│ target-bigquery│───▶│  BigQuery   │ │
│  │  (Supabase)  │    │   (Meltano)    │    │  Dataset    │ │
│  └──────────────┘    └────────────────┘    │  resale     │ │
│                                            └──────┬──────┘ │
└────────────────────────────────────────────────────┬────────┘
                                                     │
                                                     ▼
┌─────────────────────────────────────────────────────────────┐
│                  Streamlit Dashboard (Cloud)                │
│  ┌──────────────────────────────────────────────────────┐  │
│  │              load_data() Function                    │  │
│  │  ┌────────────────────────────────────────────────┐  │  │
│  │  │ 1. Try BigQuery First                          │  │  │
│  │  │    - Check if gcp_credentials_b64 in secrets   │  │  │
│  │  │    - Decode Base64 → JSON                      │  │  │
│  │  │    - Create BigQuery Client                    │  │  │
│  │  │    - Query: resale.public_resale_flat_prices   │  │  │
│  │  │    - Return df                                 │  │  │
│  │  └────────────────────────────────────────────────┘  │  │
│  │                        │                             │  │
│  │                        ▼ (if fails)                   │  │
│  │  ┌────────────────────────────────────────────────┐  │  │
│  │  │ 2. Fallback to CSV                             │  │  │
│  │  │    - Load: data/Resaleflatpricesbasedon...csv  │  │  │
│  │  │    - Convert month to datetime                 │  │  │
│  │  │    - Return df                                 │  │  │
│  │  └────────────────────────────────────────────────┘  │  │
│  └──────────────────────────────────────────────────────┘  │
│                            │                                │
│                            ▼                                │
│  ┌──────────────────────────────────────────────────────┐  │
│  │              Dashboard Components                    │  │
│  │    - Filters (town, flat_type, price, date)          │  │
│  │    - KPI Metrics (transactions, avg, median price)   │  │
│  │    - Visualizations (bar charts, line trends)        │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

## 🔧 Configuration

```python
# GCP Configuration (matches Meltano setup)
PROJECT_ID = "gen-lang-client-0767762328"
DATASET_ID = "resale"
TABLE_ID = "public_resale_flat_prices_from_jan_2017"
```

## 📋 Current Status

| Component | Status | Notes |
|-----------|--------|-------|
| **Meltano Pipeline** | ✅ Working | `meltano run tap-postgres target-bigquery` succeeds |
| **BigQuery Data** | ✅ Available | Table `resale.public_resale_flat_prices_from_jan_2017` exists |
| **Streamlit BigQuery** | ❌ Failing | `Invalid private key` error persists |
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
  - Primary: BigQuery (Meltano pipeline)
  - Fallback: Local CSV file
- **Real-time Updates**: Data refreshes on each app run

## 📁 Project Structure

```
streamlit-SGhdbresale/
├── app.py                 # Main Streamlit application
├── data/                  # Local CSV fallback data
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