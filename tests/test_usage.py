import csv

from s2f.usage import UsageTracker

RATES = {"gpt-4o-transcribe": 0.006, "whisper-1": 0.006}


class TestEstimate:
    def test_estimate_per_minute(self, tmp_path):
        t = UsageTracker(tmp_path / "u.csv", RATES)
        # 60 s at $0.006/min = 0.006
        assert abs(t.estimate("whisper-1", 60) - 0.006) < 1e-9
        # 30 s = half
        assert abs(t.estimate("whisper-1", 30) - 0.003) < 1e-9

    def test_unknown_model_returns_none(self, tmp_path):
        t = UsageTracker(tmp_path / "u.csv", RATES)
        assert t.estimate("nonexistent-model", 60) is None


class TestRecord:
    def test_record_writes_csv_and_accumulates(self, tmp_path):
        path = tmp_path / "u.csv"
        t = UsageTracker(path, RATES)
        t.record("whisper-1", 60)
        t.record("whisper-1", 30)
        assert abs(t.total - 0.009) < 1e-9

        rows = list(csv.DictReader(path.open(encoding="utf-8")))
        assert len(rows) == 2
        assert rows[0]["model"] == "whisper-1"
        assert float(rows[0]["seconds"]) == 60.0

    def test_total_persists_across_instances(self, tmp_path):
        path = tmp_path / "u.csv"
        UsageTracker(path, RATES).record("whisper-1", 60)
        # A new instance must read the previous total from the CSV.
        t2 = UsageTracker(path, RATES)
        assert abs(t2.total - 0.006) < 1e-9

    def test_unknown_model_not_recorded(self, tmp_path):
        path = tmp_path / "u.csv"
        t = UsageTracker(path, RATES)
        assert t.record("unknown", 60) is None
        assert t.total == 0.0
        assert not path.exists()
