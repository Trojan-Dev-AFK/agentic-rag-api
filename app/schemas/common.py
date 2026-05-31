from datetime import datetime
from typing import Annotated

from pydantic import PlainSerializer


def _format_datetime(dt: datetime) -> str:
    return dt.strftime("%d:%m:%Y %H:%M:%S.") + f"{dt.microsecond // 1000:03d}"


FormattedDatetime = Annotated[datetime, PlainSerializer(_format_datetime, return_type=str)]


