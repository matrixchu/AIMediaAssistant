#!/usr/bin/env bash
# Launch the AI Media Assistant MCP server over stdio.
#
# This is the command an MCP host (OpenClaw, Claude Desktop, etc.) spawns.
# It cd's to the project root so the local `.env` is loaded, and uses the
# project's virtualenv interpreter. All protocol I/O is on stdout; logs go to
# stderr (safe for stdio MCP).
set -euo pipefail

# Resolve the project root (parent of this scripts/ directory).
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON="$ROOT/.venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
  PYTHON="$(command -v python3)"
fi

exec "$PYTHON" -m ai_media_assistant.mcp.server
