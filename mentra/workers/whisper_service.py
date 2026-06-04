import sys
# Mock torch to prevent c10.dll loading/crashing or slow startup
sys.modules['torch'] = None

import json
import numpy as np
import traceback

def main():
    # Force stdout to flush after every print
    sys.stdout.reconfigure(line_buffering=True)
    
    model_size = sys.argv[1] if len(sys.argv) > 1 else "base"
    # Optional GPU-only model (argv[2]); used ONLY when CUDA is present.
    gpu_model = sys.argv[2] if len(sys.argv) > 2 else ""

    print(json.dumps({"status": "log", "message": f"Service starting with model '{model_size}'..."}))

    device = "cpu"
    compute_type = "int8"

    # Try CUDA detection
    try:
        import ctranslate2
        if ctranslate2.get_cuda_device_count() > 0:
            device = "cuda"
            compute_type = "float16"
            # Capability check passed → upgrade to the GPU model for near-cloud
            # local latency at zero cost. Falls back to CPU model if absent.
            if gpu_model:
                model_size = gpu_model
            print(json.dumps({"status": "log", "message": f"CUDA detected, will attempt to use GPU with model '{model_size}'"}))
        else:
            print(json.dumps({"status": "log", "message": "No CUDA -- using CPU by default"}))
    except Exception:
        pass
        
    try:
        from faster_whisper import WhisperModel
        
        print(json.dumps({"status": "log", "message": f"Loading WhisperModel('{model_size}', device='{device}', compute_type='{compute_type}')"}))
        model = WhisperModel(model_size, device=device, compute_type=compute_type)
        print(json.dumps({"status": "loaded"}))
        
    except Exception as e:
        if device == "cuda":
            print(json.dumps({"status": "log", "message": f"Failed to load on CUDA: {e}. Falling back to CPU..."}))
            device = "cpu"
            compute_type = "int8"
            try:
                model = WhisperModel(model_size, device=device, compute_type=compute_type)
                print(json.dumps({"status": "loaded"}))
            except Exception as e_cpu:
                print(json.dumps({"status": "error", "message": f"Failed to load WhisperModel on CPU fallback: {str(e_cpu)}\n{traceback.format_exc()}"}))
                sys.exit(1)
        else:
            print(json.dumps({"status": "error", "message": f"Failed to load WhisperModel: {str(e)}\n{traceback.format_exc()}"}))
            sys.exit(1)
        
    # Read audio chunks from stdin.buffer
    # Protocol:
    # 1. Read 4 bytes: number of samples (uint32)
    # 2. Read num_samples * 4 bytes (float32 array)
    try:
        while True:
            header = sys.stdin.buffer.read(4)
            if not header:
                break
            num_samples = int(np.frombuffer(header, dtype=np.uint32)[0])
            
            # Read the samples
            bytes_to_read = num_samples * 4
            data = bytearray()
            while len(data) < bytes_to_read:
                packet = sys.stdin.buffer.read(bytes_to_read - len(data))
                if not packet:
                    break
                data.extend(packet)
                
            if len(data) < bytes_to_read:
                print(json.dumps({"status": "log", "message": "Incomplete chunk received -- exit"}))
                break
                
            # Reconstruct float32 array
            audio_chunk = np.frombuffer(data, dtype=np.float32)
            
            # Transcribe with CPU fallback if CUDA fails during execution
            import time
            t0 = time.time()
            
            segments = []
            
            # Check if onnxruntime is available without DLL errors before enabling vad_filter
            use_vad = True
            try:
                import onnxruntime  # noqa: F401  (availability gate for Whisper vad_filter)
            except Exception:
                use_vad = False

            try:
                raw_segments, info = model.transcribe(
                    audio_chunk,
                    beam_size=5,
                    language="en",
                    without_timestamps=False,
                    condition_on_previous_text=True,
                    vad_filter=use_vad,
                    vad_parameters=dict(min_speech_duration_ms=250) if use_vad else None
                )
                segments = list(raw_segments)  # Force execution to catch DLL/CUDA runtime errors
            except Exception as transcribe_err:
                if device == "cuda":
                    print(json.dumps({"status": "log", "message": f"CUDA execution failed: {transcribe_err}. Falling back to CPU..."}))
                    device = "cpu"
                    compute_type = "int8"
                    # Reload model on CPU
                    model = WhisperModel(model_size, device=device, compute_type=compute_type)
                    # Retry transcription on CPU
                    raw_segments, info = model.transcribe(
                        audio_chunk,
                        beam_size=5,
                        language="en",
                        without_timestamps=False,
                        condition_on_previous_text=True,
                        vad_filter=use_vad,
                        vad_parameters=dict(min_speech_duration_ms=250) if use_vad else None
                    )
                    segments = list(raw_segments)
                else:
                    raise transcribe_err

            
            new_segments = []
            for segment in segments:
                text = segment.text.strip()
                if text and len(text) > 1:
                    # Calculate segment confidence
                    confidence = float(np.exp(segment.avg_logprob))
                    new_segments.append({
                        "text": text,
                        "confidence": confidence,
                        "no_speech_prob": float(segment.no_speech_prob)
                    })
                    
            elapsed = time.time() - t0
            
            print(json.dumps({
                "status": "result",
                "segments": new_segments,
                "elapsed": elapsed
            }))
            
    except Exception as e:
        print(json.dumps({"status": "error", "message": f"Run error: {str(e)}\n{traceback.format_exc()}"}))
        
if __name__ == "__main__":
    main()
