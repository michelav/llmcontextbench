from __future__ import annotations

from typing import Any, Callable
import re

from ctxbench._compat import BaseModel, Field, ValidationError


TASK_TEMPLATE_PATTERN = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


def render_task_template(
    task_template: str,
    parameters: dict[str, Any],
    *,
    on_warning: Callable[..., None] | None = None,
    task_id: str,
    instance_id: str,
) -> str:
    """Render declared task parameters and report missing or unused values."""
    placeholders = TASK_TEMPLATE_PATTERN.findall(task_template)
    if not placeholders:
        if parameters and on_warning is not None:
            for key in sorted(parameters):
                on_warning("Unused task parameter; ignoring", taskId=task_id,
                           instanceId=instance_id, parameter=key)
        return task_template

    rendered = task_template
    for placeholder in placeholders:
        if placeholder not in parameters and on_warning is not None:
            on_warning("Missing task parameter; substituting empty string", taskId=task_id,
                       instanceId=instance_id, parameter=placeholder)
        rendered = rendered.replace("{" + placeholder + "}", str(parameters.get(placeholder, "")))

    if on_warning is not None:
        for key in sorted(parameters):
            if key not in placeholders:
                on_warning("Unused task parameter; ignoring", taskId=task_id,
                           instanceId=instance_id, parameter=key)
    return rendered


class TaskValidation(BaseModel):
    type: str
    options: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def model_validate(cls, data: Any) -> "TaskValidation":
        if isinstance(data, cls):
            return data
        if not isinstance(data, dict):
            raise ValidationError("Task validation requires an object input.")
        validation_type = str(data.get("type", "")).strip()
        if not validation_type:
            raise ValidationError("Task validation.type must name a judge or registered validator.")
        config = {
            str(key): value
            for key, value in data.items()
            if isinstance(key, str) and key != "type"
        }
        return cls(type=validation_type, options=config)

    def validation_config(self) -> dict[str, Any]:
        return dict(self.options)

    def model_dump(self, mode: str = "python", **_: Any) -> dict[str, Any]:
        del mode
        return {"type": self.type, **dict(self.options)}


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

    def model_dump(self, mode: str = "python", **kwargs: Any) -> dict[str, Any]:
        payload = super().model_dump(mode=mode, **kwargs)
        payload["validation"] = self.validation.model_dump(mode=mode)
        return payload


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
