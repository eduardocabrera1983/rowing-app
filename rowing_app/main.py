"""FastAPI application – Concept2 Rowing Analytics Dashboard."""

from __future__ import annotations

import secrets
from typing import Optional

import plotly.express as px
import plotly.io as pio
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from loguru import logger
from starlette.middleware.sessions import SessionMiddleware

from .analytics import (
    compute_summary,
    monthly_volume,
    pace_trend_regression,
    personal_bests,
    results_to_dataframe,
    training_heatmap_data,
    weekly_volume,
    workout_clustering,
)
from .api_client import Concept2Client
from .auth import exchange_code_for_token, get_authorization_url, refresh_access_token
from .config import settings
from .database import init_db, load_workouts_as_models, sync_workouts, get_last_sync, get_workout_count, needs_sync

# ──────────────────────────────────────────────
# App setup
# ──────────────────────────────────────────────
app = FastAPI(title="Concept2 Rowing Analytics", version="0.1.0")
app.add_middleware(SessionMiddleware, secret_key=settings.app_secret_key)
app.mount("/static", StaticFiles(directory="rowing_app/static"), name="static")
templates = Jinja2Templates(directory="rowing_app/templates")


@app.on_event("startup")
async def startup_event():
    """Initialise the local SQLite database on app start."""
    init_db()


# ──────────────────────────────────────────────
# Auth routes
# ──────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Landing page – shows login or dashboard link."""
    token = request.session.get("access_token")
    return templates.TemplateResponse(
        "home.html",
        {"request": request, "logged_in": token is not None},
    )


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
    stored_state = request.session.get("oauth_state")
    if state and stored_state and state != stored_state:
        return HTMLResponse("State mismatch – possible CSRF attack.", status_code=400)

    token = await exchange_code_for_token(code)
    request.session["access_token"] = token.access_token
    request.session["refresh_token"] = token.refresh_token
    logger.info("User authenticated successfully.")
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
    """Main analytics dashboard."""
    token = request.session.get("access_token")
    if not token:
        return RedirectResponse("/auth/login")

    client = Concept2Client(access_token=token)

    try:
        # Fetch user profile (lightweight, always live)
        user_resp = await client.get_user()

        # Sync local DB if needed (>24 h since last sync)
        sync_info = await sync_workouts(client)

        # Read workouts from local SQLite (instant)
        results = load_workouts_as_models(
            from_date=from_date,
            to_date=to_date,
        )
    except Exception as e:
        logger.error(f"API error: {e}")
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
        return RedirectResponse("/auth/login")

    # Build analytics
    df = results_to_dataframe(results)
    summary = compute_summary(df)
    pbs = personal_bests(df)
    monthly = monthly_volume(df)
    weekly = weekly_volume(df)
    heatmap = training_heatmap_data(df)
    regression = pace_trend_regression(df)
    clustering = workout_clustering(df, n_clusters=4)

    # Build Plotly charts (as HTML snippets)
    charts = {}
    if not monthly.empty:
        fig_monthly = px.bar(
            monthly,
            x="month",
            y="total_distance_km",
            title="Monthly Distance (km)",
            labels={"month": "Month", "total_distance_km": "Distance (km)"},
        )
        fig_monthly.update_layout(template="plotly_white")
        charts["monthly_distance"] = pio.to_html(fig_monthly, full_html=False)

    if not weekly.empty:
        fig_weekly = px.bar(
            weekly,
            x="year_week",
            y="total_distance_km",
            title="Weekly Distance (km)",
            labels={"year_week": "Week", "total_distance_km": "Distance (km)"},
        )
        fig_weekly.update_layout(template="plotly_white")
        charts["weekly_distance"] = pio.to_html(fig_weekly, full_html=False)

    # ── Training Heatmap (GitHub-style) ───────────
    if heatmap:
        import plotly.graph_objects as go
        import numpy as np
        z_raw = heatmap["z_values"]
        date_raw = heatmap["date_labels"]
        # Transpose: GitHub has weeks on X-axis, weekdays on Y-axis
        z_t = np.array(z_raw).T.tolist()  # shape: 7 days × N weeks
        date_t = np.array(date_raw).T.tolist()  # matching shape
        weeks = heatmap["weeks"]
        days = heatmap["days"]  # ["Mon", "Tue", ..., "Sun"]
        # Reverse days so Mon is at the top (GitHub style)
        z_t = z_t[::-1]
        date_t = date_t[::-1]
        days_reversed = days[::-1]
        num_weeks = len(weeks)

        fig_heat = go.Figure(data=go.Heatmap(
            z=z_t,
            x=weeks,            # X-axis: weeks (many columns)
            y=days_reversed,    # Y-axis: Mon–Sun (7 rows)
            customdata=date_t,
            colorscale=[
                [0.0, "#ebedf0"], [0.001, "#9be9a8"],
                [0.25, "#40c463"], [0.5, "#30a14e"], [1.0, "#216e39"],
            ],
            hovertemplate="Date: %{customdata}<br>Distance: %{z:,.0f}m<extra></extra>",
            colorbar=dict(title="Meters", thickness=10, len=0.5),
            xgap=4,
            ygap=4,
        ))
        # Build month labels: show "Jan", "Feb", … at the first week of each month
        import re
        month_map = {
            "01": "Jan", "02": "Feb", "03": "Mar", "04": "Apr",
            "05": "May", "06": "Jun", "07": "Jul", "08": "Aug",
            "09": "Sep", "10": "Oct", "11": "Nov", "12": "Dec",
        }
        tick_vals, tick_text = [], []
        seen_months = set()
        for w in weeks:
            m = re.search(r"(\d{4})-W(\d{2})", w)
            if m:
                yr, wk = int(m.group(1)), int(m.group(2))
                # approximate month from ISO week
                from datetime import date
                try:
                    d = date.fromisocalendar(yr, wk, 1)
                    key = f"{d.year}-{d.month:02d}"
                    if key not in seen_months:
                        seen_months.add(key)
                        tick_vals.append(w)
                        tick_text.append(f"{month_map[f'{d.month:02d}']} {d.year}")
                except Exception:
                    pass

        fig_heat.update_layout(
            title=dict(text="Training Heatmap — Distance per Day", y=0.98,
                       font=dict(size=14)),
            xaxis=dict(
                side="top", tickangle=0,
                tickfont=dict(size=10),
                tickvals=tick_vals,
                ticktext=tick_text,
            ),
            yaxis=dict(tickfont=dict(size=11), automargin=True),
            # Square cells: width proportional to weeks, height fixed for 7 rows
            width=max(600, num_weeks * 20 + 140),
            height=240,
            template="plotly_white",
            margin=dict(l=50, r=80, t=70, b=10),
            plot_bgcolor="#fff",
        )
        charts["heatmap"] = pio.to_html(fig_heat, full_html=False)

    # ── Pace Trend Regression ─────────────────────
    if regression:
        import plotly.graph_objects as go
        # Build gradient colorscale: green (faster) → gold → red (slower)
        paces_arr = regression["paces"]
        pace_min = min(paces_arr)
        pace_max = max(paces_arr)
        pace_range = pace_max - pace_min if pace_max > pace_min else 1
        green_threshold = min(max((160 - pace_min) / pace_range, 0), 1)
        yellow_threshold = min(green_threshold + 0.1, 1)
        colorscale = [
            [0, "green"],
            [green_threshold, "green"],
            [yellow_threshold, "gold"],
            [1, "red"],
        ]
        fig_reg = go.Figure()
        # Trace 0: Actual Pace (gradient-colored dots)
        fig_reg.add_trace(go.Scatter(
            x=regression["dates"], y=regression["paces"],
            mode="markers", name="Actual Pace",
            marker=dict(
                size=8,
                color=paces_arr,
                colorscale=colorscale,
                cmin=pace_min,
                cmax=pace_max,
                showscale=False,
            ),
            hovertemplate="Date: %{x}<br>Pace: %{text}<extra></extra>",
            text=regression["pace_formatted"],
        ))
        # Trace 1 (invisible legend ref): Faster
        fig_reg.add_trace(go.Scatter(
            x=[None], y=[None], mode="markers",
            marker=dict(size=10, color="green"),
            name="Faster",
        ))
        # Trace 2 (invisible legend ref): Slower
        fig_reg.add_trace(go.Scatter(
            x=[None], y=[None], mode="markers",
            marker=dict(size=10, color="red"),
            name="Slower",
        ))
        # Trace 3: Linear
        fig_reg.add_trace(go.Scatter(
            x=regression["dates"], y=regression["trend_y"],
            mode="lines", name=f"Linear (R\u00b2={regression['r_squared']:.2f})",
            line=dict(color="red", width=2, dash="dash"),
        ))
        # Trace 4: Polynomial
        fig_reg.add_trace(go.Scatter(
            x=regression["dates"], y=regression["poly_y"],
            mode="lines", name=f"Polynomial deg {regression['poly_degree']} (R\u00b2={regression['poly_r_squared']:.2f})",
            line=dict(color="#9C27B0", width=2.5),
        ))
        # Trace 5: Rolling Avg
        fig_reg.add_trace(go.Scatter(
            x=regression["dates"], y=regression["rolling_avg"],
            mode="lines", name="10-workout Rolling Avg",
            line=dict(color="#03A9F4", width=2),
        ))
        # M:SS y-axis
        all_paces = [p for p in regression["paces"] if p is not None]
        rmin = (int(min(all_paces)) // 5) * 5
        rmax = ((int(max(all_paces)) // 5) + 1) * 5
        rtickv = list(range(rmin, rmax + 1, 5))
        rtickt = [f"{v // 60}:{v % 60:02d}" for v in rtickv]
        direction = "Getting Faster" if regression["improving"] else "Getting Slower"
        fig_reg.add_annotation(
            x=0.02, y=0.98, xref="paper", yref="paper",
            text=f"<b>Rate:</b> {abs(regression['pace_change_per_month']):.1f}s /500m per month<br><b>{direction}</b>",
            showarrow=False, bgcolor="rgba(255,255,255,0.8)", bordercolor="#ccc",
            font=dict(size=12), align="left",
        )
        fig_reg.update_layout(
            title="Pace Trend \u2014 Linear & Polynomial Regression",
            xaxis_title="Date", yaxis_title="Pace /500m",
            yaxis=dict(tickvals=rtickv, ticktext=rtickt),
            template="plotly_white", height=500,
            legend=dict(x=0.02, y=0.02, bgcolor="rgba(255,255,255,0.8)"),
        )
        charts["regression"] = pio.to_html(fig_reg, full_html=False)

    # ── Workout Clustering ────────────────────────
    if clustering:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
        # Fixed colors mapped to labels (left→right = Sprint → Long)
        label_colors = {
            "Sprint": "#FFC107",
            "5K Steady-State": "#2196F3",
            "10K Steady-State": "#FF5722",
            "Long Endurance": "#4CAF50",
        }
        fallback_colors = ["#9C27B0", "#00BCD4", "#E91E63", "#795548"]

        # Cluster scatter (Distance vs Pace)
        fig_cl = make_subplots(
            rows=1, cols=2,
            subplot_titles=["Distance vs Pace", "Distance vs Duration"],
            horizontal_spacing=0.12,
        )
        # Profiles are already sorted by distance in analytics.py
        for i, profile in enumerate(clustering["cluster_profiles"]):
            cid = profile["id"]
            pts = [p for p in clustering["scatter_data"] if p["cluster"] == cid]
            color = label_colors.get(profile["label"], fallback_colors[i % len(fallback_colors)])
            dists = [p["distance"] for p in pts]
            paces = [p["pace"] for p in pts]
            tmins = [p["time_min"] for p in pts]
            fig_cl.add_trace(go.Scatter(
                x=dists, y=paces, mode="markers",
                name=profile["label"],
                marker=dict(size=8, color=color, opacity=0.7),
                legendgroup=f"c{cid}",
            ), row=1, col=1)
            fig_cl.add_trace(go.Scatter(
                x=dists, y=tmins, mode="markers",
                name=profile["label"],
                marker=dict(size=8, color=color, opacity=0.7),
                legendgroup=f"c{cid}", showlegend=False,
            ), row=1, col=2)
        # M:SS on left y-axis
        all_cl_paces = [p["pace"] for p in clustering["scatter_data"]]
        cmin = (int(min(all_cl_paces)) // 5) * 5
        cmax = ((int(max(all_cl_paces)) // 5) + 1) * 5
        ctickv = list(range(cmin, cmax + 1, 10))
        ctickt = [f"{v // 60}:{v % 60:02d}" for v in ctickv]
        fig_cl.update_xaxes(title_text="Distance (m)", row=1, col=1)
        fig_cl.update_xaxes(title_text="Distance (m)", row=1, col=2)
        fig_cl.update_yaxes(title_text="Pace /500m", tickvals=ctickv, ticktext=ctickt, row=1, col=1)
        fig_cl.update_yaxes(title_text="Duration (min)", row=1, col=2)
        fig_cl.update_layout(
            title="Workout Clusters — K-Means",
            template="plotly_white", height=500, width=1000,
        )
        charts["clustering"] = pio.to_html(fig_cl, full_html=False)

        # Pie chart for training balance
        labels = [p["label"] for p in clustering["cluster_profiles"]]
        counts = [p["count"] for p in clustering["cluster_profiles"]]
        colors_pie = [label_colors.get(p["label"], "#999") for p in clustering["cluster_profiles"]]
        fig_pie = go.Figure(data=[go.Pie(
            labels=labels, values=counts,
            marker=dict(colors=colors_pie),
            textinfo="label+percent",
        )])
        fig_pie.update_layout(title="Training Balance", template="plotly_white")
        charts["cluster_pie"] = pio.to_html(fig_pie, full_html=False)

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user": user_resp.data,
            "summary": summary,
            "personal_bests": pbs,
            "charts": charts,
            "clustering": clustering,
            "regression": regression,
            "from_date": from_date or "",
            "to_date": to_date or "",
            "sync_info": sync_info,
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
