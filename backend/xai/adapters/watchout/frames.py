"""``FrameImages`` port over WatchOut's ``extract_frame_jpeg``: the image the GUI shows."""

from utils.frames import THUMBNAIL_WIDTH, FrameError, extract_frame_jpeg

from xai.contract.model import KeyFrame
from xai.reporting.ports import FrameUnavailable


class WatchOutFrameImages:
    def __init__(self, width: int = THUMBNAIL_WIDTH) -> None:
        self.width = width

    def image(self, key_frame: KeyFrame) -> bytes:
        reference = key_frame.frame_image_ref
        if reference is None:
            raise FrameUnavailable("the analysis does not record the path of its video")
        try:
            jpeg: bytes = extract_frame_jpeg(reference.video_path, key_frame.frame_index, self.width)
        except FrameError as error:
            raise FrameUnavailable(str(error)) from error
        return jpeg
