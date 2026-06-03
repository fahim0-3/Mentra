# Bundled VAD model

Place the Silero VAD ONNX model here so meeting mode needs no network at start:

```
mentra/workers/models/silero_vad.onnx
```

## How the app finds the model
`mentra/workers/vad_gate.py` (`SileroVAD`) resolves the model path in this order:
1. An explicit `model_path` argument (if any).
2. The `SILERO_VAD_MODEL_PATH` environment variable.
3. This bundled location: `mentra/workers/models/silero_vad.onnx`.

If no model is found, or it fails to load, the app logs a warning and falls
back to the pure-Python adaptive energy detector. The app never crashes and
never downloads at meeting start.

## One-time fetch (optional, do this once before going offline)
The model is ~1.8 MB and licensed MIT by the Silero team.

PowerShell:
```powershell
Invoke-WebRequest `
  -Uri "https://github.com/snakers4/silero-vad/raw/master/src/silero_vad/data/silero_vad.onnx" `
  -OutFile "mentra/workers/models/silero_vad.onnx"
```

The download URL is also recorded as `SILERO_VAD_MODEL_URL` in
`mentra/utils/styles.py`. Both Silero v4 (h/c state) and v5 (unified state)
ONNX signatures are supported by the loader.
