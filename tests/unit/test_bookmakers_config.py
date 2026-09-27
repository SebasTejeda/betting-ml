from pathlib import Path

import pytest
from pydantic import ValidationError

from betting_ml.config import load_bookmakers

PERUVIAN_MANUAL = {"teapuesto", "inkabet", "doradobet", "apuestatotal", "betano"}


def test_bookmakers_yaml_schema() -> None:
    books = load_bookmakers()
    assert books.reference.key == "pinnacle"
    assert not books.reference.accessible
    assert books.accessible_keys >= PERUVIAN_MANUAL
    for key in PERUVIAN_MANUAL:
        book = books.get(key)
        assert book is not None and book.source == "manual" and book.role == "soft"
    assert {"pinnacle", "betfair_ex_eu", "betsson"} <= books.api_keys
    assert books.get("betfair_ex_eu").commission == pytest.approx(0.05)  # type: ignore[union-attr]
    # Only bookmakers operating in Peru are accessible.
    assert not books.get("onexbet").accessible  # type: ignore[union-attr]
    assert books.get("nope") is None


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "bookmakers.yaml"
    path.write_text(body, encoding="utf-8")
    return path


@pytest.mark.parametrize(
    "body",
    [
        "bookmakers:\n  - {key: a, name: A, role: soft, accessible: true, source: api}\n",  # no reference
        "bookmakers:\n  - {key: p, name: P, role: reference, accessible: false, source: api}\n"
        "  - {key: p, name: P2, role: soft, accessible: true, source: api}\n",  # duplicated key
        "bookmakers:\n  - {key: p, name: P, role: reference, accessible: false, source: api}\n"
        "  - {key: x, name: X, role: exchange, accessible: false, source: api}\n",  # exchange w/o commission
        "bookmakers:\n  - {key: p, name: P, role: reference, accessible: false, source: api}\n"
        "  - {key: s, name: S, role: soft, accessible: true, source: api, commission: 0.05}\n",
        "bookmakers:\n  - {key: p, name: P, role: reference, accessible: false, source: scraping}\n",
        "bookmakers:\n  - {key: P-1, name: P, role: reference, accessible: false, source: api}\n",
    ],
)
def test_invalid_catalogs_rejected(tmp_path: Path, body: str) -> None:
    with pytest.raises(ValidationError):
        load_bookmakers(_write(tmp_path, body))
