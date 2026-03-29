"""Feature 10 notification module tests."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.db.models import Anomaly
from app.notifications import email, sender, slack


def test_notify_noop_when_notifications_disabled(monkeypatch):
    monkeypatch.setattr(sender.settings, "NOTIFICATIONS_ENABLED", False)
    monkeypatch.setattr(sender.settings, "NOTIFICATION_EMAIL_ENABLED", True)
    monkeypatch.setattr(sender.settings, "NOTIFICATION_SLACK_ENABLED", True)

    email_mock = MagicMock()
    slack_mock = MagicMock()
    monkeypatch.setattr(sender, "send_email_notification", email_mock)
    monkeypatch.setattr(sender, "send_slack_notification", slack_mock)

    sender.notify("ingestion_completed", {"dataset_name": "A"})

    email_mock.assert_not_called()
    slack_mock.assert_not_called()


def test_notify_dispatches_channels_and_isolates_failures(monkeypatch):
    monkeypatch.setattr(sender.settings, "NOTIFICATIONS_ENABLED", True)
    monkeypatch.setattr(sender.settings, "NOTIFICATION_EMAIL_ENABLED", True)
    monkeypatch.setattr(sender.settings, "NOTIFICATION_SLACK_ENABLED", True)

    monkeypatch.setattr(sender, "send_email_notification", MagicMock(side_effect=RuntimeError("email down")))
    slack_mock = MagicMock()
    monkeypatch.setattr(sender, "send_slack_notification", slack_mock)
    monkeypatch.setattr(sender, "logger", MagicMock())

    sender.notify("ingestion_failed", {"dataset_name": "A", "error_message": "x"})

    slack_mock.assert_called_once()


def test_parse_recipients_splits_and_strips():
    recipients = email._parse_recipients(" a@example.com, ,b@example.com , c@example.com ")
    assert recipients == ["a@example.com", "b@example.com", "c@example.com"]


def test_email_send_noop_when_config_missing(monkeypatch):
    monkeypatch.setattr(email.settings, "NOTIFICATION_EMAIL_TO", None)
    monkeypatch.setattr(email.settings, "NOTIFICATION_EMAIL_SMTP_HOST", None)
    monkeypatch.setattr(email.settings, "NOTIFICATION_EMAIL_FROM", None)

    smtp_ctor = MagicMock()
    monkeypatch.setattr(email.smtplib, "SMTP", smtp_ctor)

    email.send_notification("ingestion_completed", {"dataset_name": "X"})
    smtp_ctor.assert_not_called()


def test_email_send_uses_bcc_and_smtp(monkeypatch):
    monkeypatch.setattr(email.settings, "NOTIFICATION_EMAIL_TO", "a@example.com,b@example.com")
    monkeypatch.setattr(email.settings, "NOTIFICATION_EMAIL_SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(email.settings, "NOTIFICATION_EMAIL_SMTP_PORT", 587)
    monkeypatch.setattr(email.settings, "NOTIFICATION_EMAIL_FROM", "noreply@example.com")
    monkeypatch.setattr(email.settings, "NOTIFICATION_EMAIL_SMTP_USER", "smtp-user")
    monkeypatch.setattr(email.settings, "NOTIFICATION_EMAIL_SMTP_PASSWORD", "smtp-pass")
    monkeypatch.setattr(email, "logger", MagicMock())

    sent = {"message": None, "starttls": 0, "login": 0}

    class _SMTP:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def starttls(self):
            sent["starttls"] += 1

        def login(self, user, password):
            assert user == "smtp-user"
            assert password == "smtp-pass"
            sent["login"] += 1

        def send_message(self, message):
            sent["message"] = message

    monkeypatch.setattr(email.smtplib, "SMTP", lambda *args, **kwargs: _SMTP())

    email.send_notification("ingestion_completed", {"dataset_name": "X", "profiles_ingested": 12})

    assert sent["starttls"] == 1
    assert sent["login"] == 1
    assert sent["message"] is not None
    assert sent["message"]["To"] == "noreply@example.com"
    assert sent["message"]["Bcc"] == "a@example.com, b@example.com"


def test_slack_send_noop_when_webhook_missing(monkeypatch):
    monkeypatch.setattr(slack.settings, "NOTIFICATION_SLACK_WEBHOOK_URL", None)

    post_mock = MagicMock()
    monkeypatch.setattr(slack.httpx, "post", post_mock)

    slack.send_notification("ingestion_completed", {"dataset_name": "x"})
    post_mock.assert_not_called()


def test_slack_send_posts_payload(monkeypatch):
    monkeypatch.setattr(slack.settings, "NOTIFICATION_SLACK_WEBHOOK_URL", "https://hooks.slack.test")
    monkeypatch.setattr(slack, "logger", MagicMock())

    response = MagicMock()
    response.raise_for_status = MagicMock()
    post_mock = MagicMock(return_value=response)
    monkeypatch.setattr(slack.httpx, "post", post_mock)

    slack.send_notification("anomalies_detected", {"anomaly_count": 3})

    post_mock.assert_called_once()
    response.raise_for_status.assert_called_once()


def test_anomaly_stub_dispatches_notify_when_rows_exist(monkeypatch):
    from app.anomaly import tasks as anomaly_tasks

    notify_mock = MagicMock()
    monkeypatch.setattr(anomaly_tasks, "notify", notify_mock)

    row = Anomaly(
        float_id=1,
        profile_id=10,
        anomaly_type="spatial_baseline",
        severity="high",
        variable="temperature",
        baseline_value=10.0,
        observed_value=20.0,
        deviation_percent=100.0,
        description="test",
        detected_at=datetime.now(UTC),
        region="Arabian Sea",
    )

    anomaly_tasks._notify_new_anomalies([row])

    notify_mock.assert_called_once()
    args, kwargs = notify_mock.call_args
    assert args[0] == "anomalies_detected"
    assert args[1]["anomaly_count"] == 1


def test_anomaly_stub_noop_on_empty_rows(monkeypatch):
    from app.anomaly import tasks as anomaly_tasks

    notify_mock = MagicMock()
    monkeypatch.setattr(anomaly_tasks, "notify", notify_mock)

    anomaly_tasks._notify_new_anomalies([])

    notify_mock.assert_not_called()
