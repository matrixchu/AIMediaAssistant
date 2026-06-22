#!/usr/bin/env bash
# Register (or update) the AI Media Assistant MCP server inside OpenClaw, then
# probe it so you can immediately see the exposed tools.
#
# OpenClaw will spawn our stdio MCP server and call it using the local Ollama
# model configured in ~/.openclaw/openclaw.json (zero API cost).
#
# Usage:  ./scripts/register_openclaw.sh [server-name]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NAME="${1:-ai-media}"
WRAPPER="$ROOT/scripts/mcp_stdio.sh"

if ! command -v openclaw >/dev/null 2>&1; then
  echo "error: 'openclaw' CLI not found on PATH." >&2
  exit 1
fi

chmod +x "$WRAPPER"

echo ">> Registering MCP server '$NAME' with OpenClaw…"
# Replace any existing definition so re-runs are idempotent.
openclaw mcp unset "$NAME" >/dev/null 2>&1 || true

openclaw mcp add "$NAME" \
  --command "$WRAPPER" \
  --cwd "$ROOT" \
  --env "PYTHONUNBUFFERED=1" \
  --connect-timeout 30 \
  --timeout 120

echo
echo ">> Probing '$NAME' (lists the tools OpenClaw can now call)…"
openclaw mcp probe "$NAME" || true

cat <<EOF

Done. Try it from OpenClaw, for example:

  openclaw agent --message "用 ai-media 搜索并下载《沙丘2》"
  openclaw chat        # then: 追《最后生还者》第二季

OpenClaw will plan with your local Ollama model (qwen3:8b) and call the
ai-media tools: search_media, download_media, follow_show, list_subscriptions,
get_download_status, get_recommendations, get_system_status.
EOF
