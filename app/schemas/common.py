"""Literal types shared by the public API schema and the LLM output schema (single source)."""

from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

IssueType = Literal["Security", "Breach", "Bug", "Performance", "CodeSmell"]
Severity = Literal["Critical", "High", "Medium", "Low"]
Complexity = Literal["Low", "Medium", "High"]

ISSUE_TYPES: tuple[str, ...] = get_args(IssueType)
SEVERITY_ORDER: tuple[str, ...] = get_args(Severity)  # most severe first
COMPLEXITY_ORDER: tuple[str, ...] = get_args(Complexity)  # least complex first


class CamelModel(BaseModel):
    """Serialises as camelCase (matches the .NET DTO), accepts snake_case in code."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
