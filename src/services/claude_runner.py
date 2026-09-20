"""Run one headless Claude Code job (`claude -p`) with this app's MCP tools.

Claude runs on the logged-in Claude Code subscription of this machine. The default coding-agent
prompt is replaced by our own rules, and only the tools named here are enabled.
"""

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass

from config import settings

SRC_DIR = pathlib.Path(__file__).resolve().parent.parent
MCP_SERVER = SRC_DIR / "mcp_server" / "fire_mcp.py"


@dataclass
class ClaudeRun:
    text: str = ""
    cost_usd: float | None = None
    turns: int | None = None
    error_detail: str = ""
    timed_out: bool = False


def run_claude(
    *,
    system_prompt: str,
    prompt: str,
    tools: list[str],
    mcp_env: dict[str, str],
    cwd: pathlib.Path,
    timeout: int,
    allow_read: bool = True,
) -> ClaudeRun:
    """`tools` are MCP tool names (mcp__fire__...); `mcp_env` reaches the MCP server process."""
    with tempfile.TemporaryDirectory(prefix="fire_claude_") as tmp:
        config_path = pathlib.Path(tmp) / "mcp.json"
        config_path.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "fire": {
                            "command": sys.executable,
                            "args": [str(MCP_SERVER)],
                            "env": {
                                "PYTHONPATH": str(SRC_DIR),
                                "FIRE_DATABASE_URL": settings.FIRE_DATABASE_URL,
                                "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
                                **mcp_env,
                            },
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        cmd = [
            shutil.which("claude") or "claude",
            "-p",
            "--model", settings.CLAUDE_MODEL,
            "--effort", settings.CLAUDE_EFFORT,
            "--system-prompt", system_prompt,
            "--tools", "Read" if allow_read else "",
            "--allowedTools", *(["Read"] if allow_read else []), *tools,
            "--strict-mcp-config", "--mcp-config", str(config_path),
            "--permission-mode", "dontAsk",
            "--no-session-persistence",
            "--output-format", "json",
        ]
        env = os.environ.copy()
        # Never let a stray API key silently switch billing away from the logged-in subscription.
        env.pop("ANTHROPIC_API_KEY", None)
        try:
            proc = subprocess.run(
                cmd, input=prompt, capture_output=True, text=True, encoding="utf-8",
                timeout=timeout, cwd=cwd, env=env,
            )
        except subprocess.TimeoutExpired:
            return ClaudeRun(error_detail=f"Timed out after {timeout}s", timed_out=True)

    run = ClaudeRun(text=proc.stdout)
    try:
        payload = json.loads(proc.stdout)
        run.cost_usd, run.turns = payload.get("total_cost_usd"), payload.get("num_turns")
        run.text = str(payload.get("result", ""))
    except json.JSONDecodeError:
        pass
    run.error_detail = (proc.stderr or run.text)[-2000:]
    return run
