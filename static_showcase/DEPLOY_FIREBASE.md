# Deploy the static showcase to Firebase Hosting

This archived deployment variant is intentionally inference-free. It displays saved
policy analysis, three-model comparison data, model-specific SHAP charts, and
the saved K-median solution from `frontend/public/data`.

Model training, K-median solving, CSV analysis, Gemini analysis, route
calculation, authentication, and survey submission are not part of the hosted
showcase. Run the Python backend locally when those capabilities are needed.

The static files are archived in static_showcase/data and are not used by the
current Render-oriented live application. Copy that directory to
frontend/public/data before building this Firebase variant.

## Refresh the static data locally

Train Gradient Boosting, Random Forest, and Decision Tree locally. Each run
must be completed and retained under `backend/weights/model_lab/runs`. Then run:

```powershell
$env:PYTHONPATH = "$PWD\backend"
python backend/scripts/export_static_showcase.py
```

The exporter selects the newest completed run for each model type, generates
the combined static payload, and copies the model-specific SHAP images and the
default K-median solution into `static_showcase/data`.

## Build and deploy

Create a Firebase project on the no-cost Spark plan and enable Hosting. Then:

```powershell
npm install --global firebase-tools
firebase login
firebase use hanoi-policy-makers
npm --prefix frontend ci
npm --prefix frontend run build
firebase deploy --only hosting
```

No Cloud Run service, Cloud Storage bucket, Firestore database, service-account
key, or production API secret is required for this static deployment.

To deploy under a different Firebase project, change `.firebaserc`. To point
the read-only notices to another repository, set `VITE_GITHUB_URL` before the
frontend build.
