"""
Shared Pydantic types used across all schemas.

The project-wide datetime format for API responses is `DD:MM:YYYY HH:MM:SS.mmm`.
Timestamps are stored as TIMESTAMPTZ (UTC) in PostgreSQL and serialised to this
string format by `FormattedDatetime` at the Pydantic layer.
"""

from datetime import datetime
from typing import Annotated

from pydantic import PlainSerializer


def _format_datetime(dt: datetime) -> str:
    """Serialise a datetime to `DD:MM:YYYY HH:MM:SS.mmm`."""
    return dt.strftime("%d:%m:%Y %H:%M:%S.") + f"{dt.microsecond // 1000:03d}"


FormattedDatetime = Annotated[datetime, PlainSerializer(_format_datetime, return_type=str)]
