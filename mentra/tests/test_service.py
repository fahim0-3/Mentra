import subprocess
import sys
import numpy as np
import json
import time

def test():
    print("Starting Whisper subprocess service...")
    proc = subprocess.Popen(
        [sys.executable, "-u", "mentra/workers/whisper_service.py", "tiny"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=False
    )
    
    # Read status output from service
    t_start = time.time()
    while True:
        line = proc.stdout.readline().decode('utf-8')
        if not line:
            print("Service stopped before emitting status.")
            break
        print(f"Service stdout (load phase): {line.strip()}")
        data = json.loads(line)
        if data.get("status") == "loaded":
            print(f"Model loaded successfully in {time.time() - t_start:.2f}s!")
            break
        elif data.get("status") == "error":
            print(f"Service error: {data.get('message')}")
            break
            
    # Send a dummy chunk (2 seconds of audio at 16kHz, so 32000 samples)
    # Let's generate a tiny sine wave so it's not complete silence
    print("Generating 2 seconds of dummy audio...")
    sr = 16000
    t = np.linspace(0, 2, sr * 2, dtype=np.float32)
    audio = 0.5 * np.sin(2 * np.pi * 440 * t).astype(np.float32)
    
    # Write header and bytes
    print("Sending audio to service...")
    proc.stdin.write(np.uint32(len(audio)).tobytes())
    proc.stdin.write(audio.tobytes())
    proc.stdin.flush()
    
    # Wait for result
    print("Waiting for transcription result...")
    while True:
        line = proc.stdout.readline().decode('utf-8')
        if not line:
            print("Service stopped before emitting result.")
            break
        print(f"Received from service: {line.strip()}")
        data = json.loads(line)
        if data.get("status") == "result":
            segments = data.get("segments", [])
            text = " ".join(s.get("text", "") for s in segments)
            print(f"Transcription text: \"{text}\" in {data.get('elapsed'):.2f}s!")
            break
        elif data.get("status") == "error":
            print(f"Run error: {data.get('message')}")
            break
    
    # Clean terminate
    print("Terminating service...")
    proc.terminate()
    proc.wait()
    print("Done!")

if __name__ == "__main__":
    test()
