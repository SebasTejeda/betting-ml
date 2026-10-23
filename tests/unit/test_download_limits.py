"""Spec 004, integration I07 (coverage deferred by the spec 003 audit, T021): every external
download has a timeout, a deadline for the whole body and a size limit, going over them is never
retried, and nothing unreadable is written to disk."""

from __future__ import annotations

import gzip
import json
import socket
import threading
import time
from datetime import date
from pathlib import Path

import httpx
import pytest
import requests
import urllib3

from betting_ml.adapters.clubelo import ClubEloSource
from betting_ml.adapters.http import Download, DownloadError, DownloadTooLargeError, HttpClient
from betting_ml.adapters.openfootball import OpenFootballFormatError, OpenFootballSource
from betting_ml.adapters.the_odds_api import OddsApiError, TheOddsApiClient

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
OF_SAMPLE = FIXTURES / "openfootball" / "cl_2023-24_sample.txt"
ELO_SAMPLE = FIXTURES / "clubelo" / "2023-09-18.csv"


class _Streamed:
    """A streamed requests.Response whose ``raw.read1`` hands out one network read per call
    (``b""`` at the end): counts the reads and whether it was closed."""

    def __init__(
        self, chunks: list[bytes | Exception], headers: dict[str, str] | None = None
    ) -> None:
        self.chunks = iter(chunks)
        self.headers = headers or {}
        self.status_code = 200
        self.read = 0
        self.closed = False
        self.raw = self

    def raise_for_status(self) -> None:
        return None

    def read1(self, amt: int, decode_content: bool = True) -> bytes:
        chunk = next(self.chunks, b"")
        if isinstance(chunk, Exception):
            raise chunk
        self.read += 1 if chunk else 0
        return chunk

    def close(self) -> None:
        self.closed = True


class _Session(requests.Session):
    def __init__(self, responses: list[_Streamed]) -> None:
        super().__init__()
        self.responses = responses
        self.kwargs: list[dict[str, object]] = []

    def get(self, url: str, **kwargs: object) -> _Streamed:  # type: ignore[override]
        self.kwargs.append(kwargs)
        return self.responses.pop(0)


def _client(responses: list[_Streamed], **options: object) -> tuple[HttpClient, _Session]:
    session = _Session(responses)
    return HttpClient(session=session, sleep=lambda _: None, **options), session  # type: ignore[arg-type]


# ------------------------------------------------------------------ HttpClient
def test_a_download_is_streamed_with_a_timeout_and_closed() -> None:
    response = _Streamed([b"a,b\n", b"1,2\n"])
    http, session = _client([response], timeout=7.0)
    assert http.get("https://x/file.csv") == Download("https://x/file.csv", b"a,b\n1,2\n")
    assert session.kwargs == [{"timeout": 7.0, "stream": True}]
    assert response.closed


def test_a_declared_size_over_the_limit_is_refused_before_reading() -> None:
    response = _Streamed([b"x" * 10], headers={"Content-Length": "2048"})
    http, session = _client([response], max_bytes=1024)
    with pytest.raises(DownloadTooLargeError, match="2048 bytes declared"):
        http.get("https://x/huge.csv")
    assert response.read == 0 and response.closed
    assert len(session.kwargs) == 1  # never retried


def test_an_undeclared_body_is_cut_as_soon_as_it_passes_the_limit() -> None:
    response = _Streamed([b"x" * 400] * 100)  # 40 kB, no Content-Length
    http, session = _client([response], max_bytes=1000)
    with pytest.raises(DownloadTooLargeError, match="more than 1000 bytes"):
        http.get("https://x/stream")
    assert response.read == 3  # stopped at 1200 bytes, not at 40 kB
    assert response.closed and len(session.kwargs) == 1


def test_a_body_that_drips_past_the_deadline_is_refused() -> None:
    ticks = iter(range(0, 1000, 50))  # each chunk "takes" 50 s
    response = _Streamed([b"x"] * 10)
    http, session = _client([response], deadline_seconds=120.0, clock=lambda: next(ticks))
    with pytest.raises(DownloadError, match=r"not complete after 120.0s"):
        http.get("https://x/slow")
    assert response.read == 3 and len(session.kwargs) == 1


def test_a_read_timeout_inside_the_body_is_a_network_error_and_retried() -> None:
    timeout = urllib3.exceptions.ReadTimeoutError(None, "x", "read timed out")  # type: ignore[arg-type]
    cut = _Streamed([b"a,b\n", timeout])
    http, session = _client([cut, _Streamed([b"a,b\n1,2\n"])])
    assert http.get("https://x/file.csv").content == b"a,b\n1,2\n"
    assert len(session.kwargs) == 2 and cut.closed


def test_a_real_server_dripping_bytes_is_cut_at_the_deadline() -> None:
    """A real socket, not a double: every byte arrives well within ``timeout``, so only the
    deadline can stop it (reading whole chunks used to wait for the full body)."""
    server = socket.create_server(("127.0.0.1", 0))
    port = server.getsockname()[1]

    def drip() -> None:
        connection, _ = server.accept()
        with connection:
            connection.recv(4096)
            connection.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 40\r\n\r\n")
            try:
                for _ in range(40):
                    time.sleep(0.1)
                    connection.sendall(b"x")
            except OSError:  # the client hung up at its deadline
                pass

    worker = threading.Thread(target=drip, daemon=True)
    worker.start()
    http = HttpClient(retries=1, timeout=2.0, deadline_seconds=0.5)
    started = time.monotonic()
    with pytest.raises(DownloadError, match=r"not complete after 0.5s"):
        http.get(f"http://127.0.0.1:{port}/slow")
    assert time.monotonic() - started < 2.0  # the whole body would take 4 s
    server.close()
    worker.join(timeout=5)


# ------------------------------------------------------------------ files written to disk
def test_clubelo_never_writes_an_oversized_download(tmp_path: Path) -> None:
    http, _ = _client([_Streamed([ELO_SAMPLE.read_bytes()])], max_bytes=100)
    source = ClubEloSource(tmp_path, http=http, today=date(2023, 9, 20))
    with pytest.raises(DownloadTooLargeError):
        source.ratings_on(date(2023, 9, 18))
    assert not source.raw_path(date(2023, 9, 18)).exists()


@pytest.mark.parametrize(
    "body",
    [
        b"\xff\xfe not utf-8 \x80",
        OF_SAMPLE.read_text(encoding="utf-8").replace("# Matches    17", "# Matches    3").encode(),
    ],
    ids=["not-utf8", "more-matches-than-declared"],
)
def test_openfootball_never_caches_a_file_it_cannot_read(tmp_path: Path, body: bytes) -> None:
    http, _ = _client([_Streamed([body])])
    source = OpenFootballSource(tmp_path, http=http)
    with pytest.raises(OpenFootballFormatError):
        source.fetch_season("UCL", "2023-24")
    assert not source.raw_path("UCL", "2023-24").exists()


def test_openfootball_keeps_its_good_copy_when_a_refresh_is_unreadable(tmp_path: Path) -> None:
    good = OF_SAMPLE.read_bytes()
    http, _ = _client([_Streamed([good]), _Streamed([b"\x80 broken"])])
    source = OpenFootballSource(tmp_path, http=http, refresh_seasons={"2023-24"})
    first = source.fetch_season("UCL", "2023-24")
    with pytest.raises(OpenFootballFormatError):
        source.fetch_season("UCL", "2023-24")  # current season: downloaded again
    assert source.raw_path("UCL", "2023-24").read_bytes() == good
    assert len(first) > 0


# ------------------------------------------------------------------ The Odds API
EVENT = {"id": "evt-001", "home_team": "Real Madrid", "away_team": "RB Leipzig"}
KEY = "odds-key-for-limit-tests-0123"


def _odds_client(handler: object, calls: list[str], **options: object) -> TheOddsApiClient:
    def counted(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return handler(request)  # type: ignore[operator, no-any-return]

    return TheOddsApiClient(
        KEY,
        regions="eu",
        http=httpx.Client(transport=httpx.MockTransport(counted)),
        sleep=lambda _: None,
        **options,  # type: ignore[arg-type]
    )


def test_a_gzipped_answer_is_read_once_decoded() -> None:
    calls: list[str] = []
    body = gzip.compress(json.dumps(EVENT).encode())
    client = _odds_client(
        lambda request: httpx.Response(
            200,
            content=body,
            headers={"content-encoding": "gzip", "x-requests-remaining": "490"},
        ),
        calls,
    )
    response = client.event_odds("soccer_uefa_champs_league", "evt-001", ["h2h"])
    assert response.events == [EVENT] and response.credits.remaining == 490


@pytest.mark.parametrize("declared", [True, False], ids=["declared", "streamed"])
def test_an_oversized_odds_answer_is_refused_and_never_retried(declared: bool) -> None:
    calls: list[str] = []
    big = json.dumps([EVENT] * 2000).encode()  # ~150 kB
    headers = {} if declared else {"transfer-encoding": "chunked"}

    def handler(request: httpx.Request) -> httpx.Response:
        if declared:
            return httpx.Response(200, content=big, headers=headers)
        return httpx.Response(
            200, content=iter([big[i : i + 4096] for i in range(0, len(big), 4096)])
        )

    client = _odds_client(handler, calls, max_bytes=10_000)
    with pytest.raises(OddsApiError, match="502") as refused:
        client.events("soccer_uefa_champs_league")
    assert KEY not in str(refused.value)
    assert len(calls) == 1


def test_an_odds_answer_past_the_deadline_is_refused() -> None:
    calls: list[str] = []
    ticks = iter(range(0, 1000, 40))
    chunks = [json.dumps([EVENT]).encode()[i : i + 8] for i in range(0, 64, 8)]
    client = _odds_client(
        lambda request: httpx.Response(200, content=iter(chunks)),
        calls,
        deadline_seconds=60.0,
        clock=lambda: next(ticks),
    )
    with pytest.raises(OddsApiError, match=r"not complete after 60.0s"):
        client.events("soccer_uefa_champs_league")
    assert len(calls) == 1
