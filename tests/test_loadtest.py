"""The load-test tool is a deliverable, so it has to work like any other code."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOADTEST = PROJECT_ROOT / "scripts" / "loadtest.py"


def run_loadtest(tmp_path, *arguments):
    """Run the tool as a real command and give back its parsed results."""
    results_file = tmp_path / "results.json"
    finished = subprocess.run(
        [sys.executable, str(LOADTEST), "--json", str(results_file), *arguments],
        capture_output=True,
        text=True,
        timeout=300,
        cwd=PROJECT_ROOT,
    )
    assert results_file.is_file(), f"no results written\n{finished.stdout}\n{finished.stderr}"
    return finished, json.loads(results_file.read_text(encoding="utf-8"))


def test_the_chat_scenario_delivers_every_message_to_the_right_room(tmp_path):
    finished, results = run_loadtest(
        tmp_path, "--scenario", "chat", "--users", "4", "--messages", "3", "--prefix", "ci",
    )

    assert finished.returncode == 0, finished.stdout
    report = results[0]
    assert report["passed"] is True
    assert report["measurements"]["delivery rate"] == "100.00%"
    assert report["measurements"]["cross-room leaks"] == 0
    # 4 users over 2 rooms, 3 messages each, every room member receives each one.
    assert report["measurements"]["messages delivered / expected"] == "24 / 24"


def test_the_abuse_scenario_proves_the_server_refuses_bad_input(tmp_path):
    finished, results = run_loadtest(tmp_path, "--scenario", "abuse", "--prefix", "ci")

    assert finished.returncode == 0, finished.stdout
    report = results[0]
    assert report["passed"] is True
    for check in (
        "unissued token refused",
        "empty message refused",
        "over-length message refused",
        "control characters refused",
        "DLP blocks the secret recipe",
        "frame-limit overflow closes the connection",
        "duplicate username refused",
        "wrong password refused",
    ):
        assert report["measurements"][check] == "yes", f"{check} -> {report['measurements'][check]}"


def test_a_failing_scenario_reports_a_non_zero_exit_code():
    """The tool has to be usable from a pipeline, so failure must be visible."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("loadtest", LOADTEST)
    loadtest = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loadtest)

    report = loadtest.Report("demo", "nothing")
    assert report.passed is True
    report.fail("something went wrong")
    assert report.passed is False
    assert report.failures == ["something went wrong"]


def test_percentiles_describe_the_spread():
    import importlib.util

    spec = importlib.util.spec_from_file_location("loadtest", LOADTEST)
    loadtest = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loadtest)

    assert loadtest.percentiles([]) is None
    spread = loadtest.percentiles([0.001 * n for n in range(1, 101)])
    assert spread["p50_ms"] == pytest.approx(50.5, abs=1)
    assert spread["max_ms"] == pytest.approx(100, abs=1)
