"""Unit tests for deliver.py helpers that don't need a running Splunk."""
import csv
import gzip

import deliver


def _write_gzip_csv(path, rows):
    with gzip.open(path, "wt", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def test_read_results_missing_file_returns_empty():
    assert deliver.read_results(None) == []
    assert deliver.read_results("/no/such/file.csv.gz") == []


def test_read_results_parses_gzip_csv(tmp_path):
    p = tmp_path / "results.csv.gz"
    _write_gzip_csv(str(p), [{"host": "a", "count": "1"}, {"host": "b", "count": "2"}])
    rows = deliver.read_results(str(p))
    assert rows == [{"host": "a", "count": "1"}, {"host": "b", "count": "2"}]


def test_load_config_prefers_kv_over_params(monkeypatch):
    import kvstore
    monkeypatch.setattr(kvstore, "get",
                        lambda auth, name: {"viz_type": "splunk.bar", "width": "1000",
                                            "destinations": [{"type": "email", "to": "x@y"}]})
    cfg = deliver.load_config("KEY", "my_search",
                              {"viz_type": "splunk.line", "width": 800, "to": "ignored@z"})
    assert cfg["viz_type"] == "splunk.bar"      # KV wins
    assert cfg["width"] == 1000                  # coerced to int
    assert cfg["destinations"] == [{"type": "email", "to": "x@y"}]


def test_load_config_falls_back_to_params_and_email_dest(monkeypatch):
    import kvstore
    monkeypatch.setattr(kvstore, "get", lambda auth, name: {})
    cfg = deliver.load_config("KEY", "my_search",
                              {"viz_type": "splunk.area", "to": "a@b"})
    assert cfg["viz_type"] == "splunk.area"      # param used when KV empty
    assert cfg["theme"] == "dark"                # default
    # a bare `to` param with no KV destinations becomes a single email destination
    assert cfg["destinations"] == [{"type": "email", "to": "a@b"}]


def test_load_config_parses_json_string_options(monkeypatch):
    import kvstore
    monkeypatch.setattr(kvstore, "get",
                        lambda auth, name: {"options": '{"charting.chart": "bar"}'})
    cfg = deliver.load_config("KEY", "s", {})
    assert cfg["options"] == {"charting.chart": "bar"}
