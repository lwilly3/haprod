"""
Look at the timeline before replacing a zone.

    python zone.py <pid> clips                       # A-roll clips with their timeline start/end
    python zone.py <pid> old <a> <b>                 # old spoken text + every element placed on [a, b]
    python zone.py <pid> new <raw.json> <at> [<in>]  # new take's words in timeline time, if it starts at <at>
"""
import json
import sys

from common import clip_starts, source_words_on_timeline, timeline


def clips(pid):
    tl = timeline(pid)
    for c, s in zip(tl["aroll"], clip_starts(tl)):
        print(f"{s:9.3f} {s + c['out'] - c['in']:9.3f}  {c['id']:5} {c.get('src', 'source')[-50:]:50} "
              f"in={c['in']} out={c['out']} tr={c.get('transition')} gain={c.get('gain_db')}")


def old(pid, a, b):
    tl = timeline(pid)
    print("=== old words (timeline time)")
    words = source_words_on_timeline(pid, tl, a, b)
    line = []
    for t, w in words:
        line.append(f"{t:.2f}:{w}")
        if w[-1:] in ".?!":
            print(" ".join(line))
            line = []
    print(" ".join(line))
    print("=== elements touching the zone")
    for tr in ("zooms", "broll", "motion", "audio", "texts", "markers"):
        for x in tl[tr]:
            t = x.get("at", x.get("t"))
            end = t + (x["dur"] if "dur" in x else (x["out"] - x["in"] if "out" in x else 0))
            if end > a - 2 and t < b + 3:
                if tr == "motion":
                    info = f"dur={x['dur']} beat={x.get('beat')} {x.get('idea', '')[:240]!r}"
                else:
                    info = json.dumps({k: v for k, v in x.items() if k not in ("id", "at", "in", "role")}, ensure_ascii=False)[:160]
                print(f"{tr:6} {x['id']:8} {t:9.2f} {end:9.2f} {info}")


def new(raw_path, at, start_in=0.0):
    raw = json.loads(open(raw_path, encoding="utf-8").read())
    print(" ".join(f"{at + w['start'] - start_in:.2f}:{w['text']}" for w in raw["words"]
                   if w["type"] == "word" and w["start"] >= start_in))


if __name__ == "__main__":
    pid, cmd, *args = sys.argv[1:]
    if cmd == "clips":
        clips(pid)
    elif cmd == "old":
        old(pid, float(args[0]), float(args[1]))
    else:
        new(args[0], float(args[1]), float(args[2]) if len(args) > 2 else 0.0)
