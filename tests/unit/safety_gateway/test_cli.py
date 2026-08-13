from __future__ import annotations

import pytest
from safety_gateway.main import parse_args


def test_mock_flag_is_required() -> None:
    with pytest.raises(SystemExit):
        parse_args([])


def test_mock_flag_accepted() -> None:
    args = parse_args(["--mock"])
    assert args.mock is True
