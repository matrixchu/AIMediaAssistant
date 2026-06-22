"""Interactive command-line chat with the AI media agent.

Run with:  python -m ai_media_assistant.cli
"""

from __future__ import annotations

import sys

from .agent.runner import AgentRunner
from .database import init_db
from .shared.logging import setup_logging
from .shared.schemas import AgentRequest


def main() -> None:
    setup_logging("WARNING")
    init_db()
    runner = AgentRunner()

    print("🎬 AI Media Assistant — type a request (or 'exit').")
    print("Examples: 下载《沙丘2》 · 追《最后生还者》第二季 · 推荐科幻电影\n")

    # Support a one-shot request passed as CLI args.
    if len(sys.argv) > 1:
        message = " ".join(sys.argv[1:])
        print(runner.run(AgentRequest(message=message)).reply)
        return

    while True:
        try:
            message = input("you ▸ ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if message.lower() in {"exit", "quit", "q"}:
            break
        if not message:
            continue
        response = runner.run(AgentRequest(message=message))
        print(f"bot ▸ {response.reply}\n")


if __name__ == "__main__":
    main()
