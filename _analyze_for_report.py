"""
Standalone analysis script to compute the numbers needed for the internal report.
Loads data using the dashboard's logic, excludes TR74101, prints all key statistics.
"""
import sys
from unittest.mock import MagicMock

# Mock streamlit so we can import dashboard functions without running the app
_mock_st = MagicMock()
_mock_st.cache_data = lambda **kwargs: (lambda f: f)
sys.modules["streamlit"] = _mock_st

import pandas as pd
import numpy as np
from scipy import stats as sp_stats
from pathlib import Path

# Load function source up to the Streamlit app section
src = Path("sinchi_dashboard.py").read_text()
# Cut off at the Streamlit app section marker
cut = src.index("#                      S T R E A M L I T   A P P")
func_src = src[:cut]

ns = {}
exec(func_src, ns)

load_data         = ns["load_data"]
paired_stats      = ns["paired_stats"]
pval_stars        = ns["pval_stars"]
cohen_label       = ns["cohen_label"]
compute_physical_impact = ns["compute_physical_impact"]
pettitt_test      = ns["pettitt_test"]
STAGES            = ns["STAGES"]
ELEMENTS          = ns["ELEMENTS"]

# Load data, exclude TR74101
comp = load_data()
comp = comp[comp["TR"] != "74101"].reset_index(drop=True)

print(f"Lots analyzed: {len(comp)}")
print(f"TRs: {comp['TR'].tolist()}")
print()

# Separate Pb/Ag from Zn/Ag
comp_pbag = comp[comp["Lot_Type"] == "Pb/Ag"].reset_index(drop=True)
comp_znag = comp[comp["Lot_Type"] == "Zn/Ag"].reset_index(drop=True)
print(f"Pb/Ag lots: {len(comp_pbag)}")
print(f"Zn/Ag lots: {len(comp_znag)}")
print()

# ───────────── Per-stage stats for Ag and Pb (Pb/Ag lots only) ─────────────
print("=" * 70)
print("PAIRED STATISTICS — Pb/Ag lots only (excluding TR74101)")
print("=" * 70)

for elem_col, elem_name in [("Ag g", "Silver (Ag)"), ("Pb %", "Lead (Pb)"),
                             ("As %", "Arsenic"), ("Sb %", "Antimony"),
                             ("Sn %", "Tin"), ("Bi %", "Bismuth")]:
    print(f"\n>>> {elem_name} [{elem_col}]")
    for stage_lbl, pk, sk, _, _ in STAGES:
        p = comp_pbag[f"{pk}_{elem_col}"]
        s = comp_pbag[f"{sk}_{elem_col}"]
        r = paired_stats(p, s)
        if r.get("insufficient"):
            print(f"  {stage_lbl:12} n={r['n']:>2}  (insufficient)")
            continue
        print(f"  {stage_lbl:12} n={r['n']:>2}  "
              f"mean Δ = {r['mean_delta']:+8.3f}  "
              f"Sinchi-higher = {r['pct_sinchi_higher']:>5.1f}%  "
              f"t-p = {r['t_pval']:.4f} {pval_stars(r['t_pval'])}  "
              f"Wil-p = {r['wilcoxon_pval']:.4f} {pval_stars(r['wilcoxon_pval'])}  "
              f"sign-p = {r['sign_pval']:.4f} {pval_stars(r['sign_pval'])}  "
              f"d = {r['cohen_d']:+.3f} ({cohen_label(r['cohen_d'])})  "
              f"95%CI=[{r['ci95_lo']:+.2f}, {r['ci95_hi']:+.2f}]")

# ───────────── Physical impact ─────────────
print()
print("=" * 70)
print("PHYSICAL IMPACT — UK finals (Pb/Ag lots only)")
print("=" * 70)
fin = compute_physical_impact(comp_pbag)
ag_vals = fin["Extra_Ag_oz"].dropna()
pb_vals = fin["Extra_Pb_t"].dropna()
print(f"\nExtra payable Ag (troy oz) per lot at UK finals:")
for _, r in fin.iterrows():
    v = r["Extra_Ag_oz"]
    if pd.notna(v):
        dmt = r["DMT"]
        delta = r.get("UK finals_Delta_Ag", np.nan)
        print(f"  TR{r['TR']:8}  DMT={dmt:>7.1f} t   Δ_Ag = {delta:+7.1f} g/TM   Extra = {v:+8.2f} oz")

print(f"\n  NET TOTAL Ag: {ag_vals.sum():+.2f} oz  "
      f"(pos-only: {ag_vals[ag_vals>0].sum():.2f}, neg-only: {ag_vals[ag_vals<0].sum():.2f})")
print(f"  n lots with valid Ag UK data: {len(ag_vals)}")
print(f"  n lots where Sinchi benefits (positive oz): {(ag_vals > 0).sum()}")

print(f"\nExtra payable Pb (tonnes) per lot at UK finals:")
for _, r in fin.iterrows():
    v = r["Extra_Pb_t"]
    if pd.notna(v):
        dmt = r["DMT"]
        delta = r.get("UK finals_Delta_Pb", np.nan)
        print(f"  TR{r['TR']:8}  DMT={dmt:>7.1f} t   Δ_Pb = {delta:+6.2f} %     Extra = {v:+7.4f} t")

print(f"\n  NET TOTAL Pb: {pb_vals.sum():+.4f} t  "
      f"(pos-only: {pb_vals[pb_vals>0].sum():.4f}, neg-only: {pb_vals[pb_vals<0].sum():.4f})")
print(f"  n lots with valid Pb UK data: {len(pb_vals)}")
print(f"  n lots where Sinchi benefits (positive t): {(pb_vals > 0).sum()}")

# ───────────── Change point analysis for UK finals Ag ─────────────
print()
print("=" * 70)
print("CHANGE POINT ANALYSIS — UK finals Ag deltas (Pb/Ag lots)")
print("=" * 70)
labels = comp_pbag["TR"].tolist()
uk_p = comp_pbag["UK_Penfold_Ag g"].values
uk_s = comp_pbag["UK_Sinchi_Ag g"].values
d    = uk_s - uk_p
mask = pd.notna(d)
d_valid = d[mask]
lbl_valid = [l for l, m in zip(labels, mask) if m]

if len(d_valid) >= 4:
    cp_idx, K, p_val = pettitt_test(d_valid)
    print(f"  Pettitt cp_idx={cp_idx} (label '{lbl_valid[cp_idx]}')  K={K:.2f}  p={p_val:.4f}")
    early = d_valid[:cp_idx]
    late  = d_valid[cp_idx:]
    print(f"  Early (pre-{lbl_valid[cp_idx]}, n={len(early)}): mean={early.mean():+.1f}, "
          f"%pos={(early>0).sum()/len(early)*100:.0f}%")
    print(f"  Late  (from {lbl_valid[cp_idx]}, n={len(late)}):  mean={late.mean():+.1f}, "
          f"%pos={(late>0).sum()/len(late)*100:.0f}%")

# ───────────── Extreme outlier lots (UK finals) ─────────────
print()
print("=" * 70)
print("OUTLIER LOTS — UK finals Ag z-scores (Pb/Ag lots)")
print("=" * 70)
mu_ag = np.median(d_valid)
sd_ag = np.std(d_valid, ddof=1)
print(f"  Baseline: median={mu_ag:+.1f} g/TM, σ={sd_ag:.1f} g/TM")
for lbl, dv in zip(lbl_valid, d_valid):
    z = (dv - mu_ag) / sd_ag
    if abs(z) > 2:
        flag = "EXTREME" if abs(z) > 3 else "HIGH" if abs(z) > 2 else ""
        print(f"  TR{lbl:8}  Δ={dv:+7.1f}  z={z:+.2f}  [{flag}]")

# UK finals Pb
print()
print("OUTLIER LOTS — UK finals Pb z-scores (Pb/Ag lots)")
uk_pb_p = comp_pbag["UK_Penfold_Pb %"].values
uk_pb_s = comp_pbag["UK_Sinchi_Pb %"].values
d_pb = uk_pb_s - uk_pb_p
mask_pb = pd.notna(d_pb)
d_pb_valid = d_pb[mask_pb]
lbl_pb_valid = [l for l, m in zip(labels, mask_pb) if m]
mu_pb = np.median(d_pb_valid)
sd_pb = np.std(d_pb_valid, ddof=1)
print(f"  Baseline: median={mu_pb:+.2f} %, σ={sd_pb:.3f} %")
for lbl, dv in zip(lbl_pb_valid, d_pb_valid):
    z = (dv - mu_pb) / sd_pb
    if abs(z) > 2:
        print(f"  TR{lbl:8}  Δ={dv:+6.2f} %  z={z:+.2f}")

# ───────────── S-Side summary ─────────────
print()
print("=" * 70)
print("S-SIDE BENCHMARK SUMMARY (Pb/Ag lots)")
print("=" * 70)
for elem_col, name in [("Ag g", "Silver"), ("Pb %", "Lead")]:
    ss_col = f"S-Side_{elem_col}"
    if ss_col not in comp_pbag.columns:
        continue
    ss = comp_pbag[ss_col]
    uk_p_col = comp_pbag[f"UK_Penfold_{elem_col}"]
    uk_s_col = comp_pbag[f"UK_Sinchi_{elem_col}"]
    m = ss.notna() & uk_p_col.notna() & uk_s_col.notna()
    if m.sum() == 0:
        print(f"  {name}: no S-Side data")
        continue
    ss_v  = ss[m].values
    ukp_v = uk_p_col[m].values
    uks_v = uk_s_col[m].values
    d_vs_p = ukp_v - ss_v
    d_vs_s = uks_v - ss_v
    print(f"\n  {name}  (n = {m.sum()} lots with S-Side + UK data)")
    print(f"    Penfold UK vs S-Side: mean Δ = {d_vs_p.mean():+.2f}  (|mean| = {abs(d_vs_p.mean()):.2f})")
    print(f"    Sinchi  UK vs S-Side: mean Δ = {d_vs_s.mean():+.2f}  (|mean| = {abs(d_vs_s.mean()):.2f})")

# ───────────── Data completeness ─────────────
print()
print("=" * 70)
print("DATA COMPLETENESS (all lots after TR74101 exclusion)")
print("=" * 70)
for _, r in comp.iterrows():
    tr = r["TR"]; lt = r["Lot_Type"]; dmt = r.get("DMT", np.nan)
    has_nat   = pd.notna(r.get("Natural_Penfold_Ag g")) and pd.notna(r.get("Natural_Sinchi_Ag g"))
    has_prep  = pd.notna(r.get("Prepared_Penfold_Ag g")) and pd.notna(r.get("Prepared_Sinchi_Ag g"))
    has_uk    = pd.notna(r.get("UK_Penfold_Ag g")) and pd.notna(r.get("UK_Sinchi_Ag g"))
    has_sside = pd.notna(r.get("S-Side_Ag g"))
    tags = []
    if has_nat:   tags.append("Nat")
    if has_prep:  tags.append("Prep")
    if has_uk:    tags.append("UK")
    if has_sside: tags.append("S-Side")
    dmt_str = f"{dmt:>6.1f} t" if pd.notna(dmt) else "  n/a"
    print(f"  TR{tr:<8} {lt:>6}  DMT={dmt_str}  stages: {','.join(tags)}")
