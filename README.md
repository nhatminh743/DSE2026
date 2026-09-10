# DSE2026

Hanoi mobility policy application with a React frontend and FastAPI backend.

Local development:

~~~powershell
uvicorn app.main:app --reload --port 8001 --app-dir backend
npm --prefix frontend run dev
~~~

For a complete Render deployment, see DEPLOY_RENDER.md.
The previous static-only export is preserved under static_showcase.
