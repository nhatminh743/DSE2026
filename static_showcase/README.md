# Static showcase archive

This directory contains the precomputed, inference-free export created on
2026-09-10:

- dataset profiling and policy EDA;
- combined Gradient Boosting, Random Forest, and Decision Tree results;
- per-model feature importance, elasticity, partial dependence, Monte Carlo,
  and SHAP outputs;
- the saved default K-median solution.

The Model Lab's **View static results** tab reads this directory through Vite's
public directory configuration. The production build publishes `data` at
`/data`, while the source artifacts remain together in this one archive folder.

Running backend/scripts/export_static_showcase.py refreshes this archived
folder. Model weights must exist locally before refreshing model/SHAP outputs.
