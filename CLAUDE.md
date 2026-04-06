# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## Commands

**Install dependencies:**
```bash
pip install -r requirements.txt
```

**Run the dashboard (recommended — auto-installs deps):**
```bat
RUN_DASHBOARD.bat
```

**Run directly:**
```bash
streamlit run sinchi_dashboard.py --server.headless true --browser.gatherUsageStats false
```

The app opens at `http://localhost:8501` in the browser.

**Default data file path** (hardcoded in `sinchi_dashboard.py` line 28):
```
C:\Users\carlo\OneDrive\Desktop\sinchi metals assays over time.xlsx
```
Can be overridden at runtime via the file upload widget in the sidebar.

---

## Code Architecture

`sinchi_dashboard.py` is the entire application (~900 lines, single file by design). It is structured in clearly separated sections marked with `# ═══` dividers:

| Section | Lines (approx.) | Purpose |
|---------|----------------|---------|
| **CONFIGURATION** | ~28–65 | Constants: file path, metal prices, color palette, element lists, STAGES tuple |
| **MATPLOTLIB GLOBAL STYLE** | ~68–95 | `set_chart_style()` — serif font, 200 DPI, academic look |
| **DATA LOADING & CLEANING** | ~97–174 | `load_data()` cached with `@st.cache_data`. Reads Excel → normalizes lab names via `LAB_MAP` → classifies each row via `classify_row()` → aggregates to one row per lot |
| **STATISTICAL HELPERS** | ~177–243 | `paired_stats()`, `pval_stars()`, `cohen_label()` |
| **FINANCIAL CALCULATIONS** | ~246–291 | `compute_financials()` — calculates Ag/Pb overpayment per lot and stage |
| **CHART HELPERS** | ~294–313 | `fig_to_buf()`, `safe_labels()`, `add_download()` |
| **CHART FUNCTIONS** | ~315–~750 | One function per chart type; all return a `matplotlib.figure.Figure` |
| **STREAMLIT APP (main)** | ~750–end | `main()` — sidebar controls, tab layout, wires data into charts |

### Key data flow

```
Excel (Sheet2)
  └─► load_data()
        ├─ normalize Lab column via LAB_MAP
        ├─ classify each row via classify_row() → Row_type
        ├─ exclude TR6xxxx lots and TR98203
        └─ aggregate to comp DataFrame (one row per TR, columns = {category}_{element})

comp DataFrame
  ├─► paired_stats()  → statistics per stage × element
  ├─► compute_financials()  → overpayment per lot
  └─► chart_*() functions  → matplotlib figures → Streamlit tabs
```

### `STAGES` tuple structure

```python
STAGES = [
    (label, penfold_key, sinchi_key, penfold_display_name, sinchi_display_name),
    ...
]
```
All chart functions iterate `STAGES` so adding a new stage only requires updating this constant.

### Adding new lots / lab variants

- New lab name spellings: add to `LAB_MAP` (line ~100)
- New description variants: update `classify_row()` (line ~105)
- After changes, restart Streamlit to invalidate `@st.cache_data`

---

## Sinchi Metals Assay Discrepancy Analysis

## Project Purpose

Penfold World Trade AG (buyer, headquartered in Baar, Switzerland) suspects that their supplier **Empresa Minera Sinchi Metals CV Export S.R.L.** (seller, based in Potosí, Bolivia) is systematically manipulating assay results to inflate the payable metal content (silver and lead) in lead-silver concentrate shipments. This project builds an analytical dashboard and reporting toolkit to **visually and statistically prove** that the discrepancies between Penfold's laboratory chain and Sinchi's laboratory chain are not random, but systematic and financially beneficial to Sinchi.

The project owner is **Carlos**, a Traffic Operator and Minerals Commodity Trader at Penfold's La Paz, Bolivia office. His direct manager is **Sergio Lorente** (Sergio Alejandro Lorente Abastoflor), who is one of Penfold's representatives with power of attorney. The report was requested by Sergio but may later be shared (in sanitized form) with Sinchi Metals and/or ASI Bolivia to trigger an internal investigation on their side.

---

## Contract Context

### Contract Number: 2601982-P

This is a purchase contract for **lead-silver concentrates** (concentrado por flotación de plomo/plata) of Bolivian origin. The contract was signed January 27, 2026, between Penfold World Trade AG and Empresa Minera Sinchi Metals CV Export S.R.L.

### Contractual Quality Specifications

The contract specifies the following assay ranges for the concentrate:

| Element | Specification |
|---------|--------------|
| Ag (Silver) | > 3,200 g/TM |
| Pb (Lead) | > 10.00% |
| As (Arsenic) | 0.01 – 0.70% (max 1.50%) |
| Sb (Antimony) | max 3.00% |
| Sn (Tin) | max 3.00% |
| Bi (Bismuth) | max 0.20% |
| Cu (Copper) | 0.20% – 1.50% |
| Zn (Zinc) | 10.00% – 20.00% |
| Hg (Mercury) | < 10 ppm |
| Moisture | 4.00% – 8.00% (min 3.00%, max 12%) |

### Delivery Terms

- **Quantity per shipment**: Approx. 110 Wet Metric Tonnes (WMT) ±10%, which equals 5 containers
- **Delivery point**: CPT – Terminal TPA in Arica, Chile (or Terminal ITI in Iquique, Chile; or FCA Depósito Karachipampa in Potosí, Bolivia; or FCA Depósito Kanamachi in Oruro, Bolivia — defined per appendix)
- **Containers**: 20 or 40 feet, polyethylene-lined, containing 20-22 TMN (dry metric tonnes net) each, provided by the buyer

### Valuation Terms (Critical for Financial Impact Calculations)

**Silver:**
- Deduct 1.5 oz/TM from the assay
- Pay 95% of the balance
- Price: LBMA London Spot Fix average during the quotation period

**Lead:**
- Deduct 3 percentage units from the assay
- Pay 95% of the balance
- Price: LME lowest quotation (cash and 3-month) averaged during the quotation period
- Lead is only payable if content exceeds 10%

**Treatment Charge (TC):**
- Base TC is negative (i.e., Penfold pays a negative TC = premium to the seller), varying by appendix:
  - Appendix 01 (Jan 2026 delivery): USD -60.00/TMNS
  - Appendix 02 (Mar 2026 delivery): USD -80.00/TMNS
  - Appendix 03 (May 2026 delivery): USD -100.00/TMNS
- TC escalator: +USD 0.15 per USD 1.00 above USD 2,150/t LME lead price, pro rata

**Refining Charge (RC):**
- Silver: USD 0.00/oz troy payable (zero RC on all appendices)

**Penalty Elements:**
- As: USD 2.00/TMNS per 0.10% above 0.50% up to 0.70%; USD 3.00/TMNS per 0.10% above 0.70% up to 1.50%
- Sb: USD 2.00/TMNS per 0.10% above 0.50% up to 3.00%
- Sn: USD 2.00/TMNS per 0.10% above 0.50% up to 3.00%
- Bi: USD 2.00/TMNS per 0.01% above 0.05% up to 0.20%
- All penalties are on a lot-by-lot basis, all fractions pro rata

**Shrinkage (Merma):**
- 0.50% of the net dry weight is deducted for shrinkage

### Payment Structure

The contract has a multi-stage payment structure tied to different documentation milestones:

1. **85% provisional payment** — upon receipt of: vendor provisional liquidation, AHK/ASI Bolivia weight certificates, export documents (DEX), samples, local lab analysis certificates, and Chilean port storage certificate
2. **95% provisional payment** — upon receipt of: vendor provisional liquidation, price fixation or stop-loss order, accredited analysis certificates from Castro Potosí/Conde Oruro (AHK and ASI Bolivia samples), averaged for payment
3. **100% final payment** — upon receipt of: final AHK/ASI Bolivia weight reports, final AHK-UK and ASI-UK assay reports (averaged), fixed prices

### Quotation Period

- Silver and Lead prices are the London Silver Fix and LME official quotations respectively
- Quotation period: last market day of the month following the month of arrival at Chilean port (per the storage certificate)
- The seller has the right to fix prices any market day from delivery date to the end of the quotation period
- If the market is in backwardation at fixing time, the seller assumes the total difference vs. today's price (price is fixed reducing the backwardation amount)

---

## The Investigation: What We Suspect and Why

### The Core Hypothesis

Sinchi Metals (or parties acting on their behalf, potentially including ASI Bolivia) may be systematically influencing the assay results from their laboratory chain to report **higher payable metal content (Ag, Pb)** and potentially **lower penalty element content (As, Sb, Sn, Bi)** than what the mineral actually contains. This would result in Penfold overpaying on provisional and final settlements.

### Why We Suspect This

The contract requires that assay results from **both parties' laboratory chains** are averaged for payment. Each lot's material is sampled at origin (Bolivia) by two independent sampling agencies:

1. **Alfred H. Knight (AHK) Bolivia** — Penfold's appointed sampling agent
2. **Alex Stewart International (ASI) Bolivia** — Sinchi's appointed sampling agent (also referred to as ASA in older records)

These samples then flow through parallel laboratory chains, and the results are averaged at each payment stage. If one chain consistently reports higher values, it pulls the average up, and Penfold overpays.

The key evidence supporting the hypothesis:
1. At the **Bolivia/local lab stage**, Sinchi's results are almost always higher than Penfold's
2. At the **UK final stage** (where independent, accredited UK labs analyze the samples), the discrepancy largely disappears
3. The **S-Side benchmark** (samples taken at disport in China and sent to reputable independent labs) aligns much more closely with Penfold's results than with Sinchi's

This pattern is consistent with manipulation at the Bolivia collection/preparation stage — either through sample tampering, lab collusion, or both.

---

## Laboratory Chain Architecture

### Understanding Who Is Who

This is the single most important piece of context for the entire project. Getting the lab classification wrong would invalidate the entire analysis. Here is the definitive mapping:

#### Penfold's Chain (our side)

| Stage | Lab Name | Variants in Data | What Happens |
|-------|----------|-------------------|-------------|
| Natural sample | **SpectrAA** | Spectra, SPECTRAA, SpectrAA | AHK Bolivia takes a natural (unprocessed) sample at the time of container loading. This sample is sent to SpectrAA lab in Bolivia for analysis. |
| Prepared/export sample | **Castro** | Castro, Casto (typo) | AHK Bolivia takes a prepared (processed/pulverized) sample. Sent to Castro lab (in Potosí or Conde Oruro area) for accredited analysis. |
| UK final | **ASI UK** | ASI, ASI UK, ASA (all same entity) | The sample **taken by AHK Bolivia** is sent to Alex Stewart International's UK laboratory for final analysis. **CRITICAL: ASI UK analyzes the AHK (Penfold) sample**, making ASI UK effectively Penfold's final result even though ASI is Sinchi's sampling agent. This is a cross-analysis arrangement. |
| S-Side benchmark | **Various China labs** | Appears under AHK, ASA, SGS, SpectrAA, Conde in the Lab column (interns misattribute) | Samples taken at the disport (destination port, typically in China) and sent to independent, high-quality labs. These are Penfold's internal control and are **confidential** — the "Do not share with supplier" flag exists for these. |

#### Sinchi's Chain (their side)

| Stage | Lab Name | Variants in Data | What Happens |
|-------|----------|-------------------|-------------|
| Natural sample | **SavantAA** | SavantAA, Savantaa, savanta, Flores-Savanta | ASI Bolivia takes a natural sample. Sent to SavantAA lab in Bolivia. |
| Prepared/export sample | **Conde** | Conde | ASI Bolivia takes a prepared sample. Sent to Conde lab for accredited analysis. |
| UK final | **AHK UK** | AHK, AHK UK | The sample **taken by ASI Bolivia** is sent to AHK's UK laboratory for final analysis. **CRITICAL: AHK UK analyzes the ASI (Sinchi) sample**, making AHK UK effectively Sinchi's final result. |

#### Why the UK Cross-Analysis Matters

The contract mandates a cross-analysis arrangement at the UK final stage:
- AHK UK receives and analyzes the **ASI Bolivia sample** → this is effectively **Sinchi's result** because it's analyzing Sinchi's sample
- ASI UK receives and analyzes the **AHK Bolivia sample** → this is effectively **Penfold's result** because it's analyzing Penfold's sample

This is counterintuitive. The lab name doesn't determine the "side" — the **sample origin** does. AHK UK (a lab associated with Penfold) produces what is functionally Sinchi's UK result because it's analyzing material collected by Sinchi's sampling agent.

The fact that the bias **disappears at the UK stage** is actually the strongest evidence of manipulation. Both UK labs are independent, accredited, and analyzing the same type of material — but one received it through ASI Bolivia's collection process and the other through AHK Bolivia's. If ASI Bolivia's sampling is clean, both UK results should be similar. And they are — the bias at UK level is statistically indistinguishable from zero (p = 0.53).

This means the manipulation is happening **before the UK stage** — at the Bolivia sampling/local lab level.

#### Other Labs Encountered in the Data

| Lab | Classification | Notes |
|-----|---------------|-------|
| Flores | Other | Appears in early lots. Third-party lab, not consistently used. Disregard. |
| SGS | S-Side | Appears once (TR70703) as an S-Side result. Global inspection company. |
| AHK BO / AHKBO | Other | AHK Bolivia's own internal readings (often NITON portable XRF). Not used for payment. |
| AHK PE | Other | AHK Peru lab. Appeared once (TR67704). Not used for payment. |
| Niton | Other | Portable XRF device readings. Screening only, not for payment. |

#### Merged/Averaged Lab Names

These appear in the Lab column when interns enter average rows:

| Lab Value | Classification | Notes |
|-----------|---------------|-------|
| W/A, WA | Average | Weighted or simple average |
| Castro/Conde, Castro+Conde | Average | Average of Castro and Conde results |
| SpectrAA+SavantAA, SpectrAA/SavantAA | Average | Average of natural sample results |
| ASA+AHK, AHK+ASI | Average | Average of UK results |
| SavantAA/Conde | Average | Mixed average |
| Flores-Savanta | Average | Mixed average |

**Decision: We ignore all Average/WA rows and recalculate averages ourselves using the simple mean of the two raw lab results.**

**Why:** The database contains pre-calculated averages that may include weighted averaging, selective inclusion, or errors. For our analysis, we need a clean comparison of Lab A vs Lab B, and we can always compute the simple average ourselves. The contract specifies simple averaging of the two results (not weighted), so our approach is contract-consistent.

---

## Data Source and Structure

### File

The primary data file is: `sinchi metals assays over time.xlsx`
- Sheet name: `Sheet2`
- This is a manual database maintained by interns at the La Paz office
- It contains all lots from Sinchi Metals across multiple contracts

### Column Structure

| Column | Description |
|--------|------------|
| Open/Close | Whether the lot is still open (ongoing) or closed (fully settled) |
| P/S | Purchase/Sale indicator (always "Purchase" for Sinchi lots) |
| Sell Ref | Internal Penfold reference (e.g., YG963-S6) |
| TR | **TRumber** — the lot identifier. Format: 5+ digits where first 3 = contract number, remaining = lot sequence within that contract |
| Sell | Supplier code (always "SM" for Sinchi Metals) |
| Sample | Sample origin (always "BO" for Bolivia) |
| Lab | Laboratory that produced the result |
| Ref | Lab reference number |
| Description | Free-text description of the row (critical for classification) |
| Date | Date of the analysis |
| ? | Unknown column, always empty |
| Ag g | Silver content in grams per metric tonne |
| Pb % | Lead content as percentage |
| As % | Arsenic content as percentage |
| Sb % | Antimony content as percentage |
| Bi % | Bismuth content as percentage |
| Sn % | Tin content as percentage |
| Zn % | Zinc content as percentage |
| Cu % | Copper content as percentage |
| Au g | Gold content in grams per metric tonne |
| S % | Sulphur percentage |
| Al2O3 % | Alumina percentage |
| Fe % | Iron percentage |
| SiO2 % | Silica percentage |
| F % | Fluorine percentage |
| Cl ppm | Chlorine in parts per million |
| Cd % | Cadmium percentage |
| WMT | Wet metric tonnes |
| DMT | Dry metric tonnes |
| H2O | Moisture fraction |
| (unnamed) | Notes column (e.g., "AHK BO export weights", "ASI BO export weights", "Average", "Do not share with supplier") |
| weight status | Unknown, mostly empty |

### Row Types Within Each Lot

Each lot (TR number) contains multiple rows representing different analysis stages:

1. **Estimated** — Penfold's pre-shipment estimate of the mineral quality. Used for initial booking. Disregard for comparison.
2. **Natural sample rows** — Unprocessed samples taken at the time of loading, sent to SpectrAA (Penfold) or SavantAA (Sinchi)
3. **Prepared/export sample rows** — Processed samples sent to Castro (Penfold) or Conde (Sinchi)
4. **UK final rows** — Results from AHK UK or ASI UK
5. **Average/WA rows** — Pre-calculated averages in the database. We disregard these and compute our own.
6. **S-Side Result rows** — Disport samples (confidential). Identified by Description containing "S-side Result" or "DP sample". The Lab column is unreliable for S-Side rows because interns forget to change it.
7. **FINAL-P row** — The last row per lot. This is a lookup/formula row that copies the latest available values for the lot into a single row. The database uses this for current lot valuation. We disregard it.
8. **NITON rows** — Portable XRF readings (screening only). Disregard.
9. **Other rows** — Flores, SGS, AHK PE results. Not part of the standard dual-chain comparison. Disregard.
10. **Empty placeholder rows** — Rows where the Lab is set but no assay values exist (e.g., pending UK results). These have NaN in all element columns.

### Data Quality Issues

1. **Lab name inconsistency** — Same lab appears under multiple names (see normalization map above)
2. **Description inconsistency** — Over 90 unique description variants for essentially ~10 row types. The classification logic must be robust to handle all variants.
3. **"Casto" typo** — In TR67705, Castro is misspelled as "Casto"
4. **S-Side lab misattribution** — The Lab column for S-Side results is unreliable. Classification must be based on the Description containing "S-side" or "DP sample", not on the Lab value.
5. **Intern data entry errors** — Some average rows are labeled under a specific lab name (e.g., "Conde" for what is actually a Castro+Conde average). The Description is more reliable than the Lab column for classification.
6. **TR90502 and TR90503 have identical assay values** — This is correct and intentional. Both lots came from the same mineral batch (mixed before loading for homogeneity), but were split into separate lots because they have different contractual terms.
7. **TR98201A and TR98201B have identical assay values** — Same mineral, split because some WMT goes to one destination and some to another.
8. **TR98203 has no assay data** — Only Estimated and FINAL-P rows with placeholder values. Exclude from analysis.

### Filtering Decisions

**Decision: Exclude all lots with TR numbers starting with "6" (TR6xxxx).**

**Why:** The TR6xxxx lots (61401, 61402, 61403, 65401, 65402, 65403, 67701-67706) are from older contracts with different terms and, critically, many of them **do not have Sinchi-side lab results** (no SavantAA/Conde/ASI rows). This means either: (a) the dual-sampling arrangement wasn't yet in place, or (b) the data is incomplete. Either way, they cannot be used for a fair Penfold-vs-Sinchi comparison and would add noise to the analysis. After filtering, we have 18 usable lots across contracts 707, 741, 757, 811, 872, 905, 933, 955, and 982.

**Decision: Keep TR90502/90503 and TR98201A/98201B as separate lots.**

**Why:** They have different contractual terms (different TCs, delivery periods, or destinations) even though the mineral is the same. Financial impact calculations must be per-lot, so keeping them separate is correct. The assay comparison is unaffected since both lots show the same bias pattern.

---

## Classification Logic (Row Type Assignment)

The classification function processes each row in the raw data and assigns it to one of these types: `Natural_Penfold`, `Natural_Sinchi`, `Prepared_Penfold`, `Prepared_Sinchi`, `UK_Penfold`, `UK_Sinchi`, `S-Side`, `Average`, `Estimated`, `FINAL-P`, `Other`, `Natural_Sinchi_local`, `Unclassified`.

### Priority Order of Classification Rules

1. If Lab = "FINAL-P" → `FINAL-P` (always, regardless of description)
2. If Lab = "Estimated" → `Estimated`
3. If Description contains "s-side" or "dp sample" → `S-Side` (takes precedence over lab name because lab attribution is unreliable for S-Side rows)
4. If Lab is in the set of known average/combined lab names → `Average`
5. If Description contains average keywords AND Lab is not a raw-data lab → `Average`
6. If Lab = "SpectrAA" → `Natural_Penfold`
7. If Lab = "SavantAA" → `Natural_Sinchi`
8. If Lab = "Castro" → `Prepared_Penfold`
9. If Lab = "Conde":
   - If Description contains "natural" but NOT "prepared" → `Natural_Sinchi_local`
   - Otherwise → `Prepared_Sinchi`
10. If Lab = "AHK" → `UK_Sinchi` (because AHK UK analyzes the ASI/Sinchi sample)
11. If Lab = "ASI" → `UK_Penfold` (because ASI UK analyzes the AHK/Penfold sample)
12. If Lab is Flores, SGS, AHK_BO, AHK PE, or Niton → `Other`
13. Otherwise → `Unclassified`

**Why this order:** The S-Side check (step 3) must come before lab-specific checks because the same labs (AHK, ASA, SpectrAA, etc.) appear in the Lab column for S-Side rows due to intern error. If we classified by lab first, S-Side results would be miscategorized as UK finals or naturals.

### Lab Name Normalization Map

Applied before classification:

```python
{
    "Casto": "Castro",       # Typo
    "AHK UK": "AHK",         # Same entity
    "AHK BO": "AHK_BO",      # Distinct: AHK Bolivia internal readings
    "AHKBO": "AHK_BO",       # Variant spelling
    "ASI UK": "ASI",          # Same entity (Alex Stewart International)
    "ASA": "ASI",             # Old name (Alex Stewart Assayers → Alex Stewart International)
}
```

**Why ASA = ASI:** Alex Stewart used to be called "Alex Stewart Assayers" (ASA) and rebranded to "Alex Stewart International" (ASI). Some people at Penfold still use the old name. In the data, ASA and ASI refer to the same laboratory and must be treated identically.

---

## Aggregation Logic

### Per-Lot Aggregation

For each lot (TR number) and each category (e.g., Natural_Penfold), we take the **simple mean** of all available values for each element. This handles cases where a lot has multiple rows for the same category (e.g., two SpectrAA natural samples from different container subsets).

**Why simple mean:** The contract specifies simple averaging (not weighted). Some lots have sub-lot results (Lot A, Lot B) that are then averaged — taking the mean of all values in the category achieves the same result.

### Elements of Interest

**Payable elements (higher = more money for Sinchi):**
- Ag g — Silver in grams per metric tonne
- Pb % — Lead as percentage

**Penalty elements (lower = less penalty for Sinchi):**
- As % — Arsenic
- Sb % — Antimony
- Sn % — Tin
- Bi % — Bismuth

**Decision: Track all 6 elements, but the primary focus is on Ag and Pb for the bias investigation.**

**Why:** If Sinchi is manipulating results, the most financially impactful manipulation would be on the payable metals (Ag, Pb). Penalty element manipulation (reporting lower As/Sb/Sn/Bi) would also benefit Sinchi but is secondary in financial magnitude. We track all 6 to build a comprehensive picture.

---

## Statistical Methodology

### Hypothesis

- **H₀ (null):** The mean difference (Sinchi − Penfold) for each element at each stage is zero. Any observed differences are due to normal analytical variability.
- **H₁ (alternative):** The mean difference is systematically non-zero, indicating bias.

### Tests Applied

For each stage × element combination:

1. **Paired one-sample t-test** on the deltas (Sinchi − Penfold). Tests whether the mean delta is significantly different from zero. Assumes approximate normality of deltas (reasonable for n > 10).

2. **Wilcoxon signed-rank test** — Non-parametric alternative that does not assume normality. More robust for small samples.

3. **Binomial sign test** — Simply tests whether Sinchi is higher more often than expected by chance (50/50). The most conservative test.

4. **Cohen's d** — Effect size measure. Interpretation: < 0.2 negligible, 0.2–0.5 small, 0.5–0.8 medium, > 0.8 large.

5. **95% confidence interval** for the mean delta using the t-distribution.

### Key Results (as of current data)

| Stage | Element | N | % Sinchi Higher | Mean Δ | t-test p | Cohen's d | Interpretation |
|-------|---------|---|-----------------|--------|----------|-----------|----------------|
| Natural | Ag g | 13 | 92.3% | +218.4 g | 0.0038 ** | 0.991 (large) | Highly significant systematic bias |
| Natural | Pb % | 11 | 81.8% | +0.42% | 0.3169 | 0.318 (small) | Directional but not significant |
| Prepared | Ag g | 15 | 73.3% | +115.1 g | 0.0099 ** | 0.770 (medium) | Significant systematic bias |
| Prepared | Pb % | 15 | 46.7% | +0.02% | 0.9627 | 0.012 (negligible) | No bias |
| UK finals | Ag g | 15 | 40.0% | +16.3 g | 0.5312 | 0.166 (negligible) | No bias — validates hypothesis |
| UK finals | Pb % | 15 | 53.3% | +0.12% | 0.7036 | 0.100 (negligible) | No bias |

**The statistical story:** The bias is strongest at the natural sample stage (p = 0.004 for Ag), diminishes at the prepared sample stage (p = 0.01), and completely vanishes at the UK final stage (p = 0.53). This gradient is precisely what you would expect if the manipulation occurs at the Bolivia sampling/local lab level. Independent UK labs, analyzing separate samples, find no systematic difference.

---

## Financial Impact Methodology

### How Overpayment Is Calculated

The contract averages Penfold's and Sinchi's results for payment. If Sinchi's result is inflated by Δ, the average is inflated by Δ/2. This Δ/2 "inflation" translates to overpayment as follows:

**For Silver:**
```
extra_oz_per_TM = (Δ_Ag / 2) × (1 / 31.1035)  [convert g to oz]
extra_payable_oz = extra_oz_per_TM × 0.95        [95% payable]
overpayment_per_TM = extra_payable_oz × Ag_price_per_oz
total_overpayment = overpayment_per_TM × DMT
```

**For Lead (only if Pb content > ~13%, i.e., above the 3-unit deduction + 10% minimum):**
```
extra_pct = (Δ_Pb / 2) / 100
extra_payable_frac = extra_pct × 0.95            [95% payable]
overpayment_per_TM = extra_payable_frac × Pb_price_per_tonne
total_overpayment = overpayment_per_TM × DMT
```

### Reference Prices Used

- Silver: **USD 72.00/oz** (approximate LBMA spot as of April 2026)
- Lead: **USD 2,000/t** (approximate LME cash as of April 2026)

**Decision: Use a single reference price for all lots rather than per-lot fixation prices.**

**Why:** We don't have the actual fixation prices per lot in this dataset. The reference prices provide an order-of-magnitude estimate. The script has these as configurable variables at the top — if Carlos obtains actual fixation prices per lot later, they can be substituted for exact calculations.

**Decision: The TC escalator is NOT factored into the financial calculation.**

**Why:** The TC escalator (+$0.15 per $1 above $2,150 LME Pb) affects the treatment charge, not the metal valuation directly. Including it would add complexity for marginal accuracy improvement. Can be added later if needed.

### DMT (Dry Metric Tonnes)

DMT per lot is taken as the simple average of all non-null DMT values in the lot's rows. This is reasonable because multiple rows may report slightly different DMT values (from different weight certificates), and the average is what's used for settlement.

---

## Dashboard Architecture

### Technology Choice: Streamlit + Matplotlib

**Why Streamlit:**
- Carlos runs this on his Windows PC at the La Paz office
- Streamlit requires zero frontend knowledge — it's pure Python
- It provides built-in interactivity (filters, toggles, sliders) with no JavaScript
- It runs locally (no deployment needed), preserving data confidentiality
- It has native file upload, download buttons, and dataframe display

**Why Matplotlib (not Plotly, not Altair):**
- The charts must be **export-ready for a Word/PowerPoint report** at executive/academic quality
- Matplotlib produces publication-quality static renders at 200 DPI
- Matplotlib gives pixel-level control over layout, preventing overlapping labels
- Plotly's interactive charts look great on screen but export poorly to static images
- Every chart has a download button that exports a print-ready PNG

**Why not a web app (React, etc.):**
- Carlos needs this running locally with zero deployment overhead
- The data is confidential — it should not leave his machine
- Streamlit achieves the same interactivity with 1/10th the code

### Dashboard Structure (10 Tabs)

1. **Executive Summary** — Metric cards (key percentages), summary bias bars, UK heatmap
2. **Silver (Ag)** — Multi-stage variance chart, paired bars + deltas for all 3 stages, box plots
3. **Lead (Pb)** — Same structure as Silver
4. **Impurities** — Combined 2×2 chart for As/Sb/Sn/Bi deltas, prepared-stage heatmap
5. **Temporal / Delta Curves** — Chronological delta lines + **cumulative sum** (the "when did it start" chart)
6. **Correlation & Bland–Altman** — 1:1 scatter with regression + standard agreement plots
7. **S-Side Benchmark** — Confidential tab (toggle-controlled). UK finals vs S-Side bars.
8. **Financial Impact** — Per-lot and cumulative overpayment bar charts
9. **Statistical Proof** — Full table of all hypothesis tests, auto-generated findings
10. **Export** — One-click multi-sheet Excel download

### Interactive Controls (Sidebar)

- **File upload** — Can override the default file path by uploading a new Excel
- **Contract filter** — Multi-select by first 3 digits of TRumber (chronological filter)
- **S-Side toggle** — Show/hide all S-Side benchmark data (for sanitization before sharing)
- **Benefit highlighting** — Yellow outline on data points where the discrepancy benefits Sinchi
- **Silver price input** — Adjustable for financial impact recalculation
- **Lead price input** — Adjustable for financial impact recalculation

---

## Chart Design Decisions

### Palette

| Color | Hex | Usage |
|-------|-----|-------|
| Penfold blue | #1565C0 | Penfold data series, negative deltas (Penfold higher) |
| Sinchi red | #C62828 | Sinchi data series, positive deltas (Sinchi higher) |
| S-Side green | #2E7D32 | Benchmark data, S-Side series |
| Natural purple | #7E57C2 | Natural stage in multi-stage charts |
| Prepared teal | #26A69A | Prepared stage in multi-stage charts |
| UK orange | #EF6C00 | UK finals stage in multi-stage charts |
| Highlight yellow | #FFD600 | Edge color for points that benefit Sinchi |

**Why these specific colors:** Red/blue provides intuitive "them vs us" framing. The stage colors (purple/teal/orange) are chosen to be visually distinct from each other and from the red/blue pair. Yellow highlight is universally attention-grabbing without conflicting with any data color.

### Typography

- Font family: Serif (Times New Roman / DejaVu Serif)
- **Why serif:** Academic/executive reports traditionally use serif fonts. This makes the charts feel authoritative and report-ready when inserted into Word documents.
- Title size: 11pt bold
- Label size: 9pt
- Tick size: 8pt
- Legend size: 8pt

### Layout Principles

- All charts use `fig.tight_layout()` to prevent label overlap
- X-axis labels are rotated 45° with `ha="right"` alignment
- Labels are truncated to 9 characters maximum to prevent crowding
- Paired bar charts use a 3:1.2 height ratio (main chart : delta subplot)
- Correlation plots use `set_aspect("equal")` for proper 1:1 visual comparison
- Every chart has adequate margins (`savefig.pad_inches = 0.15`)
- DPI is set to 200 for print quality (300 DPI was tested but doubled file sizes with negligible visual improvement at typical report sizes)

---

## File Structure

```
sinchi_dashboard/
├── sinchi_dashboard.py    # Main Streamlit application (all code in one file)
├── requirements.txt       # Python dependencies
├── RUN_DASHBOARD.bat      # Windows one-click launcher
├── README.md              # Setup and usage instructions
├── CLAUDE.md              # This file — project context for Claude Code
└── sinchi metals assays over time.xlsx  # Data file (copy here or use default path)
```

**Decision: Everything in one Python file.**

**Why:** Carlos is not a developer. A single file is easier to manage, update, and troubleshoot. There's no benefit to splitting ~900 lines into modules when the project has a single entry point and a single user.

---

## Future Work / Known Limitations

1. **Per-lot fixation prices** — The financial impact uses reference prices, not actual fixation prices. If Carlos can provide a table of (TR number → Ag fixed price, Pb fixed price), the calculation can be made exact.

2. **TC escalator** — Not currently factored into financial calculations.

3. **Only 18 lots** — The dataset contains ~32 lots total, but after filtering TR6xxxx (no Sinchi-side data), only 18 remain. If older lots can have their Sinchi-side data recovered or if new lots are added, the statistical power will increase.

4. **Report generation** — The dashboard generates charts that can be inserted into a Word report. A future enhancement could auto-generate a complete Word document with all charts, statistics, and boilerplate text.

5. **Penalty element financial impact** — Currently only Ag and Pb overpayment is calculated. Penalty element savings (Sinchi reporting lower As/Sb/Sn/Bi) could also be quantified.

6. **Date-based filtering** — The dashboard filters by contract number. A date picker could be added using the First_date column, but most lots have inconsistent or missing dates in the source data.

7. **External sharing version** — A button or mode that automatically strips all S-Side data, removes the S-Side tab, and removes the financial impact tab would make it easy to generate the version shared with Sinchi/ASI BO.

8. **Automated anomaly detection** — CUSUM (cumulative sum control chart) or change-point detection algorithms could mathematically identify the exact lot where the bias regime changed. Currently the cumulative delta chart serves this purpose visually.

---

## How to Update the Dashboard

When new lots are added to the Excel:
1. Re-export from the database
2. Replace the Excel file
3. Refresh the Streamlit page (or restart with `RUN_DASHBOARD.bat`)

When metal prices change:
1. Adjust the sidebar inputs in the running dashboard, OR
2. Edit `AG_PRICE_USD_OZ` and `PB_PRICE_USD_T` at the top of `sinchi_dashboard.py`

When new labs or description variants appear:
1. Check if the classification logic handles them (run the dashboard and look for "Unclassified" in the data)
2. If not, add the new lab name to `LAB_MAP` or add a new rule to `classify_row()`

---

## Glossary

| Term | Meaning |
|------|---------|
| TRumber | Trade Reference Number. Penfold's lot identifier. Format: first 3 digits = contract, remaining digits = lot sequence. |
| WMT | Wet Metric Tonnes — weight of material including moisture |
| DMT | Dry Metric Tonnes — weight after moisture deduction |
| TMNS | Tonelada Métrica Neta Seca — same as DMT in Spanish |
| TMH | Tonelada Métrica Húmeda — same as WMT in Spanish |
| TM | Metric tonne (1,000 kg) |
| TC | Treatment Charge — paid by buyer to seller (negative TC = buyer pays premium) |
| RC | Refining Charge — deducted from payable metal value |
| LBMA | London Bullion Market Association — silver price benchmark |
| LME | London Metal Exchange — lead price benchmark |
| CPT | Carriage Paid To (Incoterm) |
| FCA | Free Carrier (Incoterm) |
| DEX | Declaración de Exportación — Bolivian export declaration |
| AHK | Alfred H. Knight — independent inspection/sampling company (Penfold's agent) |
| ASI / ASA | Alex Stewart International / Alex Stewart Assayers — independent inspection/sampling company (Sinchi's agent). Same entity, different historical names. |
| S-Side | Seller-side / Ship-side — samples taken at the destination port (disport), typically in China. Used as an independent benchmark. **Confidential.** |
| Backwardation | Market condition where spot price > future price. Contract clause: seller absorbs the difference. |
| Merma | Shrinkage — 0.50% deduction from net dry weight |
| Stop Loss | Price fixation order where the price is automatically fixed if it drops to a specified level |
