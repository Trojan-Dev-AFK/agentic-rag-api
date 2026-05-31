"""LangGraph tool: generate Plotly chart payloads from structured JSON."""

import json
from typing import Any

from langchain_core.tools import tool

from app.core.logger import get_logger

logger = get_logger(__name__)


@tool
def generate_graph(data_json: str) -> str:
    """
    Generate an interactive chart or graph in Plotly JSON format.
    Use this tool ONLY when the user explicitly asks for a chart, graph, plot, or visual breakdown.

    Args:
        data_json: A JSON string with these keys:
            - title (str): Chart title.
            - chart_type (str): One of 'line', 'bar', 'pie', 'scatter'.
            - labels (list[str]): Category names or x-axis values.
            - values (list[float]): Numerical values for each label.
            - x_axis_title (str, optional): Label for the horizontal axis.
            - y_axis_title (str, optional): Label for the vertical axis.

    Example data_json::

        '{"title": "Q1 Revenue", "chart_type": "bar",
          "labels": ["Jan", "Feb", "Mar"], "values": [100, 150, 200]}'
    """
    logger.info("Graph generation invoked", extra={"payload_length": len(data_json)})

    try:
        data = json.loads(data_json)
    except json.JSONDecodeError as exc:
        logger.warning("Graph generation failed — invalid JSON input", extra={"reason": str(exc)})
        return json.dumps({"error": "Invalid JSON provided. Please provide a valid JSON string."})

    title = data.get("title", "Chart")
    chart_type = data.get("chart_type", "bar")
    labels = data.get("labels", [])
    values = data.get("values")
    series = data.get("series")
    x_axis_title = data.get("x_axis_title")
    y_axis_title = data.get("y_axis_title")

    if not labels:
        logger.warning("Graph generation failed — missing labels", extra={"title": title})
        return json.dumps({"error": "'labels' is required and must be a non-empty list."})

    supported_types = ["line", "bar", "pie", "scatter"]
    chosen_type = chart_type.lower() if isinstance(chart_type, str) and chart_type.lower() in supported_types else "bar"
    if chosen_type != chart_type:
        logger.warning(
            "Unsupported chart type — defaulting to bar",
            extra={"requested": chart_type, "using": chosen_type},
        )

    traces: list[Any] = []

    if series and isinstance(series, list):
        for s in series:
            name = s.get("name", "series")
            y = s.get("values", [])
            if not isinstance(y, list) or len(y) != len(labels):
                logger.warning(
                    "Graph generation failed — series length mismatch",
                    extra={"series_name": name, "labels": len(labels), "values": len(y)},
                )
                return json.dumps({"error": f"Series '{name}' must have the same length as 'labels'."})
            trace: dict[str, Any] = {"type": "pie" if chosen_type == "pie" else chosen_type}
            if chosen_type == "pie":
                trace.update({"labels": labels, "values": y, "name": name})
            else:
                trace.update({"x": labels, "y": y, "name": name})
                if chosen_type == "line":
                    trace["mode"] = "lines+markers"
                elif chosen_type == "scatter":
                    trace["mode"] = "markers"
            traces.append(trace)

    elif isinstance(values, list):
        if len(values) != len(labels):
            logger.warning(
                "Graph generation failed — values/labels length mismatch",
                extra={"labels": len(labels), "values": len(values)},
            )
            return json.dumps({"error": "'values' length must match 'labels' length."})
        if chosen_type == "pie":
            traces.append({"type": "pie", "labels": labels, "values": values, "textinfo": "percent+label"})
        else:
            trace = {"type": chosen_type, "x": labels, "y": values}
            if chosen_type == "line":
                trace["mode"] = "lines+markers"
            elif chosen_type == "scatter":
                trace["mode"] = "markers"
            traces.append(trace)

    else:
        logger.warning("Graph generation failed — no values or series provided")
        return json.dumps({"error": "Provide either 'values' (single series) or 'series' (multiple series)."})

    layout = {
        "title": title,
        "xaxis": {"title": x_axis_title} if x_axis_title else {},
        "yaxis": {"title": y_axis_title} if y_axis_title else {},
        "responsive": True,
        "legend": {"orientation": "h"},
    }

    plotly_payload = {
        "is_graph": True,
        "chart_type": chosen_type,
        "payload": {"data": traces, "layout": layout},
    }

    logger.info(
        "Graph generated successfully",
        extra={"title": title, "chart_type": chosen_type, "series_count": len(traces)},
    )
    return json.dumps(plotly_payload)
