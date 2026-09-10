from __future__ import annotations

import json
from typing import Any

import httpx

from app.config import settings


async def _generate_content(prompt: str) -> str:
    if not settings.GEMINI_API_KEY:
        raise ValueError("Configure GEMINI_API_KEY in the backend environment first")

    endpoint = (
        f"{settings.GEMINI_API_BASE_URL.rstrip('/')}/models/"
        f"{settings.GEMINI_MODEL}:generateContent"
    )
    async with httpx.AsyncClient(timeout=90.0) as client:
        response = await client.post(
            endpoint,
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": settings.GEMINI_API_KEY,
            },
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.2},
            },
        )
        response.raise_for_status()
        payload = response.json()
    try:
        parts = payload["candidates"][0]["content"]["parts"]
        content = "\n".join(part["text"] for part in parts if part.get("text"))
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("Gemini returned an unsupported response shape") from exc
    if not content:
        raise ValueError("Gemini did not return an explanation")
    return content


def _compact_model_results(results: dict[str, Any]) -> dict[str, Any]:
    models = {}
    for name, output in (results.get("models") or {}).items():
        metrics = output.get("metrics") or {}
        models[name] = {
            "selection_score": output.get("score"),
            "current_mode_macro_avg": (metrics.get("current_mode") or {}).get("macro avg"),
            "fallback_macro_avg": (metrics.get("fallback_modes") or {}).get("macro avg"),
            "top_current_features": (output.get("feature_importance") or {}).get("current_mode", [])[:10],
        }
    return {
        "run_id": results.get("run_id"),
        "source": results.get("actual_source"),
        "training_rows": results.get("row_count"),
        "selected_default_model": results.get("selected_default_model"),
        "models": models,
        "monte_carlo": results.get("monte_carlo"),
        "travel_time_elasticity": results.get("travel_time_elasticity"),
    }


async def analyze_model_results(results: dict[str, Any]) -> dict[str, Any]:
    summary = _compact_model_results(results)
    prompt = (
        "You are a concise transport-model validation analyst. Review the following "
        "transport-mode model results. Compare the candidate models, "
        "identify likely overfitting or weak classes, interpret the Monte Carlo migration ranges, "
        "and give specific next validation steps. Do not invent facts outside the supplied JSON.\n\n"
        + json.dumps(summary, ensure_ascii=False)
    )
    return {"model": settings.GEMINI_MODEL, "analysis": await _generate_content(prompt)}


CHART_CONTEXT = {
    "feature_current": ("Current-mode feature importance", ("feature_importance", "current_mode")),
    "feature_car": ("Car fallback feature importance", ("feature_importance", "fallback_modes", "alt_car")),
    "feature_ebike": ("E-bike fallback feature importance", ("feature_importance", "fallback_modes", "alt_ebike")),
    "feature_bike": ("Bike fallback feature importance", ("feature_importance", "fallback_modes", "alt_bike")),
    "feature_bus": ("Bus fallback feature importance", ("feature_importance", "fallback_modes", "alt_bus")),
    "feature_ltrain": ("Light-rail fallback feature importance", ("feature_importance", "fallback_modes", "alt_ltrain")),
    "feature_taxi": ("Taxi fallback feature importance", ("feature_importance", "fallback_modes", "alt_taxi")),
    "feature_walk": ("Walking fallback feature importance", ("feature_importance", "fallback_modes", "alt_walk")),
    "elasticity": ("Travel-time elasticity", ("elasticity",)),
    "partial_dependence": ("E-bike distance partial dependence", ("partial_dependence",)),
    "monte_carlo": ("Monte Carlo mode migration after a total ICE ban", ("monte_carlo", "total_ice_ban")),
    "shap_summary": ("SHAP summary for E-bike adoption", ("feature_importance", "fallback_modes", "alt_ebike")),
    "shap_distance": ("SHAP dependence for trip distance and E-bike adoption", ("partial_dependence",)),
}


def _chart_data(insights: dict[str, Any], path: tuple[str, ...]) -> Any:
    value: Any = insights
    for key in path:
        value = value.get(key) if isinstance(value, dict) else None
    return value


async def explain_model_chart(chart_id: str, insights: dict[str, Any]) -> dict[str, Any]:
    if chart_id not in CHART_CONTEXT:
        raise ValueError("Unsupported model insight chart")
    title, path = CHART_CONTEXT[chart_id]
    chart_data = _chart_data(insights, path)
    prompt = (
        "You are explaining one transport-model chart to a policymaker. Explain what the "
        "chart measures, the strongest visible pattern, what action it may inform, and one "
        "important limitation. Use plain language and no more than 180 words. Do not imply "
        "causality and do not invent values.\n\n"
        f"Chart: {title}\nData: {json.dumps(chart_data, ensure_ascii=False)}"
    )
    return {
        "model": settings.GEMINI_MODEL,
        "chart_id": chart_id,
        "analysis": await _generate_content(prompt),
    }
