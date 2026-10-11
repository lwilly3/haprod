"""
Timeline : le montage tel que Studio le décrit, indépendamment du logiciel qui le finira.

C'est le format de travail : le dérush en produit une, les étapes suivantes l'enrichissent
(zooms, sound design, transitions) et elle s'exporte vers DaVinci Resolve en FCPXML.

    {
      "fps_num": 30000, "fps_den": 1001, "width": 3840, "height": 2160,
      "assets": {"<id>": {path, name, duration, video, audio, width, height, audio_channels, audio_rate,
                          timecode}},      # timecode de départ du fichier (« 07:46:56;02 »), ou None
      "clips": [                      # la piste principale, bout à bout
        {"asset": "<id>", "in": s, "out": s,
         "zoom": [{"t": s, "scale": 1.3, "x": 0.0, "y": 0.0}],   # t depuis le début du clip ;
                                                                  # x, y : décalage du centre, en fraction de la largeur / hauteur
         "transition": {"type": "dissolve", "duration": s},       # avec le clip précédent, centrée sur la coupe
         "gain_db": 3}                                            # volume du clip (absent : 0 dB)
      ],
      "audio": [                      # sons posés par-dessus (sound design, musique)
        {"asset": "<id>", "at": s, "in": s, "out": s, "gain_db": -6, "role": "sfx" | "music"}
      ],
      "video": [                      # plans posés au-dessus (B-roll, motion design avec alpha)
        {"asset": "<id>", "at": s, "in": s, "out": s, "lane": 1, "mute": true}
      ],
      "markers": [{"t": s, "text": "…", "kind": "chapter" | "note"}]
    }

Toutes les durées sont en secondes ; les transitions ne décalent rien (elles mangent la
marge des rushes de part et d'autre de la coupe).
"""
from fractions import Fraction
from pathlib import Path
from urllib.parse import quote
from xml.sax.saxutils import quoteattr

from . import media

FCPXML_VERSION = "1.10"
# effets standards de Final Cut, que Resolve reconnaît par leur nom
CROSS_DISSOLVE = ("Cross Dissolve", "FxPlug:4731E73A-8DAC-4113-9A30-AE85B1761265")
AUDIO_CROSSFADE = ("Audio Crossfade", "FFAudioTransition")
ROLES = {"sfx": "effects", "music": "music", "dialogue": "dialogue"}
AUDIO_RATES = {32000: "32k", 44100: "44.1k", 48000: "48k", 88200: "88.2k", 96000: "96k"}


# --- Construction ---------------------------------------------------------------

def asset(path: str | Path, name: str | None = None) -> dict:
    """Un média décrit par ffprobe, tel que la timeline le référence."""
    path = Path(path)
    info = media.probe(path)
    return {"path": str(path), "name": name or path.stem, "duration": info.get("duration") or 0.0,
            "video": bool(info.get("width")), "audio": bool(info.get("audio")),
            "width": info.get("width"), "height": info.get("height"),
            "fps_num": info.get("fps_num"), "fps_den": info.get("fps_den"),
            "audio_channels": info.get("audio_channels") or 2, "audio_rate": info.get("audio_rate") or 48000,
            "timecode": info.get("timecode")}


def timecode(rush: dict) -> str | None:
    """Le timecode de départ d'un rush ; relu sur le fichier pour les rushes ajoutés avant qu'on le note."""
    return rush["timecode"] if "timecode" in rush else media.probe(Path(rush["path"])).get("timecode")


def from_ranges(project: dict, ranges: list[dict]) -> dict:
    """La timeline d'un dérush : les plages gardées bout à bout, sans effet."""
    rushes = {r["id"]: r for r in project["rushes"]}
    assets = {}
    for r in ranges:
        rush = rushes[r["rush"]]
        assets[rush["id"]] = {"path": rush["path"], "name": rush["name"], "duration": rush.get("duration") or 0.0,
                              "video": True, "audio": rush.get("audio", True),
                              "width": rush.get("width"), "height": rush.get("height"),
                              "fps_num": rush.get("fps_num"), "fps_den": rush.get("fps_den"),
                              "audio_channels": rush.get("audio_channels") or 2,
                              "audio_rate": rush.get("audio_rate") or 48000, "timecode": timecode(rush)}
    first = rushes[ranges[0]["rush"]] if ranges else {}
    return {"fps_num": first.get("fps_num") or 25, "fps_den": first.get("fps_den") or 1,
            "width": first.get("width") or 1920, "height": first.get("height") or 1080,
            "assets": assets,
            "clips": [{"asset": r["rush"], "in": r["start"], "out": r["end"]} for r in ranges],
            "audio": []}


def clip_starts(timeline: dict) -> list[float]:
    """La position de chaque clip de la piste principale."""
    starts, cursor = [], 0.0
    for clip in timeline["clips"]:
        starts.append(cursor)
        cursor += clip["out"] - clip["in"]
    return starts


def check(timeline: dict) -> list[str]:
    """Ce qu'un logiciel de montage refuserait : transitions sans marge, sons hors timeline."""
    problems = []
    assets, clips = timeline["assets"], timeline["clips"]
    for n, clip in enumerate(clips):
        if not 0 <= clip["in"] < clip["out"] <= assets[clip["asset"]]["duration"] + 1e-3:
            problems.append(f"clip {n + 1} : plage {clip['in']:.2f}–{clip['out']:.2f} s hors du rush")
        tr = clip.get("transition")
        if not tr:
            continue
        if n == 0:
            problems.append("le premier clip ne peut pas avoir de transition d'entrée")
            continue
        half = tr["duration"] / 2
        prev = clips[n - 1]
        if clip["in"] - half < 0:
            problems.append(f"clip {n + 1} : pas assez de marge avant pour la transition ({clip['in']:.2f} s)")
        if prev["out"] + half > assets[prev["asset"]]["duration"]:
            problems.append(f"clip {n} : pas assez de marge après pour la transition")
    total = sum(c["out"] - c["in"] for c in clips)
    for sound in timeline["audio"]:
        if not 0 <= sound["at"] < total:
            problems.append(f"son {assets[sound['asset']]['name']} hors de la timeline ({sound['at']:.2f} s)")
    for item in timeline.get("video", []):
        if not 0 <= item["at"] < total:
            problems.append(f"plan {assets[item['asset']]['name']} hors de la timeline ({item['at']:.2f} s)")
    return problems


# --- Export FCPXML (DaVinci Resolve, Final Cut Pro) -----------------------------------

def _src(path: str) -> str:
    return "file:///" + quote(Path(path).as_posix().lstrip("/"), safe="/:")


def fcpxml(timeline: dict, name: str) -> str:
    frame = Fraction(timeline["fps_den"], timeline["fps_num"])
    width, height = timeline["width"], timeline["height"]
    assets, clips = timeline["assets"], timeline["clips"]

    def frames(t: float) -> int:
        return round(Fraction(t).limit_denominator(1_000_000) / frame)

    def tc(t: float | int, already_frames: bool = False, asset: str | None = None) -> str:
        """Un temps FCPXML : un nombre entier d'images, en fraction de secondes. Avec `asset` : un temps dans
        ce média, décalé de son timecode de départ (Resolve ne retrouve pas le fichier sans)."""
        value = (t if already_frames else frames(t)) * frame + (origin[asset] if asset else 0)
        return f"{value.numerator}/{value.denominator}s" if value.denominator != 1 else f"{value.numerator}s"

    # début de chaque média, en secondes, d'après son timecode
    origin = {key: media.timecode_frames(a.get("timecode"), a.get("fps_num") or timeline["fps_num"],
                                         a.get("fps_den") or timeline["fps_den"])
                   * Fraction(a.get("fps_den") or timeline["fps_den"], a.get("fps_num") or timeline["fps_num"])
              for key, a in assets.items()}

    # resources : un format par cadence / taille, un asset par média, les effets de transition
    resources, formats, ids = [], {}, {}

    def format_id(w: int, h: int, num: int, den: int) -> str:
        key = (w, h, num, den)
        if key not in formats:
            formats[key] = f"r{len(formats) + 1}"
            fd = Fraction(den, num)
            resources.append(f'<format id="{formats[key]}" frameDuration="{fd.numerator}/{fd.denominator}s" '
                             f'width="{w}" height="{h}"/>')
        return formats[key]

    seq_format = format_id(width, height, timeline["fps_num"], timeline["fps_den"])
    for key, a in assets.items():
        rid = ids[key] = f"a{len(ids) + 1}"
        attrs = [f'id="{rid}"', f"name={quoteattr(a['name'])}", f'start="{tc(0, True, key)}"', f'duration="{tc(a["duration"])}"',
                 f'hasVideo="{int(a["video"])}"', f'hasAudio="{int(a["audio"])}"']
        if a["video"]:
            attrs.append(f'format="{format_id(a["width"] or width, a["height"] or height, a.get("fps_num") or timeline["fps_num"], a.get("fps_den") or timeline["fps_den"])}"')
        if a["audio"]:
            attrs += ['audioSources="1"', f'audioChannels="{a["audio_channels"]}"', f'audioRate="{a["audio_rate"]}"']
        resources.append(f"<asset {' '.join(attrs)}><media-rep kind=\"original-media\" src={quoteattr(_src(a['path']))}/></asset>")
    if any(c.get("transition") for c in clips):
        resources.append(f'<effect id="fx-dissolve" name="{CROSS_DISSOLVE[0]}" uid="{CROSS_DISSOLVE[1]}"/>')
        resources.append(f'<effect id="fx-crossfade" name="{AUDIO_CROSSFADE[0]}" uid="{AUDIO_CROSSFADE[1]}"/>')

    # positions en images, calculées une fois pour que tout tombe juste
    starts = [frames(t) for t in clip_starts(timeline)]
    ins = [frames(c["in"]) for c in clips]
    lengths = [frames(c["out"]) - frames(c["in"]) for c in clips]
    total = (starts[-1] + lengths[-1]) if clips else 0

    def transform(clip: dict, src_in: int) -> str:
        keys = clip.get("zoom") or []
        if not keys:
            return ""
        # position FCPXML : décalage du centre, en pourcentage de la hauteur de l'image
        def pos(k): return f"{k.get('x', 0) * width / height * 100 + 0:.4f} {-k.get('y', 0) * 100 + 0:.4f}"
        def scale(k): return f"{k['scale']:.4f} {k['scale']:.4f}"
        if len(keys) == 1:
            return f'<adjust-transform position="{pos(keys[0])}" scale="{scale(keys[0])}"/>'
        def anim(fn): return "".join(f'<keyframe time="{tc(src_in + frames(k["t"]), True, clip["asset"])}" value="{fn(k)}"/>' for k in keys)
        return (f'<adjust-transform position="{pos(keys[0])}" scale="{scale(keys[0])}">'
                f'<param name="position"><keyframeAnimation>{anim(pos)}</keyframeAnimation></param>'
                f'<param name="scale"><keyframeAnimation>{anim(scale)}</keyframeAnimation></param>'
                f"</adjust-transform>")

    # sons, plans et marqueurs se rattachent au clip de la piste principale sous lequel ils commencent
    attached: dict[int, list[str]] = {}
    lanes = {"sfx": -1, "music": -2}

    def host_of(at: int) -> int:
        return max((n for n, s in enumerate(starts) if s <= at), default=0)

    for item in sorted(timeline.get("video", []), key=lambda v: v["at"]):
        at = frames(item["at"])
        host = host_of(at)
        a = assets[item["asset"]]
        length = frames(item["out"]) - frames(item["in"])
        # un plan sans son (B-roll muet, motion design) : seule l'image est utilisée
        only_image = ' srcEnable="video"' if (item.get("mute", True) or not a["audio"]) and a["video"] else ""
        attached.setdefault(host, []).append(
            f'<asset-clip ref="{ids[item["asset"]]}" lane="{item.get("lane", 1)}" '
            f'offset="{tc(ins[host] + at - starts[host], True, clips[host]["asset"])}" '
            f'start="{tc(frames(item["in"]), True, item["asset"])}" duration="{tc(length, True)}" '
            f'name={quoteattr(a["name"])}{only_image}/>')
    for mark in sorted(timeline.get("markers", []), key=lambda m: m["t"]):
        at = frames(mark["t"])
        host = host_of(at)
        tag = "chapter-marker" if mark.get("kind") == "chapter" else "marker"
        attached.setdefault(host, []).append(
            f'<{tag} start="{tc(ins[host] + at - starts[host], True, clips[host]["asset"])}" duration="{tc(1, True)}" '
            f'value={quoteattr(mark.get("text") or "")}/>')

    for sound in sorted(timeline["audio"], key=lambda s: s["at"]):
        at = frames(sound["at"])
        host = host_of(at)
        a = assets[sound["asset"]]
        role = sound.get("role", "sfx")
        gain = sound.get("gain_db")
        volume = f'<adjust-volume amount="{gain:+.1f}dB"/>' if gain else ""
        length = frames(sound["out"]) - frames(sound["in"])
        attached.setdefault(host, []).append(
            f'<asset-clip ref="{ids[sound["asset"]]}" lane="{lanes.get(role, -1)}" '
            f'offset="{tc(ins[host] + at - starts[host], True, clips[host]["asset"])}" '
            f'start="{tc(frames(sound["in"]), True, sound["asset"])}" duration="{tc(length, True)}" '
            f'name={quoteattr(a["name"])} audioRole="{ROLES.get(role, "effects")}">{volume}</asset-clip>')

    spine = []
    for n, clip in enumerate(clips):
        tr = clip.get("transition")
        if tr and n:
            dur = frames(tr["duration"])
            spine.append(f'<transition name="{CROSS_DISSOLVE[0]}" offset="{tc(starts[n] - dur // 2, True)}" '
                         f'duration="{tc(dur, True)}"><filter-video ref="fx-dissolve" name="{CROSS_DISSOLVE[0]}"/>'
                         f'<filter-audio ref="fx-crossfade" name="{AUDIO_CROSSFADE[0]}"/></transition>')
        a = assets[clip["asset"]]
        spine.append(f'<asset-clip ref="{ids[clip["asset"]]}" offset="{tc(starts[n], True)}" '
                     f'start="{tc(ins[n], True, clip["asset"])}" duration="{tc(lengths[n], True)}" name={quoteattr(a["name"])} '
                     f'tcFormat="{"DF" if ";" in (a.get("timecode") or "") else "NDF"}">{transform(clip, ins[n])}'
                     + (f'<adjust-volume amount="{clip["gain_db"]:+.1f}dB"/>' if clip.get("gain_db") else "")
                     + f"{''.join(attached.get(n, []))}</asset-clip>")

    rate = AUDIO_RATES.get(max((a["audio_rate"] for a in assets.values() if a["audio"]), default=48000), "48k")
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>\n'
            f'<fcpxml version="{FCPXML_VERSION}"><resources>{"".join(resources)}</resources>'
            f'<library><event name="Studio"><project name={quoteattr(name)}>'
            f'<sequence format="{seq_format}" duration="{tc(total, True)}" tcStart="0s" tcFormat="NDF" '
            f'audioLayout="stereo" audioRate="{rate}"><spine>{"".join(spine)}</spine></sequence>'
            f"</project></event></library></fcpxml>\n")

