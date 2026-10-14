"""
Le script d'un projet : script/script.json en est la source.

  blocks    les blocs du texte dans l'ordre (paragraphe, titre, citation, liste…) :
            {id, md}, `md` étant le Markdown du bloc ; l'id ne change pas quand on retouche le texte
  plans     les plans rattachés aux blocs (voir new_plan) ; `block` vaut None quand le bloc a disparu
  setups    les configurations de tournage (cadre, lieu, lumière) : {id, name, note}, A, B, C… dans l'ordre
  sections  le setup de chaque section : {id du bloc titre: id du setup}
  md_hash   l'empreinte du script.md écrit au dernier enregistrement
  draft     la version du script (V1, V2…) : {id, name, created}

Les versions : on repart d'une copie du script (V2) sans perdre l'ancienne (V1). Seule la version
active est dans script.json et script.md, que tout le reste lit ; les autres attendent, complètes
(texte, plans, setups), dans script/drafts/<id>.json. Changer de version, c'est échanger les fichiers.

Un plan : {id, block, end, q, type, frame, setup, note, media, on, by}
  block     le bloc où commence le passage qu'il illustre, `end` celui où il finit (None : le même)
  q         le texte exact du passage, blocs séparés par une ligne vide ("" : tout le bloc)
  type      un de PLAN_TYPES ; frame, le cadrage, pour ce qui se filme
  setup     le setup où il se tourne ("" : celui de sa section, pour un face caméra)
  media     les fichiers qui lui sont associés : [{url, name, kind, duration}]
  on        tourné / trouvé
  by        "claude" quand il vient d'une ligne [VISUEL : …] du script

script.md n'en est que la vue Markdown, réécrite à chaque enregistrement : c'est lui que Claude
lit et réécrit, que le dérush compare aux rushes et qu'on exporte. Quand il a changé sans passer
par ici (Claude, édition à la main, projet d'avant script.json), `load` recale les blocs dessus :
un paragraphe inchangé ou retouché garde son id, et ses plans avec.

Claude écrit ses intentions de plan en lignes [VISUEL : Type — description], juste avant le
paragraphe qu'elles illustrent : au recalage, elles deviennent des plans de ce paragraphe et
quittent le texte.

Filet de sécurité (studio/data n'est pas versionné) : un script non vide n'est jamais remplacé
par un script vide, et script/versions/ garde des copies tournantes du texte (voir _snapshot).
"""
import hashlib
import json
import re
import threading
import time
import uuid
from difflib import SequenceMatcher

from . import service

JSON_FILE = "script.json"
VERSIONS_DIR = "versions"
DRAFTS_DIR = "drafts"
# une copie au plus toutes les 10 minutes pendant l'édition, les 50 dernières gardées
VERSION_EVERY = 10 * 60
VERSION_KEEP = 50
# un texte qui perd plus de la moitié de sa longueur d'un coup est copié quoi qu'il arrive
VERSION_SHRINK = 0.5
# en dessous, un paragraphe réécrit est considéré comme un nouveau paragraphe
SIMILAR = 0.5

PLAN_TYPES = ("Face caméra", "B-roll", "Écran", "Image", "Animation", "Texte à l'écran", "Son", "Insert",
              "Plan de coupe")
_CUE = re.compile(r"^\[\s*VISUELS?\s*:\s*(.+?)\s*\]$", re.IGNORECASE | re.DOTALL)
_CUE_SPLIT = re.compile(r"\s+[—–-]\s+|\s*:\s+")
# quand Claude n'a pas donné le type : des mots qui le trahissent, dans l'ordre
_GUESS = (("Face caméra", ("face caméra", "face cam", "plateau")),
          ("Texte à l'écran", ("texte à l'écran", "titre", "incrustation", "à l'écran «")),
          ("Animation", ("schéma", "animation", "animé", "carte", "graphique", "courbe", "infographie", "chronologie")),
          ("Écran", ("capture", "screencast", "page web", "site", "interface", "tweet", "article")),
          ("Image", ("photo", "logo", "image", "portrait", "affiche", "couverture")),
          ("Son", ("musique", "bruitage", "jingle", "son de", "son d'")))

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock(pid: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(pid, threading.Lock())


def new_id() -> str:
    return "b" + uuid.uuid4().hex[:8]


def _hash(md: str) -> str:
    return hashlib.sha1(md.encode("utf-8")).hexdigest()


def split(md: str) -> list[str]:
    """Les blocs d'un texte Markdown : ce qui est séparé par une ligne vide."""
    blocks, current = [], []
    for line in md.replace("\r\n", "\n").split("\n"):
        if line.strip():
            current.append(line)
        elif current:
            blocks.append("\n".join(current))
            current = []
    if current:
        blocks.append("\n".join(current))
    return blocks


def render(blocks: list[dict]) -> str:
    text = "\n\n".join(b["md"] for b in blocks if b["md"].strip())
    return text + "\n" if text else ""


def _similarity(a: str, b: str) -> float:
    m = SequenceMatcher(None, a, b, autojunk=False)
    return m.ratio() if m.real_quick_ratio() >= SIMILAR and m.quick_ratio() >= SIMILAR else 0.0


def reconcile(old: list[dict], parts: list[str]) -> list[dict]:
    """Les blocs de `parts` (le nouveau texte), avec l'id du bloc d'avant qui leur correspond."""
    matcher = SequenceMatcher(None, [b["md"] for b in old], parts, autojunk=False)
    out = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            out += [{"id": old[i]["id"], "md": parts[j]} for i, j in zip(range(i1, i2), range(j1, j2))]
            continue
        # passage retouché : chaque nouveau bloc reprend l'id de l'ancien qui lui ressemble le plus
        pool = old[i1:i2]
        for j in range(j1, j2):
            scored = [(_similarity(b["md"], parts[j]), b) for b in pool]
            score, best = max(scored, key=lambda s: s[0], default=(0.0, None))
            if best and score >= SIMILAR:
                pool.remove(best)
                out.append({"id": best["id"], "md": parts[j]})
            else:
                out.append({"id": new_id(), "md": parts[j]})
    return out


# --- Plans ---------------------------------------------------------------------------------

def new_plan(block: str | None, type_: str, note: str = "", **extra) -> dict:
    return {"id": "p" + uuid.uuid4().hex[:8], "block": block, "end": None, "q": "", "type": type_, "frame": "",
            "setup": "", "note": note, "media": [], "on": False, **extra}


def _detach(data: dict) -> None:
    """Les plans dont le bloc a disparu restent, sans bloc : l'interface propose de les rattacher.
    Ceux que Claude avait proposés et que personne n'a complétés disparaissent avec leur bloc."""
    ids = {b["id"] for b in data["blocks"]}
    kept = []
    for plan in data["plans"]:
        if plan.get("block") not in ids:
            if plan.get("by") == "claude" and not plan.get("media") and not plan.get("on"):
                continue
            plan["block"] = None
        if plan.get("end") not in ids:
            # la fin du passage a disparu : le plan se replie sur son premier bloc
            plan["end"] = None
        kept.append(plan)
    data["plans"] = kept


def guess_type(text: str) -> str:
    low = text.lower()
    return next((t for t, words in _GUESS if any(w in low for w in words)), "B-roll")


def cue_plan(text: str) -> tuple[str, str]:
    """(type, description) d'une indication « Type — description » ; sans type reconnu, on le devine."""
    alone = next((t for t in PLAN_TYPES if t.lower() == text.strip().lower()), None)
    if alone:
        return alone, ""
    parts = _CUE_SPLIT.split(text, maxsplit=1)
    if len(parts) == 2:
        known = next((t for t in PLAN_TYPES if t.lower() == parts[0].strip().lower()), None)
        if known:
            return known, parts[1].strip()
    return guess_type(text), text.strip()


def _split_cues(md: str) -> tuple[list[str], str]:
    """Les indications [VISUEL : …] d'un bloc (le bloc entier, ou des lignes collées au texte) et le texte restant."""
    m = _CUE.match(md.strip())
    if m:
        return [m.group(1)], ""
    cues, lines = [], []
    for line in md.split("\n"):
        m = _CUE.match(line.strip())
        if m:
            cues.append(m.group(1))
        else:
            lines.append(line)
    return cues, "\n".join(lines).strip("\n")


def _extract_cues(data: dict) -> bool:
    """Les lignes [VISUEL : …] deviennent des plans du paragraphe qui suit (à défaut, qui précède)."""
    blocks, pending, found = [], [], False

    def attach(block_id: str) -> None:
        for text in pending:
            type_, note = cue_plan(text)
            data["plans"].append(new_plan(block_id, type_, note, by="claude"))
        pending.clear()

    for b in data["blocks"]:
        cues, md = _split_cues(b["md"])
        if cues:
            pending += [" ".join(c.split()) for c in cues]
            found = True
            if not md.strip():
                continue
            b = {**b, "md": md}
        if pending and not b["md"].lstrip().startswith("#"):
            attach(b["id"])
        blocks.append(b)
    if pending and blocks:
        attach(blocks[-1]["id"])
    data["blocks"] = blocks
    return found


def _plain(md: str) -> str:
    return " ".join(re.sub(r"\[([^\]]*)\]\([^)]*\)|[*_`>#]", lambda m: m.group(1) or "", md).split())


def _migrate_shots(pid: str, data: dict) -> None:
    """Les plans de l'ancienne étape Tournage (project.json, rattachés à une phrase) rejoignent le script."""
    for shot in service.load(pid).get("shots") or []:
        q = " ".join(str(shot.get("q") or "").replace("**", "").split())
        block = next((b["id"] for b in data["blocks"] if q and q in _plain(b["md"])), None)
        data["plans"].append({**new_plan(block, shot.get("type") or "Face caméra", shot.get("note") or ""),
                              "q": q, "frame": shot.get("frame") or "", "on": bool(shot.get("on"))})
    data["shots_migrated"] = True


# --- Lecture / écriture --------------------------------------------------------------------

def _path(pid: str):
    return service.project_dir(pid) / service.SCRIPT_DIR / JSON_FILE


def _read(pid: str) -> dict:
    path = _path(pid)
    data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    return {"blocks": data.get("blocks", []), "plans": data.get("plans", []), "setups": data.get("setups", []),
            "sections": data.get("sections", {}), "md_hash": data.get("md_hash"),
            "shots_migrated": data.get("shots_migrated", False),
            "draft": data.get("draft") or {"id": "v1", "name": "V1",
                                           "created": path.stat().st_mtime if path.is_file() else time.time()}}


def _write(pid: str, data: dict) -> None:
    path = _path(pid)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def _write_md(pid: str, md: str) -> None:
    (service.project_dir(pid) / service.SCRIPT_DIR / service.SCRIPT_FILE).write_text(md, encoding="utf-8")


def _snapshot(pid: str, md: str, force: bool = False) -> None:
    """Copie `md` dans script/versions/, sauf si la dernière copie a moins de VERSION_EVERY (hors `force`)."""
    if not md.strip():
        return
    folder = service.project_dir(pid) / service.SCRIPT_DIR / VERSIONS_DIR
    folder.mkdir(exist_ok=True)
    files = sorted(folder.glob("script-*.md"))
    if files:
        if not force and time.time() - files[-1].stat().st_mtime < VERSION_EVERY:
            return
        if files[-1].read_text(encoding="utf-8") == md:
            return
    path = folder / time.strftime("script-%Y%m%d-%H%M%S.md")
    path.write_text(md, encoding="utf-8")
    kept = sorted(folder.glob("script-*.md"))
    for old in kept[:-VERSION_KEEP]:
        old.unlink(missing_ok=True)


def load(pid: str) -> dict:
    """Le script, recalé sur script.md si celui-ci a changé depuis le dernier enregistrement."""
    with _lock(pid):
        data = _read(pid)
        md = service.read_doc(pid, service.SCRIPT_FILE)
        changed = False
        if _hash(md) != data["md_hash"]:
            # script.md a été réécrit hors de l'éditeur (Claude, à la main) : on garde le texte d'avant
            _snapshot(pid, render(data["blocks"]), force=True)
            data["blocks"] = reconcile(data["blocks"], split(md))
            _detach(data)
            if _extract_cues(data):
                # les indications sont passées dans les plans : script.md ne garde que le texte
                md = render(data["blocks"])
                _write_md(pid, md)
            data["md_hash"] = _hash(md)
            changed = True
        if not data["shots_migrated"]:
            _migrate_shots(pid, data)
            changed = True
        if changed:
            _write(pid, data)
        return data


def counts(pid: str) -> dict:
    """Le nombre de plans et de plans faits, sans recaler le script (pour la barre latérale)."""
    plans = _read(pid)["plans"]
    return {"total": len(plans), "done": sum(1 for p in plans if p.get("on"))}


def plans(pid: str) -> list[dict]:
    """Les plans tels qu'enregistrés, sans recaler le script."""
    return _read(pid)["plans"]


def save(pid: str, blocks: list[dict]) -> None:
    """Les blocs venus de l'éditeur ; script.md est réécrit d'après eux."""
    seen = set()
    clean = []
    for b in blocks:
        md = str(b.get("md", "")).strip("\n")
        if not md.strip():
            continue
        bid = str(b.get("id") or "")
        if not bid or bid in seen:
            bid = new_id()
        seen.add(bid)
        clean.append({"id": bid, "md": md})
    with _lock(pid):
        data = _read(pid)
        if not clean and data["blocks"]:
            raise ValueError("enregistrement d'un script vide refusé : le script actuel n'est pas vide")
        previous = render(data["blocks"])
        md = render(clean)
        _snapshot(pid, previous, force=len(md) < len(previous) * VERSION_SHRINK)
        data.update(blocks=clean, md_hash=_hash(md))
        _detach(data)
        _write_md(pid, md)
        _write(pid, data)


def save_plans(pid: str, plans: list[dict]) -> list[dict]:
    """Les plans venus de l'interface, remplacés tels quels (un plan dont le bloc n'existe plus est détaché)."""
    clean = []
    for p in plans:
        if p.get("type") not in PLAN_TYPES:
            raise ValueError(f"type de plan inconnu : {p.get('type')}")
        clean.append({**new_plan(None, p["type"]), **p})
    with _lock(pid):
        data = _read(pid)
        data["plans"] = clean
        _detach(data)
        _write(pid, data)
        return data["plans"]


def save_setups(pid: str, setups: list[dict], sections: dict[str, str]) -> dict:
    """Les setups et leur affectation aux sections ; un setup supprimé quitte les plans et les sections."""
    clean = [{"id": str(s.get("id") or "s" + uuid.uuid4().hex[:8]), "name": str(s.get("name") or ""),
              "note": str(s.get("note") or "")} for s in setups]
    ids = {s["id"] for s in clean}
    with _lock(pid):
        data = _read(pid)
        data["setups"] = clean
        data["sections"] = {b: s for b, s in sections.items() if s in ids}
        for plan in data["plans"]:
            if plan.get("setup") and plan["setup"] not in ids:
                plan["setup"] = ""
        _write(pid, data)
        return {"setups": data["setups"], "sections": data["sections"], "plans": data["plans"]}


# --- Versions ------------------------------------------------------------------------------

def _drafts_dir(pid: str):
    return service.project_dir(pid) / service.SCRIPT_DIR / DRAFTS_DIR


def _draft_path(pid: str, draft_id: str):
    if not re.fullmatch(r"[a-z0-9]+", draft_id):
        raise ValueError("version inconnue")
    return _drafts_dir(pid) / f"{draft_id}.json"


def _stored(pid: str) -> list[dict]:
    """Les versions rangées (pas l'active), de la plus ancienne à la plus récente."""
    folder = _drafts_dir(pid)
    stored = [json.loads(p.read_text(encoding="utf-8")) for p in folder.glob("*.json")] if folder.is_dir() else []
    return sorted(stored, key=lambda d: d["draft"]["created"])


def drafts(pid: str) -> list[dict]:
    """Les versions du script, de la plus ancienne à la plus récente : {id, name, created, active, words}."""
    active = _read(pid)
    out = [{**d["draft"], "active": d is active, "words": len(render(d["blocks"]).split())}
           for d in [active, *_stored(pid)]]
    return sorted(out, key=lambda d: d["created"])


def _stash(pid: str, data: dict) -> None:
    """Range une version dans drafts/, avec ses plans et ses setups."""
    folder = _drafts_dir(pid)
    folder.mkdir(exist_ok=True)
    path = folder / f"{data['draft']['id']}.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def _install(pid: str, data: dict) -> None:
    """`data` devient la version active : script.json et sa vue script.md."""
    md = render(data["blocks"])
    data["md_hash"] = _hash(md)
    _write_md(pid, md)
    _write(pid, data)


def fork(pid: str) -> None:
    """Une nouvelle version, copie de l'active (mêmes blocs, mêmes plans), qui prend sa place."""
    load(pid)
    with _lock(pid):
        data = _read(pid)
        _stash(pid, data)
        names = [d["draft"]["name"] for d in [data, *_stored(pid)]]
        numbers = [int(m.group(1)) for n in names if (m := re.fullmatch(r"V(\d+)", n))]
        data["draft"] = {"id": "v" + uuid.uuid4().hex[:8], "name": f"V{max(numbers, default=1) + 1}",
                         "created": time.time()}
        _write(pid, data)


def activate(pid: str, draft_id: str) -> None:
    """La version `draft_id` devient l'active ; l'actuelle est rangée dans drafts/."""
    load(pid)
    with _lock(pid):
        current = _read(pid)
        if current["draft"]["id"] == draft_id:
            return
        path = _draft_path(pid, draft_id)
        if not path.is_file():
            raise ValueError("version inconnue")
        _stash(pid, current)
        _install(pid, json.loads(path.read_text(encoding="utf-8")))
        path.unlink()


def rename(pid: str, draft_id: str, name: str) -> None:
    name = " ".join(name.split())[:40]
    if not name:
        raise ValueError("nom vide")
    with _lock(pid):
        current = _read(pid)
        if current["draft"]["id"] == draft_id:
            current["draft"]["name"] = name
            _write(pid, current)
            return
        path = _draft_path(pid, draft_id)
        if not path.is_file():
            raise ValueError("version inconnue")
        data = json.loads(path.read_text(encoding="utf-8"))
        data["draft"]["name"] = name
        _stash(pid, data)


def delete(pid: str, draft_id: str) -> None:
    """Supprime une version ; si c'est l'active, la plus récente des autres prend sa place.
    Son texte reste dans les copies de script/versions/."""
    with _lock(pid):
        current = _read(pid)
        others = _stored(pid)
        if not others:
            raise ValueError("c'est la seule version du script")
        if current["draft"]["id"] != draft_id:
            path = _draft_path(pid, draft_id)
            if not path.is_file():
                raise ValueError("version inconnue")
            _snapshot(pid, render(json.loads(path.read_text(encoding="utf-8"))["blocks"]), force=True)
            path.unlink()
            return
        _snapshot(pid, render(current["blocks"]), force=True)
        _install(pid, others[-1])
        _draft_path(pid, others[-1]["draft"]["id"]).unlink()
