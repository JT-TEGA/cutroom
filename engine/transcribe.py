#!/usr/bin/env python3
"""Word-level transcription with faster-whisper (cached per file).

  transcribe.py raw/a.mp4 raw/b.mov            # transcribe (skips cached)
  transcribe.py raw/a.mp4 --show               # print timed transcript
  transcribe.py raw/a.mp4 --model small --force

Output: work/_cache/transcripts/<clip-key>.json
  {"src", "duration", "language", "model", "words": [{"w","s","e","p"}], "segments": [...]}
"""
import argparse
import time

from .common import (
    FF,
    cache_dir,
    describe,
    die,
    ffprobe,
    file_key,
    load_brand,
    read_json,
    rel,
    resolve,
    run,
    tc,
    transcript_path,
    write_json,
)
from .config import log


def extract_wav(src):
    """16 kHz mono wav, cached; also used by autocut for cut-point snapping."""
    out = cache_dir("audio") / f"{file_key(src)}.wav"
    if not out.exists():
        run(FF + ["-i", resolve(src), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", out])
    return out


def transcribe(src, model_name, language, vocab):
    import warnings
    warnings.filterwarnings("ignore", category=RuntimeWarning)  # harmless numpy/Accelerate noise on macOS
    from faster_whisper import WhisperModel  # imported here so --show works without loading it
    info = ffprobe(src)
    if not info["has_audio"]:
        return {"src": rel(resolve(src)), "duration": info["duration"], "language": None,
                "model": None, "words": [], "segments": [], "no_audio": True}
    wav = extract_wav(src)
    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    # A disfluent prompt nudges Whisper to keep "um/uh" instead of silently cleaning them,
    # which is exactly what we need to find and cut them.
    prompt = "Umm, uh, so like, you know, erm... " + (", ".join(vocab) + "." if vocab else "")
    t0 = time.time()
    segments, meta = model.transcribe(
        str(wav), language=language or None, word_timestamps=True, initial_prompt=prompt,
        condition_on_previous_text=False, vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 400, "speech_pad_ms": 200},
        beam_size=5,
    )
    words, segs = [], []
    for seg in segments:
        segs.append({"s": round(seg.start, 3), "e": round(seg.end, 3), "text": seg.text.strip()})
        for w in seg.words or []:
            words.append({"w": w.word.strip(), "s": round(w.start, 3), "e": round(w.end, 3),
                          "p": round(w.probability, 3)})
    return {"src": rel(resolve(src)), "duration": info["duration"], "language": meta.language,
            "model": model_name, "elapsed": round(time.time() - t0, 1), "words": words, "segments": segs}


def show(tr, gap=0.6):
    """Readable transcript: one line per phrase, pauses marked."""
    log(f"\n== {tr['src']}  ({tc(tr['duration'])}, {len(tr['words'])} words)")
    if not tr["words"]:
        log("   (no speech)")
        return
    line, start, prev_e = [], None, None
    for w in tr["words"]:
        if prev_e is not None and w["s"] - prev_e > gap:
            log(f"  [{tc(start)}] {' '.join(line)}")
            log(f"           ... pause {w['s'] - prev_e:.1f}s")
            line, start = [], None
        if start is None:
            start = w["s"]
        line.append(w["w"] if w["p"] > 0.5 else f"{w['w']}(?)")
        prev_e = w["e"]
    if line:
        log(f"  [{tc(start)}] {' '.join(line)}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("clips", nargs="+")
    ap.add_argument("--model")
    ap.add_argument("--language")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--show", action="store_true", help="print the timed transcript")
    a = ap.parse_args()
    brand = load_brand()
    model = a.model or brand["whisper_model"]
    lang = a.language or brand["language"]
    from .media import expand, is_image
    for clip, _, _ in expand(a.clips):          # folders -> their clips, in capture order
        if is_image(clip):
            continue
        if not resolve(clip).exists():
            die(f"clip not found: {clip}")
        out = transcript_path(clip)
        if out.exists() and not a.force:
            tr = read_json(out)
        else:
            log(f"transcribing {clip} ({describe(ffprobe(clip))}) with {model} ...", flush=True)
            tr = transcribe(clip, model, lang, brand.get("vocab"))
            write_json(out, tr)
            log(f"  -> {rel(out)}  ({len(tr['words'])} words, {tr.get('elapsed', 0)}s)")
        if a.show:
            show(tr)


if __name__ == "__main__":
    main()
