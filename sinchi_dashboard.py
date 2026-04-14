"""
Sinchi Metals Assay Discrepancy Dashboard
==========================================
Assay data  →  Assay Exchanges - Low Silver Sinchi 1.xlsx  (structured, clean)
Weights + S-Side  →  sinchi metals assays over time.xlsx   (original)

Run:  streamlit run sinchi_dashboard.py
"""
import streamlit as st
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from scipy import stats as sp_stats
from io import BytesIO
from pathlib import Path
import warnings

# Only suppress matplotlib/font warnings — preserve all data-related warnings
warnings.filterwarnings("ignore", category=UserWarning, module="matplotlib")
warnings.filterwarnings("ignore", message=".*Glyph.*missing.*")

# ═══════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════

# Primary assay source — new structured file (Ownership & Stage explicit)
NEW_FILE_PATH  = r"C:\claude\SMPY\Assay Exchanges - Low Silver Sinchi 1.xlsx"
NEW_FILE_LOCAL = "Assay Exchanges - Low Silver Sinchi 1.xlsx"   # same-dir copy
NEW_FILE_SHEET = "Sheet1"

# Original file — used ONLY for DMT weights and S-Side results
ORIG_FILE_PATH  = r"C:\Users\carlo\OneDrive\Desktop\sinchi metals assays over time.xlsx"
ORIG_FILE_LOCAL = r"C:\claude\SMPY\sinchi metals assays over time.xlsx"
ORIG_FILE_SHEET = "Sheet2"

# Contract constants (used for physical impact calculations)
AG_DEDUCT_OZ     = 1.5          # Not used in delta calc (cancels out), kept for reference
PB_DEDUCT_UNITS  = 3.0          # Deduction from Pb assay before payable calculation
PB_MIN_PAYABLE   = 10.0         # Contract: Pb only payable if assay > 10 %
PAYABLE_FRACTION = 0.95
OZ_PER_GRAM      = 1 / 31.1035

# Chart palette
C_PENFOLD = "#1565C0"
C_SINCHI  = "#C62828"
C_SSIDE   = "#2E7D32"
C_DELTA_P = "#C62828"
C_DELTA_N = "#1565C0"
C_NEUTRAL = "#78909C"
C_BG      = "#FFFFFF"

# Elements tracked in analysis (Zn added as spec-range element)
ELEMENTS = ["Ag g", "Pb %", "As %", "Sb %", "Sn %", "Bi %", "Zn %"]
PAYABLES  = ["Ag g", "Pb %"]
PENALTIES = ["As %", "Sb %", "Sn %", "Bi %"]

# Lab name normalization — applied to BOTH data sources before any logic.
# Keys are lowercase; values are the canonical name used everywhere.
LAB_NORM = {
    # Sinchi natural lab variants
    "savantaa":       "SavantAA",
    "savanta":        "SavantAA",
    "savant":         "SavantAA",
    "flores-savanta": "SavantAA",
    # Sinchi prepared lab variants
    "conde":          "Conde",
    "conde morales":  "Conde",
    # Penfold natural lab variants
    "spectraa":       "SpectrAA",
    "spectra":        "SpectrAA",
    # Penfold prepared lab variants
    "castro":         "Castro",
    "casto":          "Castro",           # typo in TR67705
    # UK labs
    "ahk uk":         "AHK UK",
    "ahk":            "AHK UK",
    "asi uk":         "ASI UK",
    "asi":            "ASI UK",
    "asa uk":         "ASI UK",           # old name variant
    "asa":            "ASI UK",           # old name (Alex Stewart Assayers)
    # Bolivia internal / other
    "ahk bo":         "AHK_BO",
    "ahkbo":          "AHK_BO",
    "ahk pe":         "AHK_PE",
    "niton":          "Niton",
    "sgs":            "SGS",
    "flores":         "Flores",
}


def normalize_lab(lab_value):
    """Map any lab name variant to its canonical form."""
    if pd.isna(lab_value):
        return lab_value
    key = str(lab_value).strip().lower()
    return LAB_NORM.get(key, str(lab_value).strip())


# Maps new file's Stage value → comp column category prefix
STAGE_KEY_MAP = {"Natural": "Natural", "Prepared": "Prepared", "UK_Final": "UK"}

# Note on UK finals: ownership is explicitly set in the new file based on which
# sampling agency collected the sample — not which UK lab analysed it.
# For older lots (707xx–811xx) the cross-analysis swap was not yet in place.
# The new file already reflects the correct ownership for every lot.
STAGES = [
    ("Natural",   "Natural_Penfold",  "Natural_Sinchi",
     "SpectrAA (Penfold)", "SavantAA (Sinchi)"),
    ("Prepared",  "Prepared_Penfold", "Prepared_Sinchi",
     "Castro (Penfold)",   "Conde (Sinchi)"),
    ("UK finals", "UK_Penfold",       "UK_Sinchi",
     "Penfold sample → UK lab", "Sinchi sample → UK lab"),
]

CATEGORIES = [
    "Natural_Penfold", "Natural_Sinchi",
    "Prepared_Penfold", "Prepared_Sinchi",
    "UK_Penfold", "UK_Sinchi", "S-Side",
]

# ═══════════════════════════════════════════════════════════════════════
# MATPLOTLIB GLOBAL STYLE
# ═══════════════════════════════════════════════════════════════════════
def set_chart_style():
    plt.rcParams.update({
        "font.family":        "serif",
        "font.serif":         ["Times New Roman", "DejaVu Serif"],
        "font.size":          9,
        "axes.titlesize":     11,
        "axes.titleweight":   "bold",
        "axes.labelsize":     9,
        "xtick.labelsize":    8,
        "ytick.labelsize":    8,
        "legend.fontsize":    8,
        "figure.facecolor":   C_BG,
        "axes.facecolor":     C_BG,
        "axes.grid":          True,
        "grid.alpha":         0.25,
        "grid.linewidth":     0.4,
        "axes.spines.top":    False,
        "axes.spines.right":  False,
        "axes.linewidth":     0.6,
        "figure.dpi":         200,
        "savefig.dpi":        200,
        "savefig.bbox":       "tight",
        "savefig.pad_inches": 0.15,
    })

set_chart_style()

# ═══════════════════════════════════════════════════════════════════════
# DATA LOADING
# ═══════════════════════════════════════════════════════════════════════
def _find_new_file():
    """Return the assay file path, preferring same-directory copy."""
    for p in [NEW_FILE_LOCAL, NEW_FILE_PATH]:
        if Path(p).exists():
            try:
                with open(p, "rb") as fh:
                    fh.read(4)
                return p
            except (PermissionError, OSError):
                continue
    return None


def _find_orig_file():
    """
    Return the first path that both exists AND is readable.
    Tries the local SMPY copy before OneDrive to avoid permission issues
    when OneDrive has the file locked or access is denied.
    """
    for p in [ORIG_FILE_LOCAL, "sinchi metals assays over time.xlsx",
              ORIG_FILE_PATH]:   # local first
        if Path(p).exists():
            try:
                with open(p, "rb") as fh:
                    fh.read(4)               # verify we can actually open it
                return p
            except (PermissionError, OSError):
                continue
    return None


@st.cache_data(show_spinner="Loading and cleaning data …")
def load_data(new_file_bytes=None, orig_file_bytes=None):
    """
    Build the comp DataFrame (one row per lot) from two sources:
      - new_file   : assay values — structured with explicit Ownership & Stage columns
      - orig_file  : DMT weights (FINAL-P rows) + S-Side results (description filter)

    TR numbers are stored without the 'TR' prefix (e.g. '74101').
    For TR98201, which appears as 98201A + 98201B in the original file,
    DMTs are summed and S-Side values averaged.
    """
    # ── New assay file ─────────────────────────────────────────────────
    if new_file_bytes is not None:
        assay_raw = pd.read_excel(BytesIO(new_file_bytes), sheet_name=NEW_FILE_SHEET)
    else:
        new_path = _find_new_file()
        if new_path is None:
            raise FileNotFoundError(
                f"Assay file not found. Expected at: {NEW_FILE_PATH}\n"
                f"Or in the same directory as sinchi_dashboard.py: {NEW_FILE_LOCAL}"
            )
        assay_raw = pd.read_excel(new_path, sheet_name=NEW_FILE_SHEET)

    assay_df = assay_raw.dropna(subset=["TR_Number"]).copy()
    assay_df = assay_df.rename(columns={
        "Ag_g": "Ag g", "Pb_pct": "Pb %", "Zn_pct": "Zn %",
        "As_pct": "As %", "Sb_pct": "Sb %", "Sn_pct": "Sn %",
        "Bi_pct": "Bi %", "Cu": "Cu %",
    })
    # Normalize lab names (handles "Conde Morales", "Savanta", "ASA UK", etc.)
    if "Lab" in assay_df.columns:
        assay_df["Lab"] = assay_df["Lab"].map(normalize_lab)
    # Category key = "{stage_prefix}_{Ownership}"
    assay_df["_cat"] = assay_df.apply(
        lambda r: f"{STAGE_KEY_MAP.get(r['Stage'], r['Stage'])}_{r['Ownership']}",
        axis=1,
    )

    # ── Original file (weights + S-Side only) ─────────────────────────
    dmt_lookup   = {}   # TR_orig (e.g. "98201A") → float DMT
    sside_lookup = {}   # TR_orig → {elem → float}

    try:
        if orig_file_bytes is not None:
            orig_raw = pd.read_excel(BytesIO(orig_file_bytes),
                                     sheet_name=ORIG_FILE_SHEET, header=0)
        else:
            orig_path = _find_orig_file()
            orig_raw = (pd.read_excel(orig_path, sheet_name=ORIG_FILE_SHEET, header=0)
                        if orig_path else None)

        if orig_raw is not None:
            orig = orig_raw.copy()
            orig["_tr"]   = orig["TR"].astype(str).str.strip()
            orig["_desc"] = orig["Description"].fillna("").str.strip().str.lower()
            orig["_lab"]  = orig["Lab"].map(normalize_lab)

            # DMT from FINAL-P rows — use LAST row per TR (most recently settled weight)
            fp = orig[orig["_lab"] == "FINAL-P"][["_tr", "DMT"]].dropna(subset=["DMT"])
            dmt_lookup = fp.groupby("_tr")["DMT"].last().to_dict()

            # S-Side: identified by description keyword
            ss = orig[orig["_desc"].str.contains("s-side|dp sample", na=False)]
            for tr_orig, grp in ss.groupby("_tr"):
                sside_lookup[tr_orig] = {}
                for elem in ["Ag g", "Pb %", "As %", "Sb %", "Sn %", "Bi %"]:
                    if elem in grp.columns:
                        vals = grp[elem].dropna()
                        if len(vals):
                            sside_lookup[tr_orig][elem] = round(float(vals.mean()), 3)
    except Exception as exc:
        import logging
        logging.warning("Original file (weights/S-Side) could not be loaded: %s", exc)
        # Weights and S-Side will be NaN — assay analysis still proceeds

    # ── Build one row per lot ──────────────────────────────────────────
    records = []
    for tr_full in sorted(assay_df["TR_Number"].unique()):
        tr_num = tr_full.replace("TR", "")          # strip prefix → "70701"
        lot    = assay_df[assay_df["TR_Number"] == tr_full]
        lot_type = lot["Lot_Type"].iloc[0] if "Lot_Type" in lot.columns else "Pb/Ag"
        rec    = {"TR": tr_num, "Contract": tr_num[:3], "Lot_Type": str(lot_type)}

        # DMT: direct match, or sum A + B sub-lots (e.g. 98201A + 98201B)
        if tr_num in dmt_lookup:
            rec["DMT"] = round(dmt_lookup[tr_num], 3)
        else:
            dmt_a = dmt_lookup.get(f"{tr_num}A", 0)
            dmt_b = dmt_lookup.get(f"{tr_num}B", 0)
            rec["DMT"] = round(dmt_a + dmt_b, 3) if (dmt_a or dmt_b) else np.nan

        # Assay values per category (mean handles multiple sub-rows, e.g. 98201A/B)
        for cat in CATEGORIES[:-1]:          # exclude S-Side
            sub = lot[lot["_cat"] == cat]
            for elem in ELEMENTS:
                vals = sub[elem].dropna() if elem in sub.columns else pd.Series(dtype=float)
                rec[f"{cat}_{elem}"] = round(float(vals.mean()), 3) if len(vals) else np.nan

        # S-Side from original file; average A/B sub-lots if present
        for elem in ELEMENTS:
            vals = []
            for tv in [tr_num, f"{tr_num}A", f"{tr_num}B"]:
                if tv in sside_lookup and elem in sside_lookup[tv]:
                    vals.append(sside_lookup[tv][elem])
            rec[f"S-Side_{elem}"] = round(float(np.mean(vals)), 3) if vals else np.nan

        records.append(rec)

    comp = pd.DataFrame(records)
    comp["sort_key"] = comp["TR"].str.extract(r"(\d+)")[0].astype(int)
    comp = comp.sort_values("sort_key").reset_index(drop=True)
    return comp


# ═══════════════════════════════════════════════════════════════════════
# STATISTICAL HELPERS
# ═══════════════════════════════════════════════════════════════════════
def paired_stats(p_vals, s_vals):
    mask = pd.notna(p_vals) & pd.notna(s_vals)
    p = np.asarray(p_vals[mask], dtype=float)
    s = np.asarray(s_vals[mask], dtype=float)
    n = len(p)
    if n < 3:
        return {"n": n, "insufficient": True}

    d      = s - p
    mean_d = np.mean(d)
    std_d  = np.std(d, ddof=1)
    se     = std_d / np.sqrt(n)
    ci95   = sp_stats.t.interval(0.95, df=n-1, loc=mean_d, scale=se)

    t_stat, t_pval = sp_stats.ttest_1samp(d, 0)
    try:
        w_stat, w_pval = sp_stats.wilcoxon(d)
    except ValueError:
        w_stat, w_pval = np.nan, np.nan

    n_pos     = int(np.sum(d > 0))
    n_nonzero = int(np.sum(d != 0))       # exclude ties from sign test denominator
    sign_pval = sp_stats.binomtest(n_pos, n_nonzero, 0.5).pvalue if n_nonzero > 0 else np.nan
    cohen_d   = mean_d / std_d if std_d > 0 else np.nan

    p_mean    = np.mean(p)
    pct_bias  = round(mean_d / abs(p_mean) * 100, 2) if p_mean != 0 else np.nan

    return {
        "n":                 n,
        "mean_delta":        round(mean_d, 4),
        "pct_rel_bias":      pct_bias,
        "median_delta":      round(np.median(d), 4),
        "std_delta":         round(std_d, 4),
        "ci95_lo":           round(ci95[0], 4),
        "ci95_hi":           round(ci95[1], 4),
        "pct_sinchi_higher": round(n_pos / n * 100, 1),
        "t_stat":            round(t_stat, 3),
        "t_pval":            t_pval,
        "wilcoxon_stat":     w_stat,
        "wilcoxon_pval":     w_pval,
        "sign_pval":         sign_pval,
        "cohen_d":           round(cohen_d, 3),
        "insufficient":      False,
    }


def pval_stars(p):
    if pd.isna(p): return ""
    if p < 0.001: return "***"
    if p < 0.01:  return "**"
    if p < 0.05:  return "*"
    return "n.s."


def cohen_label(d):
    if pd.isna(d): return ""
    ad = abs(d)
    if ad < 0.2: return "negligible"
    if ad < 0.5: return "small"
    if ad < 0.8: return "medium"
    return "large"


# ═══════════════════════════════════════════════════════════════════════
# DELTA HELPERS  (absolute vs % relative)
# ═══════════════════════════════════════════════════════════════════════
def delta_values(p_arr, s_arr, pct_mode=False):
    """Return Sinchi − Penfold, optionally as % of |Penfold|."""
    p = np.asarray(p_arr, dtype=float)
    s = np.asarray(s_arr, dtype=float)
    mask = pd.notna(p) & pd.notna(s)
    d = np.where(mask, s - p, np.nan)
    if pct_mode:
        with np.errstate(divide="ignore", invalid="ignore"):
            d = np.where(mask & (p != 0), (s - p) / np.abs(p) * 100, np.nan)
    return d


def delta_unit(base_unit, pct_mode):
    return "% Δ" if pct_mode else base_unit


def delta_ylabel(pct_mode):
    return "Δ%  (Sinchi − Penfold) / |Penfold|" if pct_mode else "Δ  (Sinchi − Penfold)"


# ═══════════════════════════════════════════════════════════════════════
# PHYSICAL IMPACT CALCULATIONS  (no USD — lot-specific prices unknown)
# ═══════════════════════════════════════════════════════════════════════
def compute_physical_impact(comp):
    """
    Compute per-lot deltas and extra payable physical quantities.
    USD conversion is intentionally omitted because each lot has different
    fixation prices, quotation periods, and contract appendices.
    Damage is expressed in troy ounces (Ag) and payable tonnes (Pb).
    """
    rows = []
    for _, r in comp.iterrows():
        lot_type = str(r.get("Lot_Type", "Pb/Ag"))
        fr = {"TR": r["TR"], "Contract": r["Contract"],
              "DMT": r["DMT"], "Lot_Type": lot_type}
        best_stage = None

        for stage_lbl, p_key, s_key, _, _ in STAGES:
            for short, col in [("Ag", "Ag g"), ("Pb", "Pb %")]:
                pv = r.get(f"{p_key}_{col}", np.nan)
                sv = r.get(f"{s_key}_{col}", np.nan)
                fr[f"{stage_lbl}_Penfold_{short}"] = pv
                fr[f"{stage_lbl}_Sinchi_{short}"]  = sv
                if pd.notna(pv) and pd.notna(sv):
                    delta = sv - pv
                    fr[f"{stage_lbl}_Delta_{short}"] = round(delta, 3)
                    best_stage = stage_lbl
                else:
                    fr[f"{stage_lbl}_Delta_{short}"] = np.nan

        fr["Settlement_Stage"] = best_stage or "N/A"
        dmt = r["DMT"]

        # Extra payable Ag at UK finals (contract: −1.5 oz/TM, pay 95 %)
        # The 1.5 oz deduction cancels out in a delta-based calculation.
        ag_uk_d = fr.get("UK finals_Delta_Ag", np.nan)
        if pd.notna(ag_uk_d) and pd.notna(dmt):
            fr["Extra_Ag_oz"] = round(
                (ag_uk_d / 2) * OZ_PER_GRAM * PAYABLE_FRACTION * dmt, 2)
        else:
            fr["Extra_Ag_oz"] = np.nan

        # Extra payable Pb at UK finals (contract: −3 units, pay 95 %)
        pb_uk_d = fr.get("UK finals_Delta_Pb", np.nan)
        if pd.notna(pb_uk_d) and pd.notna(dmt):
            fr["Extra_Pb_t"] = round(
                (pb_uk_d / 2) / 100 * PAYABLE_FRACTION * dmt, 4)
        else:
            fr["Extra_Pb_t"] = np.nan

        rows.append(fr)
    return pd.DataFrame(rows)


# ═══════════════════════════════════════════════════════════════════════
# CHART HELPERS
# ═══════════════════════════════════════════════════════════════════════
def fig_to_buf(fig):
    buf = BytesIO()
    fig.savefig(buf, format="png", facecolor=C_BG)
    buf.seek(0)
    return buf


def safe_labels(labels, max_len=9):
    return [str(l)[:max_len] for l in labels]


def add_download(fig, key, label="⬇ Download chart"):
    buf = fig_to_buf(fig)
    st.download_button(label, buf, file_name=f"{key}.png",
                       mime="image/png", key=f"dl_{key}")


def completeness_df(comp):
    """Return a DataFrame showing paired-data availability per lot × stage."""
    checks = [
        ("Natural Ag",  "Natural_Penfold_Ag g",  "Natural_Sinchi_Ag g"),
        ("Prepared Ag", "Prepared_Penfold_Ag g", "Prepared_Sinchi_Ag g"),
        ("UK final Ag", "UK_Penfold_Ag g",       "UK_Sinchi_Ag g"),
        ("S-Side Ag",   None,                     "S-Side_Ag g"),
    ]
    rows = []
    for _, r in comp.iterrows():
        row = {"TR": r["TR"], "Contract": r["Contract"]}
        for lbl, p_col, s_col in checks:
            has_p = pd.notna(r.get(p_col, np.nan)) if p_col else True
            has_s = pd.notna(r.get(s_col, np.nan))
            if p_col is None:
                row[lbl] = "✓" if has_s else "—"
            elif has_p and has_s:
                row[lbl] = "✓ paired"
            elif has_p:
                row[lbl] = "Penfold only"
            elif has_s:
                row[lbl] = "Sinchi only"
            else:
                row[lbl] = "—"
        rows.append(row)
    return pd.DataFrame(rows)


# ═══════════════════════════════════════════════════════════════════════
# CHART: PAIRED BARS + DELTA
# ═══════════════════════════════════════════════════════════════════════
def chart_paired_bars(comp, elem_col, unit, stage_name, p_key, s_key,
                      p_label, s_label, labels, show_sside=False,
                      highlight_benefit=False, pct_mode=False, show_dmt=False):
    n = len(labels)
    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(max(7, n * 0.55 + 2), 5.2),
        height_ratios=[3, 1.3], gridspec_kw={"hspace": 0.40},
    )
    x = np.arange(n)
    w = 0.32

    p_data = comp[f"{p_key}_{elem_col}"].values
    s_data = comp[f"{s_key}_{elem_col}"].values

    ax1.bar(x - w/2, p_data, w, label=p_label, color=C_PENFOLD, alpha=0.82, zorder=3)
    ax1.bar(x + w/2, s_data, w, label=s_label, color=C_SINCHI,  alpha=0.82, zorder=3)

    if show_sside and f"S-Side_{elem_col}" in comp.columns:
        ss = comp[f"S-Side_{elem_col}"].values
        ax1.plot(x, ss, "D-", color=C_SSIDE, ms=4.5, lw=1.3,
                 label="S-Side benchmark", zorder=4)

    ax1.set_title(stage_name, pad=6)
    ax1.set_ylabel(unit)
    ax1.set_xticks(x)
    ax1.set_xticklabels(safe_labels(labels), rotation=45, ha="right")
    ax1.legend(loc="upper right", framealpha=0.92, edgecolor="#ccc")

    mask = pd.notna(p_data) & pd.notna(s_data)
    n_paired = int(mask.sum())
    if n_paired:
        diffs_abs = s_data[mask] - p_data[mask]
        pct_higher = (diffs_abs > 0).sum() / n_paired * 100
        avg = np.mean(diffs_abs)
        ax1.text(0.0, 1.015, (
            f"n = {n_paired}  ·  Sinchi higher in {pct_higher:.0f} % of lots  ·  "
            f"avg abs Δ = {'+' if avg >= 0 else ''}{avg:.1f} {unit}"
        ), transform=ax1.transAxes, fontsize=7.5, style="italic", color="#666")

    # Delta subplot
    deltas = delta_values(p_data, s_data, pct_mode)
    colors = [C_DELTA_P if (pd.notna(d) and d > 0) else C_DELTA_N for d in deltas]
    ec  = ["#FFD600" if (highlight_benefit and pd.notna(d) and d > 0)
           else "none" for d in deltas]
    lws = [1.5 if (highlight_benefit and pd.notna(d) and d > 0) else 0 for d in deltas]
    ax2.bar(x, deltas, 0.52, color=colors, alpha=0.72,
            edgecolor=ec, linewidth=lws, zorder=3)
    ax2.axhline(0, color="black", lw=0.5, zorder=2)
    # Value labels on each delta bar
    for xi, dv in zip(x, deltas):
        if pd.notna(dv) and dv != 0:
            fmt = f"{dv:+.1f}" if pct_mode else f"{dv:+.0f}"
            ax2.text(xi, dv + (abs(dv)*0.04 + 0.5) * np.sign(dv),
                     fmt, ha="center",
                     va="bottom" if dv >= 0 else "top",
                     fontsize=6.5, color="#222", zorder=5)

    if show_sside and f"S-Side_{elem_col}" in comp.columns:
        ss_data   = comp[f"S-Side_{elem_col}"].values
        ss_deltas = delta_values(p_data, ss_data, pct_mode)
        ax2.plot(x, ss_deltas, "D", color=C_SSIDE, ms=5,
                 markeredgecolor="white", label="S-Side Δ (vs Penfold)", zorder=4)
        ax2.legend(fontsize=7, loc="upper left", framealpha=0.9)

    d_unit = delta_unit(unit, pct_mode)
    ax2.set_ylabel(f"Δ ({d_unit})")
    ax2.set_xticks(x)

    # X-axis labels: lot name optionally followed by DMT
    if show_dmt and "DMT" in comp.columns:
        dmt_vals = comp["DMT"].values
        xticklabels = []
        for i, lbl in enumerate(safe_labels(labels)):
            dv = dmt_vals[i] if i < len(dmt_vals) else np.nan
            dmt_str = f"\n{dv:.0f}t" if pd.notna(dv) else f"\nN/A"
            xticklabels.append(lbl + dmt_str)
    else:
        xticklabels = safe_labels(labels)

    ax2.set_xticklabels(xticklabels, rotation=45, ha="right")
    ax1.set_xticks(x)
    ax1.set_xticklabels(xticklabels, rotation=45, ha="right")

    ax2.set_title(
        ("% delta relative to Penfold" if pct_mode
         else "Delta  (red = Sinchi higher → overpayment risk)"
              + ("  ·  DMT shown below lot name" if show_dmt else "")),
        fontsize=8, fontweight="normal", color="#666", loc="left",
    )
    fig.tight_layout()
    return fig


# ═══════════════════════════════════════════════════════════════════════
# CHART: MULTI-STAGE VARIANCE
# ═══════════════════════════════════════════════════════════════════════
def chart_multistage_delta(comp, elem_col, unit, labels,
                           highlight_benefit=False, pct_mode=False):
    n = len(labels)
    fig, ax = plt.subplots(figsize=(max(7, n * 0.55 + 2), 4))
    x = np.arange(n)
    w = 0.24
    stage_colors = ["#7E57C2", "#26A69A", "#EF6C00"]
    stage_names  = ["Natural", "Prepared", "UK finals"]

    for i, (_, p_key, s_key, _, _) in enumerate(STAGES):
        p = comp[f"{p_key}_{elem_col}"].values
        s = comp[f"{s_key}_{elem_col}"].values
        d = delta_values(p, s, pct_mode)
        n_valid = int(np.sum(pd.notna(p) & pd.notna(s)))
        offset  = (i - 1) * w
        bars = ax.bar(x + offset, d, w,
                      label=f"{stage_names[i]} (n={n_valid})",
                      color=stage_colors[i], alpha=0.78, zorder=3)
        if highlight_benefit:
            for j, bar in enumerate(bars):
                if pd.notna(d[j]) and d[j] > 0:
                    bar.set_edgecolor("#FFD600")
                    bar.set_linewidth(1.4)

    ax.axhline(0, color="black", lw=0.5, zorder=2)
    d_unit = delta_unit(unit, pct_mode)
    ax.set_title(f"Variance across all stages — {d_unit}", pad=6)
    ax.set_ylabel(delta_ylabel(pct_mode))
    ax.set_xticks(x)
    ax.set_xticklabels(safe_labels(labels), rotation=45, ha="right")
    ax.legend(loc="upper right", framealpha=0.92, edgecolor="#ccc")
    fig.tight_layout()
    return fig


# ═══════════════════════════════════════════════════════════════════════
# CHART: 1:1 CORRELATION
# ═══════════════════════════════════════════════════════════════════════
def chart_correlation(comp, elem_col, unit, labels,
                      highlight_benefit=False, show_sside=False):
    fig, axes = plt.subplots(1, 3, figsize=(13.5, 4.2))
    stage_colors = [C_PENFOLD, "#26A69A", C_SINCHI]

    for idx, (stage_lbl, p_key, s_key, p_lab, s_lab) in enumerate(STAGES):
        ax = axes[idx]
        p = comp[f"{p_key}_{elem_col}"].values
        s = comp[f"{s_key}_{elem_col}"].values
        mask = pd.notna(p) & pd.notna(s)
        px, sx = p[mask], s[mask]

        if len(px) < 2:
            ax.text(0.5, 0.5, "Insufficient data", ha="center",
                    va="center", transform=ax.transAxes, color="#999")
            ax.set_title(stage_lbl, fontsize=10)
            continue

        lo = min(px.min(), sx.min()) * 0.95
        hi = max(px.max(), sx.max()) * 1.05
        ax.plot([lo, hi], [lo, hi], "--", color="#999", lw=0.8, zorder=1,
                label="Perfect agreement")

        sc_colors = [C_DELTA_P if sx[i] > px[i] else C_DELTA_N
                     for i in range(len(px))]
        ecs = (["#FFD600" if sx[i] > px[i] else "white" for i in range(len(px))]
               if highlight_benefit else ["white"] * len(px))
        ax.scatter(px, sx, c=sc_colors, s=48, edgecolors=ecs,
                   linewidths=0.8, zorder=3, alpha=0.85)

        lot_labels = np.array(labels)[mask]
        for i, txt in enumerate(lot_labels):
            ax.annotate(txt, (px[i], sx[i]), fontsize=5.5,
                        xytext=(3, 3), textcoords="offset points", color="#555")

        slope, intercept, r, p_val, _ = sp_stats.linregress(px, sx)
        xfit = np.linspace(lo, hi, 50)
        ax.plot(xfit, slope * xfit + intercept, "-", color=stage_colors[idx],
                lw=1.2, alpha=0.7,
                label=(f"Fit: y = {slope:.2f}x {'+' if intercept >= 0 else '−'} "
                       f"{abs(intercept):.0f}  (R² = {r**2:.3f})"))

        ax.set_xlim(lo, hi); ax.set_ylim(lo, hi)
        ax.set_aspect("equal", adjustable="box")
        ax.set_xlabel(f"Penfold  ({unit})", fontsize=8)
        ax.set_ylabel(f"Sinchi  ({unit})", fontsize=8)
        ax.set_title(f"{stage_lbl}  (n={int(mask.sum())})", fontsize=10)
        ax.legend(fontsize=6.5, loc="upper left", framealpha=0.9)

    fig.suptitle(f"1∶1 Correlation — {unit}", fontweight="bold", y=1.01)
    fig.tight_layout()
    return fig


# ═══════════════════════════════════════════════════════════════════════
# CHART: BLAND-ALTMAN
# ═══════════════════════════════════════════════════════════════════════
def chart_bland_altman(comp, elem_col, unit, labels):
    fig, axes = plt.subplots(1, 3, figsize=(13.5, 4))
    for idx, (stage_lbl, p_key, s_key, _, _) in enumerate(STAGES):
        ax = axes[idx]
        p = comp[f"{p_key}_{elem_col}"].values
        s = comp[f"{s_key}_{elem_col}"].values
        mask = pd.notna(p) & pd.notna(s)
        px, sx = p[mask], s[mask]

        if len(px) < 3:
            ax.text(0.5, 0.5, "Insufficient data", ha="center",
                    va="center", transform=ax.transAxes, color="#999")
            ax.set_title(stage_lbl, fontsize=10)
            continue

        means = (px + sx) / 2
        diffs = sx - px
        md = np.mean(diffs)
        sd = np.std(diffs, ddof=1)

        ax.scatter(means, diffs, s=40,
                   c=[C_DELTA_P if d > 0 else C_DELTA_N for d in diffs],
                   alpha=0.8, zorder=3, edgecolors="white", linewidths=0.5)
        ax.axhline(md, color=C_SINCHI, lw=1, ls="-",
                   label=f"Mean Δ = {md:+.1f}")
        ax.axhline(md + 1.96*sd, color="#999", lw=0.8, ls="--",
                   label=f"+1.96 SD = {md+1.96*sd:+.1f}")
        ax.axhline(md - 1.96*sd, color="#999", lw=0.8, ls="--",
                   label=f"−1.96 SD = {md-1.96*sd:+.1f}")
        ax.axhline(0, color="black", lw=0.4)

        lot_labels = np.array(labels)[mask]
        for i, txt in enumerate(lot_labels):
            ax.annotate(txt, (means[i], diffs[i]), fontsize=5.5,
                        xytext=(3, 3), textcoords="offset points", color="#555")

        ax.set_xlabel(f"Mean ({unit})", fontsize=8)
        ax.set_ylabel(f"Difference (S − P)  ({unit})", fontsize=8)
        ax.set_title(f"{stage_lbl}  (n={int(mask.sum())})", fontsize=10)
        ax.legend(fontsize=6.5, loc="upper right", framealpha=0.9)

    fig.suptitle(f"Bland–Altman agreement — {unit}", fontweight="bold", y=1.01)
    fig.tight_layout()
    return fig


# ═══════════════════════════════════════════════════════════════════════
# CHART: DELTA TIME SERIES + CUMULATIVE SUM
# ═══════════════════════════════════════════════════════════════════════
def chart_delta_timeseries(comp, elem_col, unit, labels, pct_mode=False):
    n = len(labels)
    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(max(7, n * 0.55 + 2), 5.5),
        gridspec_kw={"hspace": 0.42},
    )
    x = np.arange(n)
    stage_styles = [
        ("Natural",   "Natural_Penfold",  "Natural_Sinchi",  "#7E57C2", "o"),
        ("Prepared",  "Prepared_Penfold", "Prepared_Sinchi", "#26A69A", "s"),
        ("UK finals", "UK_Penfold",       "UK_Sinchi",       "#EF6C00", "^"),
    ]

    for lbl, pk, sk, col, mkr in stage_styles:
        p = comp[f"{pk}_{elem_col}"].values
        s = comp[f"{sk}_{elem_col}"].values
        d = delta_values(p, s, pct_mode)
        ax1.plot(x, d, f"{mkr}-", color=col, ms=5, lw=1.2,
                 label=lbl, alpha=0.85, zorder=3)

    ax1.axhline(0, color="black", lw=0.5, zorder=1)
    ax1.fill_between(x, 0, [999]*n, alpha=0.03, color=C_SINCHI, zorder=0)
    ax1.fill_between(x, 0, [-999]*n, alpha=0.03, color=C_PENFOLD, zorder=0)
    d_unit = delta_unit(unit, pct_mode)
    ax1.set_title(f"Δ chronological — {d_unit}", pad=6)
    ax1.set_ylabel(delta_ylabel(pct_mode))
    ax1.set_xticks(x)
    ax1.set_xticklabels(safe_labels(labels), rotation=45, ha="right")
    ax1.legend(fontsize=7, loc="upper left", framealpha=0.92)
    ax1.text(0.99, 0.97, "Above zero → Sinchi higher", fontsize=6.5,
             transform=ax1.transAxes, ha="right", va="top",
             color=C_SINCHI, style="italic")

    # S-Side delta overlay on ax1 (vs Penfold UK)
    if f"S-Side_{elem_col}" in comp.columns:
        ss_data  = comp[f"S-Side_{elem_col}"].values
        uk_p     = comp[f"UK_Penfold_{elem_col}"].values
        ss_delta = delta_values(uk_p, ss_data, pct_mode)
        if int(pd.notna(ss_delta).sum()) > 0:
            ax1.plot(x, ss_delta, "D", color=C_SSIDE, ms=6,
                     markeredgecolor="white", ls=":", lw=1.5,
                     label="S-Side Δ vs Penfold UK", zorder=4)
            ax1.legend(fontsize=7, loc="upper left", framealpha=0.92)

    # Cumulative sum panel
    for lbl, pk, sk, col, _ in stage_styles:
        p = comp[f"{pk}_{elem_col}"].values
        s = comp[f"{sk}_{elem_col}"].values
        d = delta_values(p, s, pct_mode)
        d_filled = np.where(pd.notna(d), d, 0)
        cs = np.cumsum(d_filled)
        ax2.plot(x, cs, "-", color=col, lw=1.5, label=lbl, alpha=0.85)
        ax2.fill_between(x, 0, cs, alpha=0.08, color=col)

    ax2.axhline(0, color="black", lw=0.5)
    ax2.set_title("Cumulative Δ  (upward slope = systematic Sinchi inflation)",
                  fontsize=8.5, fontweight="normal", color="#555", loc="left")
    ax2.set_ylabel(f"Cumulative Δ ({d_unit})")
    ax2.set_xticks(x)
    ax2.set_xticklabels(safe_labels(labels), rotation=45, ha="right")
    ax2.legend(fontsize=7, loc="upper left", framealpha=0.92)
    fig.tight_layout()
    return fig


# ═══════════════════════════════════════════════════════════════════════
# CHART: PHYSICAL IMPACT  (extra payable oz / tonnes at UK finals)
# ═══════════════════════════════════════════════════════════════════════
def chart_physical_impact(fin_df):
    lots = fin_df[fin_df["Extra_Ag_oz"].notna()].copy()
    if lots.empty:
        fig, ax = plt.subplots(figsize=(8, 3))
        ax.text(0.5, 0.5, "No UK finals data with DMT available", ha="center",
                va="center", transform=ax.transAxes)
        return fig

    n = len(lots)
    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(max(7, n * 0.65 + 2), 7),
        height_ratios=[1, 1], gridspec_kw={"hspace": 0.55},
    )
    x = np.arange(n)

    # ── Panel 1: Extra payable Ag troy ounces ──────────────────────────
    ag_vals = lots["Extra_Ag_oz"].values
    colors_ag = [C_DELTA_P if v > 0 else C_DELTA_N for v in ag_vals]
    ax1.bar(x, ag_vals, 0.55, color=colors_ag, alpha=0.8, zorder=3)
    ax1.axhline(0, color="black", lw=0.5, zorder=2)
    ax1.set_title(
        "Extra payable silver per lot — UK finals\n"
        "(positive = Sinchi's result inflates the averaged payment basis)",
        pad=6)
    ax1.set_ylabel("Extra payable troy ounces (Ag)")
    for xi, v in zip(x, ag_vals):
        if pd.notna(v) and v != 0:
            ax1.text(xi, v + np.sign(v) * abs(v) * 0.04,
                     f"{v:+,.1f}", ha="center",
                     va="bottom" if v >= 0 else "top",
                     fontsize=7, color="#222", zorder=5)
    total_ag = np.nansum(ag_vals)
    ax1.text(0.98, 0.93,
             f"NET TOTAL:  {total_ag:+,.1f} oz",
             transform=ax1.transAxes, fontsize=10, fontweight="bold",
             ha="right", va="top",
             color=C_DELTA_P if total_ag > 0 else C_DELTA_N,
             bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="#ccc"))
    dmt_vals = lots["DMT"].values
    xlbls_ag = [f"{tr}\n{d:.0f} t" if pd.notna(d) else str(tr)
                for tr, d in zip(lots["TR"].tolist(), dmt_vals)]
    ax1.set_xticks(x)
    ax1.set_xticklabels(xlbls_ag, rotation=45, ha="right")
    ax1.text(0.0, 1.015,
             "Contract: avg of both chains, deduct 1.5 oz/TM, pay 95 %.  "
             "Bar = (Δ ÷ 2) × 0.95 / 31.1 × DMT",
             transform=ax1.transAxes, fontsize=7, style="italic", color="#666")

    # ── Panel 2: Extra payable Pb tonnes ───────────────────────────────
    lots_pb = fin_df[fin_df["Extra_Pb_t"].notna()].copy()
    if lots_pb.empty:
        ax2.text(0.5, 0.5, "No Pb data", ha="center", va="center",
                 transform=ax2.transAxes, color="#999")
    else:
        n_pb = len(lots_pb)
        x_pb = np.arange(n_pb)
        pb_vals = lots_pb["Extra_Pb_t"].values
        colors_pb = [C_DELTA_P if v > 0 else C_DELTA_N for v in pb_vals]
        ax2.bar(x_pb, pb_vals, 0.55, color=colors_pb, alpha=0.8, zorder=3)
        ax2.axhline(0, color="black", lw=0.5, zorder=2)
        ax2.set_title(
            "Extra payable lead per lot — UK finals\n"
            "(positive = Sinchi's result inflates the averaged payment basis)",
            pad=6)
        ax2.set_ylabel("Extra payable tonnes (Pb content)")
        for xi, v in zip(x_pb, pb_vals):
            if pd.notna(v) and v != 0:
                ax2.text(xi, v + np.sign(v) * abs(v) * 0.04,
                         f"{v:+.3f}", ha="center",
                         va="bottom" if v >= 0 else "top",
                         fontsize=7, color="#222", zorder=5)
        total_pb = np.nansum(pb_vals)
        ax2.text(0.98, 0.93,
                 f"NET TOTAL:  {total_pb:+,.3f} t",
                 transform=ax2.transAxes, fontsize=10, fontweight="bold",
                 ha="right", va="top",
                 color=C_DELTA_P if total_pb > 0 else C_DELTA_N,
                 bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="#ccc"))
        dmt_pb = lots_pb["DMT"].values
        xlbls_pb = [f"{tr}\n{d:.0f} t" if pd.notna(d) else str(tr)
                    for tr, d in zip(lots_pb["TR"].tolist(), dmt_pb)]
        ax2.set_xticks(x_pb)
        ax2.set_xticklabels(xlbls_pb, rotation=45, ha="right")
        ax2.text(0.0, 1.015,
                 "Contract: avg of both chains, deduct 3 units, pay 95 % "
                 "(only if Pb > 10 %).  Bar = (Δ ÷ 2) / 100 × 0.95 × DMT",
                 transform=ax2.transAxes, fontsize=7, style="italic", color="#666")

    fig.tight_layout()
    return fig


# ═══════════════════════════════════════════════════════════════════════
# CHART: SUMMARY HORIZONTAL BARS
# ═══════════════════════════════════════════════════════════════════════
def chart_summary_bars(comp):
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.5))
    stage_labels = ["Natural\n(SpectrAA vs\nSavantAA)",
                    "Prepared\n(Castro vs\nConde)",
                    "UK finals\n(Penfold chain\nvs Sinchi chain)"]
    stage_keys = [("Natural_Penfold",  "Natural_Sinchi"),
                  ("Prepared_Penfold", "Prepared_Sinchi"),
                  ("UK_Penfold",       "UK_Sinchi")]

    for ax_i, (elem_col, title) in enumerate(
            [("Ag g", "Silver (Ag)"), ("Pb %", "Lead (Pb)")]):
        pcts = []
        for pk, sk in stage_keys:
            p = comp[f"{pk}_{elem_col}"]
            s = comp[f"{sk}_{elem_col}"]
            m = pd.notna(p) & pd.notna(s)
            if m.sum() == 0:
                pcts.append(0)
            else:
                diffs = s[m].values - p[m].values
                pcts.append((diffs > 0).sum() / len(diffs) * 100)
        y    = np.arange(3)
        cols = [C_SINCHI if p > 55 else C_NEUTRAL if p > 45 else C_PENFOLD
                for p in pcts]
        axes[ax_i].barh(y, pcts, color=cols, alpha=0.82, height=0.55)
        axes[ax_i].axvline(50, color="black", lw=0.7, ls="--", alpha=0.4)
        axes[ax_i].set_xlim(0, 110)
        axes[ax_i].set_yticks(y)
        axes[ax_i].set_yticklabels(stage_labels, fontsize=8)
        axes[ax_i].set_xlabel("% of lots where Sinchi reports higher", fontsize=8)
        axes[ax_i].set_title(title, fontsize=10)
        for i, p in enumerate(pcts):
            axes[ax_i].text(p + 1.5, i, f"{p:.0f} %",
                            va="center", fontsize=9, fontweight="bold")
    fig.suptitle("Bias summary — share of lots where Sinchi result exceeds Penfold",
                 fontweight="bold", y=1.02)
    fig.tight_layout()
    return fig


# ═══════════════════════════════════════════════════════════════════════
# CHART: STAGE GRADIENT  (bias narrows from Natural → Prepared → UK)
# ═══════════════════════════════════════════════════════════════════════
def chart_stage_gradient(comp):
    """
    Arrow/bar chart showing how mean bias changes across stages.
    This is the central evidence chart: large bias at Bolivia level
    that disappears at independent UK labs = manipulation at source.
    """
    stage_labels = ["Natural\n(Bolivia — unprocessed)", "Prepared\n(Bolivia — processed)",
                    "UK Finals\n(independent labs)"]
    stage_keys = [("Natural_Penfold", "Natural_Sinchi"),
                  ("Prepared_Penfold", "Prepared_Sinchi"),
                  ("UK_Penfold", "UK_Sinchi")]
    stage_colors = ["#7E57C2", "#26A69A", "#EF6C00"]

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5))

    for ax_i, (elem_col, title, unit) in enumerate(
            [("Ag g", "Silver (Ag)", "g/TM"), ("Pb %", "Lead (Pb)", "%")]):
        means, cis, ns, pct_higher = [], [], [], []
        for pk, sk in stage_keys:
            p = comp[f"{pk}_{elem_col}"]
            s = comp[f"{sk}_{elem_col}"]
            m = pd.notna(p) & pd.notna(s)
            d = (s[m].values - p[m].values)
            n = len(d)
            ns.append(n)
            if n >= 2:
                mn = np.mean(d)
                se = np.std(d, ddof=1) / np.sqrt(n)
                ci = sp_stats.t.interval(0.95, df=n-1, loc=mn, scale=se)
                means.append(mn)
                cis.append((mn - ci[0], ci[1] - mn))
                pct_higher.append((d > 0).sum() / n * 100)
            else:
                means.append(np.nan)
                cis.append((0, 0))
                pct_higher.append(np.nan)

        ax = axes[ax_i]
        y = np.arange(3)
        ci_arr = np.array(cis).T
        ax.barh(y, means, 0.5, color=stage_colors, alpha=0.82, zorder=3)
        ax.errorbar(means, y, xerr=ci_arr, fmt="none",
                    color="black", capsize=5, lw=1.2, zorder=4)
        ax.axvline(0, color="black", lw=0.8, ls="--")

        # Pre-compute where every annotation will sit so we can size the
        # x-axis correctly.  The label is placed *past the end of the CI
        # error bar* (not just past the mean) so it never sits on top of
        # the CI whiskers.
        ci_upper = [means[i] + cis[i][1] if pd.notna(means[i]) else np.nan
                    for i in range(3)]
        ci_lower = [means[i] - cis[i][0] if pd.notna(means[i]) else np.nan
                    for i in range(3)]
        # Small constant pad in data units — scales with the widest bar
        max_mag = max([abs(v) for v in ci_upper + ci_lower if pd.notna(v)]
                      or [1.0])
        gap = max(max_mag * 0.03, 0.5)

        for i, (mn, n, pct) in enumerate(zip(means, ns, pct_higher)):
            if pd.notna(mn):
                if mn >= 0:
                    anchor = ci_upper[i] + gap
                    ha = "left"
                else:
                    anchor = ci_lower[i] - gap
                    ha = "right"
                ax.text(anchor, i,
                        f"{mn:+.1f} {unit}  ({pct:.0f}% ↑, n={n})",
                        va="center", ha=ha, fontsize=8, fontweight="bold",
                        color="#222")

        ax.set_yticks(y)
        ax.set_yticklabels(stage_labels, fontsize=9)
        ax.set_xlabel(f"Mean Δ (Sinchi − Penfold)  [{unit}]", fontsize=9)
        ax.set_title(title, fontsize=11)
        ax.invert_yaxis()  # Natural on top

        # Extend x-axis so the annotation text (which starts past the CI
        # end and runs outward) has enough room to be drawn in full.
        pos_bounds = [ci_upper[i] for i in range(3)
                      if pd.notna(means[i]) and means[i] >= 0]
        neg_bounds = [ci_lower[i] for i in range(3)
                      if pd.notna(means[i]) and means[i] <  0]
        max_pos = max(pos_bounds) if pos_bounds else 0
        min_neg = min(neg_bounds) if neg_bounds else 0
        # Label text runs ~the same number of data units as the widest bar,
        # so pad by ~100 % of the largest CI magnitude on the label side.
        pad_right = max_mag * 1.05 if pos_bounds else max_mag * 0.15
        pad_left  = max_mag * 1.05 if neg_bounds else max_mag * 0.15
        ax.set_xlim(min_neg - pad_left, max_pos + pad_right)

        # Shade the "Sinchi benefits" zone
        xlim = ax.get_xlim()
        ax.axvspan(0, xlim[1], alpha=0.04, color=C_SINCHI, zorder=0)
        ax.set_xlim(xlim)

    fig.suptitle(
        "Bias gradient: mean delta narrows from Bolivia to UK\n"
        "(error bars = 95% CI of mean)",
        fontweight="bold", y=1.03)
    fig.tight_layout()
    return fig


# ═══════════════════════════════════════════════════════════════════════
# CHART: DELTA HEATMAP
# ═══════════════════════════════════════════════════════════════════════
def chart_heatmap(comp, labels, stage_idx=2, pct_mode=False):
    _, p_key, s_key, _, _ = STAGES[stage_idx]
    stage_name = STAGES[stage_idx][0]
    elems = ["Ag g", "Pb %", "As %", "Sb %", "Sn %", "Bi %", "Zn %"]
    n_lots, n_elem = len(labels), len(elems)

    data = np.full((n_lots, n_elem), np.nan)
    for i, (_, row) in enumerate(comp.iterrows()):
        for j, e in enumerate(elems):
            p = row.get(f"{p_key}_{e}", np.nan)
            s = row.get(f"{s_key}_{e}", np.nan)
            if pd.notna(p) and pd.notna(s):
                data[i, j] = ((s - p) / abs(p) * 100
                              if (pct_mode and p != 0) else s - p)

    fig, ax = plt.subplots(figsize=(7, max(4, n_lots * 0.35 + 1)))
    vmax = np.nanmax(np.abs(data)) if not np.all(np.isnan(data)) else 1
    im = ax.imshow(data, aspect="auto", cmap="RdBu_r",
                   vmin=-vmax, vmax=vmax, interpolation="nearest")
    ax.set_xticks(np.arange(n_elem))
    ax.set_xticklabels(elems, fontsize=8)
    ax.set_yticks(np.arange(n_lots))
    ax.set_yticklabels(safe_labels(labels), fontsize=7)
    d_lbl = "% Δ" if pct_mode else "Δ"
    ax.set_title(f"Delta heatmap ({d_lbl}) — {stage_name}\n"
                 "(red = Sinchi higher, blue = Penfold higher)",
                 fontsize=10, pad=8)
    cb = fig.colorbar(im, ax=ax, fraction=0.03, pad=0.04)
    cb.set_label(f"{d_lbl} (Sinchi − Penfold)", fontsize=8)

    for i in range(n_lots):
        for j in range(n_elem):
            v = data[i, j]
            if pd.notna(v):
                fmt = f"{v:.1f}" if abs(v) >= 1 else f"{v:.2f}"
                ax.text(j, i, fmt, ha="center", va="center", fontsize=5.5,
                        color="white" if abs(v) > vmax * 0.55 else "black")
    fig.tight_layout()
    return fig


# ═══════════════════════════════════════════════════════════════════════
# CHART: COMPACT ALL-STAGES HEATMAP  (Ag & Pb × 3 stages, all lots)
# ═══════════════════════════════════════════════════════════════════════
def chart_compact_heatmap(comp, labels):
    """
    Compact heatmap: rows = lots, columns = Ag & Pb at each stage.
    Shows the red pattern at a glance — Sinchi consistently higher at
    Bolivia level, mixed at UK.
    """
    col_defs = [
        ("Ag\nNatural",  "Natural_Penfold",  "Natural_Sinchi",  "Ag g"),
        ("Ag\nPrepared", "Prepared_Penfold", "Prepared_Sinchi", "Ag g"),
        ("Ag\nUK",       "UK_Penfold",       "UK_Sinchi",       "Ag g"),
        ("Pb\nNatural",  "Natural_Penfold",  "Natural_Sinchi",  "Pb %"),
        ("Pb\nPrepared", "Prepared_Penfold", "Prepared_Sinchi", "Pb %"),
        ("Pb\nUK",       "UK_Penfold",       "UK_Sinchi",       "Pb %"),
    ]
    n_lots = len(labels)
    n_cols = len(col_defs)
    data = np.full((n_lots, n_cols), np.nan)

    for i, (_, row) in enumerate(comp.iterrows()):
        for j, (_, pk, sk, elem) in enumerate(col_defs):
            pv = row.get(f"{pk}_{elem}", np.nan)
            sv = row.get(f"{sk}_{elem}", np.nan)
            if pd.notna(pv) and pd.notna(sv) and pv != 0:
                data[i, j] = (sv - pv) / abs(pv) * 100   # always % relative

    fig, ax = plt.subplots(figsize=(8, max(4, n_lots * 0.32 + 1)))
    vmax = np.nanmax(np.abs(data)) if not np.all(np.isnan(data)) else 1
    im = ax.imshow(data, aspect="auto", cmap="RdBu_r",
                   vmin=-vmax, vmax=vmax, interpolation="nearest")
    ax.set_xticks(np.arange(n_cols))
    ax.set_xticklabels([c[0] for c in col_defs], fontsize=8)
    ax.set_yticks(np.arange(n_lots))
    ax.set_yticklabels(safe_labels(labels), fontsize=7.5)

    # Stage separator lines
    ax.axvline(2.5, color="black", lw=1.5, alpha=0.4)

    for i in range(n_lots):
        for j in range(n_cols):
            v = data[i, j]
            if pd.notna(v):
                fmt = f"{v:+.1f}" if abs(v) >= 1 else f"{v:+.2f}"
                ax.text(j, i, fmt, ha="center", va="center", fontsize=5.5,
                        color="white" if abs(v) > vmax * 0.5 else "black")

    cb = fig.colorbar(im, ax=ax, fraction=0.025, pad=0.03)
    cb.set_label("% Δ relative to Penfold", fontsize=8)
    ax.set_title(
        "All lots × all stages — % relative delta (Sinchi − Penfold)\n"
        "Red = Sinchi higher (benefits Sinchi)  ·  Blue = Penfold higher",
        fontsize=10, pad=8)
    fig.tight_layout()
    return fig


# ═══════════════════════════════════════════════════════════════════════
# CHART: IMPACT HEATMAP  (delta × DMT for UK finals)
# ═══════════════════════════════════════════════════════════════════════
def chart_impact_heatmap(comp, labels):
    """
    Heatmap where cell colour = delta × DMT at UK finals.
    Makes the point: even if most lots are blue (Penfold higher),
    the few red lots are so large they dominate the total impact.
    """
    elems = [("Ag g", "g·t"), ("Pb %", "%·t")]
    pk_keys = ["UK_Penfold", "UK_Sinchi"]
    n_lots = len(labels)

    data = np.full((n_lots, len(elems)), np.nan)
    annot = np.full((n_lots, len(elems)), "", dtype=object)

    for i, (_, row) in enumerate(comp.iterrows()):
        dmt = row.get("DMT", np.nan)
        for j, (elem, unit) in enumerate(elems):
            pv = row.get(f"UK_Penfold_{elem}", np.nan)
            sv = row.get(f"UK_Sinchi_{elem}", np.nan)
            if pd.notna(pv) and pd.notna(sv) and pd.notna(dmt):
                delta = sv - pv
                impact = delta * float(dmt)
                data[i, j] = impact
                annot[i, j] = f"{impact:+,.0f}"

    fig, ax = plt.subplots(figsize=(5, max(4, n_lots * 0.32 + 1)))
    vmax = np.nanmax(np.abs(data)) if not np.all(np.isnan(data)) else 1
    im = ax.imshow(data, aspect="auto", cmap="RdBu_r",
                   vmin=-vmax, vmax=vmax, interpolation="nearest")
    ax.set_xticks(np.arange(len(elems)))
    ax.set_xticklabels(["Ag impact\n(g·t)", "Pb impact\n(%·t)"], fontsize=9)
    ax.set_yticks(np.arange(n_lots))

    # Labels with DMT
    dmt_vals = comp["DMT"].values if "DMT" in comp.columns else [np.nan]*n_lots
    ylabels = [f"{lbl}  ({dmt:.0f} t)" if pd.notna(dmt) else lbl
               for lbl, dmt in zip(labels, dmt_vals)]
    ax.set_yticklabels(ylabels, fontsize=7.5)

    for i in range(n_lots):
        for j in range(len(elems)):
            txt = annot[i, j]
            if txt:
                v = data[i, j]
                text_color = "white" if abs(v) > vmax * 0.45 else "black"
                ax.text(j, i, txt, ha="center", va="center",
                        fontsize=7.5, color=text_color, fontweight="bold")

    cb = fig.colorbar(im, ax=ax, fraction=0.04, pad=0.03)
    cb.set_label("Δ × DMT  (red = Sinchi inflates)", fontsize=8)
    ax.set_title(
        "UK finals — impact heatmap (delta × DMT)\n"
        "Few large red cells dominate even if most are blue",
        fontsize=10, pad=8)

    # Net totals below
    ag_total = np.nansum(data[:, 0])
    pb_total = np.nansum(data[:, 1])
    ax.text(0.5, -0.08,
            f"Net Ag: {ag_total:+,.0f} g·t    Net Pb: {pb_total:+,.2f} %·t",
            transform=ax.transAxes, fontsize=9, ha="center",
            fontweight="bold",
            color=C_SINCHI if ag_total > 0 else C_PENFOLD)

    fig.tight_layout()
    return fig


# ═══════════════════════════════════════════════════════════════════════
# CHART: BOX PLOTS
# ═══════════════════════════════════════════════════════════════════════
def chart_boxplots(comp, elem_col, unit, pct_mode=False):
    fig, ax = plt.subplots(figsize=(6, 3.8))
    box_data, box_labels = [], []
    for lbl, pk, sk, _, _ in STAGES:
        p = comp[f"{pk}_{elem_col}"].values
        s = comp[f"{sk}_{elem_col}"].values
        mask = pd.notna(p) & pd.notna(s)
        if mask.sum():
            d = delta_values(p[mask], s[mask], pct_mode)
            d_clean = d[pd.notna(d)]
            if len(d_clean):
                box_data.append(d_clean)
                box_labels.append(f"{lbl}\n(n={int(mask.sum())})")

    if not box_data:
        ax.text(0.5, 0.5, "No data", ha="center", va="center",
                transform=ax.transAxes)
        return fig

    bp = ax.boxplot(box_data, labels=box_labels, patch_artist=True,
                    widths=0.45, showmeans=True,
                    meanprops=dict(marker="D", markerfacecolor=C_SINCHI,
                                   markeredgecolor="white", markersize=5))
    colors_bp = ["#B39DDB", "#80CBC4", "#FFCC80"]
    for patch, c in zip(bp["boxes"], colors_bp):
        patch.set_facecolor(c); patch.set_alpha(0.7)
    ax.axhline(0, color="black", lw=0.6, ls="--")
    d_unit = delta_unit(unit, pct_mode)
    ax.set_ylabel(f"Δ  (Sinchi − Penfold)  {d_unit}")
    ax.set_title(f"Distribution of deltas — {d_unit}", pad=6)
    fig.tight_layout()
    return fig


# ═══════════════════════════════════════════════════════════════════════
# REGIME-CHANGE HELPERS
# ═══════════════════════════════════════════════════════════════════════
def pettitt_test(x):
    """
    Non-parametric Pettitt (1979) change-point test.
    Tests H0: no change point vs H1: mean shift at some unknown time k.
    Returns (change_point_idx, K_statistic, approx_p_value).
    Note: p-value approximation is conservative for n < 20.
    """
    from scipy.stats import rankdata
    x = np.asarray(x, dtype=float)
    n = len(x)
    R = rankdata(x)
    Ut = np.zeros(n + 1)
    for t in range(1, n + 1):
        Ut[t] = 2.0 * np.sum(R[:t]) - t * (n + 1)
    abs_Ut = np.abs(Ut[1:n])           # positions 1..n-1
    K      = np.max(abs_Ut)
    cp_idx = int(np.argmax(abs_Ut))    # 0-based index in x (split AFTER this position)
    p_val  = min(1.0, 2.0 * np.exp(-6.0 * K**2 / (n**3 + n**2)))
    return cp_idx + 1, K, p_val        # cp_idx+1 = first element of "late" group


def regime_split_stats(d_valid, cp_idx):
    """Return paired dicts of stats for early and late groups at cp_idx."""
    early = d_valid[:cp_idx]
    late  = d_valid[cp_idx:]
    results = {}
    for label, arr in [("early", early), ("late", late)]:
        if len(arr) >= 2:
            t, p = sp_stats.ttest_1samp(arr, 0)
            cohen = np.mean(arr) / np.std(arr, ddof=1) if np.std(arr, ddof=1) > 0 else np.nan
        else:
            t, p, cohen = np.nan, np.nan, np.nan
        results[label] = {
            "n":      len(arr),
            "mean":   round(float(np.mean(arr)), 1) if len(arr) else np.nan,
            "std":    round(float(np.std(arr, ddof=1)), 1) if len(arr) >= 2 else np.nan,
            "pct_pos": round((arr > 0).sum() / len(arr) * 100, 1) if len(arr) else np.nan,
            "t_pval": p,
            "cohen_d": round(cohen, 3) if pd.notna(cohen) else np.nan,
        }
    # Between-group test
    if len(early) >= 2 and len(late) >= 2:
        t2, p2 = sp_stats.ttest_ind(early, late, equal_var=False)
        results["between_p"] = p2
    else:
        results["between_p"] = np.nan
    return results


# ─── CHART: UK finals timeline + CUSUM ────────────────────────────────
def chart_uk_regime_change(comp, elem_col, unit, labels,
                           cp_lot_label=None, pct_mode=False):
    """
    Three-panel chart for UK finals regime-change analysis:
      1. Delta per lot with rolling mean and linear trend
      2. One-sided CUSUM (detects sustained upward shift)
      3. Contract-level mean delta bar chart
    cp_lot_label: if supplied, draws a vertical change-point line.
    """
    pk, sk = "UK_Penfold", "UK_Sinchi"
    p_arr = comp[f"{pk}_{elem_col}"].values
    s_arr = comp[f"{sk}_{elem_col}"].values
    d     = delta_values(p_arr, s_arr, pct_mode)
    n     = len(labels)
    x     = np.arange(n)
    mask  = pd.notna(d)

    # Contract-level means
    comp2 = comp.copy(); comp2["_d"] = d
    by_contract = (comp2.groupby("Contract")["_d"]
                   .agg(mean="mean", count="count", sem=lambda v: v.std(ddof=1)/np.sqrt(len(v)))
                   .reset_index())

    fig, (ax1, ax2, ax3) = plt.subplots(
        3, 1, figsize=(max(9, n * 0.60 + 2), 9),
        gridspec_kw={"hspace": 0.52},
    )

    # ── Panel 1: per-lot delta ─────────────────────────────────────────
    bar_colors = [C_DELTA_P if (pd.notna(v) and v > 0) else C_DELTA_N for v in d]
    ax1.bar(x[mask], d[mask],
            [0.55]*int(mask.sum()),
            color=[c for c, m in zip(bar_colors, mask) if m],
            alpha=0.75, zorder=3)
    ax1.axhline(0, color="black", lw=0.5, zorder=2)
    # Value labels
    for xi, dv in zip(x[mask], d[mask]):
        if pd.notna(dv):
            fmt = f"{dv:+.1f}" if pct_mode else f"{dv:+.0f}"
            ax1.text(xi, dv + (abs(dv)*0.04 + 0.5)*np.sign(dv), fmt,
                     ha="center", va="bottom" if dv >= 0 else "top",
                     fontsize=6, color="#222", zorder=5)

    # Rolling mean (window 3)
    d_s = pd.Series(d)
    roll = d_s.rolling(3, min_periods=2, center=True).mean()
    ax1.plot(x, roll.values, "o--", color="#7E57C2", ms=4, lw=1.3,
             alpha=0.85, label="Rolling mean (3-lot window)", zorder=4)

    # Linear trend over valid points
    x_v = x[mask].astype(float)
    d_v = d[mask]
    if len(x_v) >= 4:
        slope, intercept, r_val, p_trend, _ = sp_stats.linregress(x_v, d_v)
        xfit = np.linspace(x_v[0], x_v[-1], 100)
        ax1.plot(xfit, slope * xfit + intercept, "-",
                 color="#EF6C00", lw=1.8, alpha=0.85,
                 label=(f"Linear trend: {slope:+.1f} / lot  "
                        f"(p = {p_trend:.3f}{'*' if p_trend<0.05 else ''})"),
                 zorder=5)

    # Change-point line
    if cp_lot_label and cp_lot_label in labels:
        cp_x = labels.index(cp_lot_label) - 0.5
        ax1.axvline(cp_x, color="#FFD600", lw=1.8, ls="--", zorder=6,
                    label=f"Change-point boundary ({cp_lot_label})")

    d_unit = delta_unit(unit, pct_mode)
    ax1.set_title(f"UK finals Ag delta per lot — {d_unit}", pad=6)
    ax1.set_ylabel(delta_ylabel(pct_mode))
    ax1.set_xticks(x)
    ax1.set_xticklabels(safe_labels(labels), rotation=45, ha="right")
    ax1.legend(fontsize=7, loc="upper left", framealpha=0.92)

    # Early vs late means annotation
    if cp_lot_label and cp_lot_label in labels:
        cp_i = labels.index(cp_lot_label)
        d_e = d[:cp_i]; d_l = d[cp_i:]
        m_e = np.nanmean(d_e) if pd.notna(d_e).sum() else np.nan
        m_l = np.nanmean(d_l) if pd.notna(d_l).sum() else np.nan
        ax1.axhline(m_e, xmax=cp_i/n, color=C_PENFOLD,
                    lw=1.2, ls=":", alpha=0.7)
        ax1.axhline(m_l, xmin=cp_i/n, color=C_SINCHI,
                    lw=1.2, ls=":", alpha=0.7)
        # Use data coordinates (no transform) — x midpoints in tick-position space
        x_early_mid = (cp_i - 1) / 2.0
        x_late_mid  = cp_i + (n - 1 - cp_i) / 2.0
        if pd.notna(m_e):
            ax1.text(max(0, x_early_mid), m_e,
                     f"early mean = {m_e:+.0f}",
                     fontsize=7, color=C_PENFOLD, ha="center", va="bottom")
        if pd.notna(m_l):
            ax1.text(min(n - 1, x_late_mid), m_l,
                     f"late mean = {m_l:+.0f}",
                     fontsize=7, color=C_SINCHI, ha="center", va="bottom")

    # ── Panel 2: one-sided CUSUM (S+) ─────────────────────────────────
    # Targets upward shift; k = 0.5 * historical sigma
    d_filled = np.where(mask, d, 0.0)
    sigma_est = np.nanstd(d[mask]) if mask.sum() >= 2 else 1.0
    k = 0.5 * sigma_est
    S_plus = np.zeros(n)
    S_minus = np.zeros(n)
    for i in range(1, n):
        S_plus[i]  = max(0.0, S_plus[i-1]  + d_filled[i] - k)
        S_minus[i] = max(0.0, S_minus[i-1] - d_filled[i] - k)

    ax2.plot(x, S_plus,  "-o", color=C_SINCHI,  ms=4, lw=1.4,
             label="CUSUM+ (upward shift detector)", zorder=3)
    ax2.plot(x, S_minus, "-s", color=C_PENFOLD, ms=4, lw=1.0,
             alpha=0.6, label="CUSUM− (downward shift)", zorder=3)

    # Decision threshold h = 5 * sigma
    h = 5.0 * sigma_est
    ax2.axhline(h, color="#FFD600", lw=1.3, ls="--",
                label=f"Alert threshold h = 5σ = {h:.0f}")
    ax2.axhline(0, color="black", lw=0.4)
    ax2.fill_between(x, 0, S_plus, alpha=0.10, color=C_SINCHI)

    if cp_lot_label and cp_lot_label in labels:
        ax2.axvline(labels.index(cp_lot_label) - 0.5,
                    color="#FFD600", lw=1.8, ls="--", zorder=6)

    ax2.set_title("One-sided CUSUM — persistent upward shift detector",
                  pad=6)
    ax2.set_ylabel("Cumulative score")
    ax2.set_xticks(x)
    ax2.set_xticklabels(safe_labels(labels), rotation=45, ha="right")
    ax2.legend(fontsize=7, loc="upper left", framealpha=0.92)
    ax2.text(0.99, 0.97,
             "CUSUM+ rising above threshold = sustained positive bias detected",
             transform=ax2.transAxes, fontsize=6.5, ha="right", va="top",
             color="#555", style="italic")

    # ── Panel 3: mean UK delta per contract ────────────────────────────
    by_contract_valid = by_contract[by_contract["count"] > 0]
    cx = np.arange(len(by_contract_valid))
    bar_c = [C_DELTA_P if v > 0 else C_DELTA_N
             for v in by_contract_valid["mean"].values]
    ax3.bar(cx, by_contract_valid["mean"].values, 0.55,
            color=bar_c, alpha=0.78, zorder=3)
    ax3.errorbar(cx, by_contract_valid["mean"].values,
                 yerr=by_contract_valid["sem"].values * 1.96,
                 fmt="none", color="black", capsize=4, lw=1.0, zorder=4)
    ax3.axhline(0, color="black", lw=0.5, zorder=2)
    ax3.set_title("Mean UK delta by contract (± 95 % CI of mean)",
                  pad=6)
    ax3.set_ylabel(f"Mean Δ ({d_unit})")
    ax3.set_xticks(cx)
    ax3.set_xticklabels(
        [f"{r['Contract']}\n(n={r['count']:.0f})"
         for _, r in by_contract_valid.iterrows()],
        rotation=0, fontsize=8,
    )
    for ci, (_, row) in enumerate(by_contract_valid.iterrows()):
        ax3.text(ci, row["mean"] + (4 if row["mean"] >= 0 else -4),
                 f"{row['mean']:+.0f}",
                 ha="center", va="bottom" if row["mean"] >= 0 else "top",
                 fontsize=8, fontweight="bold")

    fig.tight_layout()
    return fig


# ─── CHART: UK early-vs-late side-by-side ─────────────────────────────
def chart_uk_split_comparison(comp, labels, cp_lot_label,
                               elem_col="Ag g", unit="g/TM", pct_mode=False):
    """
    Side-by-side paired bar charts: UK delta before vs after the change point.
    Shows individual lot bars plus mean line, t-test p-value.
    """
    pk, sk = "UK_Penfold", "UK_Sinchi"
    p_arr = comp[f"{pk}_{elem_col}"].values
    s_arr = comp[f"{sk}_{elem_col}"].values
    d     = delta_values(p_arr, s_arr, pct_mode)
    mask  = pd.notna(d)

    cp_i = labels.index(cp_lot_label) if cp_lot_label in labels else len(labels)
    early_idx = [i for i in range(cp_i)  if mask[i]]
    late_idx  = [i for i in range(cp_i, len(labels)) if mask[i]]

    d_unit = delta_unit(unit, pct_mode)
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4.5),
                                    sharey=True)

    for ax, idx_list, period_name in [
        (ax1, early_idx, f"Early — up to {labels[cp_i-1]}"),
        (ax2, late_idx,  f"Recent — from {labels[cp_i]}"),
    ]:
        if not idx_list:
            ax.text(0.5, 0.5, "No data", ha="center",
                    va="center", transform=ax.transAxes)
            ax.set_title(period_name, fontsize=10)
            continue

        vals  = d[idx_list]
        xlabs = [labels[i] for i in idx_list]
        xx    = np.arange(len(vals))
        cols  = [C_DELTA_P if v > 0 else C_DELTA_N for v in vals]
        ax.bar(xx, vals, 0.55, color=cols, alpha=0.78, zorder=3)
        ax.axhline(0, color="black", lw=0.5, zorder=2)

        mn = float(np.mean(vals))
        ax.axhline(mn, color="#FF6F00", lw=1.6, ls="--",
                   label=f"Mean = {mn:+.0f} {d_unit}", zorder=4)

        if len(vals) >= 2:
            t_val, p_val = sp_stats.ttest_1samp(vals, 0)
            cohen = mn / np.std(vals, ddof=1)
            ann = (f"n = {len(vals)}\n"
                   f"Mean Δ = {mn:+.0f}\n"
                   f"t-test p = {p_val:.4f} {pval_stars(p_val)}\n"
                   f"Cohen's d = {cohen:.2f} ({cohen_label(cohen)})")
        else:
            ann = f"n = {len(vals)}\nMean Δ = {mn:+.0f}"

        ax.text(0.03, 0.97, ann, transform=ax.transAxes, fontsize=8,
                va="top", ha="left",
                bbox=dict(boxstyle="round,pad=0.4", fc="white",
                          ec="#ccc", alpha=0.92))
        ax.set_title(period_name, fontsize=10, pad=6)
        ax.set_ylabel(f"Δ ({d_unit})")
        ax.set_xticks(xx)
        ax.set_xticklabels(xlabs, rotation=45, ha="right")
        ax.legend(fontsize=7.5, loc="upper right", framealpha=0.9)

    fig.suptitle(
        f"UK finals {elem_col} delta — before vs after change point\n"
        f"Change point boundary: {cp_lot_label}",
        fontweight="bold", y=1.02,
    )
    fig.tight_layout()
    return fig


# ─── CHART: Outlier flag for UK finals ────────────────────────────────
def chart_uk_outlier_flags(comp, labels, elem_col="Ag g", unit="g/TM",
                            pct_mode=False):
    """
    Z-score chart: how many standard deviations each UK delta is from the
    historical mean, using only the 'baseline' (pre-change) distribution.
    Useful for identifying specific lots that are anomalous.
    """
    pk, sk = "UK_Penfold", "UK_Sinchi"
    p_arr = comp[f"{pk}_{elem_col}"].values
    s_arr = comp[f"{sk}_{elem_col}"].values
    d     = delta_values(p_arr, s_arr, pct_mode)
    n     = len(labels)
    mask  = pd.notna(d)

    # Baseline: all valid observations (robust estimate)
    d_valid = d[mask]
    mu    = float(np.median(d_valid))          # use median for robustness
    sigma = float(np.std(d_valid, ddof=1))
    z     = np.where(mask, (d - mu) / sigma, np.nan)

    fig, ax = plt.subplots(figsize=(max(8, n * 0.60 + 2), 3.8))
    x = np.arange(n)
    bar_colors = [C_DELTA_P if (pd.notna(z[i]) and z[i] > 0) else C_DELTA_N
                  for i in range(n)]
    ax.bar(x[mask], z[mask],
           [0.55]*int(mask.sum()),
           color=[c for c, m in zip(bar_colors, mask) if m],
           alpha=0.78, zorder=3)

    # ± 2σ and ± 3σ threshold lines
    for thresh, ls_, alpha_ in [(2, "--", 0.5), (3, "-", 0.8)]:
        ax.axhline( thresh, color=C_SINCHI,  lw=1.0, ls=ls_, alpha=alpha_,
                    label=f"+{thresh}σ" if thresh == 2 else None)
        ax.axhline(-thresh, color=C_PENFOLD, lw=1.0, ls=ls_, alpha=alpha_)

    ax.axhline(0, color="black", lw=0.5)
    ax.fill_between(x, -2, 2, alpha=0.05, color="#78909C", label="±2σ zone")

    # Annotate lots outside ±2σ
    for i in range(n):
        if pd.notna(z[i]) and abs(z[i]) > 2:
            ax.text(i, z[i] + (0.15 if z[i] > 0 else -0.15),
                    f"{labels[i]}\n({d[i]:+.0f})",
                    ha="center",
                    va="bottom" if z[i] > 0 else "top",
                    fontsize=6, color="#333",
                    bbox=dict(boxstyle="round,pad=0.2", fc="white",
                              ec="#ccc", alpha=0.85))

    ax.set_title(
        f"UK finals {elem_col} delta — z-score relative to median baseline\n"
        "Lots outside ±2σ are statistically anomalous",
        pad=6,
    )
    ax.set_ylabel("Z-score  (σ from baseline)")
    ax.set_xticks(x)
    ax.set_xticklabels(safe_labels(labels), rotation=45, ha="right")
    ax.legend(fontsize=7, loc="upper left", framealpha=0.92)
    d_unit = delta_unit(unit, pct_mode)
    ax.text(0.99, 0.98,
            f"Baseline: median = {mu:+.0f} {d_unit}, σ = {sigma:.0f} {d_unit}",
            transform=ax.transAxes, fontsize=7, ha="right", va="top",
            color="#555", style="italic")
    fig.tight_layout()
    return fig


# ═══════════════════════════════════════════════════════════════════════
# CHART: S-SIDE BENCHMARK
# ═══════════════════════════════════════════════════════════════════════
def chart_sside_benchmark(comp, elem_col, unit, labels):
    if f"S-Side_{elem_col}" not in comp.columns:
        fig, ax = plt.subplots(figsize=(8, 3))
        ax.text(0.5, 0.5, "No S-Side data", ha="center",
                va="center", transform=ax.transAxes)
        return fig

    mask = comp[f"S-Side_{elem_col}"].notna()
    sub  = comp[mask].copy()
    if sub.empty:
        fig, ax = plt.subplots(figsize=(8, 3))
        ax.text(0.5, 0.5, "No S-Side data", ha="center",
                va="center", transform=ax.transAxes)
        return fig

    slabels = sub["TR"].tolist()
    n = len(slabels)
    fig, (ax_abs, ax_d) = plt.subplots(
        2, 1, figsize=(max(7, n * 0.65 + 2), 8),
        gridspec_kw={"hspace": 0.52},
    )
    x = np.arange(n)
    w = 0.24

    _, p_key, s_key, p_lab, s_lab = STAGES[2]   # UK finals only
    uk_p = sub[f"{p_key}_{elem_col}"].values
    uk_s = sub[f"{s_key}_{elem_col}"].values
    ss   = sub[f"S-Side_{elem_col}"].values

    # ── Panel 1: absolute values ───────────────────────────────────────
    ax_abs.bar(x - w, uk_p, w, label=p_lab,            color=C_PENFOLD, alpha=0.8, zorder=3)
    ax_abs.bar(x,     uk_s, w, label=s_lab,             color=C_SINCHI,  alpha=0.8, zorder=3)
    ax_abs.bar(x + w, ss,   w, label="S-Side (China)", color=C_SSIDE,   alpha=0.8, zorder=3)

    ax_abs.set_title(f"S-Side benchmark vs UK finals — absolute values ({unit})", pad=6)
    ax_abs.set_ylabel(unit)
    ax_abs.set_xticks(x)
    ax_abs.set_xticklabels(slabels, rotation=45, ha="right")
    ax_abs.legend(fontsize=7.5, loc="upper right", framealpha=0.92)

    # ── Panel 2: deltas relative to S-Side ────────────────────────────
    # Δ = chain − S-Side  (positive = chain reports higher than S-Side)
    d_p = uk_p - ss   # Penfold UK minus S-Side
    d_s = uk_s - ss   # Sinchi UK minus S-Side
    ax_d.bar(x - w/2, d_p, w, label=f"{p_lab} − S-Side", color=C_PENFOLD, alpha=0.8, zorder=3)
    ax_d.bar(x + w/2, d_s, w, label=f"{s_lab} − S-Side",  color=C_SINCHI,  alpha=0.8, zorder=3)
    ax_d.axhline(0, color="black", lw=0.6, ls="--", zorder=2)

    m2 = pd.notna(uk_p) & pd.notna(ss)
    m3 = pd.notna(uk_s) & pd.notna(ss)
    if m2.sum():
        avg_vs_p = np.nanmean(d_p[m2])
        ax_d.axhline(avg_vs_p, color=C_PENFOLD, lw=1.2, ls=":", alpha=0.7)
        ax_d.text(n - 0.5, avg_vs_p, f"avg {avg_vs_p:+.1f}",
                  fontsize=7, color=C_PENFOLD, ha="right", va="bottom")
    if m3.sum():
        avg_vs_s = np.nanmean(d_s[m3])
        ax_d.axhline(avg_vs_s, color=C_SINCHI, lw=1.2, ls=":", alpha=0.7)
        ax_d.text(n - 0.5, avg_vs_s, f"avg {avg_vs_s:+.1f}",
                  fontsize=7, color=C_SINCHI, ha="right", va="top")

    ax_d.set_title(
        "Δ vs S-Side (independent benchmark)  —  positive = chain reports HIGHER than S-Side",
        pad=6,
    )
    ax_d.set_ylabel(f"Chain − S-Side  ({unit})")
    ax_d.set_xticks(x)
    ax_d.set_xticklabels(slabels, rotation=45, ha="right")
    ax_d.legend(fontsize=7.5, loc="upper right", framealpha=0.92)
    ax_d.text(
        0.01, 0.97,
        "If Sinchi's chain inflates values, its bars should be higher (more positive) than Penfold's",
        transform=ax_d.transAxes, fontsize=6.5, style="italic", color="#555",
        ha="left", va="top",
    )

    fig.tight_layout()
    return fig


# ═══════════════════════════════════════════════════════════════════════
# CHART: IMPURITIES (As, Sb, Sn, Bi, Zn)
# ═══════════════════════════════════════════════════════════════════════
def chart_impurities_combined(comp, labels, highlight_benefit=False, pct_mode=False):
    elems = [("As %", "Arsenic"), ("Sb %", "Antimony"),
             ("Sn %", "Tin"),     ("Bi %", "Bismuth"), ("Zn %", "Zinc")]
    n_elems = len(elems)
    # 2 cols × 3 rows (last slot empty)
    fig, axes = plt.subplots(3, 2, figsize=(14, 10))
    axes_flat = axes.ravel()
    n = len(labels)
    x = np.arange(n)
    w = 0.24
    stage_colors = ["#7E57C2", "#26A69A", "#EF6C00"]
    stage_names  = ["Natural", "Prepared", "UK finals"]

    for ax_i, (elem_col, elem_name) in enumerate(elems):
        ax = axes_flat[ax_i]
        for si, (_, pk, sk, _, _) in enumerate(STAGES):
            p = comp[f"{pk}_{elem_col}"].values
            s = comp[f"{sk}_{elem_col}"].values
            d = delta_values(p, s, pct_mode)
            bars = ax.bar(x + (si-1)*w, d, w,
                          label=stage_names[si],
                          color=stage_colors[si], alpha=0.75, zorder=3)
            if highlight_benefit:
                for j, bar in enumerate(bars):
                    if pd.notna(d[j]) and d[j] < 0:   # lower penalty = Sinchi benefit
                        bar.set_edgecolor("#FFD600")
                        bar.set_linewidth(1.3)
        ax.axhline(0, color="black", lw=0.5)
        d_unit = delta_unit(elem_col.split()[1] if " " in elem_col else "%", pct_mode)
        ax.set_title(f"{elem_name} ({elem_col})", fontsize=10)
        ax.set_ylabel(f"Δ {d_unit}")
        ax.set_xticks(x)
        ax.set_xticklabels(safe_labels(labels), rotation=45, ha="right", fontsize=6.5)
        if ax_i == 0:
            ax.legend(fontsize=7, loc="upper right")

    # Hide the unused 6th subplot
    axes_flat[5].set_visible(False)

    title_suffix = " (% relative to Penfold)" if pct_mode else ""
    fig.suptitle(
        f"Penalty element deltas{title_suffix} — "
        "negative = Sinchi reports lower (benefits Sinchi)",
        fontweight="bold", y=1.01,
    )
    fig.tight_layout()
    return fig


# ═══════════════════════════════════════════════════════════════════════
# SAMPLE-INTEGRITY ANALYSIS — distinguish spike vs swap
# ═══════════════════════════════════════════════════════════════════════
# Two competing manipulation hypotheses:
#
#   A. SPIKE — Sinchi's Bolivia sample is the same physical mineral as
#      Penfold's, but had Ag (and maybe Pb) added to the pulp or to the
#      lab reading.  Signature: the non-payable bulk composition (Zn,
#      impurities) is unchanged within normal sampling noise.
#
#   B. SWAP — Sinchi's Bolivia sample is a physically different material
#      (richer stockpile, reconstituted blend, different mineralisation).
#      Signature: Δ on unrelated elements (Zn especially) exceeds normal
#      sampling noise; the whole geochemical fingerprint has shifted.
#
# The UK-finals stage gives a within-dataset baseline for natural sampling
# heterogeneity, because both chains are unbiased there.  For each Bolivia
# stage we express deltas as a multiple of UK-baseline σ ("excess"):
#       excess_e = |Δ_e - median(Δ_e at UK)| / σ_UK(e)
# Excess < 2 is indistinguishable from normal sampling noise.
# Excess > 3 means the bulk composition has genuinely shifted.
#
# Zn is the strongest neutral tracer — it's a major bulk element
# (10-20 %), not payable, not penalised, so nobody has a motive to touch
# it.  If Δ_Zn at Bolivia dwarfs Δ_Zn at UK while Δ_Ag also does, the
# sample is not the same material.
# ═══════════════════════════════════════════════════════════════════════

INTEGRITY_NEUTRAL  = ["Zn %"]                             # bulk, no payment role
INTEGRITY_IMPURITY = ["As %", "Sb %", "Sn %", "Bi %"]     # penalty — motive to understate
INTEGRITY_PAYABLE  = ["Ag g", "Pb %"]                     # payable — motive to inflate
INTEGRITY_ALL      = INTEGRITY_PAYABLE + INTEGRITY_NEUTRAL + INTEGRITY_IMPURITY


def _robust_baseline(deltas):
    """Return (median, robust σ) for a 1-D array, using MAD × 1.4826.
    Falls back to sample stdev if MAD is zero/undefined."""
    d = np.asarray(deltas, dtype=float)
    d = d[np.isfinite(d)]
    if len(d) < 3:
        return np.nan, np.nan
    med = float(np.median(d))
    mad = float(np.median(np.abs(d - med)))
    sigma = 1.4826 * mad
    if not np.isfinite(sigma) or sigma == 0:
        sigma = float(np.std(d, ddof=1)) if len(d) > 1 else np.nan
    return med, sigma


def _integrity_verdict(ag, pb, zn, imp, spike_cut=2.0, swap_cut=3.0):
    """Decision tree over the four group-level excesses.  Each argument is
    the number of UK-baseline σ the delta is from zero (or NaN)."""
    if pd.isna(ag) and pd.isna(pb):
        return "Insufficient data"

    # A large Zn shift is the clearest swap signature — it overrides the
    # payable reading since Zn has no manipulation motive of its own.
    if pd.notna(zn) and zn >= swap_cut:
        return "Swap"

    payable_high = (pd.notna(ag) and ag >= spike_cut) or (pd.notna(pb) and pb >= spike_cut)
    if not payable_high:
        return "Clean"

    zn_ok   = pd.isna(zn)  or zn  < spike_cut
    zn_mid  = pd.notna(zn) and spike_cut <= zn < swap_cut
    imp_ok  = pd.isna(imp) or imp < spike_cut
    imp_mid = pd.notna(imp) and spike_cut <= imp < swap_cut

    if zn_ok and imp_ok:
        if pd.notna(pb) and pb >= spike_cut:
            return "Spike (Ag+Pb)"
        return "Spike (Ag only)"
    if zn_ok and (not imp_ok) and not imp_mid:
        return "Spike + impurity hide"
    if zn_ok and imp_mid:
        return "Spike + impurity hide"
    if zn_mid:
        return "Ambiguous"
    return "Ambiguous"


def compute_sample_consistency(comp, spike_cut=2.0, swap_cut=3.0):
    """Per-lot × stage table of excess values and a spike/swap verdict.

    Returns one row per (TR, Bolivia stage) with:
      • d_<elem>         raw Sinchi−Penfold delta at that stage
      • excess_<elem>    |d - median(d_UK)| / σ_UK  (units of UK-noise σ)
      • excess_payable   max of Ag/Pb excess
      • excess_neutral   Zn excess
      • excess_impurity  mean excess across As/Sb/Sn/Bi
      • verdict          string label — see _integrity_verdict
    """
    # Baselines from UK finals (unbiased on both chains).
    uk_base = {}
    for e in INTEGRITY_ALL:
        p = comp.get(f"UK_Penfold_{e}")
        s = comp.get(f"UK_Sinchi_{e}")
        if p is None or s is None:
            uk_base[e] = (np.nan, np.nan)
            continue
        d_uk = (s - p).dropna().values
        uk_base[e] = _robust_baseline(d_uk)

    rows = []
    for _, r in comp.iterrows():
        for stage_lbl, pk, sk, _, _ in STAGES[:2]:     # Natural, Prepared
            row = {"TR": r["TR"], "Stage": stage_lbl,
                   "Lot_Type": r.get("Lot_Type", "")}

            excess = {}
            for e in INTEGRITY_ALL:
                pv = r.get(f"{pk}_{e}", np.nan)
                sv = r.get(f"{sk}_{e}", np.nan)
                if pd.notna(pv) and pd.notna(sv):
                    d  = sv - pv
                    row[f"d_{e}"] = round(d, 3)
                    med, sig = uk_base[e]
                    if pd.notna(sig) and sig > 0:
                        excess[e] = abs(d - med) / sig
                    else:
                        excess[e] = np.nan
                else:
                    row[f"d_{e}"]      = np.nan
                    excess[e]          = np.nan
                row[f"excess_{e}"] = round(excess[e], 2) if pd.notna(excess[e]) else np.nan

            # Group aggregates
            ag_x = excess.get("Ag g", np.nan)
            pb_x = excess.get("Pb %", np.nan)
            zn_x = excess.get("Zn %", np.nan)
            imp_vals = [excess[e] for e in INTEGRITY_IMPURITY if pd.notna(excess.get(e, np.nan))]
            imp_x = float(np.mean(imp_vals)) if imp_vals else np.nan

            pay_vals = [v for v in [ag_x, pb_x] if pd.notna(v)]
            row["excess_payable"]  = round(max(pay_vals), 2) if pay_vals else np.nan
            row["excess_neutral"]  = round(zn_x, 2) if pd.notna(zn_x) else np.nan
            row["excess_impurity"] = round(imp_x, 2) if pd.notna(imp_x) else np.nan

            # Simple internal-consistency ratios: do ratios that don't
            # involve Ag/Pb stay the same across the two chains?  A spike
            # preserves them; a swap generally does not.
            def _ratio_shift(num, den):
                pn = r.get(f"{pk}_{num}", np.nan); pd_ = r.get(f"{pk}_{den}", np.nan)
                sn = r.get(f"{sk}_{num}", np.nan); sd = r.get(f"{sk}_{den}", np.nan)
                if any(pd.isna(v) for v in [pn, pd_, sn, sd]) or pd_ == 0 or sd == 0:
                    return np.nan
                p_ratio = pn / pd_
                s_ratio = sn / sd
                return abs(s_ratio - p_ratio) / max(abs(p_ratio), 1e-9) * 100
            row["pb_zn_ratio_shift_pct"]  = round(_ratio_shift("Pb %", "Zn %"), 1) if pd.notna(_ratio_shift("Pb %", "Zn %")) else np.nan
            row["as_sb_ratio_shift_pct"]  = round(_ratio_shift("As %", "Sb %"), 1) if pd.notna(_ratio_shift("As %", "Sb %")) else np.nan
            row["sb_bi_ratio_shift_pct"]  = round(_ratio_shift("Sb %", "Bi %"), 1) if pd.notna(_ratio_shift("Sb %", "Bi %")) else np.nan

            row["verdict"] = _integrity_verdict(ag_x, pb_x, zn_x, imp_x,
                                                spike_cut, swap_cut)
            rows.append(row)

    return pd.DataFrame(rows)


def integrity_uk_baseline_table(comp):
    """Human-readable table of the UK-finals noise baseline per element."""
    rows = []
    for e in INTEGRITY_ALL:
        p = comp.get(f"UK_Penfold_{e}")
        s = comp.get(f"UK_Sinchi_{e}")
        if p is None or s is None:
            continue
        d = (s - p).dropna().values
        med, sig = _robust_baseline(d)
        rows.append({
            "Element":    e,
            "n lots":     len(d),
            "median Δ":   round(med, 3) if pd.notna(med) else np.nan,
            "σ (robust)": round(sig, 3) if pd.notna(sig) else np.nan,
            "Group":      ("payable"  if e in INTEGRITY_PAYABLE  else
                           "neutral"  if e in INTEGRITY_NEUTRAL  else
                           "impurity"),
        })
    return pd.DataFrame(rows)


# ───── Sample-integrity charts ─────
_INTEGRITY_COLORS = {
    "Spike (Ag only)":        "#1565C0",
    "Spike (Ag+Pb)":          "#0D47A1",
    "Spike + impurity hide":  "#6A1B9A",
    "Swap":                   "#C62828",
    "Ambiguous":              "#F57C00",
    "Clean":                  "#78909C",
    "Insufficient data":      "#BDBDBD",
}


def chart_integrity_scatter(cons, stage="Natural"):
    """Ag-excess vs Zn-excess scatter for one Bolivia stage.
    Green band = within UK noise (spike-compatible).
    Red band   = exceeds UK noise on Zn (swap-compatible)."""
    sub = cons[cons["Stage"] == stage].copy()
    sub = sub.dropna(subset=["excess_Ag g", "excess_Zn %"])
    fig, ax = plt.subplots(figsize=(9, 6))
    if len(sub) == 0:
        ax.text(0.5, 0.5, f"No paired Ag+Zn data at {stage} stage",
                ha="center", va="center", transform=ax.transAxes)
        return fig
    y_top = max(float(sub["excess_Zn %"].max()) * 1.2, 5)
    x_rt  = max(float(sub["excess_Ag g"].max()) * 1.1, 5)
    ax.axhspan(0, 2, color="#E8F5E9", alpha=0.55, zorder=0)
    ax.axhspan(3, y_top, color="#FFEBEE", alpha=0.55, zorder=0)
    ax.axhline(2, color="#2E7D32", ls=":", lw=0.8, zorder=1)
    ax.axhline(3, color="#C62828", ls=":", lw=0.8, zorder=1)
    ax.axvline(2, color="grey",    ls="--", lw=0.7, zorder=1)

    for v, grp in sub.groupby("verdict"):
        ax.scatter(grp["excess_Ag g"], grp["excess_Zn %"],
                   c=_INTEGRITY_COLORS.get(v, "#78909C"),
                   s=95, edgecolor="black", linewidth=0.6,
                   label=f"{v} (n={len(grp)})", zorder=3)
    for _, r in sub.iterrows():
        ax.annotate(f"TR{r['TR']}",
                    (r["excess_Ag g"], r["excess_Zn %"]),
                    xytext=(4, 4), textcoords="offset points",
                    fontsize=7, zorder=4)
    ax.text(0.98, 0.04, "spike zone (Zn within UK noise)",
            transform=ax.transAxes, ha="right", va="bottom",
            fontsize=7.5, color="#2E7D32", style="italic")
    ax.text(0.98, 0.96, "swap zone (Zn shifted beyond UK noise)",
            transform=ax.transAxes, ha="right", va="top",
            fontsize=7.5, color="#C62828", style="italic")
    ax.set_xlabel("Ag excess  (|Δ| / σ at UK finals)")
    ax.set_ylabel("Zn excess  (|Δ| / σ at UK finals)")
    ax.set_xlim(0, x_rt)
    ax.set_ylim(0, y_top)
    ax.set_title(f"Sample integrity — {stage} stage: spike vs swap")
    ax.legend(loc="upper left", fontsize=7.5, framealpha=0.92)
    fig.tight_layout()
    return fig


def chart_integrity_fingerprint(cons, tr):
    """Per-lot heatmap: rows = Natural/Prepared, cols = all tracked elements,
    cell value = excess in UK-σ units.  Colour shows where the fingerprint
    has moved; a row that is hot only on Ag/Pb is a spike, a row hot
    across Zn too is a swap."""
    sub = cons[cons["TR"] == tr]
    stages = ["Natural", "Prepared"]
    # Order: payables first, then neutral, then impurities (visual grouping)
    elements = (INTEGRITY_PAYABLE + INTEGRITY_NEUTRAL + INTEGRITY_IMPURITY)
    data = np.full((len(stages), len(elements)), np.nan)
    verdicts = {}
    for i, s in enumerate(stages):
        rr = sub[sub["Stage"] == s]
        if rr.empty: continue
        verdicts[s] = rr["verdict"].iloc[0]
        for j, e in enumerate(elements):
            data[i, j] = rr[f"excess_{e}"].iloc[0]

    fig, ax = plt.subplots(figsize=(8.5, 3.0))
    im = ax.imshow(data, cmap="RdYlGn_r", vmin=0, vmax=6, aspect="auto")
    ax.set_xticks(range(len(elements)))
    ax.set_xticklabels(elements, rotation=0, fontsize=9)
    ax.set_yticks(range(len(stages)))
    ax.set_yticklabels([f"{s}\n({verdicts.get(s, '—')})" for s in stages],
                       fontsize=8.5)
    for i in range(len(stages)):
        for j in range(len(elements)):
            v = data[i, j]
            if pd.notna(v):
                ax.text(j, i, f"{v:.1f}", ha="center", va="center",
                        fontsize=9,
                        color="white" if v > 3 else "black")
    # Colour x-labels by group
    for j, e in enumerate(elements):
        colour = ("#0D47A1" if e in INTEGRITY_PAYABLE else
                  "#2E7D32" if e in INTEGRITY_NEUTRAL else
                  "#6A1B9A")
        ax.get_xticklabels()[j].set_color(colour)
        ax.get_xticklabels()[j].set_fontweight("bold")
    cbar = fig.colorbar(im, ax=ax, shrink=0.85)
    cbar.set_label("Excess  (σ-units of UK noise)")
    ax.set_title(
        f"TR{tr} — fingerprint excess by element  "
        "(blue = payable, green = neutral Zn, purple = penalty impurity)",
        fontsize=9.5,
    )
    fig.tight_layout()
    return fig


def chart_integrity_verdict_bars(cons):
    """Stacked count of verdicts at Natural vs Prepared — a one-glance view
    of how many lots fall into each spike/swap category."""
    order = ["Clean", "Spike (Ag only)", "Spike (Ag+Pb)",
             "Spike + impurity hide", "Ambiguous", "Swap",
             "Insufficient data"]
    stages = ["Natural", "Prepared"]
    counts = {v: [int(((cons["Stage"] == s) & (cons["verdict"] == v)).sum())
                  for s in stages] for v in order}
    fig, ax = plt.subplots(figsize=(9, 4.5))
    bottom = np.zeros(len(stages))
    for v in order:
        c = counts[v]
        if sum(c) == 0:
            continue
        ax.bar(stages, c, bottom=bottom,
               color=_INTEGRITY_COLORS.get(v, "#BDBDBD"),
               edgecolor="black", linewidth=0.4, label=v)
        for i, h in enumerate(c):
            if h > 0:
                ax.text(i, bottom[i] + h/2, str(h),
                        ha="center", va="center", fontsize=9,
                        color="white", fontweight="bold")
        bottom += np.array(c)
    ax.set_ylabel("Number of lots")
    ax.set_title("Sample-integrity verdicts per Bolivia stage")
    ax.legend(loc="center left", bbox_to_anchor=(1.02, 0.5),
              fontsize=8, frameon=False)
    fig.tight_layout()
    return fig


def chart_integrity_ratio_shift(cons):
    """Per-lot bar of ratio shifts that *shouldn't* move under a pure spike.
    Pb/Zn ratio moves if Pb was added but not Zn; As/Sb and Sb/Bi ratios
    move if the underlying impurity suite changed (swap signature)."""
    stages = ["Natural", "Prepared"]
    ratios = [("pb_zn_ratio_shift_pct", "Pb/Zn"),
              ("as_sb_ratio_shift_pct", "As/Sb"),
              ("sb_bi_ratio_shift_pct", "Sb/Bi")]
    fig, axes = plt.subplots(len(stages), 1, figsize=(11, 6), sharex=True)
    if len(stages) == 1:
        axes = [axes]
    for ax, stage in zip(axes, stages):
        sub = cons[cons["Stage"] == stage].copy()
        lots = sub["TR"].tolist()
        x = np.arange(len(lots))
        w = 0.27
        colors = ["#C62828", "#6A1B9A", "#F57C00"]
        for i, ((col, lbl), c) in enumerate(zip(ratios, colors)):
            vals = sub[col].values
            ax.bar(x + (i-1)*w, vals, w, label=lbl,
                   color=c, alpha=0.85, edgecolor="black", linewidth=0.3)
        ax.axhline(0,  color="black", lw=0.5)
        ax.axhline(25, color="grey",  ls="--", lw=0.6,
                   label="25 % shift (attention)" if stage == "Natural" else None)
        ax.set_ylabel(f"{stage}\nratio shift (%)")
        ax.set_xticks(x)
        ax.set_xticklabels([f"TR{l}" for l in lots], rotation=45, ha="right",
                           fontsize=7.5)
        if stage == "Natural":
            ax.legend(loc="upper right", fontsize=7.5, ncol=4)
    fig.suptitle(
        "Cross-chain ratio shifts — large values indicate the mineral "
        "composition changed between chains (swap signature)",
        fontweight="bold", y=1.01)
    fig.tight_layout()
    return fig


# ═══════════════════════════════════════════════════════════════════════
# FORENSIC LOT ANALYSIS — CHART FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════

def _lot_row(comp, tr):
    """Return the single comp row for a given TR string."""
    rows = comp[comp["TR"] == tr]
    return rows.iloc[0] if len(rows) else None


def chart_forensic_progression(r, elems, units):
    """
    For each element in elems, plot how each chain's assay evolves
    Natural → Prepared → UK.  Divergence within one chain = red flag.
    Returns one figure with len(elems) subplots.
    """
    stage_labels = ["Natural", "Prepared", "UK finals"]
    pk_keys = ["Natural_Penfold", "Prepared_Penfold", "UK_Penfold"]
    sk_keys = ["Natural_Sinchi",  "Prepared_Sinchi",  "UK_Sinchi"]
    x = np.arange(3)

    ncols = min(2, len(elems))
    nrows = int(np.ceil(len(elems) / ncols))
    fig, axes = plt.subplots(nrows, ncols,
                             figsize=(6 * ncols, 3.8 * nrows),
                             squeeze=False)
    axes_flat = axes.ravel()

    for idx, (elem, unit) in enumerate(zip(elems, units)):
        ax = axes_flat[idx]
        p_vals = [r.get(f"{k}_{elem}", np.nan) for k in pk_keys]
        s_vals = [r.get(f"{k}_{elem}", np.nan) for k in sk_keys]
        ss_val = r.get(f"S-Side_{elem}", np.nan)

        p_mask = [pd.notna(v) for v in p_vals]
        s_mask = [pd.notna(v) for v in s_vals]

        if any(p_mask):
            px = x[[i for i, m in enumerate(p_mask) if m]]
            py = [v for v, m in zip(p_vals, p_mask) if m]
            ax.plot(px, py, "o-", color=C_PENFOLD, lw=2, ms=7,
                    label="Penfold chain", zorder=4)
            for xi, yi in zip(px, py):
                ax.annotate(f"{yi:.1f}", (xi, yi), textcoords="offset points",
                            xytext=(0, 8), ha="center", fontsize=7.5,
                            color=C_PENFOLD, fontweight="bold")

        if any(s_mask):
            sx = x[[i for i, m in enumerate(s_mask) if m]]
            sy = [v for v, m in zip(s_vals, s_mask) if m]
            ax.plot(sx, sy, "s-", color=C_SINCHI, lw=2, ms=7,
                    label="Sinchi chain", zorder=4)
            for xi, yi in zip(sx, sy):
                ax.annotate(f"{yi:.1f}", (xi, yi), textcoords="offset points",
                            xytext=(0, -14), ha="center", fontsize=7.5,
                            color=C_SINCHI, fontweight="bold")

        if pd.notna(ss_val):
            ax.axhline(ss_val, color=C_SSIDE, lw=1.5, ls="--",
                       label=f"S-Side = {ss_val:.1f}", zorder=3)

        # Shade gap between chains at each stage
        for si in range(3):
            pv, sv = p_vals[si], s_vals[si]
            if pd.notna(pv) and pd.notna(sv):
                ax.fill_between([si - 0.05, si + 0.05], [pv, pv], [sv, sv],
                                color=C_SINCHI if sv > pv else C_PENFOLD,
                                alpha=0.18, zorder=2)

        ax.set_xticks(x)
        ax.set_xticklabels(stage_labels, fontsize=8)
        ax.set_ylabel(unit, fontsize=8)
        ax.set_title(f"{elem} — stage progression", fontsize=10)
        ax.legend(fontsize=7, loc="best", framealpha=0.9)
        ax.grid(True, alpha=0.25)

    for idx in range(len(elems), len(axes_flat)):
        axes_flat[idx].set_visible(False)

    fig.suptitle("Chain progression: Natural → Prepared → UK finals",
                 fontsize=11, fontweight="bold", y=1.02)
    fig.tight_layout()
    return fig


def chart_forensic_delta_heatmap(r, comp_all):
    """
    Heatmap: rows = elements, cols = stages.
    Cell = Sinchi − Penfold delta for this lot.
    """
    pk_keys = ["Natural_Penfold", "Prepared_Penfold", "UK_Penfold"]
    sk_keys = ["Natural_Sinchi",  "Prepared_Sinchi",  "UK_Sinchi"]
    stage_names = ["Natural", "Prepared", "UK finals"]
    elems = ["Ag g", "Pb %", "As %", "Sb %", "Sn %", "Bi %", "Zn %"]
    units = ["g/TM", "%", "%", "%", "%", "%", "%"]

    nrows_h = len(elems)
    ncols_h = len(stage_names)

    data = np.full((nrows_h, ncols_h), np.nan)
    annot = np.full((nrows_h, ncols_h), "", dtype=object)

    for ei, (elem, unit) in enumerate(zip(elems, units)):
        for si, (pk, sk) in enumerate(zip(pk_keys, sk_keys)):
            pv = r.get(f"{pk}_{elem}", np.nan)
            sv = r.get(f"{sk}_{elem}", np.nan)
            if pd.notna(pv) and pd.notna(sv):
                d = float(sv - pv)
                data[ei, si] = d
                annot[ei, si] = f"{d:+.1f}"

    # Symmetric color scale
    fig, ax = plt.subplots(figsize=(7, 5))
    cmap = plt.cm.RdBu_r
    vmax = np.nanmax(np.abs(data)) if not np.all(np.isnan(data)) else 1
    im = ax.imshow(data, cmap=cmap, aspect="auto",
                   vmin=-vmax, vmax=vmax)

    ax.set_xticks(range(ncols_h))
    ax.set_xticklabels(stage_names, fontsize=9)
    ax.set_yticks(range(nrows_h))
    ax.set_yticklabels([f"{e} ({u})" for e, u in zip(elems, units)], fontsize=9)

    for ei in range(nrows_h):
        for ci in range(ncols_h):
            txt = annot[ei, ci]
            if txt:
                d_val = data[ei, ci]
                text_color = "white" if abs(d_val) > vmax * 0.6 else "black"
                ax.text(ci, ei, txt, ha="center", va="center",
                        fontsize=9, color=text_color, fontweight="bold")

    plt.colorbar(im, ax=ax, fraction=0.03, pad=0.02,
                 label="Δ (Sinchi − Penfold)  ·  red = Sinchi higher")
    ax.set_title("Delta heatmap — all elements × all stages",
                 fontsize=10, pad=8)
    fig.tight_layout()
    return fig


def chart_forensic_within_chain(r):
    """
    Shows the internal jump within each chain:
      Prepared − Natural  (how much did processing change the assay?)
    A large positive jump in Sinchi's chain but not Penfold's = red flag.
    """
    elems = ["Ag g", "Pb %", "As %", "Sb %", "Sn %", "Bi %"]
    units = ["g/TM", "%", "%", "%", "%", "%"]

    p_nat  = [r.get(f"Natural_Penfold_{e}", np.nan)  for e in elems]
    p_prep = [r.get(f"Prepared_Penfold_{e}", np.nan) for e in elems]
    s_nat  = [r.get(f"Natural_Sinchi_{e}",  np.nan)  for e in elems]
    s_prep = [r.get(f"Prepared_Sinchi_{e}", np.nan)  for e in elems]

    p_jump = [float(pp - pn) if (pd.notna(pp) and pd.notna(pn)) else np.nan
              for pn, pp in zip(p_nat, p_prep)]
    s_jump = [float(sp - sn) if (pd.notna(sp) and pd.notna(sn)) else np.nan
              for sn, sp in zip(s_nat, s_prep)]

    x = np.arange(len(elems))
    w = 0.35
    fig, ax = plt.subplots(figsize=(10, 4))

    bars_p = ax.bar(x - w/2, p_jump, w, label="Penfold: Prepared − Natural",
                    color=C_PENFOLD, alpha=0.8, zorder=3)
    bars_s = ax.bar(x + w/2, s_jump, w, label="Sinchi: Prepared − Natural",
                    color=C_SINCHI, alpha=0.8, zorder=3)

    for bars, jumps in [(bars_p, p_jump), (bars_s, s_jump)]:
        for bar, jv in zip(bars, jumps):
            if pd.notna(jv) and jv != 0:
                ax.text(bar.get_x() + bar.get_width()/2,
                        jv + np.sign(jv) * abs(jv) * 0.04,
                        f"{jv:+.1f}",
                        ha="center", va="bottom" if jv >= 0 else "top",
                        fontsize=7, color="#222", zorder=5)

    ax.axhline(0, color="black", lw=0.6, ls="--")
    ax.set_xticks(x)
    ax.set_xticklabels([f"{e}\n({u})" for e, u in zip(elems, units)], fontsize=8)
    ax.set_ylabel("Prepared − Natural (within same chain)")
    ax.set_title(
        "Within-chain processing jump: Prepared minus Natural\n"
        "Divergence between chains = suspicious change during sample preparation",
        fontsize=10, pad=6)
    ax.legend(fontsize=8, framealpha=0.9)
    ax.text(0.01, 0.97,
            "If both chains process the same physical material, large between-chain "
            "divergence here indicates sample tampering at the preparation stage.",
            transform=ax.transAxes, fontsize=6.5, style="italic",
            color="#555", va="top")
    fig.tight_layout()
    return fig


def chart_forensic_context(comp_all, tr_selected, elem_col, unit, stage_key):
    """
    Scatter: all lots' delta at given stage, with selected lot highlighted.
    Shows where this lot sits relative to the distribution.
    """
    pk = f"{stage_key}_Penfold_{elem_col}"
    sk = f"{stage_key}_Sinchi_{elem_col}"
    p_all = pd.to_numeric(comp_all[pk], errors="coerce")
    s_all = pd.to_numeric(comp_all[sk], errors="coerce")
    d_all = s_all - p_all
    valid = comp_all[d_all.notna()].copy()
    valid["_d"] = (s_all - p_all)[d_all.notna()].values

    fig, ax = plt.subplots(figsize=(max(8, len(valid) * 0.55 + 2), 3.5))
    x = np.arange(len(valid))
    colors = [C_SINCHI if v > 0 else C_PENFOLD for v in valid["_d"]]
    ax.bar(x, valid["_d"], 0.55, color=colors, alpha=0.65, zorder=3)

    # Highlight selected lot
    sel_idx = valid[valid["TR"] == tr_selected].index
    for si in sel_idx:
        pos = list(valid.index).index(si)
        dv = valid.loc[si, "_d"]
        ax.bar(pos, dv, 0.55, color=C_SINCHI if dv > 0 else C_PENFOLD,
               alpha=1.0, edgecolor="#FFD600", linewidth=2.5, zorder=5)
        ax.text(pos, dv + np.sign(dv) * abs(dv) * 0.06,
                f"◄ {tr_selected}\n{dv:+.0f}",
                ha="center", va="bottom" if dv >= 0 else "top",
                fontsize=7.5, fontweight="bold", color="#222", zorder=6)

    # Mean and ±2σ lines
    mn = valid["_d"].mean(); sd = valid["_d"].std(ddof=1)
    ax.axhline(mn, color="#666", lw=1.2, ls="-", label=f"Mean = {mn:+.1f}")
    ax.axhline(mn + 2*sd, color="#EF6C00", lw=1, ls="--",
               label=f"+2σ = {mn+2*sd:+.1f}")
    ax.axhline(mn - 2*sd, color="#EF6C00", lw=1, ls="--",
               label=f"−2σ = {mn-2*sd:+.1f}")
    ax.axhline(0, color="black", lw=0.5)

    ax.set_xticks(x)
    ax.set_xticklabels(safe_labels(valid["TR"].tolist()),
                       rotation=45, ha="right", fontsize=7.5)
    ax.set_ylabel(f"Δ (Sinchi − Penfold)  {unit}")
    ax.set_title(f"{stage_key} stage — {elem_col} delta: where does {tr_selected} sit?",
                 fontsize=10, pad=6)
    ax.legend(fontsize=7.5, loc="upper left", framealpha=0.9)
    fig.tight_layout()
    return fig


def chart_forensic_sside(r, tr):
    """Three-way bar: Penfold UK, Sinchi UK, S-Side — for this lot only."""
    elems  = ["Ag g", "Pb %"]
    labels_e = ["Silver (Ag g/TM)", "Lead (Pb %)"]
    uk_p  = [r.get(f"UK_Penfold_{e}", np.nan) for e in elems]
    uk_s  = [r.get(f"UK_Sinchi_{e}",  np.nan) for e in elems]
    ss    = [r.get(f"S-Side_{e}",     np.nan) for e in elems]

    if all(pd.isna(v) for v in ss):
        return None

    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    for ax, elem, lbl, pv, sv, ssv in zip(axes, elems, labels_e, uk_p, uk_s, ss):
        vals   = [pv, sv, ssv]
        colors_b = [C_PENFOLD, C_SINCHI, C_SSIDE]
        names  = ["Penfold UK", "Sinchi UK", "S-Side"]
        x_b = np.arange(3)
        bars = ax.bar(x_b, [v if pd.notna(v) else 0 for v in vals],
                      0.5, color=colors_b, alpha=0.85, zorder=3)
        for bar, v, name in zip(bars, vals, names):
            if pd.notna(v):
                ax.text(bar.get_x() + bar.get_width()/2,
                        v + bar.get_height() * 0.01,
                        f"{v:.1f}", ha="center", va="bottom",
                        fontsize=9, fontweight="bold")
        # Deltas vs S-Side as text
        if pd.notna(ssv):
            lines = []
            for v, name in [(pv, "Penfold"), (sv, "Sinchi")]:
                if pd.notna(v):
                    lines.append(f"{name} vs S-Side: {v-ssv:+.1f}")
            ax.text(0.98, 0.97, "\n".join(lines),
                    transform=ax.transAxes, fontsize=8,
                    ha="right", va="top",
                    bbox=dict(boxstyle="round,pad=0.3", fc="white",
                              ec="#ccc", alpha=0.9))
        ax.set_xticks(x_b)
        ax.set_xticklabels(names, fontsize=9)
        ax.set_title(lbl, fontsize=10)
        ax.set_ylabel(elem.split()[1] if " " in elem else elem)

    fig.suptitle(f"S-Side three-way comparison — {tr}", fontweight="bold")
    fig.tight_layout()
    return fig


# ═══════════════════════════════════════════════════════════════════════
# EXCEL EXPORT
# ═══════════════════════════════════════════════════════════════════════
def build_excel(comp, fin_df, stats_data):
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as w:
        comp.to_excel(w, sheet_name="Cleaned Assay Data", index=False)
        fin_df.to_excel(w, sheet_name="Physical Impact", index=False)
        pd.DataFrame(stats_data).to_excel(w, sheet_name="Statistical Tests",
                                          index=False)
        delta_rows = []
        for _, r in comp.iterrows():
            dr = {"TR": r["TR"], "Contract": r["Contract"]}
            for stage_lbl, pk, sk, _, _ in STAGES:
                for e in ELEMENTS:
                    p = r.get(f"{pk}_{e}", np.nan)
                    s = r.get(f"{sk}_{e}", np.nan)
                    dr[f"{stage_lbl}_Δ_{e}"] = round(s - p, 4) if pd.notna(p) and pd.notna(s) else np.nan
                    if pd.notna(p) and pd.notna(s) and p != 0:
                        dr[f"{stage_lbl}_Δ%_{e}"] = round((s-p)/abs(p)*100, 2)
                    else:
                        dr[f"{stage_lbl}_Δ%_{e}"] = np.nan
            delta_rows.append(dr)
        pd.DataFrame(delta_rows).to_excel(w, sheet_name="Lot-by-Lot Deltas", index=False)
        completeness_df(comp).to_excel(w, sheet_name="Data Completeness", index=False)
    buf.seek(0)
    return buf


# ═══════════════════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════════════
#                      S T R E A M L I T   A P P
# ═══════════════════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════════════
st.set_page_config(page_title="Sinchi Metals — Assay Analysis",
                   layout="wide", page_icon="⚖️")

st.markdown("""
<style>
    .block-container {padding-top: 1.2rem; padding-bottom: 1rem;}
    h1 {font-size: 1.5rem !important;}
    .stTabs [data-baseweb="tab-list"] {gap: 4px;}
    .stTabs [data-baseweb="tab"] {padding: 6px 16px; font-size: 0.85rem;}
</style>
""", unsafe_allow_html=True)

st.title("⚖️  Sinchi Metals — Assay Discrepancy Analysis")

# ── Sidebar ───────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Data sources")
    new_uploaded  = st.file_uploader(
        "Assay file (new structured)",
        type=["xlsx", "xls"],
        help="Default: Assay Exchanges - Low Silver Sinchi 1.xlsx",
    )
    orig_uploaded = st.file_uploader(
        "Original file (weights & S-Side)",
        type=["xlsx", "xls"],
        help="Default: sinchi metals assays over time.xlsx",
    )
    st.divider()

    st.header("Display")
    show_sside    = st.toggle("Show S-Side benchmark", value=True,
                              help="Confidential — remove before sharing externally")
    highlight_ben = st.toggle("Highlight Sinchi benefit", value=False,
                              help="Yellow outline on bars that financially favour Sinchi")
    pct_delta     = st.toggle("Show % relative delta", value=False,
                              help="Express delta as % of Penfold value "
                                   "(highlights relative differences in smaller lots)")
    show_dmt      = st.toggle("Show DMT under bars", value=False,
                              help="Display settled dry metric tonnes beneath each lot label "
                                   "in delta charts — shows the weight context of each discrepancy")

# ── Load data ─────────────────────────────────────────────────────────
try:
    new_bytes  = new_uploaded.read()  if new_uploaded  else None
    orig_bytes = orig_uploaded.read() if orig_uploaded else None
    comp = load_data(new_bytes, orig_bytes)
except Exception as e:
    st.error(
        f"Could not load data: {e}\n\n"
        "Check that **Assay Exchanges - Low Silver Sinchi 1.xlsx** is at:\n"
        f"`{NEW_FILE_PATH}`\n\n"
        "Or upload both files using the sidebar."
    )
    st.stop()

# Contract filter (after data loads)
all_contracts = sorted(comp["Contract"].unique())
with st.sidebar:
    st.divider()
    st.header("Filters")
    sel_contracts = st.multiselect("Filter by contract (first 3 digits)",
                                   all_contracts, default=all_contracts)
comp = comp[comp["Contract"].isin(sel_contracts)].reset_index(drop=True)

# Lot-type filter — separates Pb/Ag from Zn/Ag concentrates
all_lot_types = sorted(comp["Lot_Type"].dropna().unique()) if "Lot_Type" in comp.columns else ["Pb/Ag"]
with st.sidebar:
    sel_lot_types = st.multiselect(
        "Concentrate type",
        options=all_lot_types,
        default=all_lot_types,
        help="Pb/Ag = lead-silver concentrate (main analysis). "
             "Zn/Ag = zinc-silver concentrate (different payable structure).",
    )
if "Lot_Type" in comp.columns and sel_lot_types:
    comp = comp[comp["Lot_Type"].isin(sel_lot_types)].reset_index(drop=True)

labels = comp["TR"].tolist()
fin_df = compute_physical_impact(comp)

# Collect statistics
stats_data = []
for stage_lbl, pk, sk, _, _ in STAGES:
    for e in ELEMENTS:
        st_res = paired_stats(comp[f"{pk}_{e}"], comp[f"{sk}_{e}"])
        st_res["Stage"]   = stage_lbl
        st_res["Element"] = e
        stats_data.append(st_res)

# ═══════════════════════════════════════════════════════════════════════
# TABS
# ═══════════════════════════════════════════════════════════════════════
tabs = st.tabs([
    "📊 Summary",
    "🥈 Silver",
    "🔩 Lead",
    "☣️ Impurities",
    "📈 Delta Curves",
    "🎯 Correlation",
    "🔒 S-Side",
    "💰 Physical Impact",
    "📐 Statistics",
    "🕵️ UK Trend",
    "🧪 Integrity",
    "🔬 Forensic",
    "⚖️ Impact",
    "📥 Export",
])

# ── TAB 0: Executive Summary ──────────────────────────────────────────
with tabs[0]:
    ag_nat  = paired_stats(comp["Natural_Penfold_Ag g"],  comp["Natural_Sinchi_Ag g"])
    ag_prep = paired_stats(comp["Prepared_Penfold_Ag g"], comp["Prepared_Sinchi_Ag g"])
    ag_uk   = paired_stats(comp["UK_Penfold_Ag g"],       comp["UK_Sinchi_Ag g"])
    total_extra_oz = fin_df["Extra_Ag_oz"].sum() if "Extra_Ag_oz" in fin_df.columns else np.nan

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Ag Natural — Sinchi higher",
              f"{ag_nat.get('pct_sinchi_higher', '—')} %",
              f"avg Δ = {ag_nat.get('mean_delta', '—')} g  "
              f"({ag_nat.get('pct_rel_bias', '—')} %)")
    c2.metric("Ag Prepared — Sinchi higher",
              f"{ag_prep.get('pct_sinchi_higher', '—')} %",
              f"avg Δ = {ag_prep.get('mean_delta', '—')} g  "
              f"({ag_prep.get('pct_rel_bias', '—')} %)")
    c3.metric("Ag UK finals — Sinchi higher",
              f"{ag_uk.get('pct_sinchi_higher', '—')} %",
              f"avg Δ = {ag_uk.get('mean_delta', '—')} g  "
              f"({ag_uk.get('pct_rel_bias', '—')} %)")
    c4.metric("Extra payable Ag (UK finals)",
              f"{total_extra_oz:+,.1f} oz" if pd.notna(total_extra_oz) else "—",
              "across all lots with UK data")

    st.markdown("---")
    st.subheader("Stage gradient — the core evidence")
    st.markdown(
        "The bias is **largest at the Bolivia level** (where samples are collected "
        "and processed locally) and **narrows toward zero at the UK level** (where "
        "independent, accredited labs analyse the samples). This gradient is "
        "consistent with manipulation at the Bolivia sampling/local lab stage."
    )
    fig_grad = chart_stage_gradient(comp)
    st.pyplot(fig_grad, use_container_width=True)
    add_download(fig_grad, "stage_gradient")
    plt.close(fig_grad)

    st.markdown("---")
    fig_sum = chart_summary_bars(comp)
    st.pyplot(fig_sum, use_container_width=True)
    add_download(fig_sum, "summary_bars")
    plt.close(fig_sum)

    st.subheader("Complete delta heatmap — all lots × all stages")
    st.markdown(
        "Each cell = % relative delta (Sinchi − Penfold) / |Penfold|.  \n"
        "**Left half** = Silver (Ag). **Right half** = Lead (Pb).  \n"
        "The red wall at the Bolivia stages (Natural, Prepared) that turns "
        "blue/neutral at UK is the smoking gun."
    )
    fig_ch = chart_compact_heatmap(comp, labels)
    st.pyplot(fig_ch, use_container_width=True)
    add_download(fig_ch, "compact_heatmap_all")
    plt.close(fig_ch)

    st.subheader("Delta heatmap — UK finals (all elements)")
    fig_hm = chart_heatmap(comp, labels, stage_idx=2, pct_mode=pct_delta)
    st.pyplot(fig_hm, use_container_width=True)
    add_download(fig_hm, "heatmap_uk")
    plt.close(fig_hm)

    st.subheader("Data completeness by lot")
    cdf = completeness_df(comp)

    def _color_completeness(val):
        if val == "✓ paired":   return "background-color: #c8e6c9"
        if val == "✓":          return "background-color: #c8e6c9"
        if "only" in str(val):  return "background-color: #fff9c4"
        if val == "—":          return "background-color: #ffcdd2"
        return ""

    st.dataframe(
        cdf.style.map(_color_completeness,
                      subset=[c for c in cdf.columns if c not in ("TR","Contract")]),
        use_container_width=True, hide_index=True,
    )

# ── TAB 1: Silver ─────────────────────────────────────────────────────
with tabs[1]:
    st.subheader("Multi-stage variance — Silver (Ag g/TM)")
    fig_mv = chart_multistage_delta(comp, "Ag g", "Ag g/TM", labels,
                                    highlight_benefit=highlight_ben,
                                    pct_mode=pct_delta)
    st.pyplot(fig_mv, use_container_width=True)
    add_download(fig_mv, "ag_multistage_delta")
    plt.close(fig_mv)

    for stage_lbl, pk, sk, plab, slab in STAGES:
        fig = chart_paired_bars(comp, "Ag g", "Ag g/TM", stage_lbl,
                                pk, sk, plab, slab, labels,
                                show_sside=show_sside,
                                highlight_benefit=highlight_ben,
                                pct_mode=pct_delta,
                                show_dmt=show_dmt)
        st.pyplot(fig, use_container_width=True)
        add_download(fig, f"ag_{stage_lbl.replace(' ','_')}")
        plt.close(fig)

    st.subheader("Distribution of Ag deltas by stage")
    fig_bp = chart_boxplots(comp, "Ag g", "g/TM", pct_mode=pct_delta)
    st.pyplot(fig_bp, use_container_width=True)
    add_download(fig_bp, "ag_boxplots")
    plt.close(fig_bp)

# ── TAB 2: Lead ───────────────────────────────────────────────────────
with tabs[2]:
    st.subheader("Multi-stage variance — Lead (Pb %)")
    fig_mv = chart_multistage_delta(comp, "Pb %", "Pb %", labels,
                                    highlight_benefit=highlight_ben,
                                    pct_mode=pct_delta)
    st.pyplot(fig_mv, use_container_width=True)
    add_download(fig_mv, "pb_multistage_delta")
    plt.close(fig_mv)

    for stage_lbl, pk, sk, plab, slab in STAGES:
        fig = chart_paired_bars(comp, "Pb %", "Pb %", stage_lbl,
                                pk, sk, plab, slab, labels,
                                show_sside=show_sside,
                                highlight_benefit=highlight_ben,
                                pct_mode=pct_delta,
                                show_dmt=show_dmt)
        st.pyplot(fig, use_container_width=True)
        add_download(fig, f"pb_{stage_lbl.replace(' ','_')}")
        plt.close(fig)

    st.subheader("Distribution of Pb deltas by stage")
    fig_bp = chart_boxplots(comp, "Pb %", "%", pct_mode=pct_delta)
    st.pyplot(fig_bp, use_container_width=True)
    add_download(fig_bp, "pb_boxplots")
    plt.close(fig_bp)

# ── TAB 3: Impurities ─────────────────────────────────────────────────
with tabs[3]:
    st.info(
        "For penalty elements, a **negative** delta means Sinchi reports "
        "lower impurities → fewer penalties → benefits Sinchi.  \n"
        "**Zn** is a specification-range element (10–20 %); large deviations "
        "may indicate a different mineral blend."
    )
    fig_imp = chart_impurities_combined(comp, labels,
                                        highlight_benefit=highlight_ben,
                                        pct_mode=pct_delta)
    st.pyplot(fig_imp, use_container_width=True)
    add_download(fig_imp, "impurities_combined")
    plt.close(fig_imp)

    st.subheader("Heatmap — Prepared samples")
    fig_hm2 = chart_heatmap(comp, labels, stage_idx=1, pct_mode=pct_delta)
    st.pyplot(fig_hm2, use_container_width=True)
    add_download(fig_hm2, "heatmap_prepared")
    plt.close(fig_hm2)

    st.subheader("Heatmap — Natural samples")
    fig_hm3 = chart_heatmap(comp, labels, stage_idx=0, pct_mode=pct_delta)
    st.pyplot(fig_hm3, use_container_width=True)
    add_download(fig_hm3, "heatmap_natural")
    plt.close(fig_hm3)

# ── TAB 4: Temporal / Delta Curves ────────────────────────────────────
with tabs[4]:
    st.subheader("Silver delta chronological + cumulative")
    fig_ts = chart_delta_timeseries(comp, "Ag g", "Ag g/TM", labels,
                                    pct_mode=pct_delta)
    st.pyplot(fig_ts, use_container_width=True)
    add_download(fig_ts, "ag_delta_timeseries")
    plt.close(fig_ts)

    st.subheader("Lead delta chronological + cumulative")
    fig_ts2 = chart_delta_timeseries(comp, "Pb %", "Pb %", labels,
                                     pct_mode=pct_delta)
    st.pyplot(fig_ts2, use_container_width=True)
    add_download(fig_ts2, "pb_delta_timeseries")
    plt.close(fig_ts2)

    st.caption(
        "**How to read the cumulative chart:** A consistently upward slope "
        "indicates systematic inflation by Sinchi over time. A flat section "
        "indicates fair agreement. A sudden steepening pinpoints when "
        "manipulation may have intensified."
    )

# ── TAB 5: Correlation & Bland-Altman ─────────────────────────────────
with tabs[5]:
    st.subheader("1∶1 Correlation — Silver")
    fig_c1 = chart_correlation(comp, "Ag g", "Ag g/TM", labels,
                               highlight_benefit=highlight_ben,
                               show_sside=show_sside)
    st.pyplot(fig_c1, use_container_width=True)
    add_download(fig_c1, "ag_correlation")
    plt.close(fig_c1)

    st.subheader("1∶1 Correlation — Lead")
    fig_c2 = chart_correlation(comp, "Pb %", "Pb %", labels,
                               highlight_benefit=highlight_ben,
                               show_sside=show_sside)
    st.pyplot(fig_c2, use_container_width=True)
    add_download(fig_c2, "pb_correlation")
    plt.close(fig_c2)

    st.subheader("Bland–Altman — Silver")
    fig_ba1 = chart_bland_altman(comp, "Ag g", "g/TM", labels)
    st.pyplot(fig_ba1, use_container_width=True)
    add_download(fig_ba1, "ag_bland_altman")
    plt.close(fig_ba1)

    st.subheader("Bland–Altman — Lead")
    fig_ba2 = chart_bland_altman(comp, "Pb %", "%", labels)
    st.pyplot(fig_ba2, use_container_width=True)
    add_download(fig_ba2, "pb_bland_altman")
    plt.close(fig_ba2)

# ── TAB 6: S-Side Benchmark ───────────────────────────────────────────
with tabs[6]:
    if not show_sside:
        st.warning("S-Side data is hidden. Enable the toggle in the sidebar.")
    else:
        st.info("🔒 **CONFIDENTIAL** — remove this section before sharing "
                "with Sinchi Metals or ASI Bolivia.")

        st.subheader("Silver — S-Side vs UK finals")
        fig_ss1 = chart_sside_benchmark(comp, "Ag g", "Ag g/TM", labels)
        st.pyplot(fig_ss1, use_container_width=True)
        add_download(fig_ss1, "sside_ag")
        plt.close(fig_ss1)

        st.subheader("Lead — S-Side vs UK finals")
        fig_ss2 = chart_sside_benchmark(comp, "Pb %", "Pb %", labels)
        st.pyplot(fig_ss2, use_container_width=True)
        add_download(fig_ss2, "sside_pb")
        plt.close(fig_ss2)

        st.markdown(
            "**Interpretation:** S-Side results (independent Chinese labs at "
            "disport) serve as an unbiased benchmark. If they align closer to "
            "Penfold than to Sinchi, it supports the hypothesis that Sinchi's "
            "Bolivian lab chain produces inflated values."
        )

# ── TAB 7: Physical Impact ────────────────────────────────────────────
with tabs[7]:
    st.caption(
        "Physical impact at **UK finals** — the contractually determinative stage.  \n"
        "Earlier stages (Natural, Prepared) are provisional and get corrected once "
        "UK finals arrive, so only UK finals represent the true payment impact.  \n"
        "USD conversion is omitted because each lot has different fixation prices, "
        "quotation periods, and contract appendices."
    )
    fig_fin = chart_physical_impact(fin_df)
    st.pyplot(fig_fin, use_container_width=True)
    add_download(fig_fin, "physical_impact")
    plt.close(fig_fin)

    st.subheader("Lot-by-lot breakdown")
    display_cols = ["TR", "Contract", "DMT", "Lot_Type"]
    for s_lbl, _, _, _, _ in STAGES:
        display_cols += [f"{s_lbl}_Delta_Ag", f"{s_lbl}_Delta_Pb"]
    display_cols += ["Extra_Ag_oz", "Extra_Pb_t"]
    available = [c for c in display_cols if c in fin_df.columns]
    st.dataframe(fin_df[available].style.format(
        {"Extra_Ag_oz": "{:+,.1f} oz", "Extra_Pb_t": "{:+,.4f} t"},
        na_rep="—",
    ), use_container_width=True)

# ── TAB 8: Statistical Proof ──────────────────────────────────────────
with tabs[8]:
    st.subheader("Hypothesis testing — is the bias statistically significant?")
    st.markdown(
        "For each stage × element combination:\n\n"
        "- **H₀**: mean delta (Sinchi − Penfold) = 0  (no systematic bias)\n"
        "- **H₁**: mean delta ≠ 0  (systematic bias exists)\n\n"
        "Three independent tests: paired *t*-test, Wilcoxon signed-rank, and sign test.  \n"
        "**% Rel. bias** = mean Δ expressed as % of Penfold mean (scale-independent)."
    )

    rows_display = []
    for s in stats_data:
        if s.get("insufficient"):
            continue
        rows_display.append({
            "Stage":        s["Stage"],
            "Element":      s["Element"],
            "N":            s["n"],
            "Mean Δ":       s["mean_delta"],
            "% Rel. bias":  f"{s.get('pct_rel_bias', '—')} %",
            "95 % CI":      f"[{s['ci95_lo']}, {s['ci95_hi']}]",
            "% Sinchi ↑":   f"{s['pct_sinchi_higher']} %",
            "t-test p":     f"{s['t_pval']:.4f} {pval_stars(s['t_pval'])}",
            "Wilcoxon p":   (f"{s['wilcoxon_pval']:.4f} {pval_stars(s['wilcoxon_pval'])}"
                             if pd.notna(s["wilcoxon_pval"]) else "—"),
            "Sign p":       f"{s['sign_pval']:.4f} {pval_stars(s['sign_pval'])}",
            "Cohen's d":    f"{s['cohen_d']} ({cohen_label(s['cohen_d'])})",
        })

    sdf = pd.DataFrame(rows_display)
    st.dataframe(sdf, use_container_width=True, hide_index=True)
    st.markdown(
        "**Significance:** \\*\\*\\* p < 0.001 &nbsp; \\*\\* p < 0.01 "
        "&nbsp; \\* p < 0.05 &nbsp; n.s. = not significant"
    )

    st.markdown("---")
    st.subheader("Key findings")
    for s in stats_data:
        if s.get("insufficient"):
            continue
        if s["Element"] in PAYABLES and s["t_pval"] < 0.05:
            direction = "higher" if s["mean_delta"] > 0 else "lower"
            st.success(
                f"**{s['Stage']} — {s['Element']}**: Sinchi's results are "
                f"statistically significantly **{direction}** "
                f"(mean Δ = {s['mean_delta']:+.2f}, "
                f"rel. bias = {s.get('pct_rel_bias','—')} %, "
                f"p = {s['t_pval']:.4f}, Cohen's d = {s['cohen_d']}). "
                f"Probability of occurring by chance: **{s['t_pval']*100:.2f} %**."
            )
        elif s["Element"] in PAYABLES and s["pct_sinchi_higher"] > 70:
            st.warning(
                f"**{s['Stage']} — {s['Element']}**: Sinchi higher in "
                f"{s['pct_sinchi_higher']} % of lots (rel. bias "
                f"{s.get('pct_rel_bias','—')} %), though p = {s['t_pval']:.3f} "
                f"falls short of significance at n = {s['n']}."
            )

# ── TAB 9: UK Regime Change ───────────────────────────────────────────
with tabs[9]:
    st.subheader("Is Sinchi's UK-stage bias a recent development?")
    st.markdown(
        "This tab tests the hypothesis that Sinchi's UK-final results were "
        "unbiased historically but have shifted upward in recent lots.  \n"
        "**How to use:** Select the lot you believe marks the start of the "
        "change (the first 'suspect' lot). The charts and statistics will "
        "update to compare the periods before and after that boundary."
    )

    # ── Pettitt auto-detection ─────────────────────────────────────────
    uk_p_all = comp["UK_Penfold_Ag g"].values
    uk_s_all = comp["UK_Sinchi_Ag g"].values
    d_uk_all = delta_values(uk_p_all, uk_s_all, pct_mode=False)  # always absolute for detection
    mask_uk  = pd.notna(d_uk_all)
    d_uk_valid = d_uk_all[mask_uk]
    labels_uk_valid = [labels[i] for i in range(len(labels)) if mask_uk[i]]

    auto_cp_idx, K_stat, pettitt_p = pettitt_test(d_uk_valid)
    auto_cp_label = labels_uk_valid[auto_cp_idx] if auto_cp_idx < len(labels_uk_valid) else labels_uk_valid[-1]

    col_a, col_b = st.columns([2, 1])
    with col_a:
        cp_lot = st.selectbox(
            "Change-point boundary (first 'suspect' lot)",
            options=labels,
            index=labels.index(auto_cp_label),
            help="Auto-detected by Pettitt test. Adjust manually if you have "
                 "contextual knowledge (e.g. a specific contract or shipment).",
        )
    with col_b:
        st.metric("Pettitt auto-detection",
                  auto_cp_label,
                  f"K = {K_stat:.0f},  p ≈ {pettitt_p:.3f}")
        if pettitt_p < 0.10:
            st.success("Statistically significant change point detected.")
        else:
            st.info(
                "Change point not statistically significant at α=0.10 "
                "(likely due to small n). Visual pattern still informative."
            )

    st.markdown("---")

    # ── Regime stats summary ───────────────────────────────────────────
    cp_i_in_valid = labels_uk_valid.index(cp_lot) if cp_lot in labels_uk_valid else len(labels_uk_valid)
    rs = regime_split_stats(d_uk_valid, cp_i_in_valid)

    c1, c2, c3 = st.columns(3)
    early_p_str = (f"{rs['early']['t_pval']:.4f} {pval_stars(rs['early']['t_pval'])}"
                   if pd.notna(rs['early'].get('t_pval')) else "—")
    late_p_str  = (f"{rs['late']['t_pval']:.4f} {pval_stars(rs['late']['t_pval'])}"
                   if pd.notna(rs['late'].get('t_pval')) else "—")
    btw_p_str   = (f"{rs['between_p']:.4f} {pval_stars(rs['between_p'])}"
                   if pd.notna(rs.get('between_p')) else "—")

    c1.metric(
        f"Early period (n={rs['early']['n']})",
        f"mean Δ = {rs['early']['mean']:+.0f} g" if pd.notna(rs['early']['mean']) else "—",
        f"p vs 0 = {early_p_str}  ·  Sinchi↑ {rs['early']['pct_pos']:.0f}%",
    )
    c2.metric(
        f"Recent period (n={rs['late']['n']})",
        f"mean Δ = {rs['late']['mean']:+.0f} g" if pd.notna(rs['late']['mean']) else "—",
        f"p vs 0 = {late_p_str}  ·  Sinchi↑ {rs['late']['pct_pos']:.0f}%",
    )
    c3.metric(
        "Early vs Recent (t-test)",
        f"p = {btw_p_str}",
        f"Δ in means = {(rs['late']['mean'] or 0) - (rs['early']['mean'] or 0):+.0f} g",
    )

    st.markdown(
        "> **How to interpret:** If the early-period p-value is high (not "
        "significant) and the recent-period p-value is low (significant), "
        "and the between-group test is also significant, that is strong "
        "statistical evidence of a regime change. If n is small, focus on "
        "the *direction* and *magnitude* of the shift rather than p-values alone."
    )

    st.markdown("---")
    st.subheader("Silver (Ag) — Timeline, CUSUM, and contract-level view")
    fig_rc = chart_uk_regime_change(comp, "Ag g", "Ag g/TM", labels,
                                    cp_lot_label=cp_lot,
                                    pct_mode=pct_delta)
    st.pyplot(fig_rc, use_container_width=True)
    add_download(fig_rc, "uk_regime_change_ag")
    plt.close(fig_rc)

    st.subheader("Silver — before vs after comparison")
    fig_sp = chart_uk_split_comparison(comp, labels, cp_lot,
                                       elem_col="Ag g", unit="g/TM",
                                       pct_mode=pct_delta)
    st.pyplot(fig_sp, use_container_width=True)
    add_download(fig_sp, "uk_split_ag")
    plt.close(fig_sp)

    st.subheader("Z-score anomaly flags — which lots are statistical outliers?")
    fig_z = chart_uk_outlier_flags(comp, labels, "Ag g", "g/TM",
                                   pct_mode=pct_delta)
    st.pyplot(fig_z, use_container_width=True)
    add_download(fig_z, "uk_zscore_ag")
    plt.close(fig_z)

    st.subheader("Lead (Pb) — same analysis")
    fig_rc2 = chart_uk_regime_change(comp, "Pb %", "Pb %", labels,
                                     cp_lot_label=cp_lot,
                                     pct_mode=pct_delta)
    st.pyplot(fig_rc2, use_container_width=True)
    add_download(fig_rc2, "uk_regime_change_pb")
    plt.close(fig_rc2)

    st.markdown("---")
    st.markdown(
        "**Limitations:**  \n"
        "- Sample sizes are small (typically n ≤ 15 UK paired lots), which "
        "limits statistical power. A p-value above 0.05 does not mean no "
        "change occurred — it may simply mean we need more lots.  \n"
        "- The Pettitt test assumes independence of observations; correlated "
        "lots (same mineral batch) may affect reliability.  \n"
        "- Use this tab alongside the Bolivia-stage results: if Bolivia bias "
        "*and* UK bias are both increasing in the same lots, that is stronger "
        "evidence than UK bias alone."
    )


# ── TAB 10: Sample Integrity (spike vs swap) ──────────────────────────
with tabs[10]:
    st.subheader("Sample integrity — spike vs swap")
    st.markdown(
        "Two competing manipulation hypotheses for the Bolivia-stage bias: "
        "**(A) Spike** — the physical sample is the same mineral Penfold pulled, "
        "but extra Ag (and possibly Pb) was added before the reading. "
        "**(B) Swap** — the sample is a physically different material "
        "(richer stockpile, reconstituted blend). "
        "They leave different chemical fingerprints, so we can separate them."
    )
    st.markdown(
        "The test uses the **UK-finals stage as a noise baseline**: both chains "
        "are unbiased there, so UK-stage Δ captures genuine sampling "
        "heterogeneity. Each Bolivia delta is expressed in multiples of that "
        "noise (σ). **Zn** is the strongest neutral tracer — it's a major bulk "
        "element with no payment role, so nobody has a motive to touch it. "
        "If Zn stays within UK noise while Ag blows past it, the sample was "
        "spiked. If Zn also jumps, the sample was swapped."
    )

    cons = compute_sample_consistency(comp)

    # Verdict overview
    st.markdown("#### Verdicts across all lots")
    fig_vbar = chart_integrity_verdict_bars(cons)
    st.pyplot(fig_vbar, use_container_width=True)
    add_download(fig_vbar, "integrity_verdicts")
    plt.close(fig_vbar)

    # UK baseline table
    with st.expander("UK-finals noise baseline per element (σ used for scoring)"):
        st.dataframe(integrity_uk_baseline_table(comp),
                     use_container_width=True, hide_index=True)

    # Scatter plots for both Bolivia stages
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("#### Natural stage")
        fig_n = chart_integrity_scatter(cons, stage="Natural")
        st.pyplot(fig_n, use_container_width=True)
        add_download(fig_n, "integrity_scatter_natural")
        plt.close(fig_n)
    with c2:
        st.markdown("#### Prepared stage")
        fig_p = chart_integrity_scatter(cons, stage="Prepared")
        st.pyplot(fig_p, use_container_width=True)
        add_download(fig_p, "integrity_scatter_prepared")
        plt.close(fig_p)

    # Per-lot fingerprint
    st.markdown("#### Per-lot fingerprint")
    st.markdown(
        "Each cell is the excess (in UK-σ units) of the Sinchi−Penfold delta "
        "for that element. Hot cells on blue (Ag/Pb) only → spike; hot cells "
        "on green (Zn) too → swap; hot cells on purple (impurities) only → "
        "targeted penalty understatement."
    )
    default_lot = "93301" if "93301" in labels else (labels[0] if labels else None)
    if default_lot is not None:
        sel_tr_int = st.selectbox("Select lot", options=labels,
                                  index=labels.index(default_lot),
                                  key="integrity_lot")
        fig_fp = chart_integrity_fingerprint(cons, sel_tr_int)
        st.pyplot(fig_fp, use_container_width=True)
        add_download(fig_fp, f"integrity_fingerprint_{sel_tr_int}")
        plt.close(fig_fp)

    # Ratio shifts
    st.markdown("#### Cross-chain ratio shifts")
    st.markdown(
        "Ratios that don't involve the payable element *shouldn't* move under "
        "a pure Ag spike. Large Pb/Zn shifts are consistent with Pb being "
        "added. Large As/Sb or Sb/Bi shifts suggest the impurity suite itself "
        "changed (swap signature)."
    )
    fig_rs = chart_integrity_ratio_shift(cons)
    st.pyplot(fig_rs, use_container_width=True)
    add_download(fig_rs, "integrity_ratio_shift")
    plt.close(fig_rs)

    # Full table
    with st.expander("Full per-lot × stage integrity table"):
        st.dataframe(cons, use_container_width=True, hide_index=True)


# ── TAB 11: Forensic Lot Analysis ─────────────────────────────────────
with tabs[11]:
    st.subheader("Forensic Lot Analysis")
    st.markdown(
        "Deep-dive into a single lot. Every value, every delta, every red flag. "
        "Select the lot you want to investigate — start with **93301**."
    )

    # ── Lot selector ──────────────────────────────────────────────────
    default_lot = "93301" if "93301" in labels else labels[0]
    sel_tr = st.selectbox("Select lot", options=labels,
                          index=labels.index(default_lot),
                          key="forensic_lot")
    r = _lot_row(comp, sel_tr)
    if r is None:
        st.error("Lot not found in data.")
        st.stop()

    lot_type = str(r.get("Lot_Type", "Pb/Ag"))
    dmt_val  = r.get("DMT", np.nan)

    # ── Top metric cards ──────────────────────────────────────────────
    st.markdown("---")
    st.markdown("#### Key deltas at a glance")
    c1, c2, c3, c4, c5 = st.columns(5)
    def _delta_metric(col, label, elem, pk, sk, fmt="+.0f"):
        pv = r.get(f"{pk}_{elem}", np.nan)
        sv = r.get(f"{sk}_{elem}", np.nan)
        if pd.notna(pv) and pd.notna(sv):
            d = float(sv - pv)
            pct = d / abs(float(pv)) * 100 if float(pv) != 0 else np.nan
            col.metric(label,
                       format(d, fmt),
                       f"{pct:+.1f}% of Penfold" if pd.notna(pct) else "")
        else:
            col.metric(label, "N/A", "")

    _delta_metric(c1, "Ag Δ Natural",  "Ag g", "Natural_Penfold",  "Natural_Sinchi")
    _delta_metric(c2, "Ag Δ Prepared", "Ag g", "Prepared_Penfold", "Prepared_Sinchi")
    _delta_metric(c3, "Ag Δ UK finals","Ag g", "UK_Penfold",       "UK_Sinchi")
    _delta_metric(c4, "Pb Δ Prepared", "Pb %", "Prepared_Penfold", "Prepared_Sinchi", "+.2f")
    # Extra payable Ag at UK finals for this lot
    lot_fin = fin_df[fin_df["TR"] == sel_tr]
    if len(lot_fin):
        extra_oz = lot_fin.iloc[0].get("Extra_Ag_oz", np.nan)
        c5.metric("Extra payable Ag (UK)",
                  f"{extra_oz:+,.1f} oz" if pd.notna(extra_oz) else "N/A",
                  f"DMT = {dmt_val:.1f} t" if pd.notna(dmt_val) else "DMT unknown")
    else:
        c5.metric("Extra payable Ag (UK)", "N/A", "")

    # ── Full raw values table ──────────────────────────────────────────
    st.markdown("---")
    st.markdown("#### All assay values — every stage, every element")
    cats = [
        ("Natural_Penfold",  "Natural  · Penfold (SpectrAA)"),
        ("Natural_Sinchi",   "Natural  · Sinchi  (SavantAA)"),
        ("Prepared_Penfold", "Prepared · Penfold (Castro)"),
        ("Prepared_Sinchi",  "Prepared · Sinchi  (Conde)"),
        ("UK_Penfold",       "UK Final · Penfold sample"),
        ("UK_Sinchi",        "UK Final · Sinchi sample"),
        ("S-Side",           "S-Side   · Independent benchmark"),
    ]
    elems_all  = ["Ag g", "Pb %", "Zn %", "As %", "Sb %", "Sn %", "Bi %"]
    table_rows = []
    for cat_key, cat_label in cats:
        row_d = {"Stage / Chain": cat_label}
        for el in elems_all:
            col_name = f"{cat_key}_{el}"
            v = r.get(col_name, np.nan)
            row_d[el] = round(float(v), 3) if pd.notna(v) else np.nan
        table_rows.append(row_d)
    raw_df = pd.DataFrame(table_rows).set_index("Stage / Chain")
    st.dataframe(raw_df.fillna("—"), use_container_width=True)

    # ── Delta table ────────────────────────────────────────────────────
    st.markdown("#### Deltas (Sinchi − Penfold) per stage")
    delta_rows = []
    for stage, pk, sk in [("Natural",  "Natural_Penfold",  "Natural_Sinchi"),
                           ("Prepared", "Prepared_Penfold", "Prepared_Sinchi"),
                           ("UK Final", "UK_Penfold",       "UK_Sinchi")]:
        row_d = {"Stage": stage}
        for el in elems_all:
            pv = r.get(f"{pk}_{el}", np.nan)
            sv = r.get(f"{sk}_{el}", np.nan)
            if pd.notna(pv) and pd.notna(sv):
                d = float(sv - pv)
                pct = d / abs(float(pv)) * 100 if float(pv) != 0 else np.nan
                row_d[el] = f"{d:+.2f} ({pct:+.1f}%)" if pd.notna(pct) else f"{d:+.2f}"
            else:
                row_d[el] = np.nan
        delta_rows.append(row_d)
    delta_df = pd.DataFrame(delta_rows).set_index("Stage")
    st.dataframe(delta_df.fillna("—"), use_container_width=True)

    # ── Stage progression charts ───────────────────────────────────────
    st.markdown("---")
    st.markdown("#### Stage progression — how each chain's value evolves")
    st.caption(
        "A chain that is internally consistent (Natural ≈ Prepared ≈ UK) "
        "is analysing the same material throughout. A chain that jumps up "
        "between stages may have substituted or enriched the sample."
    )
    payable_elems = ["Ag g", "Pb %"] if lot_type == "Pb/Ag" else ["Ag g", "Zn %"]
    payable_units = ["g/TM", "%"]
    fig_prog = chart_forensic_progression(r, payable_elems, payable_units)
    st.pyplot(fig_prog, use_container_width=True)
    add_download(fig_prog, f"forensic_progression_{sel_tr}")
    plt.close(fig_prog)

    st.markdown("#### All elements — progression")
    fig_prog_all = chart_forensic_progression(
        r,
        ["Ag g", "Pb %", "As %", "Sb %", "Sn %", "Bi %"],
        ["g/TM", "%", "%", "%", "%", "%"]
    )
    st.pyplot(fig_prog_all, use_container_width=True)
    add_download(fig_prog_all, f"forensic_progression_all_{sel_tr}")
    plt.close(fig_prog_all)

    # ── Within-chain processing jump ──────────────────────────────────
    st.markdown("---")
    st.markdown("#### Within-chain processing jump: Prepared − Natural")
    st.caption(
        "How much does each chain's assay change between taking the natural "
        "sample and the prepared sample? They are the same physical material — "
        "large divergence between the two chains at this step is a red flag."
    )
    fig_jump = chart_forensic_within_chain(r)
    st.pyplot(fig_jump, use_container_width=True)
    add_download(fig_jump, f"forensic_within_chain_{sel_tr}")
    plt.close(fig_jump)

    # ── Delta heatmap ──────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("#### Delta heatmap — all elements × all stages")
    st.caption("Red = Sinchi higher. Blue = Penfold higher. Last column = dataset average for context.")
    fig_heat = chart_forensic_delta_heatmap(r, comp)
    st.pyplot(fig_heat, use_container_width=True)
    add_download(fig_heat, f"forensic_heatmap_{sel_tr}")
    plt.close(fig_heat)

    # ── Context: where does this lot sit in the distribution? ──────────
    st.markdown("---")
    st.markdown("#### Statistical context — how does this lot compare to all others?")
    for stage_key, stage_label in [("Natural","Natural"),
                                    ("Prepared","Prepared"),
                                    ("UK","UK finals")]:
        pk_col = f"{stage_key}_Penfold_Ag g"
        sk_col = f"{stage_key}_Sinchi_Ag g"
        if pk_col in comp.columns and sk_col in comp.columns:
            fig_ctx = chart_forensic_context(comp, sel_tr, "Ag g", "g/TM", stage_key)
            st.pyplot(fig_ctx, use_container_width=True)
            add_download(fig_ctx, f"forensic_context_{stage_key}_{sel_tr}")
            plt.close(fig_ctx)

    # ── S-Side three-way ──────────────────────────────────────────────
    ss_present = pd.notna(r.get("S-Side_Ag g", np.nan)) or pd.notna(r.get("S-Side_Pb %", np.nan))
    if ss_present and show_sside:
        st.markdown("---")
        st.markdown("#### S-Side three-way: Penfold UK vs Sinchi UK vs independent benchmark")
        fig_ss = chart_forensic_sside(r, sel_tr)
        if fig_ss:
            st.pyplot(fig_ss, use_container_width=True)
            add_download(fig_ss, f"forensic_sside_{sel_tr}")
            plt.close(fig_ss)
    elif not ss_present:
        st.info("No S-Side benchmark available for this lot.")

    # ── Z-score table ──────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("#### Z-score: how anomalous is this lot at each stage?")
    st.caption(
        "Z-score = (this lot's delta − mean of all lots) / std of all lots. "
        "|z| > 2 = unusual at 5%, |z| > 3 = rare at 0.3%, |z| > 5 = essentially impossible by chance."
    )
    z_rows = []
    for stage_key, stage_label in [("Natural","Natural"),("Prepared","Prepared"),("UK","UK finals")]:
        for el in ["Ag g", "Pb %"]:
            pk = f"{stage_key}_Penfold_{el}"
            sk = f"{stage_key}_Sinchi_{el}"
            if pk not in comp.columns or sk not in comp.columns:
                continue
            p_all = pd.to_numeric(comp[pk], errors="coerce")
            s_all = pd.to_numeric(comp[sk], errors="coerce")
            d_all = (s_all - p_all).dropna()
            pv = r.get(pk, np.nan); sv = r.get(sk, np.nan)
            if pd.notna(pv) and pd.notna(sv) and len(d_all) >= 3:
                this_d = float(sv - pv)
                mn = d_all.mean(); sd = d_all.std(ddof=1)
                z  = (this_d - mn) / sd if sd > 0 else np.nan
                flag = ("🔴 EXTREME" if abs(z) > 5
                        else ("🟠 HIGH" if abs(z) > 3
                        else ("🟡 ELEVATED" if abs(z) > 2
                        else "✅ Normal"))) if pd.notna(z) else np.nan
                z_rows.append({
                    "Stage": stage_label, "Element": el,
                    "This lot Δ": round(this_d, 2),
                    "Dataset mean Δ": round(mn, 2),
                    "Dataset std": round(sd, 2),
                    "Z-score": round(z, 2) if pd.notna(z) else np.nan,
                    "Assessment": flag,
                })
    if z_rows:
        z_df = pd.DataFrame(z_rows)
        st.dataframe(z_df.fillna("—"), use_container_width=True, hide_index=True)

    # ── Auto-generated narrative ───────────────────────────────────────
    st.markdown("---")
    st.markdown("#### Auto-generated forensic summary")
    findings = []

    # Ag natural
    ag_nat_p = r.get("Natural_Penfold_Ag g", np.nan)
    ag_nat_s = r.get("Natural_Sinchi_Ag g",  np.nan)
    if pd.notna(ag_nat_p) and pd.notna(ag_nat_s):
        d = float(ag_nat_s - ag_nat_p)
        pct = d / ag_nat_p * 100
        sign = "HIGHER" if d > 0 else "LOWER"
        findings.append(
            f"**Natural stage (Ag):** Sinchi's natural sample reads "
            f"**{abs(d):.0f} g/TM {sign}** than Penfold's "
            f"({ag_nat_s:.0f} vs {ag_nat_p:.0f}, delta = {d:+.0f} g, {pct:+.1f}%)."
        )

    # Ag prepared
    ag_prep_p = r.get("Prepared_Penfold_Ag g", np.nan)
    ag_prep_s = r.get("Prepared_Sinchi_Ag g",  np.nan)
    if pd.notna(ag_prep_p) and pd.notna(ag_prep_s):
        d = float(ag_prep_s - ag_prep_p)
        pct = d / ag_prep_p * 100
        # Within-chain jump
        if pd.notna(ag_nat_p) and pd.notna(ag_prep_p):
            jump_p = float(ag_prep_p - ag_nat_p)
            jump_s = float(ag_prep_s - ag_nat_s) if pd.notna(ag_nat_s) else np.nan
            jump_txt = (f" Penfold's prepared sample moved {jump_p:+.0f} g from natural; "
                        f"Sinchi's moved {jump_s:+.0f} g — a within-chain divergence of "
                        f"{abs(jump_s - jump_p):.0f} g." if pd.notna(jump_s) else "")
        else:
            jump_txt = ""
        findings.append(
            f"**Prepared stage (Ag):** Sinchi = {ag_prep_s:.0f} g vs Penfold = {ag_prep_p:.0f} g "
            f"(delta = {d:+.0f} g, {pct:+.1f}%).{jump_txt}"
        )

    # Ag UK
    ag_uk_p = r.get("UK_Penfold_Ag g", np.nan)
    ag_uk_s = r.get("UK_Sinchi_Ag g",  np.nan)
    if pd.notna(ag_uk_p) and pd.notna(ag_uk_s):
        d = float(ag_uk_s - ag_uk_p)
        pct = d / ag_uk_p * 100
        # Context vs baseline
        uk_p_all = pd.to_numeric(comp["UK_Penfold_Ag g"], errors="coerce")
        uk_s_all = pd.to_numeric(comp["UK_Sinchi_Ag g"],  errors="coerce")
        d_all = (uk_s_all - uk_p_all).dropna()
        mn = d_all.mean(); sd = d_all.std(ddof=1)
        z  = (d - mn) / sd if sd > 0 else np.nan
        z_txt = f" Z-score vs dataset: **{z:+.1f}σ**." if pd.notna(z) else ""
        findings.append(
            f"**UK finals (Ag):** Sinchi = {ag_uk_s:.0f} g vs Penfold = {ag_uk_p:.0f} g "
            f"(delta = {d:+.0f} g, {pct:+.1f}%).{z_txt}"
        )

    # S-Side
    ss_ag = r.get("S-Side_Ag g", np.nan)
    if pd.notna(ss_ag) and pd.notna(ag_uk_p) and pd.notna(ag_uk_s):
        d_p = float(ag_uk_p - ss_ag)
        d_s = float(ag_uk_s - ss_ag)
        closer = "Penfold" if abs(d_p) < abs(d_s) else "Sinchi"
        findings.append(
            f"**S-Side benchmark (Ag):** Independent = {ss_ag:.0f} g/TM. "
            f"Penfold UK is {d_p:+.0f} g from S-Side; Sinchi UK is {d_s:+.0f} g from S-Side. "
            f"S-Side aligns more closely with **{closer}**."
        )

    # Z-score highlight
    extreme = [row for row in z_rows if pd.notna(row.get("Z-score")) and isinstance(row.get("Z-score"), float) and abs(row["Z-score"]) > 3]
    if extreme:
        ex_strs = [f"{row['Stage']} {row['Element']} z={row['Z-score']:+.1f}" for row in extreme]
        findings.append(
            f"**Statistical outliers (|z| > 3):** {', '.join(ex_strs)}. "
            "Results at this magnitude cannot be explained by normal analytical variability."
        )
    else:
        findings.append("**Statistical context:** No extreme z-scores (|z| > 3) detected at this lot.")

    # Physical impact
    if len(lot_fin):
        extra_ag = lot_fin.iloc[0].get("Extra_Ag_oz", np.nan)
        extra_pb = lot_fin.iloc[0].get("Extra_Pb_t", np.nan)
        dmt_str = f"{float(dmt_val):.1f}" if pd.notna(dmt_val) else "N/A"
        parts = []
        if pd.notna(extra_ag) and extra_ag != 0:
            parts.append(f"Ag: **{extra_ag:+,.1f} extra payable oz**")
        if pd.notna(extra_pb) and extra_pb != 0:
            parts.append(f"Pb: **{extra_pb:+,.4f} extra payable t**")
        if parts:
            findings.append(
                f"**Physical impact (UK finals basis):** {', '.join(parts)}. "
                f"DMT = {dmt_str} t."
            )

    for f_txt in findings:
        st.markdown(f"- {f_txt}")


# ── TAB 11: Weight-Adjusted Impact ────────────────────────────────────
with tabs[11]:
    st.subheader("Weight-Adjusted Impact Analysis — UK Finals")
    st.markdown(
        "Uses only **UK final assays** (the settlement-determining results). "
        "Natural and prepared assays are reconciled once finals arrive, so only "
        "finals represent the true payment impact.  \n"
        "**Impact = delta × DMT** — not divided by 2, so you see the full "
        "discrepancy between the two chains before averaging."
    )
    st.info(
        "💡 To convert to actual payment effect, divide impact by 2 "
        "(contract averages the two chains). The full value is shown here "
        "so you can compare lots on equal footing."
    )

    st.subheader("Impact heatmap — who benefits at each lot?")
    st.markdown(
        "Most lots are blue (Penfold higher at UK), but the **few red lots are "
        "disproportionately large** — high delta combined with high tonnage. "
        "The net totals at the bottom show who benefits overall."
    )
    fig_ihm = chart_impact_heatmap(comp, labels)
    st.pyplot(fig_ihm, use_container_width=True)
    add_download(fig_ihm, "impact_heatmap")
    plt.close(fig_ihm)

    st.markdown("---")

    # Build working table — Pb/Ag lots with UK finals and DMT
    imp = comp[comp["Lot_Type"] == "Pb/Ag"].copy()
    imp = imp[imp["DMT"].notna()].copy()
    imp["dmt"] = imp["DMT"].astype(float)

    # UK finals deltas only
    imp["ag_delta"] = (pd.to_numeric(imp["UK_Sinchi_Ag g"],  errors="coerce")
                     - pd.to_numeric(imp["UK_Penfold_Ag g"], errors="coerce"))
    imp["pb_delta"] = (pd.to_numeric(imp["UK_Sinchi_Pb %"],  errors="coerce")
                     - pd.to_numeric(imp["UK_Penfold_Pb %"], errors="coerce"))

    # Impact = delta × DMT  (no ÷2)
    imp["ag_impact"] = imp["ag_delta"] * imp["dmt"]
    imp["pb_impact"] = imp["pb_delta"] * imp["dmt"]

    imp_valid_ag = imp[imp["ag_impact"].notna()].copy()
    imp_valid_pb = imp[imp["pb_impact"].notna()].copy()

    # ── Chart 1: Bubble chart — delta vs DMT, bubble = |impact| ────────
    st.markdown("---")
    st.markdown("#### Bubble chart: UK delta × tonnage at a glance")
    st.caption(
        "Each bubble is one lot. X = UK Ag delta (Sinchi−Penfold), Y = DMT. "
        "Bubble area ∝ |delta × DMT|. "
        "Red = Sinchi higher, blue = Penfold higher. "
        "Large bubbles far right = largest payment impact."
    )
    fig_bub, ax_bub = plt.subplots(figsize=(10, 5.5))
    # Auto-scale: normalise bubble sizes relative to largest impact
    imp_vals = imp_valid_ag["ag_impact"].abs()
    scale = 2500 / imp_vals.max() if imp_vals.max() > 0 else 1
    for _, row in imp_valid_ag.iterrows():
        d       = row["ag_delta"]
        dmt     = row["dmt"]
        imp_val = abs(row["ag_impact"])
        color   = C_SINCHI if d > 0 else C_PENFOLD
        size    = max(40, imp_val * scale)
        ax_bub.scatter(d, dmt, s=size, color=color, alpha=0.65,
                       edgecolors="white", linewidths=0.8, zorder=3)
        # Large bubbles: label inside; small bubbles: label outside with arrow
        bubble_radius_pts = np.sqrt(size / np.pi)
        if bubble_radius_pts >= 18:
            # Fits inside — white text with dark outline for readability
            ax_bub.annotate(
                f"{row['TR']}\n{d:+.0f}\n{dmt:.0f}t",
                (d, dmt), fontsize=6, ha="center", va="center",
                color="white", fontweight="bold", zorder=5,
                bbox=dict(boxstyle="round,pad=0.15", fc=color, ec="none",
                          alpha=0.0),
            )
        else:
            # Too small — label outside with a connecting line
            ax_bub.annotate(
                f"{row['TR']}\n{d:+.0f} / {dmt:.0f}t",
                (d, dmt), fontsize=6.5, ha="left", va="bottom",
                color="#111", fontweight="bold", zorder=5,
                xytext=(8, 8), textcoords="offset points",
                arrowprops=dict(arrowstyle="-", color="#555", lw=0.7),
            )
    ax_bub.axvline(0, color="black", lw=0.8, ls="--", zorder=2)
    ax_bub.set_xlabel("Ag delta — UK finals (Sinchi − Penfold)  [g/TM]", fontsize=9)
    ax_bub.set_ylabel("DMT (dry metric tonnes)", fontsize=9)
    ax_bub.set_title("Bubble chart: UK Ag delta × DMT  —  bubble area ∝ |delta × DMT|",
                     pad=6)
    # Bubble size legend using 3 reference values
    ref_vals = [imp_vals.quantile(0.25), imp_vals.median(), imp_vals.max()]
    for rv in ref_vals:
        ax_bub.scatter([], [], s=max(40, rv * scale), color="#aaa", alpha=0.7,
                       edgecolors="white", label=f"{rv:,.0f} g·t")
    ax_bub.legend(title="Bubble = |impact| (g·t)", fontsize=7,
                  title_fontsize=7, loc="upper left", framealpha=0.9)
    fig_bub.tight_layout()
    st.pyplot(fig_bub, use_container_width=True)
    add_download(fig_bub, "impact_bubble_ag")
    plt.close(fig_bub)

    # ── Chart 2: Impact bars sorted by magnitude ────────────────────────
    st.markdown("---")
    st.markdown("#### Total impact per lot — sorted by magnitude")
    st.caption(
        "Bars show **delta × DMT** (UK finals, not ÷2). "
        "Sorted largest to smallest. DMT shown beneath each lot label."
    )
    fig_imp, (ax_ag, ax_pb) = plt.subplots(1, 2, figsize=(14, 5))

    for ax, df_i, col, ylabel, title, unit_lbl in [
        (ax_ag, imp_valid_ag.sort_values("ag_impact", key=abs, ascending=False),
         "ag_impact", "Impact  (g·t)", "Silver Ag — UK final delta × DMT", "g·t"),
        (ax_pb, imp_valid_pb.sort_values("pb_impact", key=abs, ascending=False),
         "pb_impact", "Impact  (%·t)", "Lead Pb — UK final delta × DMT", "%·t"),
    ]:
        vals   = df_i[col].values
        xlbls  = df_i["TR"].tolist()
        dmt_v  = df_i["dmt"].values
        colors = [C_SINCHI if v > 0 else C_PENFOLD for v in vals]
        xpos   = np.arange(len(vals))

        ax.bar(xpos, vals, 0.6, color=colors, alpha=0.80, zorder=3)
        ax.axhline(0, color="black", lw=0.5, zorder=2)
        for xi, (val, lbl) in enumerate(zip(vals, xlbls)):
            ax.text(xi, val + np.sign(val) * abs(val) * 0.03,
                    f"{val:+,.0f}", ha="center",
                    va="bottom" if val >= 0 else "top",
                    fontsize=7, color="#111", zorder=5)
        ax.set_xticks(xpos)
        ax.set_xticklabels(
            [f"{lbl}\n{d:.0f} t" for lbl, d in zip(xlbls, dmt_v)],
            rotation=45, ha="right", fontsize=7.5
        )
        ax.set_ylabel(ylabel, fontsize=9)
        ax.set_title(title, fontsize=10, pad=6)
        total = float(pd.Series(vals).dropna().sum())
        total_color = C_SINCHI if total > 0 else C_PENFOLD
        # Horizontal total line across the full chart
        ax.axhline(total, color=total_color, lw=1.8, ls="--", zorder=6,
                   label=f"Net total: {total:+,.0f} {unit_lbl}")
        ax.legend(fontsize=7.5, loc="lower right", framealpha=0.92)
        # Summary annotation
        ax.text(0.98, 0.97,
                f"Net: {total:+,.0f} {unit_lbl}\n"
                f"{'▲ Sinchi benefits' if total > 0 else '▼ Penfold benefits'}\n"
                f"({int((vals > 0).sum())} lots up, "
                f"{int((vals < 0).sum())} lots down)",
                transform=ax.transAxes, fontsize=7.5,
                ha="right", va="top", style="italic",
                color=total_color,
                bbox=dict(boxstyle="round,pad=0.3", fc="white",
                          ec=total_color, alpha=0.92, lw=1.2))

    fig_imp.tight_layout()
    st.pyplot(fig_imp, use_container_width=True)
    add_download(fig_imp, "impact_sorted_bars")
    plt.close(fig_imp)

    # ── Chart 3: Cumulative impact over time ────────────────────────────
    st.markdown("---")
    st.markdown("#### Cumulative impact over time (UK finals)")
    st.caption(
        "Running total of delta × DMT in chronological order. "
        "A steadily rising line = systematic overpayment accumulating over time. "
        "Each point annotated with lot name, that lot's contribution, and DMT."
    )
    imp_chron_ag = imp_valid_ag.sort_values("TR")
    imp_chron_pb = imp_valid_pb.sort_values("TR")

    fig_cum, (ax_c1, ax_c2) = plt.subplots(2, 1, figsize=(12, 7),
                                            gridspec_kw={"hspace": 0.45})
    for ax_c, df_c, col, ylabel, title, unit_lbl in [
        (ax_c1, imp_chron_ag, "ag_impact",
         "Cumulative g·t", "Silver — cumulative UK impact over time", "g·t"),
        (ax_c2, imp_chron_pb, "pb_impact",
         "Cumulative %·t", "Lead — cumulative UK impact over time", "%·t"),
    ]:
        xs   = np.arange(len(df_c))
        vals = df_c[col].values
        cumv = np.cumsum(vals)
        dmt_c = df_c["dmt"].values
        trs   = df_c["TR"].tolist()

        for i in range(len(xs)):
            c = C_SINCHI if vals[i] > 0 else C_PENFOLD
            if i < len(xs) - 1:
                ax_c.fill_between([xs[i], xs[i+1]], [cumv[i], cumv[i+1]],
                                  alpha=0.15, color=c, zorder=1)
        ax_c.plot(xs, cumv, "o-", color="#333", lw=2, ms=5, zorder=4)
        ax_c.axhline(0, color="black", lw=0.5, ls="--", zorder=2)

        for xi, (cv, dv, tr, dmt_i) in enumerate(zip(cumv, vals, trs, dmt_c)):
            ax_c.annotate(
                f"{tr}\n({dv:+,.0f})\n{dmt_i:.0f} t",
                (xi, cv), textcoords="offset points",
                xytext=(0, 10 if dv >= 0 else -24),
                ha="center", fontsize=6, color="#333", zorder=5
            )
        ax_c.set_xticks(xs)
        ax_c.set_xticklabels(
            [f"{tr}\n{d:.0f} t" for tr, d in zip(trs, dmt_c)],
            rotation=45, ha="right", fontsize=7
        )
        ax_c.set_ylabel(ylabel, fontsize=9)
        ax_c.set_title(title, fontsize=10, pad=6)
        final_val = cumv[-1] if len(cumv) else 0
        ax_c.text(0.98, 0.03, f"Final cumulative: {final_val:+,.0f} {unit_lbl}",
                  transform=ax_c.transAxes, fontsize=8,
                  ha="right", va="bottom", fontweight="bold",
                  color=C_SINCHI if final_val > 0 else C_PENFOLD)

    fig_cum.tight_layout()
    st.pyplot(fig_cum, use_container_width=True)
    add_download(fig_cum, "impact_cumulative")
    plt.close(fig_cum)

    # ── Chart 4: delta vs DMT scatter ──────────────────────────────────
    st.markdown("---")
    st.markdown("#### Is the bias correlated with lot size?")
    st.caption(
        "If Sinchi strategically inflates bigger lots more, expect a positive "
        "correlation between DMT and delta. A flat regression = indiscriminate."
    )
    fig_scat, (ax_s1, ax_s2) = plt.subplots(1, 2, figsize=(12, 4.5))
    for ax_s, df_s, dcol, title, unit_lbl in [
        (ax_s1, imp_valid_ag, "ag_delta", "Silver: DMT vs UK Ag delta", "g/TM"),
        (ax_s2, imp_valid_pb, "pb_delta", "Lead: DMT vs UK Pb delta", "%"),
    ]:
        xs   = df_s["dmt"].values
        ys   = df_s[dcol].values
        mask = pd.notna(xs) & pd.notna(ys)
        ax_s.scatter(xs[mask], ys[mask],
                     c=[C_SINCHI if v > 0 else C_PENFOLD for v in ys[mask]],
                     s=60, alpha=0.85, edgecolors="white", lw=0.6, zorder=3)
        for x_i, y_i, tr_i in zip(xs[mask], ys[mask], df_s["TR"].values[mask]):
            ax_s.annotate(tr_i, (x_i, y_i), fontsize=6.5,
                          xytext=(3, 3), textcoords="offset points", color="#555")
        if mask.sum() >= 3:
            slope, intercept, r_val, p_val, _ = sp_stats.linregress(xs[mask], ys[mask])
            xfit = np.linspace(xs[mask].min(), xs[mask].max(), 100)
            ax_s.plot(xfit, slope * xfit + intercept, "--",
                      color="#EF6C00", lw=1.5, alpha=0.8,
                      label=f"r = {r_val:.2f},  p = {p_val:.3f}{'*' if p_val < 0.05 else ''}")
            ax_s.legend(fontsize=7.5, loc="upper right", framealpha=0.9)
        ax_s.axhline(0, color="black", lw=0.5, ls="--", zorder=2)
        ax_s.set_xlabel("DMT (dry metric tonnes)", fontsize=9)
        ax_s.set_ylabel(f"UK delta ({unit_lbl})", fontsize=9)
        ax_s.set_title(title, fontsize=10, pad=6)

    fig_scat.tight_layout()
    st.pyplot(fig_scat, use_container_width=True)
    add_download(fig_scat, "impact_dmt_scatter")
    plt.close(fig_scat)

    # ── Summary table ──────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("#### Summary table — impact ranked by |Ag impact|")
    tbl = imp_valid_ag[["TR", "dmt", "ag_delta", "ag_impact"]].copy()
    tbl = tbl.merge(
        imp_valid_pb[["TR", "pb_delta", "pb_impact"]],
        on="TR", how="left"
    )
    tbl = tbl.reindex(tbl["ag_impact"].abs().sort_values(ascending=False).index)
    tbl = tbl.reset_index(drop=True)
    tbl.columns = ["Lot", "DMT (t)", "UK Ag delta (g/TM)", "Ag impact (g·t)",
                   "UK Pb delta (%)", "Pb impact (%·t)"]
    for col in ["UK Ag delta (g/TM)", "Ag impact (g·t)", "UK Pb delta (%)", "Pb impact (%·t)"]:
        tbl[col] = tbl[col].map(lambda v: f"{v:+,.1f}" if pd.notna(v) else "—")
    tbl["DMT (t)"] = tbl["DMT (t)"].map(lambda v: f"{v:.1f}")
    st.dataframe(tbl, use_container_width=True, hide_index=True)


# ── TAB 12: Export ────────────────────────────────────────────────────
with tabs[12]:
    st.subheader("Download complete analysis")
    xl_buf = build_excel(comp, fin_df, stats_data)
    st.download_button(
        "⬇  Download Excel workbook (5 sheets)",
        xl_buf,
        file_name="sinchi_assay_analysis.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    st.caption(
        "Contains: Cleaned Assay Data · Financial Impact · Statistical Tests "
        "· Lot-by-Lot Deltas (absolute + %) · Data Completeness"
    )
    st.info(
        "💡 All charts are rendered at 200 DPI — suitable for Word / PowerPoint "
        "insertion. Use the ⬇ button below each chart to download as PNG."
    )
