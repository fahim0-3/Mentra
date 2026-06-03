"""One-time downloader for the Silero VAD ONNX model.

Run this ONCE while online so meeting mode can use the genuine Silero VAD
(far more accurate than the energy fallback) without any network access at
meeting start:

    python -m mentra.workers.fetch_silero_vad

The model (~1.8 MB, MIT licensed) is saved to:
    mentra/workers/models/silero_vad.onnx
"""

import os
import sys
import urllib.request

from mentra.utils.styles import SILERO_VAD_MODEL_URL
from mentra.workers.vad_gate import SileroVAD


def main() -> int:
    dest = SileroVAD.default_model_path()
    os.makedirs(os.path.dirname(dest), exist_ok=True)

    if os.path.isfile(dest) and os.path.getsize(dest) > 0:
        print(f"Silero VAD model already present: {dest}")
        return 0

    print(f"Downloading Silero VAD model...\n  from: {SILERO_VAD_MODEL_URL}\n  to:   {dest}")
    try:
        urllib.request.urlretrieve(SILERO_VAD_MODEL_URL, dest)
    except Exception as e:
        print(f"ERROR: download failed: {e}")
        print("Meeting mode will still run using the energy-VAD fallback.")
        return 1

    size = os.path.getsize(dest) if os.path.isfile(dest) else 0
    if size <= 0:
        print("ERROR: downloaded file is empty.")
        return 1

    # Verify it actually loads through onnxruntime
    vad = SileroVAD(model_path=dest)
    print(f"Downloaded {size} bytes. VAD backend after load: {vad.backend}")
    if vad.backend != "onnx":
        print("WARNING: model present but failed to load via onnxruntime; "
              "the energy fallback will be used.")
        return 1

    print("Success — genuine Silero VAD is now bundled and will be used at meeting start.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
