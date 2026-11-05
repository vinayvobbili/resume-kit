# Rebuild the demo video

The README's demo video shows real output from real `resume` commands on the bundled example: a fictional candidate
and made-up companies (Acme, Globex). Nothing in it comes from real content. Every command is run with an explicit
`--content` on a copy of `examples/content`, so the bundled example is left alone.

```
pip install 'slidecast[mlx,yaml,playwright]' && python -m playwright install chromium
scripts/demo/make-video --docs      # writes docs/resume-kit-demo.mp4 and docs/demo.gif
```

`make-video [OUT] [--music DIR] [--docs]` runs these steps, each of which also runs on its own:

| Step | Command | Writes (in OUT, default `scripts/demo/out`) |
|---|---|---|
| Run the commands | `python scripts/demo/capture.py OUT` | `content/` (the example plus demo fixtures), `captures.json` |
| Music | `slidecast compose -o OUT --length 95 --bpm 84 --seed 7` | `music_bed.wav`, `intro_sting.wav`, `outro_sting.wav` |
| Slides and narration | `python scripts/demo/build.py OUT [--music DIR]` | `slides/*.html`, `reel.yaml` |
| Render | `slidecast render OUT/reel.yaml -o OUT/resume-kit-demo.mp4 --poster` | the video and its poster |

OUT is git-ignored. Set `PYTHON` (resume-kit's environment, default `.venv/bin/python`) and `SLIDECAST` when they
live in different environments; the voice installs a spaCy model into slidecast's, so `make-video` points
`VIRTUAL_ENV` at it.

- **The story** (slide order, titles, narration) lives in `slides()` in `build.py`.
- **The fixtures** in `scripts/demo/fixtures` are demo-only: a version that claims Kubernetes (`globex-k8s`), a
  version that picks every bullet so it spills onto page 2 (`acme-everything`, with the extra bullets in
  `extra-bullets.yaml`), and the posting that `resume draft` reads.
- **The score slide** shows `score-output.txt`, a real `resume score acme` run recorded earlier (it needs a local
  model, which `make-video` doesn't wait for). Re-record it by pasting a new run there.
- **The voice** is Kokoro `af_heart` through slidecast's in-process `mlx` provider (Apple Silicon). The music bed
  plays at volume 0.3 and ducks 16 dB under the voice; the final audio is normalized to -16 LUFS.
