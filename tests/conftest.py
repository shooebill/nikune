"""pytest共通設定"""

from typing import Iterator

import pytest

from config import settings
from nikune.content_generator import ContentGenerator


@pytest.fixture(autouse=True)
def _disable_real_typesafe_key(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """ローカルの.env等にTYPESAFE_API_KEYがあってもテストで実APIを呼ばないよう、キーを未設定扱いにする"""
    monkeypatch.setattr(settings, "TYPESAFE_API_KEY", None)
    yield


@pytest.fixture(autouse=True)
def _ignore_local_quote_comments(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """ローカルに非公開のdata/quote_comments.tsvがあっても読まず、どの環境でもフォールバック文言でテストする"""
    monkeypatch.setattr(ContentGenerator, "QUOTE_COMMENTS_FILE", "data/quote_comments.nonexistent.tsv")
    yield
