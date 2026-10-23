"""What a streamed ``requests.Response`` offers to ``adapters.http.HttpClient`` (integration
I07): fake responses of the download tests inherit it and only set ``content``."""

from __future__ import annotations

from functools import cached_property


class RawBody:
    """``response.raw``: ``read1`` hands out the body a piece at a time, then ``b""``."""

    def __init__(self, content: bytes) -> None:
        self._content = content
        self._at = 0

    def read1(self, amt: int, decode_content: bool = True) -> bytes:
        piece = self._content[self._at : self._at + amt]
        self._at += len(piece)
        return piece


class StreamedBody:
    content: bytes

    @property
    def headers(self) -> dict[str, str]:
        return {}

    @cached_property
    def raw(self) -> RawBody:
        return RawBody(self.content)

    def close(self) -> None:
        return None
