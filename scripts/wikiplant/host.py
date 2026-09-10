from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class CapabilityProfile:
    google_drive_raw_create: bool = False
    google_drive_full_read: bool = False
    google_drive_content_update: bool = False
    google_drive_paginated_list: bool = False
    private_skill_install: bool = False
    scheduled_task_create: bool = False
    scheduled_task_inspect: bool = False
    conditional_write: bool = False
    serialized_task_runs: bool = False
    observed_surface: str = "unobserved"
    observed_at: str | None = None
    tool_names: tuple[str, ...] = ()

    def storage_ready(self) -> bool:
        return all((
            self.google_drive_raw_create,
            self.google_drive_full_read,
            self.google_drive_content_update,
            self.google_drive_paginated_list,
        ))


@dataclass(frozen=True)
class HostTask:
    id: str
    title: str
    prompt: str
    schedule: str
    timezone: str
    next_local: str
    next_utc: str
    active: bool = True


class FakeHost:
    def __init__(self, capabilities: CapabilityProfile, *, auto_install_skill: bool = True):
        self.capabilities = capabilities
        self.auto_install_skill = auto_install_skill
        self.skills: dict[str, str] = {}
        self.tasks: dict[str, HostTask] = {}
        self._counter = 0

    def install_skill(self, name: str, content: str) -> str | None:
        if not self.capabilities.private_skill_install or not self.auto_install_skill:
            return None
        if name in self.skills:
            return self.skills[name]
        self._counter += 1
        reference = f"skill-{self._counter:04d}"
        self.skills[name] = reference
        return reference

    def create_task(self, task_key: str, title: str, prompt: str, schedule: str, timezone: str) -> HostTask | None:
        if not (self.capabilities.scheduled_task_create and self.capabilities.scheduled_task_inspect):
            return None
        if task_key in self.tasks:
            return self.tasks[task_key]
        self._counter += 1
        task = HostTask(
            id=f"task-{self._counter:04d}",
            title=title,
            prompt=prompt,
            schedule=schedule,
            timezone=timezone,
            next_local=f"next {schedule} ({timezone})",
            next_utc=f"derived UTC for next {schedule}",
        )
        self.tasks[task_key] = task
        return task

    def set_task_active(self, task_id: str, active: bool) -> HostTask:
        for key, task in self.tasks.items():
            if task.id == task_id:
                updated = replace(task, active=active)
                self.tasks[key] = updated
                return updated
        raise ValueError("task id is not present in this host")

    def update_task_schedule(self, task_id: str, schedule: str, timezone: str) -> HostTask:
        for key, task in self.tasks.items():
            if task.id == task_id:
                updated = replace(
                    task, schedule=schedule, timezone=timezone,
                    next_local=f"next {schedule} ({timezone})", next_utc=f"derived UTC for next {schedule}",
                )
                self.tasks[key] = updated
                return updated
        raise ValueError("task id is not present in this host")


def set_instance_tasks_active(host: FakeHost, task_ids: dict[str, str], active: bool) -> dict[str, HostTask]:
    if set(task_ids) != {"daily", "weekly"}:
        raise ValueError("instance task binding must contain exactly daily and weekly ids")
    return {kind: host.set_task_active(task_id, active) for kind, task_id in task_ids.items()}
