"""Lightweight stand-ins for the subset of Pydantic used in tests."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any, Union, get_args, get_origin

__all__ = ["BaseModel", "Field", "ValidationError", "version"]


class ValidationError(Exception):
    """Error raised when validation fails in the lightweight model."""


from . import version  # noqa: E402  # isort: skip


class BaseModel:
    """Minimal implementation of the Pydantic BaseModel API used by tests."""

    def __init__(self, **data: Any) -> None:
        """Assign validated fields to the model instance."""

        annotations = getattr(self.__class__, "__annotations__", {})
        for name in annotations:
            default_value = getattr(self.__class__, name, None)
            if isinstance(default_value, _FieldInfo):
                default_value = default_value.default
            value = data.get(name, default_value)
            setattr(self, name, value)

    @classmethod
    def model_validate(cls, data: dict[str, Any]) -> BaseModel:
        """Create a model instance from a mapping of field values."""

        if not isinstance(data, dict):  # pragma: no cover - defensive guard
            raise ValidationError("model_validate expects a mapping")
        annotations = getattr(cls, "__annotations__", {})
        values: dict[str, Any] = {}
        for name, annotation in annotations.items():
            default_value = getattr(cls, name, None)
            if isinstance(default_value, _FieldInfo):
                default_value = default_value.default
            raw_value = data.get(name, default_value)
            values[name] = cls._coerce(annotation, raw_value)
        return cls(**values)

    @classmethod
    def _coerce(cls, annotation: Any, value: Any) -> Any:
        """Convert nested data structures into model instances."""

        annotation = cls._resolve_forward_ref(annotation)
        origin = get_origin(annotation)
        if origin is None:
            if isinstance(annotation, type) and issubclass(annotation, BaseModel):
                if value is None:
                    return None
                return annotation.model_validate(value)
            return value
        if origin is Union:  # type: ignore[name-defined]
            for option in get_args(annotation):
                option = cls._resolve_forward_ref(option)
                if option is type(None):
                    if value is None:
                        return None
                    continue
                coerced = cls._coerce(option, value)
                if coerced is not None:
                    return coerced
            return value
        if origin in {list, tuple}:
            (item_type,) = get_args(annotation) or (Any,)
            item_type = cls._resolve_forward_ref(item_type)
            if value is None:
                return [] if origin is list else ()
            coerced_items = [cls._coerce(item_type, item) for item in value]
            return coerced_items if origin is list else tuple(coerced_items)
        return value

    @classmethod
    def _resolve_forward_ref(cls, annotation: Any) -> Any:
        """Resolve forward references declared in type annotations."""

        if isinstance(annotation, str):
            module = sys.modules.get(cls.__module__)
            if module is not None:
                try:
                    return eval(annotation, vars(module))
                except Exception:  # pragma: no cover - fall back to raw string
                    return annotation
            return annotation
        ref = getattr(annotation, "__forward_arg__", None)
        if ref is None:
            return annotation
        module = sys.modules.get(cls.__module__)
        if module is not None and hasattr(module, ref):
            return getattr(module, ref)
        return annotation

    def model_dump(self) -> dict[str, Any]:  # pragma: no cover - convenience helper
        """Return a mapping of field names to values."""

        annotations = getattr(self.__class__, "__annotations__", {})
        return {name: getattr(self, name, None) for name in annotations}


@dataclass
class _FieldInfo:
    default: Any = None
    description: str | None = None

    def __call__(self) -> Any:  # pragma: no cover - compatibility shim
        """Return the default value for compatibility with Pydantic."""

        return self.default


def Field(*, default: Any = None, description: str | None = None) -> Any:
    """Return metadata describing default values for compatibility with Pydantic."""

    return _FieldInfo(default=default, description=description)
