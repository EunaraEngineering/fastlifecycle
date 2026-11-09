"""Typed entity primitives and lifecycle validation decorators."""

from __future__ import annotations

import inspect
import types
from collections.abc import Awaitable, Callable, Iterable
from enum import Enum
from typing import (
    Any,
    ClassVar,
    TypeVar,
    Union,
    cast,
    get_args,
    get_origin,
    get_type_hints,
    overload,
)

from .errors import GuardRejectedError, InvariantError, TransitionInputError

Guard = Callable[..., bool | Awaitable[bool]]
Invariant = Callable[..., bool | Awaitable[bool]]
EntityType = TypeVar("EntityType", bound="Entity")


def _type_name(annotation: object) -> str:
    return getattr(annotation, "__name__", repr(annotation))


def _matches_type(value: object, annotation: object) -> bool:
    """Provide pragmatic runtime checks for transition input annotations."""
    if annotation is Any or annotation is inspect.Signature.empty:
        return True
    if annotation is None or annotation is type(None):
        return value is None
    origin = get_origin(annotation)
    if origin in (Union, types.UnionType):
        return any(_matches_type(value, option) for option in get_args(annotation))
    if origin is list:
        return isinstance(value, list) and all(
            _matches_type(item, get_args(annotation)[0]) for item in value
        )
    if origin is dict:
        args = get_args(annotation)
        return isinstance(value, dict) and all(
            _matches_type(key, args[0]) and _matches_type(item, args[1])
            for key, item in value.items()
        )
    if origin is tuple:
        return isinstance(value, tuple)
    if isinstance(annotation, type):
        return isinstance(value, annotation)
    return True


def _field_annotations(entity_type: type[Entity]) -> dict[str, object]:
    fields: dict[str, object] = {}
    for base in reversed(entity_type.__mro__):
        if not issubclass(base, Entity):
            continue
        try:
            annotations = get_type_hints(base)
        except (NameError, TypeError):
            annotations = getattr(base, "__annotations__", {})
        for name, annotation in annotations.items():
            if get_origin(annotation) is ClassVar or name.startswith("_"):
                continue
            fields[name] = annotation
    return fields


def _coerce(value: object, annotation: object) -> object:
    """Restore enum values after JSON round-tripping entity state."""
    origin = get_origin(annotation)
    if origin in (Union, types.UnionType):
        for option in get_args(annotation):
            try:
                return _coerce(value, option)
            except (TypeError, ValueError):
                continue
        return value
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        return annotation(value)
    return value


class Entity:
    """Base class for persistent lifecycle entities.

    Public fields are declared as normal class annotations with optional class
    defaults.  The ``state`` field is required on every concrete entity.
    """

    _entity_id: str | None

    def __init__(self, **values: object) -> None:
        fields = _field_annotations(type(self))
        unknown = set(values).difference(fields)
        if unknown:
            names = ", ".join(sorted(unknown))
            raise TypeError(f"Unknown fields for {type(self).__name__}: {names}")
        for name, annotation in fields.items():
            if name in values:
                value = values[name]
            elif hasattr(type(self), name):
                value = getattr(type(self), name)
            else:
                raise TypeError(
                    f"Missing required field {name!r} for {type(self).__name__}"
                )
            if not _matches_type(value, annotation):
                raise TypeError(
                    f"Field {name!r} for {type(self).__name__} must be "
                    f"{_type_name(annotation)}, got {type(value).__name__}."
                )
            setattr(self, name, value)
        self._entity_id = None

    @classmethod
    def _fields(cls) -> dict[str, object]:
        return _field_annotations(cls)

    def _persistent_values(self) -> dict[str, object]:
        return {name: getattr(self, name) for name in self._fields()}

    @classmethod
    def _from_persistent_values(
        cls: type[EntityType], values: dict[str, object], *, entity_id: str
    ) -> EntityType:
        restored = {
            name: _coerce(value, cls._fields()[name]) for name, value in values.items()
        }
        entity = cls(**restored)
        entity._entity_id = entity_id
        return entity

    @property
    def entity_id(self) -> str | None:
        """Identifier attached by a lifecycle execution or lookup."""
        return self._entity_id


class Transition:
    """Descriptor carrying a transition's declared source, target, and guards."""

    def __init__(
        self,
        function: Callable[..., object],
        *,
        source: object | Iterable[object],
        target: object,
        guards: Iterable[Guard | str] = (),
    ) -> None:
        self.function = function
        self.name = function.__name__
        self.sources = (
            tuple(source)
            if isinstance(source, Iterable)
            and not isinstance(source, (str, bytes, Enum))
            else (source,)
        )
        self.target = target
        self.guards = tuple(guards)
        self.owner: type[Entity] | None = None
        self.signature = inspect.signature(function)
        self.input_hints = get_type_hints(function)

    def __set_name__(self, owner: type[Entity], name: str) -> None:
        self.owner = owner
        self.name = name

    @overload
    def __get__(self, instance: None, owner: type[Entity]) -> Transition: ...

    @overload
    def __get__(
        self, instance: Entity, owner: type[Entity]
    ) -> Callable[..., object]: ...

    def __get__(
        self, instance: Entity | None, owner: type[Entity]
    ) -> Transition | Callable[..., object]:
        if instance is None:
            return self
        return cast(Callable[..., object], self.function.__get__(instance, owner))

    def validate_arguments(self, values: dict[str, object]) -> None:
        try:
            bound = self.signature.bind(None, **values)
        except TypeError as error:
            raise TransitionInputError(
                f"Invalid input for transition {self.name!r}: {error}"
            ) from error
        for name, value in bound.arguments.items():
            if name == "self":
                continue
            annotation = self.input_hints.get(
                name, self.signature.parameters[name].annotation
            )
            if not _matches_type(value, annotation):
                raise TransitionInputError(
                    f"Invalid input {name!r} for transition {self.name!r}: expected "
                    f"{_type_name(annotation)}, got {type(value).__name__}."
                )


def transition(
    *,
    source: object | Iterable[object],
    target: object,
    guards: Iterable[Guard | str] = (),
) -> Callable[[Callable[..., object]], Transition]:
    """Declare a state transition on an :class:`Entity` method."""

    def decorate(function: Callable[..., object]) -> Transition:
        return Transition(function, source=source, target=target, guards=guards)

    return decorate


def invariant(function: Invariant) -> Invariant:
    """Mark an entity method as an invariant checked after every transition."""
    function.__dict__["__fastlifecycle_invariant__"] = True
    return function


async def call_validation(callback: Guard | Invariant, entity: Entity) -> bool:
    """Invoke a guard or invariant whether it expects ``self`` or no argument."""
    signature = inspect.signature(callback)
    required = [
        parameter
        for parameter in signature.parameters.values()
        if parameter.default is inspect.Signature.empty
        and parameter.kind
        in (parameter.POSITIONAL_ONLY, parameter.POSITIONAL_OR_KEYWORD)
    ]
    value = callback(entity) if required else callback()
    if inspect.isawaitable(value):
        value = await value
    return bool(value)


async def validate_guards(entity: Entity, transition_def: Transition) -> None:
    for guard in transition_def.guards:
        callback = getattr(entity, guard) if isinstance(guard, str) else guard
        if not await call_validation(callback, entity):
            raise GuardRejectedError(
                f"Guard rejected transition {transition_def.name!r} for "
                f"{type(entity).__name__} {entity.entity_id!r}."
            )


async def validate_invariants(entity: Entity, transition_def: Transition) -> None:
    for base in type(entity).__mro__:
        for callback in vars(base).values():
            if getattr(callback, "__fastlifecycle_invariant__", False):
                bound = callback.__get__(entity, type(entity))
                if not await call_validation(bound, entity):
                    raise InvariantError(
                        f"Invariant {callback.__name__!r} failed after transition "
                        f"{transition_def.name!r} for {type(entity).__name__} "
                        f"{entity.entity_id!r}."
                    )
