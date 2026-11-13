import pytest
from pydantic import ValidationError

from tests.conftest import make_settings


def test_keys_are_split_trimmed_and_deduplicated():
    settings = make_settings(gemini_api_key=" k1, k2 ,,k1, k3 ")
    assert settings.gemini_api_keys == ["k1", "k2", "k3"]


def test_missing_key_fails_at_startup():
    with pytest.raises(ValidationError):
        make_settings(gemini_api_key=" , ")


def test_stub_mode_needs_no_key():
    assert make_settings(gemini_api_key="", ai_stub_mode=True).ai_stub_mode


def test_stub_mode_is_forbidden_in_prod():
    with pytest.raises(ValidationError):
        make_settings(app_env="prod", ai_stub_mode=True, internal_api_key="x")


def test_prod_requires_internal_key():
    with pytest.raises(ValidationError):
        make_settings(app_env="prod", gemini_api_key="k1")
    assert make_settings(app_env="prod", gemini_api_key="k1", internal_api_key="x")
