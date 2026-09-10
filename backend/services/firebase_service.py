from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any

from fastapi import Header, HTTPException

from app.config import settings


def _sdk():
    try:
        import firebase_admin
        from firebase_admin import auth, credentials, firestore
        return firebase_admin, auth, credentials, firestore
    except ImportError as exc:
        raise RuntimeError("Install the firebase-admin Python package to use Firebase authentication and Firestore") from exc


def firebase_app():
    firebase_admin, _, credentials, _ = _sdk()
    try:
        return firebase_admin.get_app()
    except ValueError:
        project_id = settings.FIREBASE_PROJECT_ID.strip()
        if not project_id:
            raise RuntimeError("FIREBASE_PROJECT_ID is not configured")
        options = {
            "projectId": project_id,
            "storageBucket": settings.FIREBASE_STORAGE_BUCKET,
        }
        credential_json = settings.FIREBASE_SERVICE_ACCOUNT_JSON.strip()
        credential_path = settings.FIREBASE_SERVICE_ACCOUNT_PATH
        if credential_json:
            credential = credentials.Certificate(json.loads(credential_json))
            credential_project = getattr(credential, "project_id", None)
            if credential_project and credential_project != project_id:
                raise RuntimeError(
                    "Firebase service-account project does not match FIREBASE_PROJECT_ID"
                )
        elif credential_path:
            if not credential_path.is_file():
                raise RuntimeError(
                    f"Firebase service-account file was not found at {credential_path}"
                )
            credential = credentials.Certificate(str(credential_path))
            credential_project = getattr(credential, "project_id", None)
            if credential_project and credential_project != project_id:
                raise RuntimeError(
                    "Firebase service-account project does not match FIREBASE_PROJECT_ID"
                )
        else:
            try:
                import google.auth

                google.auth.default()
            except Exception as exc:
                raise RuntimeError(
                    "Firebase Admin credentials are not configured. Run 'gcloud auth application-default login' "
                    "or set FIREBASE_SERVICE_ACCOUNT_PATH to a service-account JSON file."
                ) from exc
            credential = credentials.ApplicationDefault()
        return firebase_admin.initialize_app(credential, options)


def firestore_client():
    try:
        _, _, _, firestore = _sdk()
        return firestore.client(app=firebase_app())
    except Exception as exc:
        raise RuntimeError(
            "Firestore is unavailable. Locally, set FIREBASE_SERVICE_ACCOUNT_PATH to a Firebase service-account JSON file."
        ) from exc


def require_user(authorization: str | None = Header(None)) -> dict[str, Any]:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Sign in with Google to continue")
    token = authorization.removeprefix("Bearer ").strip()
    try:
        _, auth, _, _ = _sdk()
        decoded = auth.verify_id_token(
            token,
            app=firebase_app(),
            clock_skew_seconds=10,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        error_name = type(exc).__name__
        error_message = str(exc).strip()
        print(f"[FIREBASE AUTH] {error_name}: {error_message}")
        lowered = f"{error_name} {error_message}".casefold()
        if "expired" in lowered:
            detail = "Your Firebase sign-in expired. Refresh the page and sign in again"
        elif "aud" in lowered or "project" in lowered:
            detail = (
                "Firebase project mismatch: the browser token and backend FIREBASE_PROJECT_ID must both use "
                f"'{settings.FIREBASE_PROJECT_ID}'"
            )
        elif "certificate" in lowered or "connection" in lowered or "timeout" in lowered:
            detail = "The backend could not reach Google's Firebase token certificates"
        else:
            detail = "Firebase rejected the ID token returned by the browser. Sign out, refresh, and try again"
        raise HTTPException(status_code=401, detail=detail) from exc
    if decoded.get("firebase", {}).get("sign_in_provider") != "google.com":
        raise HTTPException(status_code=403, detail="Only Google accounts are allowed")
    return {
        **decoded,
        "sub": decoded["uid"],
        "email": decoded.get("email"),
        "name": decoded.get("name") or decoded.get("email"),
        "picture": decoded.get("picture"),
    }


def get_or_create_profile(user: dict[str, Any]) -> dict[str, Any]:
    _, _, _, firestore = _sdk()
    reference = firestore_client().collection(settings.FIRESTORE_PROFILE_COLLECTION).document(user["sub"])
    snapshot = reference.get()
    if snapshot.exists:
        profile = snapshot.to_dict() or {}
    else:
        profile = {
            "email": user.get("email"),
            "display_name": user.get("name"),
            "avatar_url": user.get("picture"),
            "created_at": firestore.SERVER_TIMESTAMP,
            "updated_at": firestore.SERVER_TIMESTAMP,
        }
        reference.set(profile)
    return {
        "id": user["sub"],
        "email": user.get("email"),
        "name": profile.get("display_name") or user.get("name"),
        "picture": profile.get("avatar_url") or user.get("picture"),
    }


def update_profile(user: dict[str, Any], display_name: str, avatar_url: str | None) -> dict[str, Any]:
    _, _, _, firestore = _sdk()
    reference = firestore_client().collection(settings.FIRESTORE_PROFILE_COLLECTION).document(user["sub"])
    current = reference.get().to_dict() or {}
    picture = avatar_url or current.get("avatar_url") or user.get("picture")
    reference.set({
        "email": user.get("email"),
        "display_name": display_name,
        "avatar_url": picture,
        "updated_at": firestore.SERVER_TIMESTAMP,
    }, merge=True)
    return {"id": user["sub"], "email": user.get("email"), "name": display_name, "picture": picture}


def create_survey_response(user: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    created_at = datetime.now(timezone.utc)
    reference = firestore_client().collection(settings.FIRESTORE_SURVEY_COLLECTION).document()
    reference.set({
        "payload": payload,
        "owner_uid": user["sub"],
        "owner_email": user.get("email"),
        "source": "web",
        "created_at": created_at,
    })
    return {"id": reference.id, "created_at": created_at.isoformat(), "message": "Survey response submitted"}


def list_survey_responses(user: dict[str, Any]) -> list[dict[str, Any]]:
    from google.cloud.firestore_v1.base_query import FieldFilter

    query = firestore_client().collection(settings.FIRESTORE_SURVEY_COLLECTION).where(
        filter=FieldFilter("owner_uid", "==", user["sub"])
    )
    rows = []
    for snapshot in query.stream():
        data = snapshot.to_dict() or {}
        created_at = data.get("created_at")
        rows.append({
            "id": snapshot.id,
            "payload": data.get("payload") or {},
            "created_at": created_at.isoformat() if hasattr(created_at, "isoformat") else str(created_at or ""),
            "source": data.get("source", "web"),
        })
    return sorted(rows, key=lambda row: row["created_at"], reverse=True)


def delete_survey_response(user: dict[str, Any], response_id: str) -> bool:
    reference = firestore_client().collection(settings.FIRESTORE_SURVEY_COLLECTION).document(response_id)
    snapshot = reference.get()
    if not snapshot.exists or (snapshot.to_dict() or {}).get("owner_uid") != user["sub"]:
        return False
    reference.delete()
    return True


def load_baseline_collection(max_rows: int) -> list[dict[str, Any]]:
    rows = []
    for snapshot in firestore_client().collection(settings.FIRESTORE_BASELINE_COLLECTION).limit(max_rows).stream():
        row = snapshot.to_dict() or {}
        row.pop("_imported_at", None)
        rows.append(row)
    return rows
