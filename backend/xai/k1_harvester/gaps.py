"""Facts WatchOut never stores, with the reason K1 writes for them."""

from xai.contract.primitives import Unavailable
from xai.contract.reasons import Reason

LINEAGE = Unavailable(
    reason=Reason.LINEAGE_NOT_PERSISTED,
    detail="WatchOut's SQL projects ClassID and times, not RelationID (iseql/compiler.py)",
)
"""Which intervals a rule used, and the variable bindings."""

KEYFRAMES = Unavailable(
    reason=Reason.KEYFRAMES_NOT_PERSISTED, detail="this WatchOut version does not store key frames"
)
"""``actions`` until the key-frame version of WatchOut."""

VISUAL_CONFIDENCE = Unavailable(
    reason=Reason.VISUAL_CONFIDENCE_NOT_RECORDED, detail="VisualPerInterval has no confidence column"
)
REID = Unavailable(
    reason=Reason.REID_SIMILARITY_NOT_PERSISTED,
    detail="Chroma stores the embeddings, not the match similarity",
)
