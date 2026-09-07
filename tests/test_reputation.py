import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "server"))

import server
from reputation import IPReputationChecker, ReputationDecision
from test_dlp import FakeWebSocket


def test_reputation_blocks_malicious_ip_and_caches_the_result():
    calls = []

    def fake_fetcher(ip, api_key):
        calls.append((ip, api_key))
        return {"data": {"attributes": {"last_analysis_stats": {"malicious": 2}}}}

    checker = IPReputationChecker(api_key="test-key", report_fetcher=fake_fetcher)

    assert checker.check_ip("8.8.8.8") == ReputationDecision(False, "IP_REPUTATION_MALICIOUS")
    assert checker.check_ip("8.8.8.8") == ReputationDecision(False, "IP_REPUTATION_MALICIOUS")
    assert calls == [("8.8.8.8", "test-key")]


def test_reputation_allows_clean_and_private_network_ips():
    def fake_fetcher(ip, api_key):
        return {"data": {"attributes": {"last_analysis_stats": {"malicious": 0, "suspicious": 0}}}}

    checker = IPReputationChecker(api_key="test-key", report_fetcher=fake_fetcher)

    assert checker.check_ip("8.8.8.8") == ReputationDecision(True, "IP_REPUTATION_CLEAN")
    assert checker.check_ip("172.20.10.3") == ReputationDecision(True, "IP_PRIVATE_NETWORK")


def test_reputation_allows_when_service_is_unavailable():
    checker = IPReputationChecker(api_key=None)

    assert checker.check_ip("8.8.8.8") == ReputationDecision(True, "REPUTATION_UNAVAILABLE")


def test_malicious_ip_is_blocked_before_authentication(monkeypatch):
    class BlockedChecker:
        def check_ip(self, ip):
            return ReputationDecision(False, "IP_REPUTATION_MALICIOUS")

    websocket = FakeWebSocket([])
    websocket.remote_address = ("8.8.8.8", 12345)
    monkeypatch.setattr(server, "reputation_checker", BlockedChecker())

    asyncio.run(server.chat(websocket))

    assert websocket.sent == ["Connection blocked: IP_REPUTATION_MALICIOUS"]
    assert websocket.closed == [(1008, "Anti-Bot reputation block")]
