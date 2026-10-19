"""Value types shared by every record of the contract draft.

Every fact is read from a WatchOut record, with a ``SourceRef`` that points to it,
or it is null with a reason from a closed catalog.
"""

import re
from dataclasses import dataclass
from enum import Enum
from typing import Annotated, Any, Generic, Literal, TypeVar, Union

from pydantic import (
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationInfo,
    model_validator,
)
from typing_extensions import TypeAliasType

from xai.contract.reasons import Reason

NonEmptyStr = Annotated[str, StringConstraints(min_length=1)]

RFC3339_PATTERN = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$"


def _rfc3339_text(value: Any, info: ValidationInfo) -> Any:
    """In JSON a timestamp is the RFC 3339 text the schema's pattern describes, nothing else."""
    if info.mode == "json" and not (isinstance(value, str) and re.fullmatch(RFC3339_PATTERN, value)):
        raise ValueError("expected an RFC 3339 date-time with an offset, e.g. 2026-10-06T20:00:00Z")
    return value


Timestamp = TypeAliasType(
    "Timestamp",
    Annotated[
        AwareDatetime,
        # The text is checked by the validator below; the parse itself may stay lax.
        Field(
            strict=False,
            json_schema_extra={"pattern": RFC3339_PATTERN},
            description="Date and time with an offset (RFC 3339), e.g. 2026-10-06T20:00:00Z.",
        ),
        BeforeValidator(_rfc3339_text),
    ],
)


def _is_none(value: object) -> bool:
    return value is None


def _drop_null(schema: dict[str, Any]) -> None:
    """JSON schema of an optional field: the value type only, without ``null`` and its default."""
    variants = schema.pop("anyOf", None)
    if variants is not None:
        kept = [v for v in variants if v != {"type": "null"}]
        if len(kept) == 1:
            schema.update(kept[0])
        else:
            schema["anyOf"] = kept
    schema.pop("default", None)


def absent_if_none(**kwargs: Any) -> Any:
    """An optional field that is left out of the JSON when it has no value.

    The draft distinguishes two kinds of empty field:

    - a *required* field that WatchOut cannot provide is written as ``null`` and
      has an entry in the record's ``unavailable`` map (for example ``rule.bindings``);
    - an *optional* field that does not apply is left out (for example ``unit`` on a
      strictness parameter, or ``sources`` when every field has the same source).

    Fields declared with this helper are of the second kind. In Python their value is
    ``None`` when absent; in the JSON text they are never ``null``, and the schema
    does not admit it.
    """
    return Field(default=None, exclude_if=_is_none, json_schema_extra=_drop_null, **kwargs)


class ContractModel(BaseModel):
    """Base of every contract record: immutable, strict about types and unknown keys.

    ``strict`` makes the model accept what the JSON schema accepts: no ``"24"`` for a
    number. The contract is read from JSON text (``load_draft``), where enums and dates
    are strings; Python code builds records with enum and datetime objects.

    ``class`` is a Python keyword, so a few fields use an alias; both the alias and
    the field name are accepted on input, and the alias is always written.
    """

    model_config = ConfigDict(
        frozen=True,
        strict=True,
        extra="forbid",
        validate_by_alias=True,
        validate_by_name=True,
        serialize_by_alias=True,
    )

    @model_validator(mode="before")
    @classmethod
    def _optional_fields_are_left_out(cls, data: Any, info: ValidationInfo) -> Any:
        """In the JSON text an optional field is left out, never ``null`` (see ``absent_if_none``)."""
        if info.mode == "json" and isinstance(data, dict):
            nulls = [
                name
                for name, field in cls.model_fields.items()
                if field.exclude_if is _is_none and name in data and data[name] is None
            ]
            if nulls:
                raise ValueError(f"leave out {', '.join(nulls)} instead of writing null")
        return data


class Stage(str, Enum):
    """WatchOut stage a ``SourceRef`` points to.

    ``config`` is ``Analyses`` or ``AppConfig``; ``code`` is a value of WatchOut's code
    or of ``pipeline_constants.yaml``.
    """

    SAMPLING = "sampling"
    VLM = "vlm"
    REID = "reid"
    LAMBDA = "Λ"
    IAD = "iad"
    AUDIO = "audio"
    ISEQL = "iseql"
    KEYFRAMES = "keyframes"
    CONFIG = "config"
    CODE = "code"


class SourceRef(ContractModel):
    """The WatchOut record a fact was read from. Never contains line numbers."""

    stage: Stage
    store: NonEmptyStr
    """File or table read, e.g. ``VisualPerInterval`` or ``Analyses:<id>``."""
    record_id: NonEmptyStr
    """String that finds the record again, e.g. ``59`` or ``handoff/A#/intervals/0``."""
    mode: Literal["read", "not_available"]
    """``not_available``: the fact is in the draft but no WatchOut record holds it."""


class DerivedSource(ContractModel):
    """A value computed from other fields of the same record (e.g. ``effective_hz``)."""

    derived_from: Annotated[list[NonEmptyStr], Field(min_length=1)]


class RequestSource(ContractModel):
    """A value taken from the harvest request (e.g. ``detection_mode`` from ``condition``)."""

    from_request: Literal["analysis_id", "event_type", "condition", "params"]
    value: str


Source = TypeAliasType(
    "Source",
    Annotated[
        Union[SourceRef, DerivedSource, RequestSource],
        Field(
            description="Where a field of a record comes from: a WatchOut record, other fields, the request."
        ),
    ],
)


class Unavailable(ContractModel):
    """Why a field is null. ``reason`` comes from the closed catalog."""

    reason: Reason
    detail: NonEmptyStr


SourceMap = TypeAliasType(
    "SourceMap",
    Annotated[
        dict[NonEmptyStr, Source],
        Field(
            description=(
                "Field -> Source, when the fields of a record come from different records. "
                "Fields of nested objects use a dotted path, e.g. sampling.source_fps."
            )
        ),
    ],
)

UnavailableMap = TypeAliasType(
    "UnavailableMap",
    Annotated[
        dict[NonEmptyStr, Unavailable],
        Field(
            description=(
                "Field -> Unavailable, for every required field of the record that is null "
                "because WatchOut cannot provide it. Dotted paths allowed."
            )
        ),
    ],
)


class Anchor(ContractModel):
    """A time span in frames and in seconds.

    ``read_as`` says which pair was read from WatchOut; the other pair is converted
    with the declared fps. When the fps is missing the converted pair is null
    and the containing record says why in its ``unavailable`` map.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "allOf": [
                {
                    "if": {"properties": {"read_as": {"const": "frames"}}},
                    "then": {
                        "properties": {"start_frame": {"type": "integer"}, "end_frame": {"type": "integer"}}
                    },
                },
                {
                    "if": {"properties": {"read_as": {"const": "seconds"}}},
                    "then": {"properties": {"start_s": {"type": "number"}, "end_s": {"type": "number"}}},
                },
            ]
        }
    )

    start_frame: int | None
    end_frame: int | None
    start_s: float | None
    end_s: float | None
    read_as: Literal["frames", "seconds"]

    @model_validator(mode="after")
    def _read_pair_is_present(self) -> "Anchor":
        read = (self.start_frame, self.end_frame) if self.read_as == "frames" else (self.start_s, self.end_s)
        if None in read:
            raise ValueError(f"read_as={self.read_as!r} but that pair is not complete")
        return self


T = TypeVar("T")


@dataclass(frozen=True)
class Fact(Generic[T]):
    """A value read from WatchOut together with where it was read.

    Harvesters work with ``Fact[T] | Unavailable`` (alias ``Reading[T]``) and only
    at the end split it into the record value, its ``sources`` entry or its
    ``unavailable`` entry. It is not part of the serialized draft.
    """

    value: T
    source: Source


Reading = Union[Fact[T], Unavailable]
"""Either a fact with its source or the reason it is missing."""
