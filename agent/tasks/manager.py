# agent/tasks/manager.py
"""任务管理器"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Callable, Optional

from agent.tasks.task import Task, TaskStatus, TaskType


class TaskManager:
    """任务管理器 - 负责任务注册、查询、依赖管理"""

    def __init__(self):
        self.tasks: dict[str, Task] = {}
        self.task_graph: dict[str, list[str]] = {}  # 依赖图（邻接表）

    def create_task(
        self,
        name: str,
        type: TaskType,
        executor: Optional[Callable],
        args: dict,
        dependencies: list[str],
    ) -> Task:
        """创建任务"""
        task_id = f"task-{uuid.uuid4().hex[:8]}"

        # 检查循环依赖
        if self._has_circular_dependency(task_id, dependencies):
            raise ValueError(f"检测到循环依赖: {task_id} -> {dependencies}")

        task = Task(
            id=task_id,
            name=name,
            type=type,
            status=TaskStatus.PENDING,
            executor=executor,
            args=args,
            dependencies=dependencies,
            children=[],
            result=None,
            created_at=datetime.now(),
            started_at=None,
            completed_at=None,
            progress=0.0,
            checkpoint_data=None,
        )

        self.tasks[task_id] = task
        self.task_graph[task_id] = dependencies

        return task

    def get_ready_tasks(self) -> list[Task]:
        """获取所有就绪的任务（依赖已满足）"""
        ready = []
        for _task_id, task in self.tasks.items():
            if task.status != TaskStatus.PENDING:
                continue

            # 检查所有依赖是否完成
            deps_completed = all(
                self.tasks[dep_id].status == TaskStatus.COMPLETED
                for dep_id in task.dependencies
                if dep_id in self.tasks
            )

            if deps_completed:
                ready.append(task)

        return ready

    def get_blocked_tasks(self) -> list[Task]:
        """获取所有被阻塞的任务"""
        blocked = []
        for task in self.tasks.values():
            if task.status == TaskStatus.PENDING and task not in self.get_ready_tasks():
                blocked.append(task)
        return blocked

    def get_task_chain(self, task_id: str) -> list[str]:
        """获取任务的完整依赖链"""
        chain = []
        visited = set()

        def dfs(tid: str):
            if tid in visited:
                return
            visited.add(tid)

            for dep_id in self.task_graph.get(tid, []):
                dfs(dep_id)

            chain.append(tid)

        dfs(task_id)
        return chain

    def update_status(self, task_id: str, status: TaskStatus) -> None:
        """更新任务状态"""
        if task_id not in self.tasks:
            raise KeyError(f"任务不存在: {task_id}")

        self.tasks[task_id].status = status

        if status == TaskStatus.RUNNING:
            self.tasks[task_id].started_at = datetime.now()
        elif status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
            self.tasks[task_id].completed_at = datetime.now()

    def update_dependencies(self, task_id: str, dependencies: list[str]) -> None:
        """更新任务依赖"""
        if self._has_circular_dependency(task_id, dependencies):
            raise ValueError(f"检测到循环依赖: {task_id} -> {dependencies}")

        self.tasks[task_id].dependencies = dependencies
        self.task_graph[task_id] = dependencies

    def _has_circular_dependency(self, task_id: str, dependencies: list[str]) -> bool:
        """检测循环依赖"""
        visited = set()

        def dfs(tid: str) -> bool:
            if tid == task_id:
                return True
            if tid in visited:
                return False

            visited.add(tid)

            return any(dfs(dep_id) for dep_id in self.task_graph.get(tid, []))

        return any(dfs(dep_id) for dep_id in dependencies)
