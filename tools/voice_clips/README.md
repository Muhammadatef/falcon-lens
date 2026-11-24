# tools/voice_clips

Pre-generates every spoken Falcon line as an audio clip with a LOCAL TTS engine (Apple Silicon, MLX), so the
browser plays them instantly. There is no runtime TTS. Offline tool: not part of the uv workspace, not run in CI
(the tests need only numpy/scipy/ffmpeg).

    cd tools/voice_clips && uv sync --extra mlx
    # built-in voices (committed): macOS Majed for Arabic, Kokoro bm_fable for English
    uv run python generate.py --engine macos --lang ar_ae --script draft_script.yaml --out ../../web/public/voice/ar_ae
    uv run python generate.py --engine kokoro --lang en  --script draft_script.yaml --out ../../web/public/voice/en
    # final script (once feat/voice-emirati-script lands) is the default:
    #   packages/falcon_core/src/falcon_core/i18n/voice_script.yaml

Engines: `macos` (say, Majed/Daniel), `kokoro` (English), `chatterbox` (multilingual v3 with `--ref`, else the
bundled fp16 voice), `voicetut` (reference speakers), `silma` (separate torch venv, see below).
Output per clip: mono 24 kHz (`--rate 22050` allowed), trimmed, -16 LUFS (BS.1770), peak <= -1 dBFS, 40 ms fades,
`.mp3` (or `.ogg` when ffmpeg lacks libmp3lame), plus `manifest.json` `[{id,file,text,ms,engine,voice}]`.
The web reads `/voice/<lang>/manifest.json` (`ar_ae`, `en`).

## Cloning an owner-consented voice (live stack only)
Reference path: `FL_VOICE_REF_AR_AE` (default `data/private/voice/ref_ar_ae.wav`, gitignored). Consent is required
(docs/PRIVACY.md section "Voice cloning"). Render into `data/private/voice/clips/ar_ae/` and copy that folder over
`web/public/voice/ar_ae/` only on the machine that runs the live stack, never commit it. Clone clips carry
`voice: "ref-<name>"` in the manifest and a test fails if such a manifest is inside the repo's tracked tree.

    uv run python generate.py --engine chatterbox --lang ar_ae --ref data/private/voice/ref_ar_ae.wav --out ../../data/private/voice/clips/ar_ae

## SILMA
SILMA's `silma-tts` package pulls `onnxruntime-gpu` (no macOS arm64 wheel), so use a separate venv:
`uv venv silma-venv && uv pip install -p silma-venv/bin/python --no-deps silma-tts==1.0.5 && uv pip install -p silma-venv/bin/python torch torchaudio cached-path click ema-pytorch hydra-core librosa pydub safetensors soundfile tomli torchdiffeq tqdm transformers unidecode vocos x-transformers matplotlib omegaconf huggingface_hub`,
then `FL_SILMA_PYTHON=silma-venv/bin/python FL_VOICE_REF_TEXT="<transcript of the ref>" ... --engine silma --ref ref.wav`.
`silma_worker.py` stubs `nemo-text-processing` and `catt-tashkeel` (no auto tashkeel).

Models are read from `FL_VOICE_MODELS` (default `~/neo-models`); nothing is downloaded by this tool.
