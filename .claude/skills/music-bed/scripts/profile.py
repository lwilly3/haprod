"""Profile music files: duration, audible start/end, short-term loudness every 4 s.

Usage: profile.py <file.wav> [more files]
The audible end (short-term > median − 12 dB) is what must land on the end of a section: Epidemic edits
end with a long fade (up to ~10 s) that disappears under the voice.
"""
import sys

from common import short_term


def profile(path: str) -> None:
    st = [(t, x) for t, x in short_term(path) if x > -70]
    if not st:
        print(path, "silent")
        return
    values = sorted(x for _, x in st)
    med = values[len(values) // 2]
    loud = [t for t, x in st if x > med - 12]
    end = st[-1][0]
    print(f"{path}\n  duration {end:.1f} s · median {med:.1f} LUFS · audible {loud[0]:.1f} -> {loud[-1]:.1f} s")
    blocks = []
    for s in range(0, int(end) + 1, 4):
        w = [x for t, x in st if s <= t < s + 4]
        if w:
            blocks.append(f"{s}:{sum(w) / len(w):.0f}")
    print("  " + " ".join(blocks))


if __name__ == "__main__":
    for p in sys.argv[1:]:
        profile(p)
