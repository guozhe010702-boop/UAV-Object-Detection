import importlib.util
from pathlib import Path
import time

import pytest
from PIL import Image

from uav_app.inference_io import LatestFrames
from uav_app.preprocess import Preprocessor

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('score_visdrone', ROOT / 'tools/score_visdrone.py')
scorer = importlib.util.module_from_spec(spec);spec.loader.exec_module(scorer)


def test_dataset_category_aliases_cover_all_ten_scored_categories():
    assert scorer.category_name('pedestrians') == 'pedestrian'
    assert scorer.category_name('awning_tricycle') == 'awning-tricycle'
    assert scorer.category_name('others') == 'others'
    with pytest.raises(ValueError):scorer.category_name('unknown')


def test_ignore_coverage_uses_prediction_area():
    assert scorer.ignored_fraction([0, 0, 10, 10], [[0, 0, 10, 10]]) == 1
    assert scorer.ignored_fraction([0, 0, 10, 10], [[0, 0, 5, 10]]) == .5
    assert scorer.ignored_fraction([0, 0, 0, 10], []) == 1


def test_preprocessor_preserves_original_sequence_and_matching_image():
    source = LatestFrames()
    for i in range(4):source.put(Image.new('RGB', (100, 50), (i, 0, 0)))
    source.finish()
    worker = Preprocessor(source)
    _, _, frame = worker.frames.take()
    seq, acquired, image, rgb, transform, elapsed = frame
    assert seq == 4 and image.getpixel((0, 0)) == (3, 0, 0)
    assert rgb[320, 320].tolist() == [3, 0, 0] and elapsed >= 0
    assert worker.frames.take() is None
    worker.close();assert not worker.thread.is_alive()


def test_preprocessor_propagates_capture_failure_and_exits():
    source = LatestFrames();source.finish('CAPTURE TEST FAILURE')
    worker = Preprocessor(source)
    with pytest.raises(RuntimeError, match='CAPTURE TEST FAILURE'):worker.frames.take()
    worker.close();assert not worker.thread.is_alive()
