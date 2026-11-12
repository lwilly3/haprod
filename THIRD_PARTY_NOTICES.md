# Third-party notices

Daryl is licensed under the AGPL-3.0 (see [LICENSE](LICENSE)). This repository also contains, or
loads at run time, the third-party work listed below, each under its own license.

## Included in this repository

### HyperFrames skills (Apache-2.0)

The following Claude Code skills come from [heygen-com/hyperframes](https://github.com/heygen-com/hyperframes)
(`skills/` folder), Copyright 2026 HeyGen, Inc., licensed under the Apache License 2.0
(full text in [LICENSES/Apache-2.0.txt](LICENSES/Apache-2.0.txt)):

- `.claude/skills/gsap`
- `.claude/skills/hyperframes-animation`
- `.claude/skills/hyperframes-cli`
- `.claude/skills/hyperframes-core`
- `.claude/skills/hyperframes-keyframes`
- `.claude/skills/hyperframes-registry`
- `.claude/skills/motion-graphics`
- `.claude/skills/three`

The example videos of `hyperframes-animation` (`examples/assets/*.mp4`) are not included: get them
from the HyperFrames repository if you need them.

### youtube-scriptwriting skill (MIT)

`skills/youtube-scriptwriting` comes from [cdeistopened/skill-stack](https://github.com/cdeistopened/skill-stack),
Copyright (c) 2025 Wayne Sutton, licensed under the MIT license (see [its LICENSE](skills/youtube-scriptwriting/LICENSE)).

### youtube-titles skill

`skills/youtube-titles` started as an adaptation of a skill from the
`alexmcfarland-ai/co-writer-plugins` repository, which is no longer available.

## Used at run time, not included

These are installed or downloaded by you, under their own terms:

| Component | License | How it is used |
| --- | --- | --- |
| [HyperFrames](https://github.com/heygen-com/hyperframes) CLI | Apache-2.0 | Renders motion design and the final video, run with `npx` |
| [GSAP](https://gsap.com) | GSAP standard license | Loaded from jsDelivr by the motion design compositions |
| [FFmpeg](https://ffmpeg.org) | LGPL / GPL, depending on the build | Installed by you, called from the command line |
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) and the Whisper models | MIT | Local transcription |
| NVIDIA CUDA libraries (`nvidia-*` Python packages) | NVIDIA license | Optional, to run Whisper on the GPU |
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | Unlicense | Downloads videos you add as sources |
| Python and npm dependencies | MIT, BSD, Apache-2.0 | See `backend/requirements.txt` and `web/package.json` |
| IBM Plex Sans and Mono (Google Fonts) | SIL Open Font License 1.1 | Interface and motion design fonts |

The [editing-os](backend/scripts/import_editing_os.py) motion design kit is not included either: the
import script reads your own copy of it.
