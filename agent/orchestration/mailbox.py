"""文件邮箱 — 智能体间异步通信。

收件箱: ~/.sinan/teams/{team}/inboxes/{agent}.jsonl
每行一条 JSON 消息，线程安全。
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Optional


class Mailbox:
    TEAM_LEAD_NAME = "team-lead"

    def __init__(self, team_name: str = "default", base_dir: Optional[Path] = None):
        self._team_name = team_name
        self._base_dir = base_dir or (Path.home() / ".sinan" / "teams")
        self._inbox_dir = self._base_dir / team_name / "inboxes"
        self._inbox_dir.mkdir(parents=True, exist_ok=True)
        self._locks: dict[str, threading.Lock] = {}

    def _inbox_path(self, agent_name: str) -> Path:
        return self._inbox_dir / f"{agent_name}.jsonl"

    def _get_lock(self, agent_name: str) -> threading.Lock:
        if agent_name not in self._locks:
            self._locks[agent_name] = threading.Lock()
        return self._locks[agent_name]

    def write_message(self, recipient: str, content: str, *, sender: str = "",
                      msg_type: str = "text", summary: str = "") -> None:
        msg = {
            "from": sender, "to": recipient, "text": content,
            "type": msg_type, "summary": summary,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "read": False,
        }
        inbox = self._inbox_path(recipient)
        lock = self._get_lock(recipient)
        with lock:
            line = json.dumps(msg, ensure_ascii=False)
            with open(inbox, "a") as f:
                f.write(line + "\n")

    def read_messages(self, agent_name: str, *, unread_only: bool = False) -> list[dict]:
        inbox = self._inbox_path(agent_name)
        if not inbox.exists():
            return []
        lock = self._get_lock(agent_name)
        with lock:
            messages = []
            with open(inbox, "r") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            msg = json.loads(line)
                            if unread_only and msg.get("read", False):
                                continue
                            messages.append(msg)
                        except json.JSONDecodeError:
                            continue
            return messages

    def mark_all_read(self, agent_name: str) -> None:
        inbox = self._inbox_path(agent_name)
        if not inbox.exists():
            return
        lock = self._get_lock(agent_name)
        with lock:
            updated: list[str] = []
            with open(inbox, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        msg = json.loads(line)
                        msg["read"] = True
                        updated.append(json.dumps(msg, ensure_ascii=False))
                    except json.JSONDecodeError:
                        updated.append(line)
            with open(inbox, "w") as f:
                for line in updated:
                    f.write(line + "\n")

    def send_idle_notification(self, agent_name: str, reason: str = "available",
                               completed_task_id: str = "", summary: str = "") -> None:
        self.write_message(
            self.TEAM_LEAD_NAME,
            json.dumps({"agent": agent_name, "reason": reason,
                        "completed_task_id": completed_task_id, "summary": summary}),
            sender=agent_name, msg_type="idle_notification", summary=summary,
        )

    def send_permission_request(self, agent_name: str, request_id: str,
                                tool_name: str, description: str) -> None:
        self.write_message(
            self.TEAM_LEAD_NAME,
            json.dumps({"request_id": request_id, "agent": agent_name,
                        "tool_name": tool_name, "description": description}),
            sender=agent_name, msg_type="permission_request",
            summary=f"请求使用 {tool_name}",
        )

    def send_permission_response(self, recipient: str, request_id: str,
                                 approved: bool, error: str = "") -> None:
        self.write_message(
            recipient,
            json.dumps({"request_id": request_id, "approved": approved, "error": error}),
            sender=self.TEAM_LEAD_NAME, msg_type="permission_response",
            summary="批准" if approved else "拒绝",
        )
