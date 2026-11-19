"""Review 2026-11-18 HIGH 1: the timed (decimated) STL must stay within a stated
distance of the judged body, or the run is refused."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from run_car import DECIMATION_LIMIT_MM, check_decimation  # noqa: E402


def test_within_limits_passes():
    d = {"p99_mm": 0.05, "hausdorff_mm": 0.2, "mean_mm": 0.01}
    assert check_decimation(d) is d


@pytest.mark.parametrize("key", list(DECIMATION_LIMIT_MM))
def test_over_a_limit_is_refused(key):
    d = {"p99_mm": 0.05, "hausdorff_mm": 0.2, "mean_mm": 0.01}
    d[key] = DECIMATION_LIMIT_MM[key] * 1.01
    with pytest.raises(SystemExit, match="too far"):
        check_decimation(d)


def test_nan_is_refused():
    with pytest.raises(SystemExit):
        check_decimation({"p99_mm": float("nan"), "hausdorff_mm": 0.0})
