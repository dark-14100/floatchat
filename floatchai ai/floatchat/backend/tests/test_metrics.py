from __future__ import annotations

from app.monitoring import metrics as metrics_module


class _RecorderMetric:
    def __init__(self):
        self.label_calls = []
        self.observations = []
        self.increments = []
        self.set_values = []

    def labels(self, **kwargs):
        self.label_calls.append(kwargs)
        return self

    def observe(self, value):
        self.observations.append(value)

    def inc(self, amount=1.0):
        self.increments.append(amount)

    def set(self, value):
        self.set_values.append(value)


def test_metric_helpers_record_expected_labels(monkeypatch):
    llm_metric = _RecorderMetric()
    db_metric = _RecorderMetric()
    hit_metric = _RecorderMetric()
    miss_metric = _RecorderMetric()
    celery_metric = _RecorderMetric()
    anomaly_metric = _RecorderMetric()

    monkeypatch.setattr(metrics_module, "floatchat_llm_call_duration_seconds", llm_metric)
    monkeypatch.setattr(metrics_module, "floatchat_db_query_duration_seconds", db_metric)
    monkeypatch.setattr(metrics_module, "floatchat_redis_cache_hits_total", hit_metric)
    monkeypatch.setattr(metrics_module, "floatchat_redis_cache_misses_total", miss_metric)
    monkeypatch.setattr(metrics_module, "floatchat_celery_task_duration_seconds", celery_metric)
    monkeypatch.setattr(metrics_module, "floatchat_anomaly_scan_duration_seconds", anomaly_metric)

    token = metrics_module.set_current_endpoint("/api/v1/query")
    try:
        metrics_module.observe_llm_call_duration(0.42, "openai", "gpt-4o")
        metrics_module.observe_db_query_duration(0.07)
        metrics_module.record_cache_hit("query_result")
        metrics_module.record_cache_miss("query_result")
        metrics_module.observe_celery_task_duration(1.3, "app.ingestion.tasks.ingest_file_task")
        metrics_module.set_anomaly_scan_duration(12.5)
    finally:
        metrics_module.reset_current_endpoint(token)

    assert llm_metric.label_calls[-1] == {"provider": "openai", "model": "gpt-4o"}
    assert llm_metric.observations[-1] == 0.42

    assert db_metric.label_calls[-1] == {"endpoint": "/api/v1/query"}
    assert db_metric.observations[-1] == 0.07

    assert hit_metric.label_calls[-1] == {"operation": "query_result"}
    assert hit_metric.increments[-1] == 1.0

    assert miss_metric.label_calls[-1] == {"operation": "query_result"}
    assert miss_metric.increments[-1] == 1.0

    assert celery_metric.label_calls[-1] == {"task_name": "app.ingestion.tasks.ingest_file_task"}
    assert celery_metric.observations[-1] == 1.3

    assert anomaly_metric.set_values[-1] == 12.5
