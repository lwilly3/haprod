"""Retime the inside of a motion composition: every instant goes through a piecewise-linear map."""
import re
from bisect import bisect_right
from pathlib import Path

NUM = r"-?\d+(?:\.\d+)?"


def mapper(knots):
    """knots: [(old_t, new_t), ...] relative to the motion start; slope 1 outside the knots."""
    xs, ys = zip(*sorted(knots))
    assert all(b > a for a, b in zip(ys, ys[1:])), "knots must stay in order"

    def f(x):
        if x <= xs[0]:
            return ys[0] + (x - xs[0])
        if x >= xs[-1]:
            return ys[-1] + (x - xs[-1])
        i = bisect_right(xs, x) - 1
        return ys[i] + (x - xs[i]) * (ys[i + 1] - ys[i]) / (xs[i + 1] - xs[i])
    return f


def fmt(x):
    return f"{round(x, 2):.2f}".rstrip("0").rstrip(".") if abs(x) > 1e-9 else "0"


def remap(path: Path, knots, dur, helpers=(), dry=False):
    """
    Rewrites in place: the root data-duration / data-hero, the final `tl.to({}, { duration: D }, 0)`, every tween
    position (`}, t)`), helper calls matched by `helpers` (regexes whose named groups t1, t2… are instants, e.g.
    r'lever\\("#i\\d", (?P<t1>…), (?P<t2>…)\\)'), and the "t" of each cue in <script id="sfx">.
    Returns (map, number of instants rewritten).
    """
    f = mapper(knots)
    name = path.stem
    s = path.read_text(encoding="utf-8")
    n = 0

    def sub(pattern, text, fn, flags=0):
        nonlocal n
        out, k = re.subn(pattern, fn, text, flags=flags)
        n += k
        return out

    s = sub(rf'(data-composition-id="{name}" data-duration=")({NUM})(")', s, lambda m: m[1] + fmt(dur) + m[3])
    s = sub(rf'(data-hero=")({NUM})(")', s, lambda m: m[1] + fmt(min(f(float(m[2])), dur - 0.2)) + m[3])
    s = sub(rf"(tl\.to\(\{{\}}, \{{ duration: )({NUM})( \}}, 0\))", s, lambda m: m[1] + fmt(dur) + m[3])
    s = sub(rf"(\}}, )({NUM})(\))", s, lambda m: m[1] + fmt(f(float(m[2]))) + m[3])
    for pattern in helpers:
        def fix(m):
            g = m.group(0)
            for key in sorted((k for k in m.re.groupindex if k.startswith("t")), reverse=True):
                a, b = m.start(key) - m.start(), m.end(key) - m.start()
                g = g[:a] + fmt(f(float(m.group(key)))) + g[b:]
            return g
        s = sub(pattern, s, fix)
    s = sub(r'<script type="application/json" id="sfx">.*?</script>', s,
            lambda m: re.sub(rf'("t": )({NUM})', lambda k: k[1] + fmt(f(float(k[2]))), m[0]), flags=re.S)
    if not dry:
        write_like(path, s)
    return f, n


def write_like(path: Path, text: str) -> None:
    """Writes text keeping the file's own line endings (compositions are CRLF on this machine)."""
    data = text.replace("\r\n", "\n").encode("utf-8")
    if b"\r\n" in path.read_bytes():
        data = data.replace(b"\n", b"\r\n")
    path.write_bytes(data)
