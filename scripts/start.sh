#!/usr/bin/env bash
#
# Start TSPO Chat: prepare Python, build the browser UI, and run the server.
#
#   ./scripts/start.sh              prepare everything and run the server
#   ./scripts/start.sh --dev        also run the Vite dev server for UI work
#   ./scripts/start.sh --skip-build use web/dist as it is
#   ./scripts/start.sh --help       show this text
#
# Settings come from .env. Copy .env.example to .env to change them.

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

VENV_DIR=".venv"
RUN_DEV=0
SKIP_BUILD=0

say()  { printf '\n\033[1;35m==>\033[0m %s\n' "$1"; }
info() { printf '    %s\n' "$1"; }
die()  { printf '\n\033[1;31mError:\033[0m %s\n' "$1" >&2; exit 1; }

for argument in "$@"; do
	case "$argument" in
		--dev)        RUN_DEV=1 ;;
		--skip-build) SKIP_BUILD=1 ;;
		--help|-h)    sed -n '2,12p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
		*)            die "Unknown option: $argument (try --help)" ;;
	esac
done

# --------------------------------------------------------------------------
# Python
# --------------------------------------------------------------------------
say "Preparing Python"
PYTHON="$(command -v python3 || command -v python || true)"
[ -n "$PYTHON" ] || die "Python 3 is not installed. See https://www.python.org/downloads/"
info "$("$PYTHON" --version 2>&1)"

if [ ! -d "$VENV_DIR" ]; then
	info "Creating the $VENV_DIR virtual environment"
	"$PYTHON" -m venv "$VENV_DIR" || die "Could not create $VENV_DIR"
fi

# Absolute, so the running process is easy to identify in ps and systemd.
VENV_PYTHON="$PROJECT_ROOT/$VENV_DIR/bin/python"
[ -x "$VENV_PYTHON" ] || VENV_PYTHON="$PROJECT_ROOT/$VENV_DIR/Scripts/python.exe"   # Git Bash on Windows
[ -x "$VENV_PYTHON" ] || die "No Python inside $VENV_DIR. Delete the folder and run this again."

# Reinstall only when requirements.txt is newer than the last successful install.
STAMP="$VENV_DIR/.requirements-installed"
if [ ! -f "$STAMP" ] || [ requirements.txt -nt "$STAMP" ]; then
	info "Installing Python packages"
	"$VENV_PYTHON" -m pip install --quiet --upgrade pip
	"$VENV_PYTHON" -m pip install --quiet -r requirements.txt || die "pip install failed"
	touch "$STAMP"
else
	info "Python packages are up to date"
fi

# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------
say "Checking settings"
if [ ! -f .env ] && [ -f .env.example ]; then
	info "No .env yet; copying .env.example so the defaults are easy to edit"
	cp .env.example .env
fi
if [ -f .env ]; then
	info "Reading .env"
else
	info "Using built-in defaults"
fi

# --------------------------------------------------------------------------
# Browser UI
# --------------------------------------------------------------------------
say "Preparing the browser UI"
if [ "$SKIP_BUILD" -eq 1 ]; then
	info "Skipping the build because --skip-build was given"
elif ! command -v npm >/dev/null 2>&1; then
	info "npm is not installed, so the browser UI is skipped."
	info "The terminal client still works: $VENV_PYTHON client/cli_client.py"
	info "Install Node.js 20 or newer from https://nodejs.org/ to enable the UI."
else
	info "npm $(npm --version)"
	if [ ! -d web/node_modules ] || [ web/package-lock.json -nt web/node_modules ]; then
		info "Installing UI packages (this takes a moment the first time)"
		(cd web && npm install --no-fund --no-audit --silent) || die "npm install failed"
	fi
	# Rebuild when any source file is newer than the built page.
	if [ ! -f web/dist/index.html ] \
		|| [ -n "$(find web/src web/index.html web/vite.config.js -newer web/dist/index.html 2>/dev/null)" ]; then
		info "Building the page into web/dist"
		(cd web && npm run build --silent) || die "npm run build failed"
	else
		info "web/dist is up to date"
	fi
fi

# --------------------------------------------------------------------------
# Run
# --------------------------------------------------------------------------
if [ "$RUN_DEV" -eq 1 ]; then
	command -v npm >/dev/null 2>&1 || die "--dev needs npm installed"
	say "Starting the Vite dev server on http://localhost:5173"
	(cd web && npm run dev) &
	DEV_PID=$!
	# Stop the dev server when this script stops, however it stops.
	trap 'kill "$DEV_PID" 2>/dev/null || true' EXIT INT TERM
fi

say "Starting the chat server"
info "Web UI:  http://localhost:8000"
info "Health:  http://localhost:8000/health"
info "Press Ctrl+C to stop."
echo
exec "$VENV_PYTHON" server/server.py
