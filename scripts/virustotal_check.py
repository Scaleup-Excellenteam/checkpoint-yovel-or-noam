"""Check a file hash in VirusTotal, with optional explicit file upload.

Never scan source code, chat.db, .env files, logs, or other private files with
the public VirusTotal service. Public submissions can be shared with security
partners. A hash lookup does not upload the file.
"""

import argparse
import hashlib
import json
import mimetypes
import os
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

API_BASE_URL = "https://www.virustotal.com/api/v3"


def sha256_file(path: Path) -> str:
    """Return the SHA-256 fingerprint of a local file."""
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def api_request(url: str, api_key: str, data: bytes | None = None, content_type: str | None = None) -> dict:
    """Call VirusTotal and decode its JSON response."""
    parsed_url = urlparse(url)
    if parsed_url.scheme != "https" or parsed_url.netloc != "www.virustotal.com":
        raise ValueError("VirusTotal requests must use https://www.virustotal.com")
    headers = {"x-apikey": api_key}
    if content_type:
        headers["Content-Type"] = content_type
    request = Request(url, data=data, headers=headers, method="POST" if data else "GET")
    with urlopen(request, timeout=30) as response:  # nosec B310
        return json.loads(response.read().decode("utf-8"))


def multipart_file(path: Path) -> tuple[bytes, str]:
    """Build the multipart body required by VirusTotal's file-upload endpoint."""
    boundary = f"----tspo-{uuid.uuid4().hex}"
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    body = b"".join(
        [
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'.encode(),
            f"Content-Type: {content_type}\r\n\r\n".encode(),
            path.read_bytes(),
            f"\r\n--{boundary}--\r\n".encode(),
        ]
    )
    return body, f"multipart/form-data; boundary={boundary}"


def print_stats(report: dict) -> None:
    stats = report["data"]["attributes"].get("last_analysis_stats", {})
    print("VirusTotal result:")
    for key in ("malicious", "suspicious", "harmless", "undetected"):
        print(f"  {key}: {stats.get(key, 0)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Safely check a file with VirusTotal.")
    parser.add_argument("file", type=Path, help="File to check")
    parser.add_argument(
        "--upload",
        action="store_true",
        help="Upload if the hash is unknown. Do not use for private files.",
    )
    args = parser.parse_args()

    api_key = os.getenv("VIRUSTOTAL_API_KEY")
    if not api_key:
        raise SystemExit("Set VIRUSTOTAL_API_KEY first; never place it in source code or .env committed to Git.")
    if not args.file.is_file():
        raise SystemExit(f"File not found: {args.file}")

    file_hash = sha256_file(args.file)
    print(f"SHA-256: {file_hash}")
    try:
        print_stats(api_request(f"{API_BASE_URL}/files/{file_hash}", api_key))
        return
    except HTTPError as error:
        if error.code != 404:
            raise SystemExit(f"VirusTotal API error: HTTP {error.code}") from error

    if not args.upload:
        raise SystemExit("No existing report. The file was NOT uploaded; repeat with --upload only if it is safe to share.")

    body, content_type = multipart_file(args.file)
    analysis = api_request(f"{API_BASE_URL}/files", api_key, body, content_type)
    analysis_id = analysis["data"]["id"]
    print("File uploaded. Waiting for analysis...")
    for _ in range(3):
        time.sleep(15)
        result = api_request(f"{API_BASE_URL}/analyses/{analysis_id}", api_key)
        if result["data"]["attributes"]["status"] == "completed":
            print_stats(result)
            return
    raise SystemExit("Analysis is still queued. Check it later in the VirusTotal website.")


if __name__ == "__main__":
    main()
