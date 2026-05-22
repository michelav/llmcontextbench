from __future__ import annotations

from typing import Any

from ctxbench._compat import BaseModel, Field, ValidationError


class TaskValidation(BaseModel):
    type: str

    @classmethod
    def model_validate(cls, data: Any) -> "TaskValidation":
        if isinstance(data, cls):
            return data
        if not isinstance(data, dict):
            raise ValidationError("Task validation requires an object input.")
        validation_type = str(data.get("type", "")).strip()
        if validation_type != "judge":
            raise ValidationError("Task validation.type must be 'judge'.")
        return cls(type=validation_type)


class Task(BaseModel):
    id: str
    statement: str
    tags: list[str] = Field(default_factory=list)
    validation: TaskValidation
    contextBlocks: list[str] = Field(default_factory=list)

    @classmethod
    def model_validate(cls, data: Any) -> "Task":
        if isinstance(data, cls):
            return data
        if not isinstance(data, dict):
            raise ValidationError("Task requires an object input.")
        if "question" in data:
            raise ValidationError("Task input must use 'statement', not 'question'.")
        context_blocks = data.get("contextBlocks", data.get("contextBlock", []))
        return cls(
            id=str(data.get("id", "")).strip(),
            statement=str(data.get("statement", "")),
            tags=[str(item) for item in data.get("tags", []) if isinstance(item, str)],
            validation=TaskValidation.model_validate(data.get("validation", {})),
            contextBlocks=[str(item) for item in context_blocks if isinstance(item, str)],
        )


class TaskDataset(BaseModel):
    datasetId: str = ""
    domain: str | None = None
    language: str | None = None
    version: str | None = None
    description: str | None = None
    tasks: list[Task] = Field(default_factory=list)

    @classmethod
    def model_validate(cls, data: Any) -> "TaskDataset":
        if isinstance(data, cls):
            return data
        if not isinstance(data, dict):
            raise ValidationError("TaskDataset requires an object input.")
        if "questions" in data:
            raise ValidationError("TaskDataset input must use 'tasks', not 'questions'.")
        task_items = data.get("tasks", [])
        return cls(
            datasetId=str(data.get("datasetId", "")),
            domain=data.get("domain"),
            language=data.get("language"),
            version=data.get("version"),
            description=data.get("description"),
            tasks=[
                Task.model_validate(item)
                for item in task_items
                if isinstance(item, dict)
            ],
        )


class TaskInstanceEntry(BaseModel):
    id: str
    parameters: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def model_validate(cls, data: Any) -> "TaskInstanceEntry":
        if isinstance(data, cls):
            return data
        if not isinstance(data, dict):
            raise ValidationError("Task instance task entry must be an object.")
        return cls(
            id=str(data.get("id", "")).strip(),
            parameters={
                str(key): value
                for key, value in data.get("parameters", {}).items()
                if isinstance(key, str)
            }
            if isinstance(data.get("parameters"), dict)
            else {},
        )


class TaskInstance(BaseModel):
    instanceId: str
    contextBlocks: str = ""
    tasks: list[TaskInstanceEntry] = Field(default_factory=list)

    @classmethod
    def model_validate(cls, data: Any) -> "TaskInstance":
        if isinstance(data, cls):
            return data
        if not isinstance(data, dict):
            raise ValidationError("TaskInstance requires an object input.")
        if "questions" in data:
            raise ValidationError("TaskInstance input must use 'tasks', not 'questions'.")
        task_items = data.get("tasks", [])
        return cls(
            instanceId=str(data.get("instanceId", "")).strip(),
            contextBlocks=str(data.get("contextBlocks", "")).strip(),
            tasks=[
                TaskInstanceEntry.model_validate(item)
                for item in task_items
                if isinstance(item, dict)
            ],
        )

    def get_task(self, task_id: str) -> TaskInstanceEntry | None:
        for item in self.tasks:
            if item.id == task_id:
                return item
        return None


class TaskInstanceDataset(BaseModel):
    datasetId: str = ""
    domain: str | None = None
    version: str | None = None
    instances: list[TaskInstance] = Field(default_factory=list)

    @classmethod
    def model_validate(cls, data: Any) -> "TaskInstanceDataset":
        if isinstance(data, cls):
            return data
        if not isinstance(data, dict):
            raise ValidationError("TaskInstanceDataset requires an object input.")
        return cls(
            datasetId=str(data.get("datasetId", "")),
            domain=data.get("domain"),
            version=data.get("version"),
            instances=[
                TaskInstance.model_validate(item)
                for item in data.get("instances", [])
                if isinstance(item, dict)
            ],
        )
