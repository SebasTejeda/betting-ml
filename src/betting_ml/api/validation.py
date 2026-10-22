"""Strict input types of the API (spec 003, US4): every client-supplied string has a pattern
and a maximum length, every date a range, and input models reject unknown fields.

The constraints live in the types (StringConstraints, Interval), so the same names work in
request bodies and in path/query parameters. Patterns are a little wider than today's data
(e.g. any 1-8 alphanumeric league code), so an unknown but well-formed value still gets its
404 from the use case; anything malformed stops here with a 422.
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated

from annotated_types import Interval
from pydantic import BaseModel, ConfigDict, StringConstraints

from betting_ml.api.errors import ApiError

# no control characters (newline and tab allowed only in free notes) nor markup brackets
_NO_CONTROL = r"^[^\x00-\x1f\x7f<>]*$"
_NOTE_TEXT = r"^[^\x00-\x08\x0b\x0c\x0e-\x1f\x7f]*$"

LeagueCode = Annotated[
    str, StringConstraints(min_length=1, max_length=8, pattern=r"^[A-Za-z0-9]+$")
]
# {league}-{YYYY-MM-DD}-{home slug}-{away slug} (domain.entities.make_match_id)
MatchId = Annotated[
    str,
    StringConstraints(
        min_length=14,
        max_length=160,
        pattern=r"^[A-Za-z0-9]{1,8}-\d{4}-\d{2}-\d{2}-[a-z0-9-]{1,140}$",
    ),
]
BookmakerKey = Annotated[
    str, StringConstraints(min_length=1, max_length=40, pattern=r"^[a-z0-9_]+$")
]
TeamName = Annotated[str, StringConstraints(min_length=1, max_length=60, pattern=_NO_CONTROL)]
Note = Annotated[str, StringConstraints(max_length=500, pattern=_NOTE_TEXT)]
Currency = Annotated[str, StringConstraints(min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")]

MIN_DATE = dt.date(2000, 1, 1)
MAX_DATE = dt.date(2099, 12, 31)
ApiDate = Annotated[dt.date, Interval(ge=MIN_DATE, le=MAX_DATE)]

MAX_PAGE = 10_000
MAX_PAGE_SIZE = 500
MAX_ID = 2**31 - 1


class StrictInput(BaseModel):
    """Base of every request body: unknown fields are a 422, never silently ignored."""

    model_config = ConfigDict(extra="forbid")


def ordered_period(date_from: dt.date | None, date_to: dt.date | None) -> None:
    """``from`` after ``to`` is a client error, not an empty result."""
    if date_from is not None and date_to is not None and date_from > date_to:
        raise ApiError(
            422,
            "VALIDATION_ERROR",
            "Parámetros de entrada inválidos",
            {"errors": [{"loc": ["query", "from"], "msg": "Debe ser anterior o igual a 'to'"}]},
        )
