"""Overlap CPU letterbox with the independent NPU stage, retaining newest work only."""
import threading
import time

from .inference_io import LatestFrames
from .postprocess import letterbox


class Preprocessor:
    def __init__(self, source):
        self.source = source
        self.frames = LatestFrames()
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.run, name='uav-preprocess', daemon=True)
        self.thread.start()

    def run(self):
        try:
            while not self.stop.is_set():
                frame = self.source.take(timeout=12)
                if frame is None:
                    self.frames.finish();return
                sequence, acquired, image = frame
                before = time.monotonic()
                rgb, transform = letterbox(image)
                elapsed = (time.monotonic() - before) * 1000
                self.frames.put((sequence, acquired, image, rgb, transform, elapsed))
            self.frames.finish()
        except Exception as error:
            self.frames.finish(str(error))

    def close(self):
        self.stop.set()
        self.thread.join(timeout=3)
