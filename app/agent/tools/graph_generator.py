import json
from typing import List, Optional
from langchain_core.tools import tool

# TODO: Tool is not getting called correctly. Check it in the future.
@tool
def generate_graph(
        title: str,
        chart_type: str,
        labels: List[str],
        values: List[float],
        x_axis_title: Optional[str] = None,
        y_axis_title: Optional[str] = None
) -> str:
    """
    Generate an interactive data visualization payload (Plotly format).
    Use this tool ONLY when the user explicitly requests a chart, graph, plot, or visual breakdown of data.

    Perfect for:
    - Financial Analysis: Revenue/expense trends over time, asset allocation pie charts, budgetary bars.
    - Healthcare Analysis: Patient vitals tracking over time (blood pressure, glucose), demographic distribution, treatment efficacy rates.

    Args:
        title: The descriptive title of the chart.
        chart_type: Must be one of ['line', 'bar', 'pie', 'scatter'].
        labels: The X-axis data points, categories, dates, or time periods.
        values: The Y-axis numerical values corresponding to each label.
        x_axis_title: Optional text label for the horizontal axis.
        y_axis_title: Optional text label for the vertical axis.
    """
    # Validate the chart type to keep the payload clean
    supported_types = ['line', 'bar', 'pie', 'scatter']
    chosen_type = chart_type.lower() if chart_type.lower() in supported_types else 'bar'

    # Build a standard Plotly trace configuration
    trace = {}
    if chosen_type == 'pie':
        trace = {
            "type": "pie",
            "labels": labels,
            "values": values,
            "textinfo": "percent+label"
        }
    else:
        trace = {
            "type": chosen_type,
            "x": labels,
            "y": values,
            "mode": "lines+markers" if chosen_type == 'line' else "markers" if chosen_type == 'scatter' else None
        }

    # Build the Plotly layout schema
    layout = {
        "title": title,
        "xaxis": {"title": x_axis_title} if x_axis_title else {},
        "yaxis": {"title": y_axis_title} if y_axis_title else {},
        "responsive": True
    }

    # Package into a structured JSON string that frontends can parse natively
    plotly_payload = {
        "is_graph": True,
        "chart_type": chosen_type,
        "payload": {
            "data": [trace],
            "layout": layout
        }
    }

    return json.dumps(plotly_payload)
