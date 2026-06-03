"""Quick test to verify PyAudioWPatch can find WASAPI loopback devices."""
import pyaudiowpatch as pyaudio

p = pyaudio.PyAudio()

try:
    wasapi_info = p.get_host_api_info_by_type(pyaudio.paWASAPI)
    print(f"WASAPI API index: {wasapi_info['index']}")
    print(f"Default output device: {wasapi_info['defaultOutputDevice']}")

    default_speakers = p.get_device_info_by_index(wasapi_info["defaultOutputDevice"])
    print(f"\nDefault speakers: {default_speakers['name']}")
    print(f"  Channels: {default_speakers['maxOutputChannels']}")
    print(f"  Sample rate: {default_speakers['defaultSampleRate']}")
    print(f"  Is loopback: {default_speakers.get('isLoopbackDevice', False)}")

    print("\n--- Loopback devices ---")
    found = False
    for i in range(p.get_device_count()):
        d = p.get_device_info_by_index(i)
        if d.get("isLoopbackDevice", False):
            found = True
            print(f"  [{i}] {d['name']}")
            print(f"       Input channels: {d['maxInputChannels']}")
            print(f"       Sample rate: {d['defaultSampleRate']}")
    if not found:
        print("  (none found)")
finally:
    p.terminate()
