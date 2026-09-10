# Deploy the complete application on Render

The Render configuration runs the React frontend and FastAPI backend in one
Docker Web Service. The browser calls /api on the same host, so
VITE_API_BASE_URL is intentionally left unset.

## Included features

- live CSV analysis;
- model training, results, downloads, SHAP generation, and Gemini explanations;
- K-median solving;
- Google Places autocomplete and route calculation;
- Google sign-in and survey management through Firebase.

## 1. Prepare Google services

### Google Maps

In Google Cloud Console:

1. Select or create the project that owns the Maps API key.
2. Enable Places API and Directions API.
3. Create an API key and restrict its API access to those APIs.
4. Set conservative API quotas and a billing budget alert.

The key is used only by FastAPI. Never add it to a VITE-prefixed variable.

### Gemini

Create a Gemini Developer API key in Google AI Studio. The backend uses
gemini-3.1-flash-lite.

### Firebase authentication and surveys (optional)

To retain sign-in and survey management:

1. Enable Google sign-in in Firebase Authentication.
2. Create Firestore and apply firestore.rules.
3. Create a Firebase service-account JSON credential.
4. Keep it private. Its complete JSON is entered into Render as
   FIREBASE_SERVICE_ACCOUNT_JSON.

After Render assigns the hostname, add it (for example,
dse2026.onrender.com) to Firebase Authentication's authorized domains.

## 2. Push the repository

Commit and push this repository to GitHub. Do not commit .env, service-account
JSON files, generated model weights, or training bundles.

## 3. Create the Render Blueprint

1. Sign in to Render and choose New > Blueprint.
2. Connect this GitHub repository.
3. Render detects render.yaml and creates the dse2026 Docker Web Service.
4. Enter the prompted secret values:
   - GOOGLE_MAPS_API_KEY
   - GEMINI_API_KEY
   - FIREBASE_SERVICE_ACCOUNT_JSON (optional)
5. Apply the Blueprint and wait for the Docker build.
6. Open https://YOUR-SERVICE.onrender.com/api/health and confirm it returns
   a status of ok.
7. Open the service root URL to use the React application.

Dockerfile builds React first and copies frontend/dist into FastAPI.

## 4. Validate

1. Load the Policy Dashboard baseline data.
2. Test Route Calculator autocomplete and calculation.
3. Request a Gemini chart explanation.
4. Train one model with a small estimator count.
5. Run K-median with a small sample percentage.
6. Test sign-in and survey submission if Firebase credentials were added.

## Render free-instance limitations

The free instance has 512 MB RAM, 0.1 CPU, an ephemeral filesystem, and sleeps
after inactivity. It is appropriate for testing routing and Gemini. Full model
training and SHAP generation can exceed its memory or take a long time.
Generated weights and solver runs disappear whenever the instance restarts or
spins down.

For reliable training, use a Render plan with at least 2 GB RAM and attach a
persistent disk. Point the artifact, dataset, model-run, and K-median paths in
the backend configuration to the disk mount.

The model binaries removed during the static conversion cannot be recovered
from JSON and PNG files. Train the models again to recreate them.
