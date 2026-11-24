"""SILMA TTS worker. Runs in a SEPARATE venv (torch + silma-tts installed with --no-deps).

    FL_SILMA_PYTHON=/path/to/venv/bin/python   (see docs/research/VERIFIED_VERSIONS.md, section voice)

Input JSON (argv[1]): {"ref": wav, "ref_text": str, "texts": [str], "out_dir": dir}
Writes out_dir/<i>.wav for each text. Weights are read from FL_VOICE_MODELS/SILMA-TTS (no download).
The upstream package pulls nemo-text-processing and catt-tashkeel (not installable on macOS arm64);
they are stubbed, so text goes in WITHOUT automatic tashkeel/number normalisation.
"""

from __future__ import annotations

import json
import os
import sys
import types
from pathlib import Path
from typing import Any


def _stub(name: str, **attrs: Any) -> None:
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    sys.modules[name] = m


def main() -> int:
    job = json.loads(Path(sys.argv[1]).read_text())
    for n in ("nemo_text_processing", "nemo_text_processing.text_normalization"):
        _stub(n)
    _stub("nemo_text_processing.text_normalization.normalize", Normalizer=object)
    _stub("catt_tashkeel", CATTEncoderOnly=object)

    import soundfile as sf
    import torch
    import torchaudio

    def _load(path: str, *_a: Any, **_k: Any) -> tuple[Any, int]:  # torchaudio>=2.9 needs torchcodec; use soundfile
        data, rate = sf.read(path, dtype="float32", always_2d=True)
        return torch.from_numpy(data.T.copy()), int(rate)

    torchaudio.load = _load
    from importlib.resources import files

    from hydra.utils import get_class
    from omegaconf import OmegaConf
    from silma_tts.infer.utils_infer import infer_process, load_model, load_vocoder, preprocess_ref_audio_text

    root = Path(os.environ.get("FL_VOICE_MODELS", str(Path.home() / "neo-models"))) / "SILMA-TTS"
    cfg = OmegaConf.load(str(files("silma_tts").joinpath("config.yaml")))
    cls = get_class(f"silma_tts.model.{cfg.model.backbone}")
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    vocos_dir = next((root / "hf-cache/models--charactr--vocos-mel-24khz/snapshots").iterdir())
    vocoder = load_vocoder("vocos", True, str(vocos_dir), device, None)
    model = load_model(
        cls,
        cfg.model.arch,
        str(root / "model.pt"),
        cfg.model.mel_spec.mel_spec_type,
        str(root / "vocab.txt"),
        "euler",
        False,
        device,
    )
    ref, ref_text = preprocess_ref_audio_text(job["ref"], job["ref_text"])
    out = Path(job["out_dir"])
    out.mkdir(parents=True, exist_ok=True)
    for i, text in enumerate(job["texts"]):
        torch.manual_seed(7)
        wav, sr, _ = infer_process(
            ref,
            ref_text,
            text,
            model,
            vocoder,
            cfg.model.mel_spec.mel_spec_type,
            show_info=lambda *_: None,
            progress=None,
            target_rms=0.1,
            cross_fade_duration=0,
            nfe_step=16,
            cfg_strength=2,
            sway_sampling_coef=-1,
            speed=1.0,
            fix_duration=None,
            device=device,
            force_tashkeel=False,
        )
        sf.write(str(out / f"{i}.wav"), wav, sr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
