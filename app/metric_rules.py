"""Deterministic validation and comparison rules for Phase 5 metrics."""

from datetime import date
from numbers import Real
from typing import Any


COUNT_METRICS = {
    "reviews",
    "calls",
    "website_clicks",
    "direction_requests",
    "impressions",
    "search_clicks",
}
SUPPORTED_METRICS = COUNT_METRICS | {"rating", "last_google_post_date"}
SUPPORTED_SOURCE_TYPES = {"manual", "mock", "imported", "live_api"}


def normalize_metric_value(metric_name: str, value: Any) -> Any:
    """Validate a metric and return the value in its stored type."""
    if metric_name not in SUPPORTED_METRICS:
        raise ValueError(f"Unsupported metric: {metric_name}")

    if metric_name in COUNT_METRICS:
        if isinstance(value, bool):
            raise ValueError(f"{metric_name} must be a whole number")
        try:
            numeric_value = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"{metric_name} must be a whole number")
        if numeric_value < 0 or not numeric_value.is_integer():
            raise ValueError(f"{metric_name} must be a non-negative whole number")
        return int(numeric_value)

    if metric_name == "rating":
        if isinstance(value, bool):
            raise ValueError("rating must be a number from 0 to 5")
        try:
            rating = float(value)
        except (TypeError, ValueError):
            raise ValueError("rating must be a number from 0 to 5")
        if rating < 0 or rating > 5:
            raise ValueError("rating must be a number from 0 to 5")
        return rating

    try:
        return date.fromisoformat(str(value)).isoformat()
    except ValueError:
        raise ValueError("last_google_post_date must use YYYY-MM-DD")


def normalize_measurement_period(measurement_period: str) -> str:
    """Require a real calendar month in YYYY-MM format."""
    if len(measurement_period) != 7:
        raise ValueError("measurement_period must use YYYY-MM")
    try:
        parsed = date.fromisoformat(f"{measurement_period}-01")
    except ValueError:
        raise ValueError("measurement_period must use YYYY-MM")
    return parsed.strftime("%Y-%m")


def comparison_number(metric_name: str, value: Any) -> float:
    """Convert a stored value into a number used only for comparisons."""
    if metric_name == "last_google_post_date":
        return float(date.fromisoformat(str(value)).toordinal())
    if isinstance(value, Real) and not isinstance(value, bool):
        return float(value)
    raise ValueError(f"{metric_name} cannot be compared")


def calculate_change(metric_name: str, current_value: Any, older_value: Any) -> dict:
    """Calculate deterministic absolute and percentage change."""
    current_number = comparison_number(metric_name, current_value)
    older_number = comparison_number(metric_name, older_value)
    amount = round(current_number - older_number, 2)
    unit = "days" if metric_name == "last_google_post_date" else "value"
    percent = None
    if metric_name != "last_google_post_date" and older_number != 0:
        percent = round((amount / older_number) * 100, 2)
    return {"amount": amount, "percent": percent, "unit": unit}
