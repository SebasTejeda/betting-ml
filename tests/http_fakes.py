"""What a streamed ``requests.Response`` offers to ``adapters.http.HttpClient`` (integration
I07): fake responses of the download tests inherit it and only set ``content``."""

from __future__ import annotations

from collections.abc import Iterator


class StreamedBody:
    content: bytes

    @property
    def headers(self) -> dict[str, str]:
        return {}

    def iter_content(self, chunk_size: int) -> Iterator[bytes]:
        for start in range(0, len(self.content), chunk_size):
            yield self.content[start : start + chunk_size]

    def close(self) -> None:
        return None
