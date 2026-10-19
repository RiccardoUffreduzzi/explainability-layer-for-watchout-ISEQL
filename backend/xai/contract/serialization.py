"""Reading and writing contract drafts as JSON."""

import json
from typing import Any

from xai.contract.canonical import canonical_json
from xai.contract.model import ContractDraft


def draft_to_data(draft: ContractDraft) -> dict[str, Any]:
    """The draft as plain JSON data: nullable fields kept, absent optional fields left out."""
    return draft.model_dump(mode="json")


def dump_draft(draft: ContractDraft, *, indent: int | None = None) -> str:
    """JSON of the draft: the same draft always gives the same text.

    Without ``indent`` it is the canonical form; with it, the same keys and values
    laid out for reading (the files K1 writes).
    """
    data = draft_to_data(draft)
    if indent is None:
        return canonical_json(data)
    return json.dumps(data, sort_keys=True, ensure_ascii=False, indent=indent)


def load_draft(text: str | bytes) -> ContractDraft:
    """Parse and validate a draft written by :func:`dump_draft` or by hand."""
    return ContractDraft.model_validate_json(text)
