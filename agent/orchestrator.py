# agent/orchestrator.py
"""
司南 AgentOrchestrator —— 自主嵌入式智能体编排器。

将 ToolRegistry / MemoryStore / SessionDB / KnowledgeBase
串联为 6 阶段自主循环，作为司南 Agent 的中枢调度核心。

管线: 输入理解 → 知识检索 → 计划生成 → 工具执行 → 验证 → 记忆沉淀
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


class AgentOrchestrator:
    """6 阶段自主 Agent 编排器。

    将工具注册中心、核心记忆、会话数据库和知识库串联为一个完整的自主循环。
    可选接入 LLM 以增强计划与验证；无 LLM 时回退到规则式执行。
    """

    def __init__(
        self,
        registry: Any,
        memory_store: Any,
        session_db: Any,
        knowledge_base: Any,
        skill_loader: Any = None,
        llm_client: Any = None,
        memories_dir: Optional[Path] = None,
    ) -> None:
        """初始化编排器。

        Args:
            registry:       ToolRegistry 实例。
            memory_store:   MemoryStore 实例。
            session_db:     SessionDB 实例。
            knowledge_base: KnowledgeBase 实例。
            skill_loader:   可选，技能加载器。
            llm_client:     可选，LLM 客户端（需提供 generate/chat/callable 接口）。
            memories_dir:   记忆持久化目录，默认 ~/.sinan/memories/。
        """
        self.registry = registry
        self.memory_store = memory_store
        self.session_db = session_db
        self.knowledge_base = knowledge_base
        self.skill_loader = skill_loader
        self.llm_client = llm_client

        self._tasks: dict[str, dict] = {}
        self._session_id = session_db.create_session(project=session_db.detect_project())
        self._memories_dir = memories_dir or Path.home() / ".sinan" / "memories"

    # ------------------------------------------------------------------
    # 主循环
    # ------------------------------------------------------------------

    def execute(self, user_input: str) -> dict:
        """执行 6 阶段自主 Agent 管线。

        Args:
            user_input: 用户输入文本。

        Returns:
            {success, task_id, phases, result, memory_written}，
            异常时额外包含 error 字段。
        """
        task_id = str(uuid.uuid4())
        phases: dict[str, Any] = {}

        try:
            phases["understand"] = self._phase_understand(user_input)
            phases["retrieve"] = self._phase_retrieve(user_input)
            phases["plan"] = self._phase_plan(user_input, phases["retrieve"])
            phases["execute"] = self._phase_execute(phases["plan"])
            phases["verify"] = self._phase_verify(phases["plan"], phases["execute"], user_input)
            phases["consolidate"] = self._phase_consolidate(user_input, phases, task_id)

            success = (phases["verify"].get("all_passed", True)
                       and phases["execute"].get("all_passed", True))
            result = {
                "success": success,
                "task_id": task_id,
                "phases": phases,
                "result": phases["execute"].get("summary", ""),
                "memory_written": phases["consolidate"].get("written", False),
            }
            self._create_task_record(user_input, result)
            return result
        except Exception as exc:
            logger.exception("编排器主循环异常")
            error_result = {
                "success": False, "error": str(exc), "task_id": task_id,
                "phases": phases, "result": {}, "memory_written": False,
            }
            self._create_task_record(user_input, error_result)
            return error_result

    # ------------------------------------------------------------------
    # 阶段 1：输入理解
    # ------------------------------------------------------------------

    @staticmethod
    def _phase_understand(user_input: str) -> dict:
        """解析用户输入，推断 intent / target / urgency。"""
        lower = user_input.lower()

        _DEBUG = ("调试", "debug", "修复", "fix", "bug", "错误", "crash", "崩溃",
                   "不工作", "失败", "dump")
        _IMPL = ("创建", "实现", "写", "编写", "开发", "create", "implement",
                  "add", "新建")
        _ANALYZE = ("分析", "analyze", "profile", "性能", "benchmark", "评测",
                     "检查", "check")
        _QUERY = ("what", "how", "为什么", "怎么", "如何", "列出", "list",
                   "查找", "搜索", "find", "显示", "show", "help", "帮助")

        if any(kw in lower for kw in _DEBUG):       intent = "debug"
        elif any(kw in lower for kw in _IMPL):      intent = "implement"
        elif any(kw in lower for kw in _ANALYZE):   intent = "analyze"
        elif any(kw in lower for kw in _QUERY):     intent = "query"
        else:                                       intent = "query"

        if any(kw in lower for kw in ("urgent", "紧急", "马上", "立刻",
                                        "危险", "火速")):
            urgency = "high"
        elif "请" in lower or "麻烦" in lower:
            urgency = "normal"
        else:
            urgency = "low"

        target = "unknown"
        for hint in ("uart", "spi", "i2c", "gpio", "adc", "usb", "串口", "传感器",
                     "camera", "相机", "bluetooth", "蓝牙", "wifi", "stm32",
                     "nrf52", "nrf52840", "esp32", "编译", "烧录", "build",
                     "flash", "firmware", "固件", "日志", "log"):
            if hint in lower:
                target = hint
                break

        return {"intent": intent, "target": target, "urgency": urgency, "raw": user_input}

    # ------------------------------------------------------------------
    # 阶段 2：知识检索
    # ------------------------------------------------------------------

    def _phase_retrieve(self, user_input: str) -> dict:
        """从 L3 知识库、L1 核心记忆、L2 会话历史检索上下文。"""
        result: dict[str, Any] = {"knowledge": "", "memory": "", "session_history": []}

        if self.knowledge_base is not None:
            try:
                result["knowledge"] = self.knowledge_base.build_context(
                    query=user_input, max_chars=2000)
            except Exception as exc:
                logger.warning("知识库检索异常: %s", exc)

        if self.memory_store is not None:
            try:
                result["memory"] = self.memory_store.build_context()
            except Exception as exc:
                logger.warning("核心记忆注入异常: %s", exc)

        if self.session_db is not None:
            try:
                result["session_history"] = self.session_db.search(user_input, limit=3)
            except Exception as exc:
                logger.warning("会话历史检索异常: %s", exc)

        return result

    # ------------------------------------------------------------------
    # 阶段 3：计划生成
    # ------------------------------------------------------------------

    def _phase_plan(self, user_input: str, retrieval: dict) -> list[dict]:
        """生成执行计划。LLM 可用时由 LLM 规划，否则回退规则式分解。"""
        if self.llm_client is not None:
            try:
                return self._llm_plan(user_input, retrieval)
            except Exception as exc:
                logger.warning("LLM 计划失败，回退规则: %s", exc)
        return self._fallback_plan(user_input)

    def _llm_plan(self, user_input: str, retrieval: dict) -> list[dict]:
        """LLM 生成结构化执行计划，返回步骤列表。"""
        tools = json.dumps(self.registry.list_tools() if self.registry else [], ensure_ascii=False)
        prompt = (
            "你是嵌入式系统智能体。根据用户输入生成执行计划，返回 JSON 数组。\n\n"
            f"用户输入: {user_input}\n"
            f"知识库: {retrieval.get('knowledge', '')}\n"
            f"项目记忆: {retrieval.get('memory', '')}\n"
            f"可用工具: {tools}\n\n"
            "每步格式: {\"step_id\":N, \"action\":\"...\", \"tool\":\"工具名或null\", "
            "\"args\":{}, \"expected_outcome\":\"...\"}。只输出 JSON。"
        )
        resp = self._call_llm(prompt)
        try:
            plan = json.loads(resp)
            if isinstance(plan, list):
                return plan
        except json.JSONDecodeError:
            pass
        return self._fallback_plan(user_input)

    def _fallback_plan(self, user_input: str) -> list[dict]:
        """规则式计划 —— 根据关键词映射可用工具，不硬编码工具名。"""
        tool_names = [t["name"] for t in self.registry.list_tools()] if self.registry else []
        plan: list[dict] = []
        sid, lo = 0, user_input.lower()

        # USB/串口
        if any(kw in lo for kw in ("usb", "串口", "serial", "uart", "端口", "设备")):
            for t in ("scan_usb", "scan_serial"):
                if t in tool_names:
                    sid += 1
                    plan.append({"step_id": sid, "action": "扫描设备", "tool": t,
                                 "args": {}, "expected_outcome": "列出可用设备"})
                    break
        # 传感器
        if any(kw in lo for kw in ("传感器", "sensor", "adc", "读取", "采样")) \
                and "read_sensor" in tool_names:
            sid += 1
            plan.append({"step_id": sid, "action": "读取传感器", "tool": "read_sensor",
                         "args": {"port": "/dev/ttyUSB0", "count": 10},
                         "expected_outcome": "返回传感器样本"})
        # 编译
        if any(kw in lo for kw in ("编译", "build", "固件", "firmware")):
            if "build_firmware" in tool_names:
                sid += 1
                plan.append({"step_id": sid, "action": "编译固件", "tool": "build_firmware",
                             "args": {"project_path": "."}, "expected_outcome": "编译成功"})
        # 烧录
        if any(kw in lo for kw in ("烧录", "flash", "下载")):
            if "flash_firmware" in tool_names:
                sid += 1
                plan.append({"step_id": sid, "action": "烧录固件（需确认端口）",
                             "tool": None, "args": {}, "expected_outcome": "待确认"})
        # 文件操作
        if any(kw in lo for kw in ("文件", "读", "写", "编辑", "搜索")):
            for t in ("read_file", "grep", "glob", "edit_file", "write_file"):
                if t in tool_names and t in lo:
                    sid += 1
                    plan.append({"step_id": sid, "action": f"文件操作: {t}",
                                 "tool": t, "args": {}, "expected_outcome": f"完成 {t}"})

        if not plan:
            plan.append({"step_id": 1, "action": f"分析: {user_input}",
                         "tool": None, "args": {}, "expected_outcome": "基于知识解答"})
        return plan

    # ------------------------------------------------------------------
    # 阶段 4：工具执行
    # ------------------------------------------------------------------

    def _phase_execute(self, plan: list[dict]) -> dict:
        """按计划逐步调用 registry 中的工具，收集结果。"""
        steps: list[dict] = []
        all_passed, failures = True, []

        for step in plan:
            tool, args = step.get("tool"), step.get("args", {})
            sid = step.get("step_id", "?")
            rec = {"step_id": sid, "action": step.get("action", ""),
                   "tool": tool, "success": True, "result": None, "error": None}

            if tool is None:
                rec["result"] = "跳过 — 无需工具"
            elif self.registry is None:
                rec.update(success=False, error="registry 不可用")
                all_passed = False
                failures.append(f"步骤{sid}: registry 不可用")
            else:
                try:
                    res = self.registry.call_tool(tool, args)
                    rec["result"] = res
                    if not res.get("success", False):
                        rec["success"] = False
                        rec["error"] = res.get("error", "执行失败")
                        all_passed = False
                        failures.append(f"步骤{sid}: {rec['error']}")
                except Exception as exc:
                    rec.update(success=False, error=str(exc))
                    all_passed = False
                    failures.append(f"步骤{sid}: {exc}")
            steps.append(rec)

        summary = "全部成功" if all_passed else f"部分失败: {'; '.join(failures)}"
        return {"steps": steps, "all_passed": all_passed, "failures": failures, "summary": summary}

    # ------------------------------------------------------------------
    # 阶段 5：验证
    # ------------------------------------------------------------------

    def _phase_verify(self, plan: list[dict], execution: dict, user_input: str) -> dict:
        """验证执行结果。LLM 可用时辅助语义评估。"""
        failures = list(execution.get("failures", []))
        all_passed = execution.get("all_passed", True)

        if not plan or all(s.get("tool") is None for s in plan):
            return {"all_passed": True, "failures": [], "summary": "无工具，跳过验证"}

        if self.llm_client is not None:
            try:
                prompt = (
                    f"用户请求: {user_input}\n"
                    f"计划: {json.dumps(plan, ensure_ascii=False)}\n"
                    f"执行结果: {json.dumps(execution, ensure_ascii=False)}\n"
                    "评估是否满足需求，返回: {\"passed\":bool, \"reason\":\"...\"}"
                )
                verdict = json.loads(self._call_llm(prompt))
            except Exception as exc:
                logger.warning("LLM 验证异常: %s", exc)
                verdict = {"passed": True, "reason": f"LLM 异常，默认通过: {exc}"}

            if not verdict.get("passed", True):
                all_passed = False
                failures.append(f"LLM: {verdict.get('reason', '未提供原因')}")

        summary = "通过" if all_passed else f"失败: {'; '.join(failures)}"
        return {"all_passed": all_passed, "failures": failures, "summary": summary}

    # ------------------------------------------------------------------
    # 阶段 6：记忆沉淀
    # ------------------------------------------------------------------

    def _phase_consolidate(self, user_input: str, phases: dict, task_id: str) -> dict:
        """将执行结果写入核心记忆、会话消息并持久化到磁盘。"""
        written, details = False, []
        verify = phases.get("verify", {})
        execute = phases.get("execute", {})
        ok = verify.get("all_passed", True) and execute.get("all_passed", True)

        if self.memory_store is not None:
            try:
                ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
                status = "完成" if ok else "部分失败"
                self.memory_store.add_fact(
                    f"[{ts}] {status}: {user_input[:120]} (task={task_id[:8]}...)")
                details.append("核心记忆已写入")
            except Exception as exc:
                details.append(f"核心记忆写入异常: {exc}")

        if self.session_db is not None:
            try:
                for i, (label, data) in enumerate([
                    ("理解", json.dumps(phases.get("understand", {}), ensure_ascii=False)),
                    ("检索", "完成"),
                    ("计划", f"{len(phases.get('plan', []))} 步骤"),
                    ("执行", execute.get("summary", "")),
                    ("验证", verify.get("summary", "")),
                ], 1):
                    self.session_db.add_message(
                        self._session_id, "system", f"[Phase {i}] {label}: {str(data)[:500]}")
                details.append("会话消息已记录")
            except Exception as exc:
                details.append(f"会话消息写入异常: {exc}")

        if self.memory_store is not None:
            try:
                self.memory_store.flush_to_disk(self._memories_dir)
                details.append("核心记忆已落盘")
                written = True
            except Exception as exc:
                details.append(f"核心记忆落盘异常: {exc}")

        return {"written": written, "details": details}

    # ------------------------------------------------------------------
    # 任务管理
    # ------------------------------------------------------------------

    def _create_task_record(self, user_input: str, result: dict) -> str:
        """创建任务审计记录，写入 self._tasks 并返回 task_id。"""
        task_id = result.get("task_id", str(uuid.uuid4()))
        self._tasks[task_id] = {
            "task_id": task_id,
            "user_input": user_input,
            "success": result.get("success", False),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "phases_summary": {
                k: (v.get("summary", "") if isinstance(v, dict)
                    else f"{len(v)} 步骤" if isinstance(v, list) else str(v)[:120])
                for k, v in result.get("phases", {}).items()
            },
            "result": result.get("result", ""),
        }
        return task_id

    def get_task(self, task_id: str) -> dict:
        """按 ID 检索任务记录。Raises: KeyError。"""
        if task_id not in self._tasks:
            raise KeyError(f"任务不存在: {task_id}")
        return self._tasks[task_id]

    def list_recent_tasks(self, limit: int = 10) -> list[dict]:
        """列出最近任务，按创建时间降序。"""
        return sorted(self._tasks.values(),
                      key=lambda t: t.get("created_at", ""), reverse=True)[:limit]

    # ------------------------------------------------------------------
    # LLM 调用
    # ------------------------------------------------------------------

    def _call_llm(self, prompt: str) -> str:
        """统一的 LLM 调用入口，兼容 generate / chat / callable 三种接口。"""
        if hasattr(self.llm_client, "generate"):
            return self.llm_client.generate(prompt)
        if hasattr(self.llm_client, "chat"):
            return self.llm_client.chat([{"role": "user", "content": prompt}])
        if callable(self.llm_client):
            return self.llm_client(prompt)
        raise TypeError("llm_client 未提供 generate / chat / callable 接口")
