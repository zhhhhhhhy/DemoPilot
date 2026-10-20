"""Harness-independent clarification and idempotent business-fact protocol."""
from __future__ import annotations

import hashlib
from copy import deepcopy
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .quotation_capabilities import BUSINESS_FIELDS, capability_identity

BusinessFieldId = Literal[tuple(BUSINESS_FIELDS)]


class Clarification(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=1200)
    field_ids: list[BusinessFieldId] = Field(min_length=1, max_length=12)
    reason: Literal["missing", "conflict"]


class BusinessFacts:
    """Known seller facts; questions never select facts by their wording.

    The evaluation adapter constructs this from its seller's predeclared business
    plan and evidence. It contains no acceptance journeys or calculated answers.
    Real sales sessions continue to use the human's free-text answers.
    """

    def __init__(self, values: dict[str, Any], sources: dict[str, str]):
        self.values = deepcopy(values)
        self.sources = deepcopy(sources)

    def _get(self, field_id):
        path = field_id.split(".")
        value = self.values
        for part in path:
            if isinstance(value, list):
                found = [item for item in value if isinstance(item, dict) and item.get("id") == part]
                if not found:
                    return False, None
                value = found[0]
            elif isinstance(value, dict) and part in value:
                value = value[part]
            else:
                return False, None
        return True, deepcopy(value)

    def reply(self, requests):
        clarifications = [r if isinstance(r, Clarification) else Clarification.model_validate(r)
                          for r in requests]
        selected = []
        seen = set()
        for request in clarifications:
            for field_id in request.field_ids:
                if field_id in seen:
                    continue
                seen.add(field_id)
                available, value = self._get(field_id)
                topic = BUSINESS_FIELDS[field_id]["topic"]
                source = self.sources.get(topic)
                if not source:
                    raise ValueError(f"Missing seller provenance for field {field_id}")
                selected.append(dict(
                    field_id=field_id, status="known" if available else "not_applicable",
                    value=value if available else None,
                    source=dict(topic=topic, sha256=hashlib.sha256(source.encode()).hexdigest()),
                    resolution="original_fact_not_approval_of_proposed_change" if request.reason == "conflict" else "requested_fact",
                ))
        return dict(protocol="business-fields-v1", capabilities=capability_identity(), facts=selected)
