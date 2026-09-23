"""pytest共通設定"""

from typing import Iterator

import pytest

from config import settings


@pytest.fixture(autouse=True)
def _disable_real_typesafe_key(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """ローカルの.env等にTYPESAFE_API_KEYがあってもテストで実APIを呼ばないよう、キーを未設定扱いにする"""
    monkeypatch.setattr(settings, "TYPESAFE_API_KEY", None)
    yield
