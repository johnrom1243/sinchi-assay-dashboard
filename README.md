# Sinchi Metals — Assay Discrepancy Analysis Dashboard

A Streamlit analytics dashboard investigating systematic assay discrepancies between Penfold World Trade AG's laboratory chain and Sinchi Metals' laboratory chain across lead-silver and zinc-silver concentrate shipments.

## Quick Start (Windows)

1. Make sure **Python 3.9+** is installed ([python.org/downloads](https://www.python.org/downloads/))
2. Place your Excel files at the paths configured in `sinchi_dashboard.py` (lines ~28–30), or upload via the sidebar widget
3. **Double-click `RUN_DASHBOARD.bat`**
4. Your browser will open automatically at `http://localhost:8501`

## Manual Start

```bash
pip install -r requirements.txt
streamlit run sinchi_dashboard.py
```

## Streamlit Cloud Deployment

1. Fork or clone this repository to your GitHub account
2. Go to [share.streamlit.io](https://share.streamlit.io) and connect your GitHub account
3. Click **New app** → select this repo → set main file to `sinchi_dashboard.py`
4. Under **Advanced settings → Secrets**, add (if needed):
   ```toml
   # No secrets required for local file mode
   # Add here if you configure a remote data source in future
   ```
5. Deploy — the app will be live at `https://<your-app-name>.streamlit.app`

> **Note:** The default data file path is hardcoded to a local Windows path. When deploying to Streamlit Cloud, use the **file upload widget** in the sidebar to load your Excel files. Do not commit Excel files to the repository (they are gitignored).

## Data Files Required

| File | Purpose |
|------|---------|
| `sinchi metals assays over time.xlsx` | Primary database — used for DMT weights and S-Side results |
| `Assay Exchanges - Low Silver Sinchi 1.xlsx` | Cleaned assay exchange data (all lab results) |

Both files are excluded from git (`.gitignore`). Load them via the sidebar upload widget or set the hardcoded paths in `sinchi_dashboard.py`.

## Features

### 13-Tab Dashboard

| Tab | Content |
|-----|---------|
| 📊 Summary | Metric cards, bias heatmap, summary bars |
| 🥈 Silver | Multi-stage variance, paired bars + deltas, box plots |
| 🔩 Lead | Same structure as Silver |
| ☣️ Impurities | As/Sb/Sn/Bi delta charts and heatmap |
| 📈 Delta Curves | Chronological deltas + cumulative sum per element |
| 🎯 Correlation | 1:1 scatter with regression, Bland-Altman plots |
| 🔒 S-Side | Confidential: China benchmark vs both lab chains |
| 💰 Financials | Per-lot and cumulative Ag/Pb/Zn overpayment |
| 📐 Statistics | Full hypothesis test table (t-test, Wilcoxon, binomial, Cohen's d) |
| 🕵️ UK Trend | Regime-change detection, CUSUM, Pettitt test for UK finals |
| 🔬 Forensic | Single-lot deep-dive (stage progression, delta heatmap, S-Side) |
| ⚖️ Impact | Weight-adjusted impact: UK delta × DMT (bubble chart + sorted bars) |
| 📥 Export | Multi-sheet Excel download + all charts |

### Interactive Controls (Sidebar)
- **File upload** — override default paths with a local upload
- **Contract filter** — slice by contract number (first 3 digits of TRumber)
- **Concentrate type** — filter by Pb/Ag vs Zn/Ag lots
- **S-Side toggle** — show/hide confidential benchmark data
- **Benefit highlighting** — yellow outline on points that financially favour Sinchi
- **DMT toggle** — display dry metric tonnes beneath each bar
- **Price inputs** — adjust Ag, Pb, and Zn reference prices for financial impact

### Statistical Tests
- Paired t-test (H₀: mean delta = 0)
- Wilcoxon signed-rank test (non-parametric)
- Binomial sign test
- Cohen's d effect size with interpretation
- 95% confidence intervals
- Pettitt change-point test (UK Trend tab)
- Grubbs outlier test (UK Trend tab)

## Lab Classification

| Stage | Penfold chain | Sinchi chain |
|-------|--------------|-------------|
| Natural | SpectrAA | SavantAA |
| Prepared | Castro | Conde |
| UK finals | ASI/ASA (analyses AHK Bolivia sample) | AHK UK (analyses ASI Bolivia sample) |
| Benchmark | S-Side / China disport | — |

> **Key insight:** At the UK stage, labs cross-analyse each other's samples. AHK UK = Sinchi's result; ASI UK = Penfold's result.

## Data Notes

- Lots with TRumbers starting with `6` (TR6xxxx) are excluded — incomplete dual-chain data
- TR98203 is excluded — no assay data
- TR90502/90503 and TR98201A/98201B are kept as separate lots
- DMT per lot uses the **last** FINAL-P row (most recently settled weight)
- Average/WA rows in the database are ignored; averages are recomputed from raw lab results

## File Structure

```
SMPY/
├── sinchi_dashboard.py      # Main Streamlit application (~2850 lines)
├── requirements.txt         # Python dependencies
├── RUN_DASHBOARD.bat        # Windows one-click launcher
├── README.md                # This file
├── CLAUDE.md                # Project context for Claude Code
├── .gitignore               # Excludes data files and secrets
└── .streamlit/
    └── config.toml          # Streamlit server configuration
```
