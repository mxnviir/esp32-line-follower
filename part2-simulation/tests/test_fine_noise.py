import pytest

from fine_noise import build


def rows(refs, group="shape"):
    return [{"id": f"c{i}", "ref": r, "group": group, "scale": 1 + i * 1e-3,
             "T_at_target_s": 1.54 + i * 1e-4 + (i % 2) * 1e-5} for i, r in enumerate(refs)]


def test_one_ref_recorded():
    out = build(rows(["e39f2f5"] * 5) + rows(["e39f2f5"] * 3, "repeat"))
    assert out["ref"] == out["repeat_ref"] == "e39f2f5" and out["n_cars"] == 5


@pytest.mark.parametrize("group", ["shape", "repeat"])
def test_mixed_refs_refused(group):
    ok = rows(["e39f2f5"] * 5)
    bad = rows(["e39f2f5", "33d227a", "e39f2f5"], group)
    with pytest.raises(ValueError, match="one code sha"):
        build(ok + bad if group == "repeat" else bad + bad)
