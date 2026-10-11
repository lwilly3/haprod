"""
Ce qui touche a la machine : outils en ligne de commande, dialogues Windows.
"""
import os
import shutil
import subprocess
from pathlib import Path


def tool(name: str) -> str:
    """ffmpeg installe par winget n'est visible que dans les terminaux ouverts apres l'install."""
    found = shutil.which(name)
    if found:
        return found
    winget = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Links" / f"{name}.exe"
    if winget.exists():
        return str(winget)
    raise RuntimeError(f"{name} est introuvable : installe-le (winget install ffmpeg) puis relance.")


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
    for name in ("msedge", "chrome"):
        if shutil.which(name):
            return shutil.which(name)
    roots = [os.environ.get(k, "") for k in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA")]
    for root in filter(None, roots):
        for rel in ("Microsoft/Edge/Application/msedge.exe", "Google/Chrome/Application/chrome.exe"):
            if (Path(root) / rel).is_file():
                return str(Path(root) / rel)
    raise RuntimeError("ni Edge ni Chrome trouvé : il en faut un pour les captures de pages.")


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
    patterns = ";".join(f"*.{e}" for e in extensions)
    return _powershell(f"""
$d = New-Object System.Windows.Forms.OpenFileDialog
$d.Title = '{title}'
$d.Multiselect = $true
$d.Filter = 'Video / audio|{patterns}|Tous les fichiers|*.*'
if ($d.ShowDialog($owner) -eq 'OK') {{ $d.FileNames -join "`n" }}
""")


def pick_folder(title: str, start: str | None = None) -> str | None:
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
    """Ouvre l'explorateur sur le fichier."""
    subprocess.Popen(["explorer", "/select,", str(path)])
