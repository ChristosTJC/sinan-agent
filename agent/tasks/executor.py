# agent/tasks/executor.py
"""任务执行器"""

from __future__ import annotations

import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Optional

from agent.tasks.manager import TaskManager
from agent.tasks.task import TaskResult, TaskStatus


class TaskExecutor:
    """任务执行器 - 负责任务的实际执行"""

    def __init__(self, manager: TaskManager, max_workers: int = 4):
        self.manager = manager
        self.max_workers = max_workers
        self.pool = ThreadPoolExecutor(max_workers=max_workers)

    def execute_task(
        self,
        task_id: str,
        on_progress: Optional[Callable[[str, float], None]] = None,
    ) -> TaskResult:
        """同步执行单个任务"""
        task = self.manager.tasks.get(task_id)
        if not task:
            return TaskResult(
                success=False,
                output="",
                error=f"任务不存在: {task_id}",
            )

        # 更新状态为运行中
        self.manager.update_status(task_id, TaskStatus.RUNNING)

        try:
            # 执行任务
            if task.executor:
                output = task.executor(**task.args)
            else:
                output = ""

            # 创建成功结果
            result = TaskResult(success=True, output=str(output), error="")
            task.result = result

            # 更新状态为完成
            self.manager.update_status(task_id, TaskStatus.COMPLETED)
            task.progress = 1.0

            return result

        except Exception as e:
            # 创建失败结果
            error_msg = f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()}"
            result = TaskResult(success=False, output="", error=error_msg)
            task.result = result

            # 更新状态为失败
            self.manager.update_status(task_id, TaskStatus.FAILED)

            return result

    def execute_parallel(self, task_ids: list[str]) -> list[TaskResult]:
        """并行执行多个任务"""
        futures = {}

        for task_id in task_ids:
            future = self.pool.submit(self.execute_task, task_id)
            futures[future] = task_id

        results = []
        for future in as_completed(futures):
            result = future.result()
            results.append(result)

        return results

    def shutdown(self):
        """关闭线程池"""
        self.pool.shutdown(wait=True)
