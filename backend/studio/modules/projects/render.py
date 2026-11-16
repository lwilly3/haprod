"""
Rendu final de la vidéo longue : la timeline du montage (montage.py) en un .mp4, par ffmpeg.

Deux passes :
1. l'A-roll, morceau par morceau : une plage de la vidéo source ou d'un média inséré (ou deux, en fondu
   enchaîné autour d'une coupe), à son volume, recadrée par les zooms comme dans l'aperçu, encodée à part en qualité haute ;
   les morceaux sont recollés sans réencodage ;
2. par-dessus, le B-roll puis les motions (.mov avec transparence), puis les textes écrits à la main
   (dessinés par ffmpeg, dans la police de l'aperçu) : encodés une fois, par morceaux d'une minute coupés
   entre deux plans ; sous la voix, les sons et la musique, mixés à part sur toute la durée ; le tout recollé
   sans réencodage de l'image.

Tout tourne à la cadence de la vidéo source et les bornes des morceaux tombent sur des images :
rien ne glisse d'un morceau à l'autre.

  rendu/<qualité>.mp4      le dernier rendu de chaque qualité
  rendu/.tmp-<job>/        les morceaux et le mix, effacés à la fin
"""
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from fractions import Fraction
from pathlib import Path
from typing import Callable

from ...core import jobs
from ...core.system import h264, need_drawtext, tool
from ...core.tasks import TaskContext
from . import media, montage, service

RENDER_DIR = "rendu"
KIND = "project_long_render"
QUALITIES = {"1080p": (1920, 1080), "4k": (3840, 2160)}
AUDIO_RATE = 48000
# les matrices de couleur de la vidéo SD (ffprobe : color_space), converties en BT.709 comme le reste
BT601 = {"smpte170m", "bt470bg"}
# part de la première passe (A-roll) puis du mix des sons dans l'avancement
AROLL_SHARE = 0.5
MIX_SHARE = 0.05
# la passe finale par morceaux de cette durée (s), à peu près : chacun n'ouvre que les médias qui le concernent
CHUNK_SECONDS = 60
# ffmpeg arrêté s'il n'avance plus depuis ce temps (s) : un job en erreur plutôt qu'un job qui tourne à vide
STALL_SECONDS = 300
# ce que `ffmpeg -progress` écrit : tout le reste est un message d'erreur
# les textes : l'écriture manuscrite du système, celle de l'aperçu (font-family « Ink Free » sous Windows,
# « Bradley Hand » sous macOS), avec un contour noir (fraction de la taille du texte) et un fondu à l'entrée
# et à la sortie
TEXT_FONT = (Path("/System/Library/Fonts/Supplemental/Bradley Hand Bold.ttf") if sys.platform == "darwin"
             else Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "Inkfree.ttf")
TEXT_BORDER = 0.07
TEXT_FADE = 0.15
PROGRESS_KEYS = {"frame", "fps", "bitrate", "total_size", "out_time_us", "out_time_ms", "out_time",
                 "dup_frames", "drop_frames", "speed", "progress"}


def output_file(pid: str, quality: str) -> Path:
    return service.project_dir(pid) / RENDER_DIR / f"{quality}.mp4"


def _motion_files(pid: str, timeline: dict) -> tuple[dict[str, Path], list[str]]:
    """Le rendu de chaque motion, et ceux qui manquent."""
    found, missing = {}, []
    for m in timeline["motion"]:
        sig = montage.motion_signature(pid, m)
        file = montage.motion_render_file(pid, m["id"], sig) if sig else None
        if file and file.is_file():
            found[m["id"]] = file
        else:
            missing.append(m["title"] or m["id"])
    return found, missing


def signature(pid: str, quality: str) -> str:
    """Ce qui fait l'image et le son : un rendu fait sur la même signature est à jour."""
    timeline = montage.load(pid)
    motions, _ = _motion_files(pid, timeline)
    body = {k: timeline[k] for k in ("aroll", "zooms", "broll", "motion", "audio", "texts")}
    return hashlib.sha1(json.dumps([body, sorted(p.name for p in motions.values()), quality],
                                   sort_keys=True).encode()).hexdigest()[:12]


def plan(pid: str, quality: str) -> dict:
    """Le payload du job : tout ce que le worker doit savoir, chemins résolus."""
    if quality not in QUALITIES:
        raise ValueError(f"qualité inconnue : {quality}")
    project = service.load(pid)
    source = montage._source(project)
    if not source:
        raise ValueError("pas de vidéo source")
    timeline = montage.load(pid)
    if not timeline["aroll"]:
        raise ValueError("la timeline est vide")
    motions, missing = _motion_files(pid, timeline)
    if missing:
        raise ValueError(f"motion pas encore rendu : {', '.join(missing[:3])}{'…' if len(missing) > 3 else ''}"
                         " (le rendu se fait tout seul à l'étape Montage)")
    if any(x["text"].strip() for x in timeline["texts"]):
        need_drawtext()
    if any(x["text"].strip() for x in timeline["texts"]) and not TEXT_FONT.is_file():
        raise ValueError(f"police des textes introuvable : {TEXT_FONT}")
    info = media.probe(Path(source["path"]))
    base = service.project_dir(pid)
    width, height = QUALITIES[quality]
    source_length = info.get("duration") or source.get("duration") or 0.0

    def clip_media(c: dict) -> dict:
        """Le fichier d'un clip de l'A-roll : la vidéo source, ou le média inséré."""
        if not c.get("src"):
            return {"path": source["path"], "length": source_length, "audio": info.get("audio", True),
                    "colorspace": info.get("colorspace")}
        found = media.probe(base / c["src"])
        return {"path": str(base / c["src"]), "length": found.get("duration") or c["out"], "audio": found.get("audio", True),
                "colorspace": found.get("colorspace")}

    aroll = [{**c, **clip_media(c)} for c in timeline["aroll"]]
    ends = lambda x: {"enter": x.get("enter"), "exit": x.get("exit")}
    overlays = [{"path": str(base / b["src"]), "at": b["at"], "in": b["in"], "out": b["out"], "alpha": False,
                 "lane": "broll", "length": media.probe(base / b["src"]).get("duration") or 0.0, **ends(b)}
                for b in timeline["broll"]]
    # un motion n'a rien avant ni après sa composition : ses bords sont prolongés par son image
    overlays += [{"path": str(motions[m["id"]]), "at": m["at"], "in": 0.0, "out": m["dur"], "alpha": True,
                  "lane": "motion", "length": 0.0, **ends(m)}
                 for m in timeline["motion"]]
    sounds = [{"path": str(base / s["src"]), "at": s["at"], "in": s["in"], "out": s["out"], "gain_db": s["gain_db"]}
              for s in timeline["audio"]]
    return {"project": pid, "quality": quality, "width": width, "height": height,
            "fps_num": info.get("fps_num") or 25, "fps_den": info.get("fps_den") or 1,
            "source": {"path": source["path"], "duration": source_length, "audio": info.get("audio", True),
                       "colorspace": info.get("colorspace")},
            "aroll": aroll, "zooms": timeline["zooms"], "overlays": overlays, "sounds": sounds,
            "texts": [x for x in timeline["texts"] if x["text"].strip()], "font": str(TEXT_FONT),
            "dest": str(output_file(pid, quality)), "signature": signature(pid, quality)}


def last_job(project: dict) -> jobs.Job | None:
    return jobs.get(project["jobs"].get("long_render") or "")


def start(project: dict, quality: str) -> jobs.Job:
    payload = plan(project["id"], quality)
    current = last_job(project)
    if current and not current.finished:
        jobs.cancel(current)
    job = jobs.create(service.MODULE, KIND, payload, {})
    project["jobs"]["long_render"] = job.id
    return job


def view(project: dict, quality: str) -> dict:
    """L'état du rendu de la vidéo longue dans cette qualité."""
    pid = project["id"]
    job = last_job(project)
    timeline = montage.load(pid)
    source = montage._source(project)
    total = sum(c["out"] - c["in"] for c in timeline["aroll"])
    out = {"quality": quality, "size": QUALITIES.get(quality), "duration": total, "can_render": bool(source and total),
           "status": "none", "progress": 0.0, "stage": None, "error": None, "url": None, "current": False}
    if job and job.payload.get("quality") == quality:
        dest = Path(job.payload["dest"])
        out.update(status=job.status, progress=job.progress, stage=job.state.get("stage"), error=job.error)
        if job.status == "done" and dest.is_file():
            stamp = int(dest.stat().st_mtime)
            out["url"] = f"/api/projects/{pid}/rendu/long.mp4?quality={quality}&v={stamp}"
            out["rel"] = dest.relative_to(service.project_dir(pid)).as_posix()
            out["current"] = job.payload["signature"] == signature(pid, quality)
    elif output_file(pid, quality).is_file():
        # rendu d'une autre session : présent, mais rien ne dit qu'il est à jour
        dest = output_file(pid, quality)
        out.update(status="done", progress=1.0, url=f"/api/projects/{pid}/rendu/long.mp4?quality={quality}"
                   f"&v={int(dest.stat().st_mtime)}", rel=dest.relative_to(service.project_dir(pid)).as_posix())
    return out


# --- Les shorts ------------------------------------------------------------------------

def shorts(project: dict, selection_id: str | None = None) -> dict:
    """
    Les shorts de la sélection affichée (la dernière par défaut) : leur montage (étape Montage des
    shorts) et le dernier rendu de ce montage. Un short pas encore monté n'a rien à rendre.
    """
    from ..animations import service as animations
    from ..shorts import service as shorts_service

    tid = (project.get("source") or {}).get("transcript")
    found = [j for j in jobs.list_jobs(shorts_service.MODULE)
             if tid and j.kind == shorts_service.KIND and j.payload.get("transcript_job") == tid]
    selection = next((j for j in found if j.id == selection_id), found[-1] if found else None)
    if selection is None:
        return {"selection": None, "items": []}
    items = []
    for s in shorts_service.detail(selection)["shorts"]:
        montage_job = jobs.get(s["project"]) if s.get("project") else None
        item = {"id": s["id"], "title": s["title"], "duration": s["duration"], "montage": None,
                "size": None, "busy": False, "render": None}
        if montage_job:
            item.update(montage=montage_job.id, size=animations.size(montage_job), busy=not montage_job.finished,
                        render=animations.render_summary(animations.last_render(montage_job)))
        items.append(item)
    return {"selection": selection.id, "items": items}


def start_short(item: dict) -> None:
    """Lance le rendu d'un short monté."""
    from ..animations import service as animations

    render = item["render"]
    if not item["montage"]:
        raise ValueError("ce short n'est pas encore monté")
    if item["busy"]:
        raise ValueError("Claude retouche ce short : attends la fin de son tour")
    if render and render["status"] not in jobs.FINISHED:
        raise ValueError("un rendu de ce short est déjà en cours")
    animations.enqueue_render(jobs.get(item["montage"]))


def stop(project: dict, items: list[dict], target: str) -> None:
    """Arrête le rendu de la vidéo longue (`target` = "long") ou d'un short."""
    if target == "long":
        job = last_job(project)
    else:
        item = next((i for i in items if i["id"] == target), None)
        job = jobs.get(((item or {}).get("render") or {}).get("id") or "")
    if job and not job.finished:
        jobs.cancel(job)


# --- Les morceaux de l'A-roll -----------------------------------------------------------

def segments(aroll: list[dict], zooms: list[dict], fps: Fraction, source_duration: float) -> list[dict]:
    """
    Découpe l'A-roll en morceaux, bornes en images de la timeline :
    {start, end, clip: index du clip, src: début dans son média, fade: début de la plage entrante (transition) | None,
     clip_b: index du clip entrant, fx: la transition (xfade), cut: la coupe (images depuis start),
     held: un côté tient son image de bord, zoom: bool}.

    Une transition est centrée sur la coupe et mange la marge de part et d'autre (comme dans Resolve), au plus
    la moitié de chaque clip. Un côté sans assez de marge (un clip inséré utilisé en entier, le début ou la fin de
    la source) tient sa première ou sa dernière image ; le son coupe alors net à la coupe (L-cut).
    """
    def frame(t: float) -> int:
        return round(t * fps)

    starts, cursor = [], 0.0
    for c in aroll:
        starts.append(cursor)
        cursor += c["out"] - c["in"]
    total = frame(cursor)
    cuts = [frame(s) for s in starts]

    windows = {}  # début de la transition -> (fin, clip entrant)
    for i in range(1, len(aroll)):
        tr = aroll[i].get("transition")
        prev, cur = aroll[i - 1], aroll[i]
        if not tr:
            continue
        half = min(tr["dur"] / 2, (prev["out"] - prev["in"]) / 2, (cur["out"] - cur["in"]) / 2)
        n = int(half * fps)
        if n >= 1:
            windows[cuts[i] - n] = (cuts[i] + n, i)

    def inside_window(f: int) -> bool:
        return any(a < f < b for a, (b, _) in windows.items())

    bounds = {0, total, *cuts}
    for a, (b, _) in windows.items():
        bounds |= {a, b}
    for z in zooms:
        bounds |= {frame(z["at"]), frame(z["at"] + z["dur"])}
    edges = sorted(f for f in bounds if 0 <= f <= total and not inside_window(f))

    def clip_at(f: int) -> int:
        return max(i for i, c in enumerate(cuts) if c <= f)

    out = []
    for a, b in zip(edges, edges[1:]):
        if b <= a:
            continue
        zoomed = any(frame(z["at"]) < b and frame(z["at"] + z["dur"]) > a for z in zooms)
        if a in windows and windows[a][0] == b:
            i = windows[a][1]
            prev, cur = aroll[i - 1], aroll[i]
            reach = float(Fraction(cuts[i] - a) / fps)
            held = (prev.get("length", source_duration) - prev["out"] < reach - 1e-3) or cur["in"] < reach - 1e-3
            out.append({"start": a, "end": b, "zoom": zoomed, "fx": cur["transition"]["fx"], "clip": i - 1, "clip_b": i,
                        "cut": cuts[i] - a, "held": held,
                        "src": float(prev["in"] + (Fraction(a) / fps - Fraction(starts[i - 1]))),
                        "fade": float(cur["in"] + (Fraction(a) / fps - Fraction(starts[i])))})
        else:
            j = clip_at(a)
            out.append({"start": a, "end": b, "zoom": zoomed, "fade": None, "clip": j,
                        "src": float(aroll[j]["in"] + (Fraction(a) / fps - Fraction(starts[j])))})
    return out


def _num(x: float) -> str:
    return f"{x:.6f}".rstrip("0").rstrip(".") or "0"


def zoom_filter(zooms: list[dict], start: int, end: int, fps: Fraction) -> str:
    """
    Le recadrage des zooms qui touchent les images [start, end[ (perspective, image par image), comme
    l'aperçu : l'image est agrandie de `scale` autour de son centre puis décalée de −x, −y (en fraction
    de l'image), selon la courbe de son style (montage.zoom_amount). Le cadre reste dans l'image.
    """
    # `in` compte les images à partir de 1 dans perspective
    t = f"((in-1+{start})*{fps.denominator}/{fps.numerator})"
    first, last = float(Fraction(start) / fps), float(Fraction(end) / fps)
    k_terms = []
    for z in zooms:
        a, b = z["at"], z["at"] + z["dur"]
        if b <= first or a >= last:
            continue
        rise, fall = montage.zoom_ramps(z)
        terms = [*([f"({t}-{_num(a)})/{_num(rise)}"] if rise else []), *([f"({_num(b)}-{t})/{_num(fall)}"] if fall else [])]
        inside = f"gte({t},{_num(a)})*lt({t},{_num(b)})"
        if not terms:
            k = inside
        else:
            ramp = f"clip({terms[0] if len(terms) == 1 else f'min({terms[0]},{terms[1]})'},0,1)"
            # smooth : adouci (smoothstep) ; slow : vitesse constante
            k = f"{inside}*{ramp}" if z.get("style") == "slow" else f"{inside}*{ramp}*{ramp}*(3-2*{ramp})"
        k_terms.append((z, k))
    s = "+".join(f"{_num(z['scale'] - 1)}*{k}" for z, k in k_terms) or "0"
    x = "+".join(f"{_num(z['x'])}*{k}" for z, k in k_terms) or "0"
    y = "+".join(f"{_num(z['y'])}*{k}" for z, k in k_terms) or "0"
    scale = f"(1+{s})"
    cw, ch = f"(W/{scale})", f"(H/{scale})"
    cx = f"clip(W/2+({x})*W/{scale},{cw}/2,W-{cw}/2)"
    cy = f"clip(H/2+({y})*H/{scale},{ch}/2,H-{ch}/2)"
    left, right = f"{cx}-{cw}/2", f"{cx}+{cw}/2"
    top, bottom = f"{cy}-{ch}/2", f"{cy}+{ch}/2"
    corners = {"x0": left, "y0": top, "x1": right, "y1": top, "x2": left, "y2": bottom, "x3": right, "y3": bottom}
    return "perspective=" + ":".join(f"{k}='{v}'" for k, v in corners.items()) + ":interpolation=cubic:eval=frame"


def _samples(frames: int, fps: Fraction) -> int:
    return round(frames * AUDIO_RATE / fps)


def segment_args(p: dict, seg: dict, dest: Path) -> list[str]:
    fps = Fraction(p["fps_num"], p["fps_den"])
    rate = f"{p['fps_num']}/{p['fps_den']}"
    w, h = p["width"], p["height"]
    n = seg["end"] - seg["start"]
    samples = _samples(seg["end"], fps) - _samples(seg["start"], fps)
    length = n / fps
    # le fichier de chaque clip (un rendu d'avant les clips insérés : la vidéo source)
    src = p["source"]
    clip_a = {**src, **p["aroll"][seg.get("clip", 0)]} if p["aroll"] else src
    clip_b = {**src, **p["aroll"][seg["clip_b"]]} if seg.get("clip_b") is not None else clip_a
    # un peu plus que nécessaire : le compte exact est fait par trim
    read = f"{float(length) + 0.5:.3f}"
    args = [tool("ffmpeg"), "-y", "-v", "error", "-nostats", "-progress", "pipe:1",
            "-ss", f"{seg['src']:.6f}", "-t", read, "-i", clip_a["path"]]
    # le clip entrant sans assez de marge avant : sa première image tenue jusqu'à son début
    lead = max(0.0, -seg["fade"]) if seg["fade"] is not None else 0.0
    if seg["fade"] is not None:
        args += ["-ss", f"{max(0.0, seg['fade']):.6f}", "-t", read, "-i", clip_b["path"]]
    if seg.get("held"):
        # son coupé à la coupe : le son du clip entrant lu depuis son point d'entrée
        args += ["-ss", f"{clip_b['in']:.6f}", "-t", read, "-i", clip_b["path"]]

    def prep(clip: dict, lead: float = 0.0) -> str:
        """
        Une entrée à la cadence et en couleurs BT.709 (un clip SD inséré est en BT.601) : un A-roll aux
        propriétés uniformes, sinon ffmpeg réinitialise ses filtres en cours de passe finale et y perd des images.
        """
        convert = ("scale=iw:ih:in_color_matrix=bt601:out_color_matrix=bt709:out_range=tv,"
                   if clip.get("colorspace") in BT601 else "")
        # `lead` : la première image tenue avant le début ; la dernière est tenue après la fin du fichier (une
        # transition qui déborde d'un clip sans marge)
        hold = f"tpad=start_mode=clone:start_duration={lead:.6f}," if lead > 0 else ""
        # ramené à 0 avant la cadence : après la recherche dans la source, la première image arrive un peu après 0,
        # fps la placerait une image plus loin, et le recollage laisserait un trou d'une image dans l'A-roll
        return (f"setpts=PTS-STARTPTS,fps={rate},{convert}"
                f"setparams=colorspace=bt709:color_primaries=bt709:color_trc=bt709:range=tv,"
                f"setsar=1,format=yuv420p,{hold}tpad=stop_mode=clone:stop_duration={float(length) + 0.5:.3f},"
                f"trim=end_frame={n}")

    fit = (f"scale={w}:{h}:force_original_aspect_ratio=decrease:flags=lanczos,"
           f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p")
    zoom = (zoom_filter(p["zooms"], seg["start"], seg["end"], fps) + ",") if seg["zoom"] else ""
    sound = f"aresample={AUDIO_RATE},aformat=sample_fmts=s16:channel_layouts=stereo,apad,atrim=end_sample={samples}"

    def voice(n: int, clip: dict, label: str, count: int = samples, after: str = "") -> str:
        """Le son d'une entrée, à son volume, sur `count` échantillons ; du silence si le fichier n'en a pas."""
        if not clip.get("audio", True):
            return f"anullsrc=r={AUDIO_RATE}:cl=stereo,atrim=end_sample={count}{after}[{label}]"
        gain = f"volume={clip['gain_db']}dB," if clip.get("gain_db") else ""
        return (f"[{n}:a]{gain}aresample={AUDIO_RATE},aformat=sample_fmts=s16:channel_layouts=stereo,apad,"
                f"atrim=end_sample={count}{after}[{label}]")

    if seg["fade"] is None:
        graph = [f"[0:v]{prep(clip_a)},{zoom}{fit}[v]", voice(0, clip_a, "a")]
    else:
        graph = [f"[0:v]{prep(clip_a)}[va]", f"[1:v]{prep(clip_b, lead)}[vb]",
                 f"[va][vb]xfade=transition={seg['fx']}:duration={float(length):.6f}:offset=0,{zoom}{fit}[v]"]
        if seg.get("held"):
            # une image tenue d'un côté : le son coupe net à la coupe (L-cut), un fondu de 10 ms contre le clic
            before = _samples(seg["start"] + seg["cut"], fps) - _samples(seg["start"], fps)
            edge = min(AUDIO_RATE // 100, before, samples - before)
            graph += [voice(0, clip_a, "aa", before, f",afade=t=out:start_sample={before - edge}:nb_samples={edge}"),
                      voice(2, clip_b, "ab", samples - before, f",afade=t=in:nb_samples={edge}"),
                      "[aa][ab]concat=n=2:v=0:a=1[a]"]
        else:
            graph += [voice(0, clip_a, "aa"), voice(1, clip_b, "ab"),
                      f"[aa][ab]acrossfade=ns={samples}:c1=tri:c2=tri,{sound}[a]"]
    script = dest.with_suffix(".txt")
    script.write_text(";\n".join(graph), encoding="utf-8")
    return args + ["-filter_complex_script", str(script), "-map", "[v]", "-map", "[a]", "-frames:v", str(n),
                   *h264(12, "veryfast"), "-pix_fmt", "yuv420p",
                   "-c:a", "pcm_s16le", str(dest)]


def overlay_groups(overlays: list[dict], fps: Fraction) -> list[list[dict]]:
    """
    Les plans posés par-dessus l'A-roll, en groupes qui s'enchaînent : un plan collé au précédent de la même
    piste (à une image près) et qui a une entrée s'enchaîne avec lui, la transition centrée sur la coupe (le
    plan d'avant est prolongé d'une demi-transition, celui d'après commence une demi-transition plus tôt).
    Chaque plan reçoit `pre` / `post` (s, prolongations), `join` (la transition avec le précédent du groupe),
    `enter` / `exit` (depuis ou vers ce qui est dessous, au bord du groupe). Durées ramenées à des images
    entières et à ce que les plans permettent. Le B-roll d'abord, les motions au-dessus.
    """
    def frames(t: float) -> float:
        return round(t * fps) / fps

    groups: list[list[dict]] = []
    for lane in ("broll", "motion"):
        items = sorted((o for o in overlays if o.get("lane", "motion" if o["alpha"] else "broll") == lane),
                       key=lambda o: o["at"])
        prev = None
        for o in items:
            o = {**o, "len": o["out"] - o["in"], "pre": 0.0, "post": 0.0, "join": None}
            enter = o.get("enter")
            if prev and enter and abs(o["at"] - (prev["at"] + prev["len"])) <= 1.5 / fps:
                d = frames(min(enter["dur"], o["len"], prev["len"]) / 2) * 2
                if d > 0:
                    o["join"] = {"fx": enter["fx"], "dur": float(d)}
                    o["pre"] = float(d / 2)
                    prev["post"] = float(o["at"] + d / 2 - (prev["at"] + prev["len"]))
                    groups[-1].append(o)
                    prev = o
                    continue
            groups.append([o])
            prev = o
    for group in groups:
        first, last = group[0], group[-1]
        for key, item in (("enter", first), ("exit", last)):
            tr = item.get(key)
            d = frames(min(tr["dur"], item["len"] / 2)) if tr else 0
            item[key] = {"fx": tr["fx"], "dur": float(d)} if d > 0 else None
        for o in group:
            if o is not first:
                o["enter"] = None
            if o is not last:
                o["exit"] = None
    return groups


def _group_span(group: list[dict]) -> tuple[float, float]:
    """Le temps qu'occupe un groupe de plans sur la timeline, prolongations comprises."""
    return group[0]["at"] - group[0]["pre"], max(o["at"] + o["len"] + o["post"] for o in group)


def chunks(p: dict, total: int) -> list[tuple[int, int]]:
    """
    La passe finale en morceaux d'environ CHUNK_SECONDS, bornes en images de la timeline, coupés là où rien
    n'est posé sur l'A-roll (ni plan, ni texte) : chaque morceau n'ouvre que les quelques médias qui le
    concernent. En un seul bloc, des centaines d'entrées font gonfler ffmpeg jusqu'à se bloquer.
    """
    fps = Fraction(p["fps_num"], p["fps_den"])
    spans = [_group_span(g) for g in overlay_groups(p["overlays"], fps)]
    spans += [(x["at"], x["at"] + x["dur"]) for x in p.get("texts") or []]
    # une image de marge de part et d'autre : une coupe tombe au plus près sur le bord d'un plan
    busy = sorted((math.floor(a * fps) - 1, math.ceil(b * fps) + 1) for a, b in spans)
    size = round(CHUNK_SECONDS * fps)
    out, start = [], 0
    while start < total:
        cut = start + size
        for a, b in busy:
            if a < cut < b:
                cut = b
        if total - cut < size / 2:
            cut = total
        out.append((start, cut))
        start = cut
    return out


def chunk_args(p: dict, aroll: Path, span: tuple[int, int], dest: Path, script: Path) -> list[str]:
    """
    Un morceau de la passe finale : le B-roll, les motions et les textes par-dessus l'A-roll, sans le son
    (mixé à part, sur toute la durée : mix_args).
    """
    fps = Fraction(p["fps_num"], p["fps_den"])
    rate = f"{p['fps_num']}/{p['fps_den']}"
    w, h = p["width"], p["height"]
    first, last = span
    t0, frames = float(first / fps), last - first
    # lu un peu avant, puis coupé à la demi-image près : l'A-roll est horodaté à la milliseconde
    seek = max(0.0, t0 - 1)
    lo, hi = float((first - Fraction(1, 2)) / fps) - seek, float((last - Fraction(1, 2)) / fps) - seek
    args = [tool("ffmpeg"), "-y", "-v", "error", "-nostats", "-progress", "pipe:1",
            "-ss", f"{seek:.6f}", "-t", f"{hi + 1:.6f}", "-reinit_filter", "0", "-i", str(aroll)]
    # puis recalé sur la cadence exacte : des horodatages arrondis font perdre une image à l'encodage
    graph = [f"[0:v]trim=start={max(lo, 0):.6f}:end={hi:.6f},setpts=N*{p['fps_den']}/{p['fps_num']}/TB[base]"]
    video = "[base]"
    index = 1
    # xfade veut deux entrées de même format, même cadence, même base de temps
    norm = f"settb=expr={p['fps_den']}/{p['fps_num']},fps={rate}"
    clear = 0

    def transparent(d: float) -> str:
        nonlocal clear
        clear += 1
        graph.append(f"color=c=black@0:s={w}x{h}:r={rate}:d={d + 1:.6f},format=yuva420p,"
                     f"trim=duration={d:.6f},setpts=PTS-STARTPTS,{norm}[c{clear}]")
        return f"[c{clear}]"

    for g, group in enumerate(overlay_groups(p["overlays"], fps)):
        if not first <= round(_group_span(group)[0] * fps) < last:
            continue
        group = [{**o, "at": o["at"] - t0} for o in group if media.probe(Path(o["path"])).get("width")]
        if not group:
            continue
        plain = len(group) == 1 and not group[0]["enter"] and not group[0]["exit"]
        stream, length, start = "", 0.0, group[0]["at"] - group[0]["pre"]
        for o in group:
            # ce qu'il y a vraiment dans le média avant et après le plan ; le reste : sa première / dernière image
            before = min(o["pre"], o["in"]) if o["lane"] == "broll" else 0.0
            after = max(0.0, min(o["post"], o["length"] - o["out"])) if o["length"] else 0.0
            total = o["pre"] + o["len"] + o["post"]
            args += ["-threads", "2", "-ss", f"{o['in'] - before:.6f}", "-t", f"{before + o['len'] + after:.6f}",
                     "-i", o["path"]]
            fit = (f"scale={w}:{h}" if o["alpha"] else
                   f"scale={w}:{h}:force_original_aspect_ratio=increase:flags=lanczos,crop={w}:{h}")
            if plain:
                fmt = "yuva420p" if o["alpha"] else "yuv420p"
                graph.append(f"[{index}:v]fps={rate},{fit},format={fmt},setsar=1,"
                             f"setpts=PTS-STARTPTS+{o['at']:.6f}/TB[o{g}]")
            else:
                graph.append(f"[{index}:v]fps={rate},{fit},format=yuva420p,setsar=1,"
                             f"tpad=start_duration={o['pre'] - before:.6f}:start_mode=clone:"
                             f"stop_duration={o['post'] - after + 1:.6f}:stop_mode=clone,"
                             f"trim=duration={total:.6f},setpts=PTS-STARTPTS,{norm}[i{index}]")
                if not stream:
                    stream, length = f"[i{index}]", total
                else:
                    offset = o["at"] - o["pre"] - start
                    graph.append(f"{stream}[i{index}]xfade=transition={o['join']['fx']}:"
                                 f"duration={o['join']['dur']:.6f}:offset={offset:.6f}[x{index}]")
                    stream, length = f"[x{index}]", offset + total
            index += 1
        if not plain:
            head, tail = group[0], group[-1]
            if head["enter"]:
                d = head["enter"]["dur"]
                graph.append(f"{transparent(d)}{stream}xfade=transition={head['enter']['fx']}:"
                             f"duration={d:.6f}:offset=0[e{g}]")
                stream = f"[e{g}]"
            if tail["exit"]:
                d = tail["exit"]["dur"]
                graph.append(f"{stream}{transparent(d)}xfade=transition={tail['exit']['fx']}:"
                             f"duration={d:.6f}:offset={length - d:.6f}[q{g}]")
                stream = f"[q{g}]"
            graph.append(f"{stream}setpts=PTS-STARTPTS+{start:.6f}/TB[o{g}]")
        graph.append(f"{video}[o{g}]overlay=eof_action=pass:format=auto[v{g}]")
        video = f"[v{g}]"
    for n, x in enumerate(p.get("texts") or []):
        if not first <= round(x["at"] * fps) < last:
            continue
        graph.append(text_layer({**x, "at": x["at"] - t0}, n, w, h, rate, p["font"], script.parent))
        # le texte est dessiné au centre d'un calque transparent de la taille de l'image, qu'on décale à sa place
        graph.append(f"{video}[t{n}]overlay=x={round((x['x'] - 0.5) * w)}:y={round((x['y'] - 0.5) * h)}:"
                     f"eof_action=pass:format=auto[w{n}]")
        video = f"[w{n}]"
    graph.append(f"{video}format=yuv420p[vout]")
    script.write_text(";\n".join(graph), encoding="utf-8")
    return args + ["-filter_complex_script", str(script), "-map", "[vout]", "-frames:v", str(frames), "-r", rate,
                   *h264(18, "medium"), "-pix_fmt", "yuv420p", str(dest)]


def mix_args(p: dict, aroll: Path, dest: Path, script: Path) -> list[str]:
    """Les sons et la musique sous la voix de l'A-roll, sur toute la durée, en une passe (audio seul : rapide)."""
    args = [tool("ffmpeg"), "-y", "-v", "error", "-nostats", "-progress", "pipe:1", "-i", str(aroll)]
    graph, sounds, index = [], ["[0:a]"], 1
    # un fichier son n'est ouvert qu'une fois, puis découpé dans le graphe : un même whoosh placé des dizaines de
    # fois ferait sinon autant d'entrées, et la ligne de commande dépasserait la limite de Windows (32 767 caractères)
    uses: dict[str, list[dict]] = {}
    for s in p["sounds"]:
        uses.setdefault(s["path"], []).append(s)
    for path, group in uses.items():
        if not media.probe(Path(path)).get("audio"):
            continue
        args += ["-i", path]
        sources = [f"[{index}:a]"]
        if len(group) > 1:
            sources = [f"[a{index}k{k}]" for k in range(len(group))]
            graph.append(f"[{index}:a]asplit={len(group)}{''.join(sources)}")
        for source, s in zip(sources, group):
            label = f"[s{len(sounds)}]"
            graph.append(f"{source}atrim=start={s['in']:.6f}:duration={s['out'] - s['in']:.6f},asetpts=PTS-STARTPTS,"
                         f"aresample={AUDIO_RATE},aformat=sample_fmts=fltp:channel_layouts=stereo,"
                         f"volume={s['gain_db']}dB,adelay=delays={round(s['at'] * 1000)}:all=1{label}")
            sounds.append(label)
        index += 1
    if len(sounds) > 1:
        graph.append(f"{''.join(sounds)}amix=inputs={len(sounds)}:duration=first:normalize=0:dropout_transition=0[aout]")
    else:
        graph.append("[0:a]anull[aout]")
    script.write_text(";\n".join(graph), encoding="utf-8")
    # en flottant : ce qui dépasse 0 dB n'est écrêté qu'à l'encodage final
    return args + ["-filter_complex_script", str(script), "-map", "[aout]", "-c:a", "pcm_f32le",
                   "-ar", str(AUDIO_RATE), str(dest)]


def mux_args(listing: Path, mix: Path, dest: Path) -> list[str]:
    """Les morceaux recollés sans réencodage, avec le son mixé : le .mp4 final."""
    return [tool("ffmpeg"), "-y", "-v", "error", "-nostats", "-progress", "pipe:1",
            "-f", "concat", "-safe", "0", "-i", str(listing), "-i", str(mix), "-map", "0:v", "-map", "1:a",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "320k", "-ar", str(AUDIO_RATE), "-movflags", "+faststart",
            str(dest)]


def _filter_path(path: Path) -> str:
    """Un chemin de fichier en option de filtre ffmpeg : échappé pour les options, puis pour le graphe."""
    value = re.sub(r"([\\:'])", r"\\\1", path.as_posix())
    return re.sub(r"([\\'\[\],;])", r"\\\1", value)


def text_layer(x: dict, n: int, w: int, h: int, rate: str, font: str, folder: Path) -> str:
    """
    Un texte écrit à la main, comme dans l'aperçu : centré (lignes comprises) sur un calque transparent de la taille
    de l'image, incliné autour de son centre, avec un fondu, placé à son instant. Le texte passe par un fichier
    (rien à échapper, et `expansion=none` : un « % » reste un « % »).
    """
    file = folder / f"text-{n}.txt"
    # en octets : write_text écrirait des fins de ligne Windows, dont drawtext ferait une ligne vide de plus
    file.write_bytes(x["text"].encode("utf-8"))
    size = max(8, round(x["size"] * h))
    fade = min(TEXT_FADE, x["dur"] / 3)
    return (f"color=c=black@0:s={w}x{h}:r={rate}:d={x['dur']:.6f},format=rgba,"
            f"drawtext=fontfile={_filter_path(Path(font))}:textfile={_filter_path(file)}:expansion=none:"
            f"fontsize={size}:fontcolor=0x{x['color'].lstrip('#')}:borderw={max(1, round(size * TEXT_BORDER))}:"
            f"bordercolor=0x000000:text_align=C:x=(w-text_w)/2:y=(h-text_h)/2,"
            f"rotate={x['angle']}*PI/180:c=none,"
            f"fade=t=in:st=0:d={fade:.6f}:alpha=1,fade=t=out:st={x['dur'] - fade:.6f}:d={fade:.6f}:alpha=1,"
            f"setpts=PTS-STARTPTS+{x['at']:.6f}/TB[t{n}]")


def _run(args: list[str], on_time: Callable[[float], None], check_cancel: Callable[[], None]) -> None:
    """
    ffmpeg avec son avancement (-progress) ; arrêté net si le job est annulé, ou s'il n'avance plus depuis
    STALL_SECONDS (il continue d'écrire son avancement, figé : on surveille le temps produit).
    """
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace")
    tail: list[str] = []
    moved = time.monotonic()
    stalled = threading.Event()

    def watch() -> None:
        while proc.poll() is None:
            if time.monotonic() - moved > STALL_SECONDS:
                stalled.set()
                proc.kill()
                return
            time.sleep(5)

    threading.Thread(target=watch, daemon=True).start()
    try:
        done = -1
        for line in proc.stdout:
            check_cancel()
            line = line.strip()
            key, _, value = line.partition("=")
            if key == "out_time_us" and value.isdigit():
                if int(value) > done:
                    done, moved = int(value), time.monotonic()
                on_time(int(value) / 1e6)
            elif line and key not in PROGRESS_KEYS and not key.startswith("stream_"):
                # le reste : les messages d'erreur de ffmpeg
                tail = (tail + [line])[-10:]
        if stalled.is_set():
            raise RuntimeError(f"ffmpeg n'avance plus depuis {STALL_SECONDS // 60} min : arrêté")
        if proc.wait() != 0:
            raise RuntimeError("ffmpeg : " + " | ".join(tail)[-400:])
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


def _listing(path: Path, files: list[Path]) -> Path:
    """La liste des morceaux à recoller, pour le démuxeur concat de ffmpeg."""
    path.write_text("".join(f"file '{f.as_posix()}'\n" for f in files), encoding="utf-8")
    return path


def run(ctx: TaskContext) -> None:
    p = ctx.payload
    fps = Fraction(p["fps_num"], p["fps_den"])
    dest = Path(p["dest"])
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.parent / f".tmp-{ctx.job.id}"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir()
    try:
        parts = segments(p["aroll"], p["zooms"], fps, p["source"]["duration"])
        total = parts[-1]["end"] if parts else 0
        if not total:
            raise RuntimeError("la timeline est vide")
        duration = float(total / fps)

        def progress(value: float, stage: str) -> None:
            ctx.progress = value
            ctx.state["stage"] = stage
            ctx.save()

        ctx.set_status("rendering")
        files = []
        for i, seg in enumerate(parts):
            file = tmp / f"{i:04d}.mkv"
            done = seg["start"] / fps

            def on_time(t: float, done=done) -> None:
                progress(min(float(done) + t, duration) / duration * AROLL_SHARE, f"A-roll · morceau {i + 1}/{len(parts)}")

            _run(segment_args(p, seg, file), on_time, ctx.check_cancel)
            files.append(file)
        listing = _listing(tmp / "aroll.txt", files)
        aroll = tmp / "aroll.mkv"
        progress(AROLL_SHARE, "assemblage de l'A-roll")
        _run([tool("ffmpeg"), "-y", "-v", "error", "-nostats", "-progress", "pipe:1", "-f", "concat", "-safe", "0",
              "-i", str(listing), "-c", "copy", str(aroll)], lambda t: None, ctx.check_cancel)
        mix = tmp / "mix.wav"
        _run(mix_args(p, aroll, mix, tmp / "mix.txt"),
             lambda t: progress(AROLL_SHARE + min(t / duration, 1.0) * MIX_SHARE, "mix des sons"), ctx.check_cancel)
        parts = chunks(p, total)
        done_share = AROLL_SHARE + MIX_SHARE
        files = []
        for i, span in enumerate(parts):
            file = tmp / f"final-{i:04d}.mkv"
            done = span[0] / fps

            def on_time(t: float, done=done) -> None:
                progress(done_share + min(float(done) + t, duration) / duration * (1 - done_share),
                         f"B-roll, motions et textes · morceau {i + 1}/{len(parts)}")

            _run(chunk_args(p, aroll, span, file, tmp / f"final-{i:04d}.txt"), on_time, ctx.check_cancel)
            files.append(file)
        partial = tmp / "final.mp4"
        progress(0.99, "assemblage final")
        _run(mux_args(_listing(tmp / "final.txt", files), mix, partial), lambda t: None, ctx.check_cancel)
        partial.replace(dest)
        ctx.state["stage"] = "terminé"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
