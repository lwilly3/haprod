"""Put music cues on the timeline through the studio API (history, undo, merge with the open editor).

Usage: apply.py <pid> <cues.json> [--remove smus1,smus2] [--keep-gain old_id:new_index ...]
- Reads and writes UTF-8 end to end (a cp1252 round trip once mangled every accent of the timeline).
- New ids: smusN, after the highest existing one.
- Checks that every track but the music is byte-for-byte unchanged after the save.
"""
import json
import re
import sys
from pathlib import Path

from common import api_get, api_put


def main() -> None:
    pid, cues = sys.argv[1], json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    args = sys.argv[3:]
    remove = set(args[args.index("--remove") + 1].split(",")) if "--remove" in args else set()
    view = api_get(f"/projects/{pid}/montage")
    tl = view["timeline"]
    before = json.loads(json.dumps(tl))
    by_id = {a["id"]: a for a in tl["audio"]}
    # --keep-gain smus9:0 : the new cue 0 takes the gain the user had set on smus9
    if "--keep-gain" in args:
        for pair in args[args.index("--keep-gain") + 1:]:
            if ":" not in pair:
                break
            old, idx = pair.split(":")
            cues[int(idx)]["gain_db"] = by_id[old]["gain_db"]
    tl["audio"] = [a for a in tl["audio"] if a["id"] not in remove]
    last = max([int(m.group(1)) for a in tl["audio"] if (m := re.fullmatch(r"smus(\d+)", a["id"]))] or [0])
    for i, c in enumerate(cues, last + 1):
        c["id"] = f"smus{i}"
    tl["audio"] += cues
    saved = api_put(f"/projects/{pid}/montage", {"timeline": tl, "rev": view["rev"]})["timeline"]
    for k in before:
        if k != "audio":
            assert saved[k] == before[k], f"track {k} changed"
    keep = lambda l: [a for a in l if a["role"] != "music"]
    assert keep(saved["audio"]) == keep(before["audio"]), "sound effects changed"
    for a in sorted((a for a in saved["audio"] if a["role"] == "music"), key=lambda a: a["at"]):
        print(f"{a['id']:7} {a['at']:8.2f} -> {a['at'] + a['out'] - a['in']:8.2f}  {a['gain_db']:6.1f} dB  "
              f"{a['src'].split('/')[-1]}")


if __name__ == "__main__":
    main()
