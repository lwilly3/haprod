"""
Reporter une inspiration dans le kit : Claude réécrit une carte d'editing-os (bibliothèque, onglet
Animations) en animation du kit. Il en garde la mécanique (structure, mouvement, rythme) et
n'emploie que la charte du kit : ses variables CSS et ses briques. L'animation suit donc le design
system sans jamais être régénérée.

Le résultat : data/kit/exemple-<nom>.html, copié dans chaque projet avec les autres exemples.
"""
import hashlib
import re

from ...core import jobs
from ...core.tasks import TaskContext
from ..animations import kit
from ..settings.service import language_name
from . import library, service

KIND = "kit_adapt"

SCHEMA = {
    "type": "object",
    "required": ["slug", "html", "message"],
    "properties": {
        "slug": {"type": "string",
                 "description": "Le nom court de l'animation, en minuscules et tirets, 2 à 4 mots (ex. "
                                "« compteur-barre »)."},
        "html": {"type": "string", "description": "La composition complète, de <!doctype html> à </html>."},
        "message": {"type": "string",
                    "description": "Une ou deux phrases : ce que tu as repris de l'inspiration, ce que tu as changé."},
    },
}

SYSTEM = """\
Tu es motion designer. Tu reportes une animation d'inspiration dans le kit d'un créateur de vidéos \
YouTube éducatives (chaîne en {lang}) : tu en écris une nouvelle animation du kit. Tu ne lis aucun \
fichier : tout est dans le message.

On reprend la MÉCANIQUE de l'inspiration : la composition de l'image, les éléments et leur ordre \
d'apparition, les mouvements, les courbes, le rythme, les transitions internes. On ne reprend PAS \
son habillage : ni ses couleurs, ni ses polices, ni ses textures, ni ses textes.

Règles de la charte (impératives) :
- charge ../style.css et GSAP (https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js), comme les \
exemples du kit ;
- couleurs, polices et arrondis : uniquement les variables de style.css (var(--accent), var(--text), \
var(--card), var(--font)…). Aucune couleur écrite en dur, sauf du noir ou du blanc transparents \
(rgba) pour les ombres et les voiles. Aucune autre police que var(--font) et var(--mono). GSAP \
n'anime pas une var(--…) : pour animer une couleur, lis sa valeur au chargement \
(getComputedStyle(document.documentElement).getPropertyValue("--accent").trim()) ;
- réutilise les briques de style.css (.card, .kicker, .title, .big, .body, .node…) quand elles \
conviennent ;
- fond transparent : l'animation se pose sur la vidéo. Une inspiration plein écran devient une \
carte (.card) assez grande, pas un aplat opaque, sauf si le plein écran est son idée même ;
- structure identique aux exemples : <div id="stage" class="youtube" data-composition-id="exemple-<slug>" \
data-duration="…" data-hero="…">, une seule timeline GSAP en pause enregistrée dans \
window.__timelines["exemple-<slug>"], durée de 6 à 12 s avec une sortie à la fin, data-hero = le \
moment où tout est en place ;
- en tête du fichier, un commentaire « EXEMPLE (format youtube) : » qui décrit en {lang}, en deux ou \
trois phrases, ce que montre l'animation et quand s'en servir (c'est ce que lira Daryl pour la choisir) ;
- textes de démonstration en {lang}, sur un sujet de vulgarisation plausible ;
- déterministe : pas de Math.random(), pas de Date.now() ; pas d'oscillation décorative \
(repeat: -1, yoyo) ; chaque élément apparaît à un instant précis."""


def job_id(file: str) -> str:
    return "kit-adapt-" + hashlib.sha1(file.encode()).hexdigest()[:10]


def start(style: str, file: str) -> jobs.Job:
    cards = library.style_animations(style) or []
    card = next((c for c in cards if c["file"] == file), None)
    if not card or not library.editing_os_file(file):
        raise LookupError("inspiration inconnue")
    kit.USER_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"style": style, "file": file, "title": card["title"], "dir": str(kit.USER_DIR)}
    return service.requeue(job_id(file), KIND, payload, {})


def view() -> list[dict]:
    """Les reports en cours ou récents : {file, status, error, result}."""
    return [{"file": j.payload.get("file"), "title": j.payload.get("title"), "status": j.status,
             "finished": j.finished, "error": j.error, "result": j.state.get("result")}
            for j in jobs.list_jobs(service.MODULE) if j.kind == KIND]


def _prompt(card_html: str, card: dict) -> str:
    examples = [p for p in kit.examples() if not kit.is_mine(p)]
    parts = [f"L'inspiration : « {card['title']} » ({card['description']})", "<inspiration>", card_html, "</inspiration>", "",
             "La charte du kit (style.css) :", "<style.css>", kit.style_css(), "</style.css>", ""]
    for p in examples:
        parts += [f"Un exemple du kit ({p.name}), pour la structure et les conventions :", f"<{p.name}>",
                  p.read_text(encoding="utf-8"), f"</{p.name}>", ""]
    parts += ["Écris l'animation du kit inspirée de cette carte."]
    return "\n".join(parts)


def run(ctx: TaskContext) -> None:
    from .tasks import ask

    p = ctx.payload
    card = next((c for c in library.style_animations(p["style"]) or [] if c["file"] == p["file"]), None)
    path = library.editing_os_file(p["file"])
    if not card or not path:
        raise RuntimeError("L'inspiration n'existe plus dans la bibliothèque.")
    ctx.state["activity"] = "lit l'inspiration"
    ctx.save(force=True)
    out = ask(ctx, _prompt(path.read_text(encoding="utf-8"), card), SYSTEM.format(lang=language_name()),
              "Read", None, SCHEMA)
    output = out["output"] or {}
    html = (output.get("html") or "").strip()
    slug = re.sub(r"[^a-z0-9]+", "-", (output.get("slug") or "").lower()).strip("-")[:40] or "inspiration"
    if "<html" not in html or "gsap.timeline" not in html:
        raise RuntimeError("Claude n'a pas rendu de composition.")

    # un nom libre : on ne remplace jamais une animation du kit
    name, n = slug, 2
    while kit.example(f"exemple-{name}.html"):
        name, n = f"{slug}-{n}", n + 1
    if f'data-composition-id="exemple-{slug}"' not in html or f'__timelines["exemple-{slug}"]' not in html:
        raise RuntimeError("La composition n'est pas enregistrée sous son nom (data-composition-id, __timelines).")
    # l'id de la composition suit le nom retenu (la timeline est enregistrée sous cet id)
    html = html.replace(f"exemple-{slug}", f"exemple-{name}")
    target = kit.USER_DIR / f"exemple-{name}.html"
    target.write_text(html + "\n", encoding="utf-8")

    # couleurs écrites en dur : signalées, pas corrigées en silence
    hard = sorted(set(re.findall(r"#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b", re.sub(r"<!--.*?-->", "", html, flags=re.S))))
    ctx.state["result"] = {"name": target.name, "message": (output.get("message") or "").strip(), "hard_colors": hard}
    ctx.state["activity"] = None
    ctx.progress = 1.0
