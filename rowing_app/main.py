"""FastAPI application – Laat Lopen, Eduardo's Concept2 rowing analytics."""

from __future__ import annotations

import hashlib
import json
import math
import os
import secrets
import traceback
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from loguru import logger
from starlette.middleware.sessions import SessionMiddleware

from .analytics import (
    compute_summary,
    daily_distance_data,
    monthly_volume,
    pace_trend_regression,
    personal_bests,
    results_to_dataframe,
    stroke_detail_data,
    weekly_volume,
    workout_clustering,
)
from .api_client import Concept2Client
from .auth import exchange_code_for_token, get_authorization_url, refresh_access_token
from .config import settings
from .database import (
    fetch_and_cache_stroke_data,
    get_last_sync,
    get_latest_workout_id,
    get_workout_count,
    has_stroke_data,
    init_db,
    load_stroke_data,
    load_workouts_as_models,
    needs_sync,
    sync_workouts,
)

# ──────────────────────────────────────────────
# App setup
# ──────────────────────────────────────────────
app = FastAPI(title="Concept2 Rowing Analytics", version="0.1.0")
app.add_middleware(SessionMiddleware, secret_key=settings.app_secret_key)

STATIC_DIR = os.path.join("rowing_app", "static")


class VersionedStaticFiles(StaticFiles):
    """Serves hashed asset URLs (?v=...) as immutable so browsers never re-request them."""

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        if b"v=" in scope.get("query_string", b""):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            response.headers["Cache-Control"] = "no-cache"
        return response


app.mount("/static", VersionedStaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory="rowing_app/templates")

_asset_versions: dict[str, str] = {}


def static_url(filename: str) -> str:
    """Build a /static URL fingerprinted with the file's content hash."""
    version = None if settings.app_debug else _asset_versions.get(filename)
    if version is None:
        try:
            with open(os.path.join(STATIC_DIR, filename), "rb") as fh:
                version = hashlib.sha256(fh.read()).hexdigest()[:10]
        except OSError:
            version = "0"
        _asset_versions[filename] = version
    return f"/static/{filename}?v={version}"


templates.env.globals["static_url"] = static_url


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Catch-all: log the traceback; only expose details when debug is on."""
    tb = traceback.format_exc()
    logger.error(f"Unhandled exception on {request.url}:\n{tb}")
    if settings.app_debug:
        body = f"<h2>Server Error</h2><pre>{type(exc).__name__}: {exc}\n\n{tb}</pre>"
    else:
        body = "<h2>Server Error</h2><p>Something went wrong. Please try again later.</p>"
    return HTMLResponse(body, status_code=500)


@app.on_event("startup")
async def startup_event():
    """Initialise the local SQLite database on app start."""
    _verify_secret_key()
    init_db()


def _verify_secret_key() -> None:
    """Refuse to serve publicly with a default/weak session key."""
    key = settings.app_secret_key
    weak = key == "change-me-to-a-random-string" or "openssl rand" in key or len(key) < 32
    if not weak:
        return
    msg = (
        "APP_SECRET_KEY is missing, default, or too short. "
        "Generate one with: openssl rand -hex 32"
    )
    if settings.app_debug:
        logger.warning(f"INSECURE: {msg}")
    else:
        raise RuntimeError(msg)


# ──────────────────────────────────────────────
# Auth routes
# ──────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Redirect to public dashboard."""
    return RedirectResponse("/dashboard")


@app.get("/auth/login")
async def login(request: Request):
    """Redirect user to Concept2 OAuth2 authorization page."""
    state = secrets.token_urlsafe(32)
    request.session["oauth_state"] = state
    auth_url = get_authorization_url(state=state)
    return RedirectResponse(auth_url)


@app.get("/auth/callback")
async def auth_callback(request: Request, code: str, state: Optional[str] = None):
    """Handle OAuth2 callback from Concept2."""
    # Skip CSRF state check for personal app — avoids stale-session loops
    try:
        token = await exchange_code_for_token(code)
    except Exception as e:
        logger.error(f"Token exchange failed: {e}\n{traceback.format_exc()}")
        request.session.clear()
        return RedirectResponse("/auth/login")

    # Only the owner may authenticate/sync — everyone else just gets the public view.
    try:
        client = Concept2Client(access_token=token.access_token)
        user_resp = await client.get_user()
        username = user_resp.data.username
    except Exception as e:
        logger.error(f"Could not verify user identity: {e}")
        request.session.clear()
        return RedirectResponse("/dashboard")

    if username.lower() != settings.owner_username.lower():
        logger.warning(f"Rejected login for non-owner user '{username}'.")
        request.session.clear()
        return RedirectResponse("/dashboard")

    request.session.pop("oauth_state", None)
    request.session["access_token"] = token.access_token
    request.session["refresh_token"] = token.refresh_token
    logger.info(f"Owner '{username}' authenticated successfully.")
    return RedirectResponse("/dashboard")


@app.get("/auth/logout")
async def logout(request: Request):
    """Clear session and redirect to home."""
    request.session.clear()
    return RedirectResponse("/")


# ──────────────────────────────────────────────
# Dashboard
# ──────────────────────────────────────────────
@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
):
    """Public analytics dashboard. Authenticated users also get live sync."""
    token = request.session.get("access_token")
    sync_info = None
    is_authenticated = False

    if token:
        # Authenticated user: try to sync and get live profile
        client = Concept2Client(access_token=token)
        try:
            await client.get_user()  # verify token is still valid
            sync_info = await sync_workouts(client)
            is_authenticated = True
            # Fetch stroke data for the most recent workout if we don't have it yet
            latest_id = get_latest_workout_id()
            if latest_id is not None and not has_stroke_data(latest_id):
                await fetch_and_cache_stroke_data(client, latest_id)
        except Exception as e:
            logger.warning(f"Auth session expired, showing public dashboard: {e}")
            # Try refreshing the token
            refresh = request.session.get("refresh_token")
            if refresh:
                try:
                    new_token = await refresh_access_token(refresh)
                    request.session["access_token"] = new_token.access_token
                    request.session["refresh_token"] = new_token.refresh_token
                    return RedirectResponse("/dashboard")
                except Exception:
                    pass
            request.session.clear()

    # Always show dashboard from local DB (works for everyone)
    class _FakeResp:
        class data:
            first_name = "Eduardo"
            username = "eduardo"
    fake_resp = _FakeResp()

    results = load_workouts_as_models(
        from_date=from_date,
        to_date=to_date,
    )

    try:
        return await _build_dashboard(
            request, fake_resp, results, sync_info, from_date, to_date,
            is_authenticated=is_authenticated,
        )
    except Exception as e:
        tb = traceback.format_exc()
        logger.error(f"Dashboard build error:\n{tb}")
        detail = f"<pre>{tb}</pre>" if settings.app_debug else "<p>Something went wrong.</p>"
        return HTMLResponse(
            f"<h2>Dashboard Error</h2>{detail}",
            status_code=500,
        )


async def _build_dashboard(request, user_resp, results, sync_info, from_date, to_date, is_authenticated=False):
    """Build the full dashboard (extracted for error isolation)."""
    df = results_to_dataframe(results)
    summary = compute_summary(df)
    pbs = personal_bests(df)
    monthly = monthly_volume(df)
    weekly = weekly_volume(df)
    heatmap = daily_distance_data(df)
    regression = pace_trend_regression(df)
    clustering = workout_clustering(df, n_clusters=4)

    # Latest workout — fetch stroke data (already cached on auth) for detail chart
    latest_workout_info = None
    latest_id = get_latest_workout_id()
    if latest_id is not None and results:
        latest = max(results, key=lambda r: r.date)
        stroke_points = load_stroke_data(latest_id)
        latest_workout_info = {
            "id": latest_id,
            "date": latest.date,
            "distance": latest.distance,
            "time_formatted": latest.time_formatted,
            "has_stroke_data": bool(stroke_points),
        }
    else:
        stroke_points = []

    # ?? Chart data (rendered client-side with Apache ECharts) ??
    charts: dict = {}

    if not monthly.empty:
        charts["monthly_distance"] = {
            "labels": monthly["month"].tolist(),
            "km": [float(v) for v in monthly["total_distance_km"]],
        }

    if not weekly.empty:
        charts["weekly_distance"] = {
            "labels": weekly["year_week"].tolist(),
            "km": [float(v) for v in weekly["total_distance_km"]],
        }

    if heatmap:
        charts["heatmap"] = heatmap

    if regression:
        charts["regression"] = regression

    if clustering:
        series = []
        for profile in clustering["cluster_profiles"]:
            cid = profile["id"]
            pts = [p for p in clustering["scatter_data"] if p["cluster"] == cid]
            series.append({
                "label": profile["label"],
                "points": [
                    {
                        "d": int(p["distance"]),
                        "p": round(float(p["pace"]), 1) if p["pace"] is not None else None,
                        "t": float(p["time_min"]),
                        "spm": int(p["stroke_rate"]) if p["stroke_rate"] is not None else None,
                        "cal": int(p["calories"]) if p["calories"] is not None else None,
                    }
                    for p in pts
                ],
            })
        charts["clustering"] = {"series": series}

        cat_profiles = clustering.get("category_profiles", clustering["cluster_profiles"])
        charts["cluster_pie"] = {
            "labels": [p["label"] for p in cat_profiles],
            "values": [int(p["count"]) for p in cat_profiles],
        }

    # Stroke-level detail data for the latest workout (if cached)
    if stroke_points:
        stroke = stroke_detail_data(stroke_points)
        if stroke:
            charts["stroke_detail"] = stroke

    # Numpy scalars and NaN are not JSON-safe; normalise before |tojson.
    def _jsonable(obj):
        if isinstance(obj, dict):
            return {k: _jsonable(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [_jsonable(v) for v in obj]
        if isinstance(obj, float):
            return None if math.isnan(obj) else obj
        if hasattr(obj, "item"):  # numpy scalar
            return _jsonable(obj.item())
        return obj

    charts = _jsonable(charts)

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "user": user_resp.data,
            "summary": summary,
            "personal_bests": pbs,
            "charts": charts,
            "clustering": clustering,
            "regression": regression,
            "from_date": from_date or "",
            "to_date": to_date or "",
            "sync_info": sync_info,
            "is_authenticated": is_authenticated,
            "latest_workout": latest_workout_info,
        },
    )


# ──────────────────────────────────────────────
# API endpoints (JSON)
# ──────────────────────────────────────────────
@app.get("/export/csv")
async def export_csv(request: Request):
    """Export all workouts to a CSV file and save to project folder.
    
    Visit http://localhost:8000/export/csv while logged in.
    This saves workouts.csv for use in the Jupyter notebook tutorial.
    """
    token = request.session.get("access_token")
    if not token:
        return RedirectResponse("/auth/login")

    results = load_workouts_as_models()
    df = results_to_dataframe(results)
    df.to_csv("workouts.csv", index=False)
    logger.info(f"Exported {len(df)} workouts to workouts.csv")
    return HTMLResponse(
        f"<h2>✅ Exported {len(df)} workouts to workouts.csv</h2>"
        "<p>You can now load this file in your Jupyter notebook.</p>"
        '<p><a href="/dashboard">← Back to Dashboard</a></p>'
    )


@app.get("/sync/force")
async def force_sync(request: Request):
    """Force a full re-sync from the Concept2 API, bypassing the 24h check."""
    token = request.session.get("access_token")
    if not token:
        return RedirectResponse("/auth/login")

    client = Concept2Client(access_token=token)
    # Fetch ALL workouts fresh
    results = await client.get_all_results(workout_type="rower")

    from .database import _get_connection, _upsert_workouts, _update_sync_meta
    conn = _get_connection()
    count = _upsert_workouts(conn, results)
    _update_sync_meta(conn)
    conn.commit()
    total = conn.execute("SELECT COUNT(*) FROM workouts").fetchone()[0]
    conn.close()

    logger.info(f"Force sync: {count} workouts written, {total} total.")
    return RedirectResponse("/dashboard")


@app.get("/api/results")
async def api_results(
    request: Request,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
):
    """Return raw results as JSON (for programmatic access)."""
    token = request.session.get("access_token")
    if not token:
        return {"error": "Not authenticated"}, 401

    results = load_workouts_as_models(from_date=from_date, to_date=to_date)
    return {"count": len(results), "data": [r.model_dump() for r in results]}


@app.get("/api/summary")
async def api_summary(request: Request):
    """Return summary statistics as JSON."""
    token = request.session.get("access_token")
    if not token:
        return {"error": "Not authenticated"}, 401

    results = load_workouts_as_models()
    df = results_to_dataframe(results)
    return compute_summary(df)
