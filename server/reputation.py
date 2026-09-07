"""IP-reputation checks used by the Anti-Bot connection gate."""

import ipaddress
import json
import os
import time
from dataclasses import dataclass
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

VIRUSTOTAL_IP_URL = "https://www.virustotal.com/api/v3/ip_addresses/{ip}"
CACHE_TTL_SECONDS = 600
UNAVAILABLE_CACHE_TTL_SECONDS = 60


@dataclass(frozen=True)
class ReputationDecision:
    allowed: bool
    reason_code: str


ReportFetcher = Callable[[str, str], dict]


def fetch_virustotal_report(ip: str, api_key: str) -> dict:
    """Fetch an existing VirusTotal IP report without requesting a re-scan."""
    request = Request(
        VIRUSTOTAL_IP_URL.format(ip=ip),
        headers={"x-apikey": api_key},
        method="GET",
    )
    with urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


class IPReputationChecker:
    """Use cached VirusTotal IP evidence to make an Anti-Bot decision."""

    def __init__(
        self,
        api_key: str | None = None,
        report_fetcher: ReportFetcher = fetch_virustotal_report,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.getenv("VIRUSTOTAL_API_KEY")
        self.report_fetcher = report_fetcher
        self.cache: dict[str, tuple[float, ReputationDecision]] = {}

    def check_ip(self, ip: str) -> ReputationDecision:
        """Return an allow/block decision and a stable public reason code."""
        try:
            parsed_ip = ipaddress.ip_address(ip)
        except ValueError:
            return ReputationDecision(False, "IP_REPUTATION_INVALID")

        if not parsed_ip.is_global:
            return ReputationDecision(True, "IP_PRIVATE_NETWORK")

        cached = self.cache.get(ip)
        now = time.monotonic()
        if cached is not None and cached[0] > now:
            return cached[1]

        if not self.api_key:
            return self._cache(ip, ReputationDecision(True, "REPUTATION_UNAVAILABLE"), 60)

        try:
            report = self.report_fetcher(ip, self.api_key)
            stats = report["data"]["attributes"].get("last_analysis_stats", {})
            malicious = int(stats.get("malicious", 0))
            suspicious = int(stats.get("suspicious", 0))
        except (HTTPError, URLError, TimeoutError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            return self._cache(ip, ReputationDecision(True, "REPUTATION_UNAVAILABLE"), 60)

        if malicious > 0:
            return self._cache(ip, ReputationDecision(False, "IP_REPUTATION_MALICIOUS"))
        if suspicious > 0:
            return self._cache(ip, ReputationDecision(False, "IP_REPUTATION_SUSPICIOUS"))
        return self._cache(ip, ReputationDecision(True, "IP_REPUTATION_CLEAN"))

    def _cache(
        self,
        ip: str,
        decision: ReputationDecision,
        ttl_seconds: int = CACHE_TTL_SECONDS,
    ) -> ReputationDecision:
        self.cache[ip] = (time.monotonic() + ttl_seconds, decision)
        return decision
