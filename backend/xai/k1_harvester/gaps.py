"""Facts WatchOut never stores, with the reason K1 writes for them."""

from xai.contract.primitives import Unavailable
from xai.contract.reasons import Reason

VISUAL_CONFIDENCE = Unavailable(
    reason=Reason.VISUAL_CONFIDENCE_NOT_RECORDED, detail="VisualPerInterval has no confidence column"
)
REID = Unavailable(
    reason=Reason.REID_SIMILARITY_NOT_PERSISTED,
    detail="Chroma stores the embeddings, not the match similarity",
)
