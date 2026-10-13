"""
Replace a stretch of the A-roll with a new take and re-place everything that sits on it.

    python replace.py <config.py> [--dry]

The config is a Python file defining CFG (see SKILL.md). --dry prints the plan (new end, delta, motion spans with
overlaps, number of instants retimed per composition) without writing anything.
"""
import json
import sys
from pathlib import Path

from common import project_dir
import remap

from studio.modules.projects import montage, storyboard  # noqa: E402  (path set by common)
from studio.modules.transcript import cloud, cues  # noqa: E402

TRACKS = ("zooms", "broll", "motion", "audio", "texts")


def run(cfg: dict, dry: bool) -> None:
    pid = cfg["pid"]
    tl = montage.load(pid)
    ids = [c["id"] for c in tl["aroll"]]
    starts, t = {}, 0.0
    for c in tl["aroll"]:
        starts[c["id"]] = round(t, 3)
        t += c["out"] - c["in"]
    first, last = ids.index(cfg["clips"][0]), ids.index(cfg["clips"][-1])
    assert ids[first:last + 1] == cfg["clips"], f"clips are not contiguous: {ids[first:last + 1]}"
    old_a = starts[cfg["clips"][0]]
    old_b = starts[cfg["clips"][-1]] + tl["aroll"][last]["out"] - tl["aroll"][last]["in"]
    assert abs(old_a - cfg["old"][0]) < 0.01 and abs(old_b - cfg["old"][1]) < 0.01, \
        f"zone moved since the config was written: {old_a}–{old_b}"
    # inserted clips listed by id (a gag kept in the middle) are reused as they are
    keep = {c["id"]: c for c in tl["aroll"][first:last + 1]}
    new_clips = [dict(keep[c]) if isinstance(c, str) else c for c in cfg["aroll"]]
    new_b = old_a + sum(c["out"] - c["in"] for c in new_clips)
    delta = round(new_b - old_b, 3)

    items = {x["id"]: x for tr in TRACKS for x in tl[tr]}
    old = {i: dict(x) for i, x in items.items()}
    moved = set()
    for mid, m in cfg.get("motions", {}).items():
        f = remap.mapper(m["knots"])
        s_old = old[mid]["at"]
        items[mid]["at"], items[mid]["dur"] = m["at"], m["dur"]
        moved.add(mid)
        for sid in [x["id"] for x in tl["audio"] if x.get("motion") == mid] + m.get("sounds", []):
            items[sid]["at"] = round(m["at"] + f(old[sid]["at"] - s_old), 3)
            moved.add(sid)
    for at, group in cfg.get("groups", []):
        off = at - old[group[0]]["at"]
        group = group + [x["id"] for x in tl["audio"] if x.get("motion") in group and x["id"] not in group]
        for i in group:
            items[i]["at"] = round(old[i]["at"] + off, 3)
            moved.add(i)
    for i, at in cfg.get("fixed", {}).items():
        items[i]["at"] = at
        moved.add(i)
    for i, dur in cfg.get("durs", {}).items():
        items[i]["dur"] = dur
    drop = set(cfg.get("drop", ()))
    for tr in TRACKS:
        tl[tr] = [x for x in tl[tr] if x["id"] not in drop]
        for x in tl[tr]:
            if x["id"] in moved:
                continue
            o = old[x["id"]]["at"]
            if o >= old_b - cfg.get("tail", 1.0):
                x["at"] = round(x["at"] + delta, 3)
            elif o >= old_a - 1e-3:
                raise SystemExit(f"element left in the zone without a decision: {x['id']} at {o}")
    for k in tl["markers"]:
        if k["t"] >= old_b:
            k["t"] = round(k["t"] + delta, 3)
    used = {x["id"] for tr in montage.TRACKS for x in tl[tr]} - set(keep)
    fresh = iter(f"a{n}" for n in range(1, 1000) if f"a{n}" not in used and f"a{n}" not in keep)
    tl["aroll"][first:last + 1] = [c if c.get("id") in keep else {"id": next(fresh), "transition": None, **c}
                                   for c in new_clips]

    print(f"zone {old_a:.3f}–{old_b:.3f} → new end {new_b:.3f}, delta {delta:+.3f}")
    spans = sorted((x["at"], round(x["at"] + x["dur"], 2), x["id"]) for x in tl["motion"]
                   if old_a - 10 < x["at"] < new_b + 10)
    for a, b in zip(spans, spans[1:] + [None]):
        print("  ", a, "OVERLAP" if b and b[0] < a[1] - 1e-3 else "")
    motion_dir = project_dir(pid) / "montage" / "motion"
    for mid, m in cfg.get("motions", {}).items():
        _, n = remap.remap(motion_dir / f"{mid}.html", m["knots"], m["dur"], m.get("helpers", ()), dry=True)
        print(f"   {mid}: {n} instants retimed")
    if dry:
        return

    # history snapshot (timeline + every composition) happens here, before the compositions are touched
    saved = montage.save(pid, tl, keep_history=True, shifts=[{"at": old_b, "length": delta}])
    board = storyboard.load(pid)
    if board:
        beat_at = {x["beat"]: x["at"] for tr in ("zooms", "broll", "motion") for x in saved[tr]
                   if x.get("beat") and x["id"] in moved}
        for b in board["beats"]:
            if b["id"] in beat_at and old_a <= b.get("at", 0) < old_b:
                b["at"] = beat_at[b["id"]]
        storyboard.save(pid, board)
    for mid, m in cfg.get("motions", {}).items():
        remap.remap(motion_dir / f"{mid}.html", m["knots"], m["dur"], m.get("helpers", ()))
    for name, pairs in cfg.get("edits", {}).items():
        p = motion_dir / name
        s = p.read_text(encoding="utf-8")
        for a, b in pairs:
            assert s.count(a) == 1, (name, a)
            s = s.replace(a, b)
        remap.write_like(p, s)
    montage.after_change(pid)  # queues the renders, rewrites the FCPXML

    raw = json.loads(Path(cfg["raw"]).read_text(encoding="utf-8"))
    segs = cloud.group([(w["start"], w["end"], w["text"]) for w in raw["words"] if w["type"] == "word"])
    built = cues.build_cues(segs, "line")
    stem = Path(cfg["raw"]).name.removesuffix("_raw.json")
    out = project_dir(pid) / "transcripts"
    (out / f"{stem}.srt").write_text(cues.to_srt(built), encoding="utf-8")
    (out / f"{stem}.txt").write_text(cues.to_txt(built, "line"), encoding="utf-8")
    print("saved")


if __name__ == "__main__":
    scope: dict = {}
    exec(Path(sys.argv[1]).read_text(encoding="utf-8"), scope)
    run(scope["CFG"], "--dry" in sys.argv)
