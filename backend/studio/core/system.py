"""
Ce qui touche a la machine : outils en ligne de commande, dialogues natifs (Windows, macOS).
"""
import functools
import os
import shutil
import subprocess
import sys
from pathlib import Path

MAC = sys.platform == "darwin"
# Homebrew (Apple Silicon puis Intel) : absent du PATH quand le studio n'est pas lance d'un terminal
MAC_BIN_DIRS = ("/opt/homebrew/bin", "/usr/local/bin")
MAC_FFMPEG_FULL = ("/opt/homebrew/opt/ffmpeg-full/bin", "/usr/local/opt/ffmpeg-full/bin")


def tool(name: str) -> str:
    """ffmpeg installe par winget n'est visible que dans les terminaux ouverts apres l'install."""
    if MAC and name in ("ffmpeg", "ffprobe"):
        # le ffmpeg de Homebrew n'a plus drawtext (textes du montage) : ffmpeg-full l'a, mais hors du PATH
        for prefix in MAC_FFMPEG_FULL:
            if (Path(prefix) / name).is_file():
                return str(Path(prefix) / name)
    found = shutil.which(name)
    if found:
        return found
    if os.name != "nt":
        for folder in MAC_BIN_DIRS:
            if (Path(folder) / name).is_file():
                return str(Path(folder) / name)
        install = "brew install ffmpeg" if MAC else "avec le gestionnaire de paquets"
        raise RuntimeError(f"{name} est introuvable : installe-le ({install}) puis relance.")
    winget = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Links" / f"{name}.exe"
    if winget.exists():
        return str(winget)
    raise RuntimeError(f"{name} est introuvable : installe-le (winget install ffmpeg) puis relance.")


@functools.cache
def has_filter(name: str) -> bool:
    """Tous les ffmpeg n'ont pas tous les filtres : drawtext demande un build avec freetype."""
    out = subprocess.run([tool("ffmpeg"), "-hide_banner", "-filters"], capture_output=True, text=True).stdout
    return any(line.split()[1:2] == [name] for line in out.splitlines())


@functools.cache
def _videotoolbox() -> bool:
    """L'encodeur matériel des Mac (STUDIO_ENCODER=x264 pour garder libx264)."""
    if not MAC or os.environ.get("STUDIO_ENCODER", "auto") == "x264":
        return False
    out = subprocess.run([tool("ffmpeg"), "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
    return "h264_videotoolbox" in out


def h264(crf: int, preset: str) -> list[str]:
    """Les options d'encodage H.264 d'une qualité donnée (l'échelle CRF de libx264).

    Sur un Mac, la puce encode : mesuré sur un rush 4K (M5), 5 fois plus vite que libx264 « medium » et
    1,6 fois plus vite que « veryfast », à poids et fidélité (SSIM) équivalents : CRF 18 ~ qualité 70,
    CRF 12 ~ 85. `allow_sw` : repli logiciel de VideoToolbox si la puce refuse le format.
    """
    if _videotoolbox():
        quality = min(max(round(70 + (18 - crf) * 2.5), 1), 100)
        return ["-c:v", "h264_videotoolbox", "-q:v", str(quality), "-allow_sw", "1"]
    return ["-c:v", "libx264", "-preset", preset, "-crf", str(crf)]


def need_drawtext() -> None:
    if not has_filter("drawtext"):
        fix = "brew install ffmpeg-full, puis relance le studio" if MAC else "il faut un build avec freetype"
        raise ValueError(f"ce ffmpeg ne sait pas écrire de texte (filtre drawtext absent) : {fix}")


def secret(name: str) -> str | None:
    """Une cle d'API : l'environnement, sinon ce que l'utilisateur a range une fois pour toutes
    (variables utilisateur de Windows, Trousseau de macOS), relu a chaque appel : pas besoin de relancer."""
    found = os.environ.get(name)
    if found:
        return found
    if sys.platform == "win32":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as reg:
                return winreg.QueryValueEx(reg, name)[0] or None
        except OSError:
            return None
    if MAC:
        try:
            out = subprocess.run(["security", "find-generic-password", "-s", name, "-w"],
                                 capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            return None
        return out.stdout.strip() or None if out.returncode == 0 else None
    return None


def secret_hint(name: str, value: str = "ta-clé") -> str:
    """La commande qui range la cle, a montrer quand elle manque."""
    if sys.platform == "win32":
        return f'setx {name} "{value}"'
    if MAC:
        return f'security add-generic-password -U -s {name} -a "$USER" -w "{value}"'
    return f'export {name}="{value}"'


def kill_children_on_exit() -> None:
    """Windows ne tue pas les enfants d'un process qui meurt : un ffmpeg survivrait au worker
    (relance --reload, arret brutal) et garderait ses fichiers ouverts. Un job object les emporte avec lui."""
    if os.name != "nt":
        return
    import ctypes
    from ctypes import wintypes

    class Basic(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class Extended(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", Basic), ("IoInfo", ctypes.c_ulonglong * 6),
                    ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 0x2000, 9
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateJobObjectW.restype = wintypes.HANDLE
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]

    # le handle n'est jamais ferme : il l'est a la mort du process, ce qui tue tout le job
    job = k32.CreateJobObjectW(None, None)
    info = Extended()
    info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not (job and k32.SetInformationJobObject(job, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                                                ctypes.byref(info), ctypes.sizeof(info))
            and k32.AssignProcessToJobObject(job, k32.GetCurrentProcess())):
        print(f"Job object indisponible (erreur {ctypes.get_last_error()}) : "
              "les process lances survivront a un arret du worker.")


def browser() -> str:
    """Edge (toujours la sous Windows) ou Chrome, pour les captures de pages en headless."""
    for name in ("msedge", "chrome", "google-chrome", "chromium", "chromium-browser"):
        if shutil.which(name):
            return shutil.which(name)
    if MAC:
        apps = ("Google Chrome.app/Contents/MacOS/Google Chrome", "Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
                "Chromium.app/Contents/MacOS/Chromium", "Brave Browser.app/Contents/MacOS/Brave Browser")
        for root in (Path("/Applications"), Path.home() / "Applications"):
            for rel in apps:
                if (root / rel).is_file():
                    return str(root / rel)
        raise RuntimeError("ni Chrome ni Edge trouvé : il en faut un pour les captures de pages.")
    roots = [os.environ.get(k, "") for k in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA")]
    for root in filter(None, roots):
        for rel in ("Microsoft/Edge/Application/msedge.exe", "Google/Chrome/Application/chrome.exe"):
            if (Path(root) / rel).is_file():
                return str(Path(root) / rel)
    raise RuntimeError("ni Edge ni Chrome trouvé : il en faut un pour les captures de pages.")


def _osascript(script: str) -> list[str]:
    """AppleScript : `activate` met le dialogue devant le navigateur ; annuler (erreur -128) ne rend rien."""
    out = subprocess.run(["osascript", "-e", "activate", "-e", script],
                         capture_output=True, text=True, encoding="utf-8").stdout
    return [line.strip() for line in out.splitlines() if line.strip()]


def _applescript_string(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _powershell(script: str) -> list[str]:
    out = subprocess.run(
        ["powershell", "-NoProfile", "-STA", "-Command",
         "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8\n"
         "Add-Type -AssemblyName System.Windows.Forms\n"
         "$owner = New-Object System.Windows.Forms.Form -Property @{TopMost = $true}\n" + script],
        capture_output=True, text=True, encoding="utf-8",
    ).stdout
    return [line.strip() for line in out.splitlines() if line.strip()]


def pick_files(title: str, extensions: tuple[str, ...]) -> list[str]:
    """Selecteur de fichiers natif (le navigateur ne donne jamais le vrai chemin)."""
    if MAC:
        types = ", ".join(_applescript_string(e) for e in extensions)
        return _osascript(f"""
set picked to choose file with prompt {_applescript_string(title)} of type {{{types}}} with multiple selections allowed
set out to ""
repeat with f in picked
    set out to out & POSIX path of f & linefeed
end repeat
return out
""")
    patterns = ";".join(f"*.{e}" for e in extensions)
    return _powershell(f"""
$d = New-Object System.Windows.Forms.OpenFileDialog
$d.Title = '{title}'
$d.Multiselect = $true
$d.Filter = 'Video / audio|{patterns}|Tous les fichiers|*.*'
if ($d.ShowDialog($owner) -eq 'OK') {{ $d.FileNames -join "`n" }}
""")


def pick_folder(title: str, start: str | None = None) -> str | None:
    if MAC:
        where = (f" default location POSIX file {_applescript_string(start)}"
                 if start and Path(start).is_dir() else "")
        paths = _osascript(f"return POSIX path of (choose folder with prompt {_applescript_string(title)}{where})")
        # AppleScript termine un dossier par / : on rend le meme chemin que Windows
        return paths[0].rstrip("/") or "/" if paths else None
    # entre apostrophes PowerShell, une apostrophe s'echappe en la doublant
    selected = f"$d.SelectedPath = '{start.replace(chr(39), chr(39) * 2)}'" if start else ""
    paths = _powershell(f"""
$d = New-Object System.Windows.Forms.FolderBrowserDialog
$d.Description = '{title}'
{selected}
if ($d.ShowDialog($owner) -eq 'OK') {{ $d.SelectedPath }}
""")
    return paths[0] if paths else None


def reveal(path: Path) -> None:
    """Ouvre l'explorateur (le Finder sous macOS) sur le fichier."""
    if MAC:
        subprocess.Popen(["open", "-R", str(path)])
    elif os.name == "nt":
        subprocess.Popen(["explorer", "/select,", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path.parent)])
