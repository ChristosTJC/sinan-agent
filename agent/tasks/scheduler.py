# agent/tasks/scheduler.py
"""任务调度器"""

from __future__ import annotations

from typing import Optional

from agent.tasks.executor import TaskExecutor
from agent.tasks.manager import TaskManager
from agent.tasks.task import TaskResult, TaskStatus


class TaskScheduler:
    """任务调度器 - 负责依赖链调度和并行执行"""

    def __init__(self, manager: TaskManager, executor: TaskExecutor):
        self.manager = manager
        self.executor = executor

    def run_until_complete(self, task_id: str) -> TaskResult:
        """执行任务及其所有依赖（按依赖顺序）"""
        # 获取完整依赖链
        chain = self.manager.get_task_chain(task_id)

        # 按依赖顺序执行
        result = None
        for tid in chain:
            task = self.manager.tasks[tid]

            # 跳过已完成的任务
            if task.status == TaskStatus.COMPLETED:
                result = task.result
                continue

            # 执行任务
            result = self.executor.execute_task(tid)

            # 如果失败，停止执行
            if not result.success:
                break

        return result if result else TaskResult(success=False, output="", error="空任务链")

    def run_parallel(self, task_ids: list[str]) -> list[TaskResult]:
        """并行执行多个独立任务"""
        return self.executor.execute_parallel(task_ids)

    def run_dag(self, root_task_id: str) -> TaskResult:
        """执行 DAG（有向无环图）任务"""
        # 获取完整依赖链
        chain = self.manager.get_task_chain(root_task_id)

        # 按拓扑顺序执行
        for tid in chain:
            task = self.manager.tasks[tid]

            # 跳过已完成的任务
            if task.status == TaskStatus.COMPLETED:
                continue

            # 执行任务
            result = self.executor.execute_task(tid)

            # 如果失败，停止执行
            if not result.success:
                return result

        # 返回根任务的结果
        root_task = self.manager.tasks[root_task_id]
        return root_task.result if root_task.result else TaskResult(
            success=False, output="", error="根任务无结果"
        )
