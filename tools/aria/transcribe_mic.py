"""Transcribe the think-aloud in an Aria mic.wav with faster-whisper.

The Aria mic track in this dataset is recorded very quietly (peak about -41 dBFS),
so boost it first (ffmpeg):

  ffmpeg -i mic.wav -af "pan=mono|c0=0.34*c0+0.33*c1+0.33*c2,highpass=f=100,\
lowpass=f=6000,volume=45dB,alimiter=limit=0.9" -ar 16000 boost.wav

Then:

  pip install faster-whisper
  python3 tools/aria/transcribe_mic.py boost.wav transcript_mic.json large-v3-turbo

VAD is off on purpose: on the boosted track the VAD filter dropped all speech.
Segment times are mic.wav times; build_scenegraph.py shifts them onto the trial
clock with manifest.json mic.t0_ns.
"""
import json
import sys
import time

from faster_whisper import WhisperModel

wav, out, model = sys.argv[1], sys.argv[2], sys.argv[3]
t = time.time()
m = WhisperModel(model, device="cpu", compute_type="int8")
segs, info = m.transcribe(wav, language="ko", vad_filter=False, word_timestamps=True, beam_size=5,
                          condition_on_previous_text=False)
res = []
for s in segs:
    res.append({"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip(),
                "avg_logprob": round(s.avg_logprob, 2), "no_speech_prob": round(s.no_speech_prob, 2)})
    print(f"{s.start:7.2f}-{s.end:7.2f} [{s.avg_logprob:.2f}] {s.text.strip()}", flush=True)
with open(out, "w", encoding="utf-8") as f:
    json.dump({"model": model, "segments": res}, f, ensure_ascii=False, indent=1)
print("done", round(time.time() - t), "s")
