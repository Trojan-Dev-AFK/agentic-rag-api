import json
from typing import Any
from langchain_core.tools import tool

# TODO: This is not working as expected. Have to fix it
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

    Example data_json: '{"title": "Q1 Revenue", "chart_type": "bar", "labels": ["Jan", "Feb", "Mar"], "values": [100, 150, 200]}'
    """
    # 1. Parse and validate the input JSON from the LLM
    try:
        data = json.loads(data_json)
    except json.JSONDecodeError:
        return json.dumps({"error": "Invalid JSON provided. Please provide a valid JSON string."})

    title = data.get("title", "Chart")
    chart_type = data.get("chart_type", "bar")
    labels = data.get("labels", [])
    values = data.get("values")
    series = data.get("series")  # Optional: list of {"name":..., "values": [...]}
    x_axis_title = data.get("x_axis_title")
    y_axis_title = data.get("y_axis_title")

    # Basic validation
    if not labels:
        return json.dumps({"error": "'labels' is required and must be a non-empty list."})

    # Determine supported chart type
    supported_types = ['line', 'bar', 'pie', 'scatter']
    chosen_type = chart_type.lower() if isinstance(chart_type, str) and chart_type.lower() in supported_types else 'bar'

    # Build traces: support either a single-series via `values` or multi-series via `series`
    traces: list[Any] = []

    if series and isinstance(series, list):
        # Each series should be a dict with 'name' and 'values'
        for s in series:
            name = s.get('name', 'series')
            y = s.get('values', [])
            if not isinstance(y, list) or len(y) != len(labels):
                return json.dumps({"error": f"Series '{name}' must have the same length as 'labels'."})
            trace = {
                "type": "pie" if chosen_type == 'pie' else chosen_type,
            }
            if chosen_type == 'pie':
                trace.update({"labels": labels, "values": y, "name": name})
            else:
                trace.update({"x": labels, "y": y, "name": name})
                if chosen_type == 'line':
                    trace["mode"] = "lines+markers"
                elif chosen_type == 'scatter':
                    trace["mode"] = "markers"
            traces.append(trace)

    elif isinstance(values, list):
        # Single series provided via `values` list
        if len(values) != len(labels):
            return json.dumps({"error": "'values' length must match 'labels' length."})
        if chosen_type == 'pie':
            traces.append({"type": "pie", "labels": labels, "values": values, "textinfo": "percent+label"})
        else:
            trace = {"type": chosen_type, "x": labels, "y": values}
            if chosen_type == 'line':
                trace["mode"] = "lines+markers"
            elif chosen_type == 'scatter':
                trace["mode"] = "markers"
            traces.append(trace)

    else:
        return json.dumps({"error": "Provide either 'values' (single series) or 'series' (multiple series)."})

    # Layout
    layout = {
        "title": title,
        "xaxis": {"title": x_axis_title} if x_axis_title else {},
        "yaxis": {"title": y_axis_title} if y_axis_title else {},
        "responsive": True,
        "legend": {"orientation": "h"}
    }

    plotly_payload = {
        "is_graph": True,
        "chart_type": chosen_type,
        "payload": {
            "data": traces,
            "layout": layout
        }
    }

    return json.dumps(plotly_payload)
