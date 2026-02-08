"""Analytics and statistics engine for Concept2 workout data."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd
from loguru import logger
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler

from .models import WorkoutResult


def results_to_dataframe(results: list[WorkoutResult]) -> pd.DataFrame:
    """Convert a list of WorkoutResult models into a pandas DataFrame."""
    records = []
    for r in results:
        records.append(
            {
                "id": r.id,
                "date": r.date_parsed,
                "distance_m": r.distance,
                "time_seconds": r.time_seconds,
                "type": r.type,
                "workout_type": r.workout_type,
                "pace_500m": r.pace_per_500m,
                "stroke_rate": r.stroke_rate,
                "calories": r.calories_total,
                "heart_rate_avg": r.heart_rate.average if r.heart_rate else None,
                "drag_factor": r.drag_factor,
                "weight_class": r.weight_class,
                "verified": r.verified,
            }
        )
    df = pd.DataFrame(records)
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
        df.sort_values("date", inplace=True)
        df.reset_index(drop=True, inplace=True)
    logger.info(f"DataFrame created with {len(df)} rows")
    return df


def compute_summary(df: pd.DataFrame) -> dict[str, Any]:
    """Compute high-level summary statistics from the workout DataFrame."""
    if df.empty:
        return {"total_workouts": 0}

    total_distance_m = df["distance_m"].sum()
    total_time_s = df["time_seconds"].sum()

    summary = {
        "total_workouts": len(df),
        "total_distance_km": round(total_distance_m / 1000, 2),
        "total_time_hours": round(total_time_s / 3600, 2),
        "avg_distance_m": round(df["distance_m"].mean(), 0),
        "avg_pace_500m": _format_pace(df["pace_500m"].mean()) if df["pace_500m"].notna().any() else "N/A",
        "avg_stroke_rate": round(df["stroke_rate"].mean(), 1) if df["stroke_rate"].notna().any() else "N/A",
        "avg_calories": round(df["calories"].mean(), 0) if df["calories"].notna().any() else "N/A",
        "first_workout": df["date"].min().strftime("%Y-%m-%d"),
        "last_workout": df["date"].max().strftime("%Y-%m-%d"),
        "last_workout_display": df["date"].max().strftime("%d %b %Y"),
        "days_since_last": (pd.Timestamp.now() - df["date"].max()).days,
        "workout_type_breakdown": df["workout_type"].value_counts().to_dict(),
    }
    return summary


def monthly_volume(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate total distance and time per month."""
    if df.empty:
        return pd.DataFrame()
    monthly = df.copy()
    monthly["month"] = monthly["date"].dt.to_period("M").astype(str)
    agg = (
        monthly.groupby("month")
        .agg(
            total_distance_km=("distance_m", lambda x: round(x.sum() / 1000, 2)),
            total_time_hours=("time_seconds", lambda x: round(x.sum() / 3600, 2)),
            workouts=("id", "count"),
            avg_pace_500m=("pace_500m", "mean"),
        )
        .reset_index()
    )
    return agg


def weekly_volume(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate total distance and count per ISO week."""
    if df.empty:
        return pd.DataFrame()
    weekly = df.copy()
    weekly["week"] = weekly["date"].dt.isocalendar().week.astype(int)
    weekly["year"] = weekly["date"].dt.isocalendar().year.astype(int)
    weekly["year_week"] = weekly["year"].astype(str) + "-W" + weekly["week"].astype(str).str.zfill(2)
    agg = (
        weekly.groupby("year_week")
        .agg(
            total_distance_km=("distance_m", lambda x: round(x.sum() / 1000, 2)),
            workouts=("id", "count"),
        )
        .reset_index()
    )
    return agg


def personal_bests(df: pd.DataFrame) -> dict[str, Any]:
    """Find personal bests across common benchmark distances."""
    benchmarks: dict[str, list] = defaultdict(list)
    standard_distances = [2000, 5000, 6000, 10000, 21097, 42195]

    for dist in standard_distances:
        subset = df[df["distance_m"] == dist]
        if not subset.empty:
            best = subset.loc[subset["time_seconds"].idxmin()]
            benchmarks[f"{dist}m"] = {
                "time": _format_time(best["time_seconds"]),
                "pace": _format_pace(best["pace_500m"]) if best["pace_500m"] else "N/A",
                "date": best["date"].strftime("%Y-%m-%d"),
            }
    return dict(benchmarks)


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────
def _format_pace(pace_seconds: float | None) -> str:
    """Format pace (seconds per 500m) into M:SS.T string."""
    if pace_seconds is None or pd.isna(pace_seconds):
        return "N/A"
    minutes = int(pace_seconds // 60)
    seconds = pace_seconds % 60
    return f"{minutes}:{seconds:04.1f}"


def _format_time(total_seconds: float) -> str:
    """Format total seconds into H:MM:SS.T string."""
    hours = int(total_seconds // 3600)
    remaining = total_seconds % 3600
    minutes = int(remaining // 60)
    seconds = remaining % 60
    if hours > 0:
        return f"{hours}:{minutes:02d}:{seconds:04.1f}"
    return f"{minutes}:{seconds:04.1f}"


# ──────────────────────────────────────────────
# Training Heatmap
# ──────────────────────────────────────────────
def training_heatmap_data(df: pd.DataFrame) -> dict[str, Any]:
    """Build a week×weekday matrix of daily distance for a heatmap.

    Returns dict with keys: z_values, weeks, days, height.
    """
    if df.empty:
        return {}

    daily = df.copy()
    daily["day"] = daily["date"].dt.date

    daily_agg = (
        daily.groupby("day")
        .agg(total_meters=("distance_m", "sum"))
        .reset_index()
    )
    daily_agg["day"] = pd.to_datetime(daily_agg["day"])

    # Fill rest days with 0
    all_days = pd.date_range(start=daily_agg["day"].min(), end=daily_agg["day"].max(), freq="D")
    daily_full = daily_agg.set_index("day").reindex(all_days)
    daily_full["total_meters"] = daily_full["total_meters"].fillna(0)
    daily_full.index.name = "day"
    daily_full = daily_full.reset_index()

    # Build calendar matrix
    daily_full["week_num"] = daily_full["day"].dt.isocalendar().week.astype(int)
    daily_full["year"] = daily_full["day"].dt.isocalendar().year.astype(int)
    daily_full["weekday"] = daily_full["day"].dt.isocalendar().day.astype(int)
    daily_full["week_label"] = (
        daily_full["year"].astype(str) + "-W" +
        daily_full["week_num"].astype(str).str.zfill(2)
    )

    matrix = daily_full.pivot_table(
        index="week_label", columns="weekday",
        values="total_meters", aggfunc="sum", fill_value=0,
    )
    day_names = {1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri", 6: "Sat", 7: "Sun"}
    matrix.rename(columns=day_names, inplace=True)

    return {
        "z_values": matrix.values.tolist(),
        "weeks": matrix.index.tolist(),
        "days": matrix.columns.tolist(),
        "height": max(300, len(matrix) * 22),
    }


# ──────────────────────────────────────────────
# Pace Trend Regression
# ──────────────────────────────────────────────
def pace_trend_regression(df: pd.DataFrame) -> dict[str, Any]:
    """Fit linear and polynomial regression on pace over time.

    Returns dict with keys: dates, paces, trend_y, poly_y, rolling_avg,
    slope, r_squared, poly_r_squared, pace_change_per_month, improving.
    """
    if df.empty or not df["pace_500m"].notna().any():
        return {}

    pace_df = df[df["pace_500m"].notna()].copy().sort_values("date")
    first_day = pace_df["date"].min()
    pace_df["days_since_start"] = (pace_df["date"] - first_day).dt.days

    x = pace_df["days_since_start"].values
    y = pace_df["pace_500m"].values

    # Linear regression (degree 1)
    coefficients = np.polyfit(x, y, deg=1)
    slope, intercept = coefficients[0], coefficients[1]
    trend_y = np.polyval(coefficients, x)

    ss_res = np.sum((y - trend_y) ** 2)
    ss_tot = np.sum((y - np.mean(y)) ** 2)
    r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0

    # Polynomial regression (degree 3)
    poly_deg = 3
    poly_coeffs = np.polyfit(x, y, deg=poly_deg)
    poly_y = np.polyval(poly_coeffs, x)

    ss_res_poly = np.sum((y - poly_y) ** 2)
    poly_r_squared = 1 - (ss_res_poly / ss_tot) if ss_tot > 0 else 0

    rolling_avg = pace_df["pace_500m"].rolling(window=10, min_periods=3).mean()

    return {
        "dates": pace_df["date"].dt.strftime("%Y-%m-%d").tolist(),
        "paces": y.tolist(),
        "pace_formatted": [f"{int(s // 60)}:{s % 60:04.1f}" for s in y],
        "trend_y": trend_y.tolist(),
        "poly_y": poly_y.tolist(),
        "rolling_avg": [None if pd.isna(v) else round(v, 2) for v in rolling_avg],
        "slope": round(slope, 4),
        "r_squared": round(r_squared, 3),
        "poly_r_squared": round(poly_r_squared, 3),
        "poly_degree": poly_deg,
        "pace_change_per_month": round(slope * 30, 2),
        "improving": slope < 0,
    }


# ──────────────────────────────────────────────
# Workout Clustering (K-Means)
# ──────────────────────────────────────────────
def workout_clustering(df: pd.DataFrame, n_clusters: int = 4) -> dict[str, Any]:
    """Cluster workouts by distance, pace, and duration using K-Means.

    Returns dict with keys: cluster_data, cluster_stats, elbow_data.
    """
    features = ["distance_m", "pace_500m", "time_seconds"]
    cluster_df = df[features].dropna().copy()

    if len(cluster_df) < n_clusters:
        return {}

    # Scale features
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(cluster_df)

    # Elbow method (K=2..8)
    k_range = range(2, min(9, len(cluster_df)))
    inertias = []
    for k in k_range:
        km = KMeans(n_clusters=k, random_state=42, n_init=10)
        km.fit(X_scaled)
        inertias.append(round(km.inertia_, 1))

    # Final clustering
    n_clusters = min(n_clusters, len(cluster_df))
    kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
    kmeans.fit(X_scaled)
    cluster_df["cluster"] = kmeans.labels_

    # Cluster profiles
    stats = cluster_df.groupby("cluster").agg(
        avg_distance=("distance_m", "mean"),
        avg_pace=("pace_500m", "mean"),
        avg_duration_min=("time_seconds", lambda x: x.mean() / 60),
        count=("distance_m", "count"),
    ).round(1)

    cluster_profiles = []
    for idx, row in stats.iterrows():
        # Auto-label based on distance thresholds
        avg_dist = row["avg_distance"]
        if avg_dist < 2000:
            label = "Sprint"
        elif avg_dist < 7500:
            label = "5K Steady-State"
        elif avg_dist <= 12000:
            label = "10K Steady-State"
        else:
            label = "Long Endurance"

        cluster_profiles.append({
            "id": int(idx),
            "label": label,
            "count": int(row["count"]),
            "avg_distance": round(row["avg_distance"]),
            "avg_pace": _format_pace(row["avg_pace"]),
            "avg_duration_min": round(row["avg_duration_min"]),
        })

    # Sort clusters by average distance (Sprint → 5K → 10K → Long)
    cluster_profiles.sort(key=lambda p: stats.loc[p["id"], "avg_distance"])

    # Scatter data for chart
    scatter_data = []
    for _, row in cluster_df.iterrows():
        scatter_data.append({
            "distance": row["distance_m"],
            "pace": row["pace_500m"],
            "time_min": round(row["time_seconds"] / 60, 1),
            "cluster": int(row["cluster"]),
        })

    return {
        "scatter_data": scatter_data,
        "cluster_profiles": cluster_profiles,
        "elbow_k": list(k_range),
        "elbow_inertias": inertias,
        "n_clusters": n_clusters,
    }
