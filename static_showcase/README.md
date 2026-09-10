# Static showcase archive

This directory contains the precomputed, inference-free export created on
2026-09-10:

- dataset profiling and policy EDA;
- combined Gradient Boosting, Random Forest, and Decision Tree results;
- per-model feature importance, elasticity, partial dependence, Monte Carlo,
  and SHAP outputs;
- the saved default K-median solution.

The live application does not read this directory. To publish the static
showcase again, copy the data directory to frontend/public/data and restore the
static frontend components, or use the files in another presentation.

Running backend/scripts/export_static_showcase.py refreshes this archived
folder. Model weights must exist locally before refreshing model/SHAP outputs.
