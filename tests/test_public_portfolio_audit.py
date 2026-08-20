from pathlib import Path

from scripts.check_public_portfolio import audit


def test_public_portfolio_boundary_is_clean() -> None:
    root = Path(__file__).resolve().parents[1]
    assert audit(root) == []
