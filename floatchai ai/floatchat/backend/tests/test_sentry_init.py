from __future__ import annotations

import types

from app.monitoring import sentry as sentry_module


def test_init_sentry_disabled_when_dsn_missing(monkeypatch):
    monkeypatch.setattr(sentry_module.settings, "SENTRY_DSN_BACKEND", None)
    monkeypatch.setattr(sentry_module.settings, "SENTRY_DSN", None)

    assert sentry_module.init_sentry() is False


def test_init_sentry_uses_expected_config(monkeypatch):
    init_kwargs = {}

    def _fake_init(**kwargs):
        init_kwargs.update(kwargs)

    fake_sdk = types.SimpleNamespace(init=_fake_init)
    fake_fastapi = types.SimpleNamespace(FastApiIntegration=lambda **kwargs: ("fastapi", kwargs))
    fake_sqlalchemy = types.SimpleNamespace(SqlalchemyIntegration=lambda **kwargs: ("sqlalchemy", kwargs))

    monkeypatch.setitem(__import__("sys").modules, "sentry_sdk", fake_sdk)
    monkeypatch.setitem(__import__("sys").modules, "sentry_sdk.integrations.fastapi", fake_fastapi)
    monkeypatch.setitem(__import__("sys").modules, "sentry_sdk.integrations.sqlalchemy", fake_sqlalchemy)

    monkeypatch.setattr(sentry_module.settings, "SENTRY_DSN_BACKEND", "https://example@sentry.io/1")
    monkeypatch.setattr(sentry_module.settings, "SENTRY_DSN", None)
    monkeypatch.setattr(sentry_module.settings, "ENVIRONMENT", "test")
    monkeypatch.setattr(sentry_module.settings, "APP_VERSION", "1.2.3")
    monkeypatch.setattr(sentry_module.settings, "SENTRY_TRACES_SAMPLE_RATE", 0.25)

    assert sentry_module.init_sentry() is True
    assert init_kwargs["dsn"] == "https://example@sentry.io/1"
    assert init_kwargs["environment"] == "test"
    assert init_kwargs["release"] == "1.2.3"
    assert init_kwargs["traces_sample_rate"] == 0.25
    assert init_kwargs["send_default_pii"] is False
    assert callable(init_kwargs["before_send"])
