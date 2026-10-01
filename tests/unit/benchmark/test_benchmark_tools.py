"""Testes do ferramental de benchmark (amostrador, pontuação, matriz e relatório)."""

import json
import time

import pytest

from scripts.benchmark import report, resources, run_benchmark, scoring

pytestmark = pytest.mark.unit

STAT_1 = "cpu  100 0 100 700 100 0 0 0 0 0\n"
STAT_2 = "cpu  200 0 200 750 150 0 0 0 0 0\n"
MEMINFO = "MemTotal:        8000000 kB\nMemFree: 1 kB\nMemAvailable:    2000000 kB\n"


class TestParsers:
    def test_cpu_times(self):
        assert resources.parse_cpu_times(STAT_1) == (1000, 800)

    def test_meminfo(self):
        total, available = resources.parse_meminfo(MEMINFO)
        assert total == pytest.approx(7812.5) and available == pytest.approx(1953.1, abs=0.1)

    def test_throttled(self):
        assert resources.parse_throttled("throttled=0x50005\n") == 0x50005
        assert resources.parse_throttled("erro") is None
        assert "subtensão agora" in resources.describe_throttled(0x50005)
        assert resources.describe_throttled(0) == []

    def test_proc_stat_with_spaces_in_name(self):
        rest = " ".join(["S", "42"] + ["0"] * 9 + ["7", "3"] + ["0"] * 8 + ["150"])
        assert resources.parse_proc_stat(f"99 (my proc (x)) {rest}") == (42, 10, 150)


class TestSampler:
    def test_summary_peaks(self):
        stats = iter([STAT_1, STAT_1, STAT_2, STAT_2, STAT_2, STAT_2])
        sampler = resources.ResourceSampler(
            root_pid=1, interval=0.01, read_stat=lambda: next(stats, STAT_2), read_mem=lambda: MEMINFO,
            read_temp=lambda: 61.5, read_throttle=lambda: 0x4,
            read_tree=lambda pid: {1: (100, 2560), 2: (50, 2560)}, clock_ticks=100, page_size=4096,
        )
        sampler.start()
        time.sleep(0.15)
        sampler.stop()
        sampler.join()
        summary = sampler.summary()
        assert summary["samples"] >= 2
        assert summary["temp_c"]["max"] == 61.5
        assert summary["mem_used_mb"]["max"] == pytest.approx(5859.4, abs=0.2)
        assert summary["proc_rss_mb"]["max"] == 20.0
        assert summary["max_processes"] == 2
        assert summary["throttled"] == ["throttling agora"]
        assert summary["sys_cpu_pct"]["max"] > 0

    def test_live_reads_on_linux_only(self):
        if not __import__("pathlib").Path("/proc/stat").exists():
            pytest.skip("requer /proc")
        assert resources.parse_cpu_times(resources._read("/proc/stat"))[0] > 0


class TestScoring:
    def test_full_marks(self, tmp_path):
        (tmp_path / "relatorio.md").write_text(
            "Análise exploratória com describe() e pairplot.\ntrain_test_split e StandardScaler.\n"
            "LogisticRegression accuracy: 0.9667\nRandomForest accuracy: 0.9333\n"
            "Recomendamos LogisticRegression em produção porque generaliza melhor.\n"
        )
        (tmp_path / "grafico.png").write_bytes(b"x")
        result = scoring.score_session(tmp_path)
        assert result["score"] == result["max_score"] == 6
        assert result["accuracy"] == pytest.approx(0.9667)
        assert result["algorithms"] == ["logistic regression", "random forest"]

    def test_empty_session_scores_zero(self, tmp_path):
        assert scoring.score_session(tmp_path)["score"] == 0

    def test_implausible_accuracy_does_not_count_as_comparison(self, tmp_path):
        (tmp_path / "a.md").write_text("LogisticRegression e SVM accuracy: 0.31\n")
        result = scoring.score_session(tmp_path)
        assert result["checks"]["two_algorithms"] and not result["checks"]["comparison"]

    def test_percent_accuracy(self):
        assert scoring.reported_accuracies("Acurácia: 96,7%") == [pytest.approx(0.967)]

    def test_outcome(self, tmp_path):
        assert scoring.session_outcome(tmp_path)["metadata"] is False
        meta = {"subtasks": [{"status": "success"}, {"status": "error"}]}
        (tmp_path / "session_metadata.json").write_text(json.dumps(meta))
        out = scoring.session_outcome(tmp_path)
        assert (out["subtasks"], out["subtasks_ok"]) == (2, 1)


class TestRunner:
    def test_build_env_default_and_override(self):
        env = run_benchmark.build_env({"X": "1"}, {"DEVELOPER": "google/a", "*": "anthropic/b"})
        assert env["DEVELOPER_PROVIDER"] == "google" and env["DEVELOPER_MODEL"] == "a"
        assert env["BASE_PROVIDER"] == "anthropic" and env["REVIEWER_MODEL"] == "b"
        assert env["LLM_MODEL"] == "b" and env["X"] == "1"

    def test_sum_tokens(self):
        usage = {"by_provider_model": [
            {"total_prompt_tokens": 10, "total_completion_tokens": 5, "total_tokens": 15, "calls": 2,
             "total_cost_usd": 0.5},
            {"total_prompt_tokens": 1, "total_completion_tokens": 1, "total_tokens": 2, "calls": 1,
             "total_cost_usd": None},
        ]}
        tokens = run_benchmark.sum_tokens(usage)
        assert {k: tokens[k] for k in ("calls", "prompt_tokens", "completion_tokens", "total_tokens", "cost_usd")} == {
            "calls": 3, "prompt_tokens": 11, "completion_tokens": 6, "total_tokens": 17, "cost_usd": 0.5}
        assert run_benchmark.sum_tokens({})["calls"] == 0

    def test_build_env_extra_wins(self):
        env = run_benchmark.build_env({}, {"*": "google/a"}, {"ANTHROPIC_EFFORT": "low", "X": 3})
        assert env["ANTHROPIC_EFFORT"] == "low" and env["X"] == "3"

    def test_cost_by_provider_and_unpriced(self):
        usage = {"by_provider_model": [
            {"llm_provider": "google", "llm_model": "a", "total_cost_usd": 0.25, "total_tokens": 1},
            {"llm_provider": "google", "llm_model": "b", "total_cost_usd": 0.25, "total_tokens": 1},
            {"llm_provider": "openai", "llm_model": "c", "total_cost_usd": None, "total_tokens": 1},
        ]}
        tokens = run_benchmark.sum_tokens(usage)
        assert tokens["cost_by_provider"] == {"google": 0.5, "openai": 0.0}
        assert tokens["unpriced_models"] == ["openai/c"]

    def test_matrix_file_is_valid(self):
        from pathlib import Path
        matrix = json.loads(Path("scripts/benchmark/matrix_baixo_custo.json").read_text())
        names = [c["name"] for c in matrix["combinations"]]
        assert len(names) == len(set(names))
        blob = json.dumps(matrix).lower()
        assert not any(big in blob for big in ("opus", "pro-preview", "gemini-3.1-pro", "fable"))
        anthropic_models = {spec for c in matrix["combinations"] for spec in c["roles"].values() if "anthropic" in spec}
        assert anthropic_models == {"anthropic/claude-sonnet-5-5"}
        assert "anthropic" in matrix["budget_usd"]


def test_results_with_decimal_are_serializable():
    from decimal import Decimal

    assert json.loads(json.dumps({"x": Decimal("1.5")}, default=str)) == {"x": "1.5"}


def test_report_renders_ok_and_skipped():
    ok = {"name": "a", "status": "exit 0", "wall_seconds": 10.5,
          "resources": {
              "sys_cpu_pct": {"max": 80}, "mem_used_mb": {"max": 3000}, "temp_c": {"max": 70}, "throttled": [],
          },
          "tokens": {"prompt_tokens": 100, "completion_tokens": 50, "cost_usd": 0.12}, "db": {"connection_retries": 2},
          "outcome": {"subtasks": 3, "subtasks_ok": 3}, "score": {"score": 5, "max_score": 6, "accuracy": 0.95}}
    text = report.render([ok, {"name": "b", "status": "skipped", "reason": "KEY ausente"}])
    assert "| a | exit 0 | 10.5 | 100 | 50 | 3/3 | 5/6 | 0.950 | 80 | 3000 | 70 | não | 0.1200 | 2 |" in text
    assert "pulada (KEY ausente)" in text
