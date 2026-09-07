"""Show the Anti-Bot verdict for one IP without exposing the API key."""

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "server"))

import server  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Check an IP with the server's Anti-Bot policy.")
    parser.add_argument("ip", help="Public or private IP address to check")
    args = parser.parse_args()

    decision = server.reputation_checker.check_ip(args.ip)
    print(f"IP: {args.ip}")
    print(f"Verdict: {'ALLOW' if decision.allowed else 'BLOCK'}")
    print(f"Reason: {decision.reason_code}")


if __name__ == "__main__":
    main()
