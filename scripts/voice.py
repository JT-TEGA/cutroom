#!/usr/bin/env python3
"""Voice clean-up: make a phone voice memo sound like a proper mic.

  voice.py voiceover/vo.m4a            # clean (cached) + transcribe + show what's said
  voice.py voiceover/vo.m4a --force    # clean again

Chain: high-pass (rumble) -> FFT noise reduction, profiled on the quietest pause -> gain to speech level
-> gentle expander (pauses) -> EQ (less mud, more presence) -> light compression -> de-ess -> loudness -16 LUFS.
Timing is untouched, so transcript times stay valid. Cached in work/_cache/voice/<clip-key>-<settings>.wav.
Settings (brand < preset < brief): voice_clean (voiceover | all | off), voice_denoise_db, voice_deess,
voice_comp_ratio, voice_highpass.
"""
import argparse
import hashlib
import json
import re
import subprocess
import wave

import numpy as np

from common import (FF, PY, SCRIPTS, cache_dir, describe, die, ffprobe, file_key, load_brand, read_json, rel, resolve,
                    run, tc, write_json)
from transcribe import extract_wav

SR = 48000
REF_LUFS = -16.0
KEYS = ("voice_denoise_db", "voice_deess", "voice_comp_ratio", "voice_highpass")


def mode(cfg):
    m = cfg.get("voice_clean", "voiceover")
    if m is True:
        return "voiceover"
    return "off" if m in (False, None, "off", "none", "no") else str(m)


def wanted(cfg, kind):
    """Clean this kind of voice ("vo" = voiceover file, "cam" = to-camera talking)?"""
    m = mode(cfg)
    return m == "all" or (m == "voiceover" and kind == "vo")


def settings_key(cfg):
    return hashlib.sha1(json.dumps({k: cfg[k] for k in KEYS}, sort_keys=True).encode()).hexdigest()[:8]


def _measure(src_args):
    r = subprocess.run(["ffmpeg", "-hide_banner", *src_args, "-af", "loudnorm=print_format=json", "-f", "null", "-"],
                       capture_output=True, text=True)
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", r.stderr)
    return json.loads(m.group(0)) if m else None


def _pcm16k(src):
    with wave.open(str(extract_wav(src))) as f:
        return np.frombuffer(f.readframes(f.getnframes()), np.int16).astype(np.float32) / 32768


def _power(x, hop):
    n = len(x) // hop
    return (x[: n * hop].reshape(n, hop) ** 2).mean(1) if n else np.zeros(0)


def noise_window(src):
    """Quietest pause with room tone in it (not digital silence, not speech): (start, end, dBFS) or None."""
    p = _power(_pcm16k(src), 160)                       # 10 ms frames
    if len(p) < 40:
        return None
    speech = 10 * np.log10(np.percentile(p, 90) + 1e-12)
    for L in (0.5, 0.3, 0.2):
        k = int(L * 100)
        if len(p) <= k + 30:
            continue
        c = np.convolve(p, np.ones(k) / k, mode="valid")
        live = np.convolve((p > 1e-10).astype(float), np.ones(k), mode="valid") >= k
        c = np.where(live, c, np.inf)
        c[:15] = np.inf                                 # skip the record-button click at both ends
        c[-15:] = np.inf
        i = int(np.argmin(c))
        if np.isfinite(c[i]):
            lvl = 10 * np.log10(c[i] + 1e-12)
            if lvl < speech - 15:                       # a real pause, not a quiet word
                return i / 100, (i + k) / 100, round(float(lvl), 1)
    return None


def _decode(path, seconds=None):
    extra = ["-t", str(seconds)] if seconds else []
    r = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(resolve(path)), *extra, "-ac", "1",
                        "-ar", str(SR), "-f", "f32le", "-"], capture_output=True, check=True)
    return np.frombuffer(r.stdout, np.float32)


def _lag(src, processed, window=20.0, max_lag=0.2):
    """Samples the processed file runs late against the original (0 if they don't line up clearly)."""
    from scipy.signal import correlate
    a, b = _decode(src, window), _decode(processed, window)
    n = min(len(a), len(b))
    if n < SR:
        return 0
    c = correlate(b[:n], a[:n], mode="full", method="fft")
    mid, k = n - 1, int(max_lag * SR)
    w = c[mid - k:mid + k + 1]
    i = int(np.argmax(w))
    return max(0, i - k) if w[i] > 4 * np.median(np.abs(w)) else 0


def _level(path, a, b):
    with wave.open(str(path)) as f:
        sr = f.getframerate()
        f.setpos(int(a * sr))
        x = np.frombuffer(f.readframes(int((b - a) * sr)), np.int16).astype(np.float32) / 32768
    return round(float(10 * np.log10((x ** 2).mean() + 1e-12)), 1) if len(x) else None


def clean(src, cfg, force=False):
    """Cleaned 48 kHz mono wav for a voice file -> (path, stats). Cached per file + settings."""
    out = cache_dir("voice") / f"{file_key(src)}-{settings_key(cfg)}.wav"
    meta = out.with_suffix(".json")
    if out.exists() and meta.exists() and not force:
        return out, read_json(meta)
    info = ffprobe(src)
    if not info["has_audio"]:
        die(f"{src} has no audio")
    m = _measure(["-i", str(resolve(src))])
    in_lufs = float(m["input_i"]) if m and float(m["input_i"]) > -70 else None
    if in_lufs is None:
        die(f"{src} is silent")
    nw = noise_window(src)
    nr = float(cfg["voice_denoise_db"])
    gain = min(30.0, max(-10.0, -20.0 - in_lufs))       # bring speech near -20 LUFS before the compressor
    post = [f"volume={gain:.2f}dB"]
    if nr > 0:      # gentle expander: pauses sink up to 12 dB so compression doesn't lift the room back up
        post.append("agate=threshold=-46dB:ratio=1.8:range=-12dB:attack=8:release=220:knee=4:detection=rms")
    post += ["equalizer=f=220:t=q:w=1.1:g=-2", "equalizer=f=4200:t=q:w=0.9:g=2"]   # less mud, more presence
    if float(cfg["voice_comp_ratio"]) > 1:
        post.append(f"acompressor=threshold=-18dB:ratio={float(cfg['voice_comp_ratio']):g}:attack=8:release=150:"
                    "knee=4:makeup=1")
    if float(cfg["voice_deess"]) > 0:
        post.append(f"deesser=i={min(1.0, float(cfg['voice_deess'])):g}:m=0.5:f=0.5:s=o")
    pre = f"aformat=sample_fmts=flt:sample_rates={SR}:channel_layouts=mono,highpass=f={int(cfg['voice_highpass'])}:poles=2"
    nf = min(-20.0, max(-80.0, nw[2] + 8)) if nw else -50.0     # afftdn works best with its floor a bit above the room
    if nr > 0 and nw:
        # play the quietest pause first so the denoiser learns the room before the voice starts, then trim it off
        a, b = int(nw[0] * SR), int(nw[1] * SR)
        g = (f"[0:a]{pre},asplit=2[a][b];[a]atrim=start_sample={a}:end_sample={b},asetpts=PTS-STARTPTS[n];"
             f"[b]asetpts=PTS-STARTPTS[m];[n][m]concat=n=2:v=0:a=1,"
             f"asendcmd=c='0.0 afftdn sn start',asendcmd=c='{(b - a) / SR - 0.02:.3f} afftdn sn stop',"
             f"afftdn=nr={nr:g}:nf={nf:g}:tn=1,atrim=start_sample={b - a},asetpts=PTS-STARTPTS,{','.join(post)}[v]")
    elif nr > 0:
        g = f"[0:a]{pre},afftdn=nr={nr:g}:nf={nf:g}:tn=1,{','.join(post)}[v]"
    else:
        g = f"[0:a]{pre},{','.join(post)}[v]"
    tmp = out.with_suffix(".tmp.wav")
    run(FF + ["-i", resolve(src), "-filter_complex", g, "-map", "[v]", "-c:a", "pcm_f32le", tmp])
    lag = _lag(src, tmp)                                  # afftdn delays the sound ~25 ms: put it back in sync
    mm = _measure(["-i", str(tmp)])
    ln = (f"atrim=start_sample={lag},asetpts=PTS-STARTPTS,apad=pad_len={lag},"
          f"loudnorm=I={REF_LUFS}:TP=-1.5:LRA=11:measured_I={mm['input_i']}:measured_TP={mm['input_tp']}:"
          f"measured_LRA={mm['input_lra']}:measured_thresh={mm['input_thresh']}:offset={mm['target_offset']}:"
          f"linear=true,aresample={SR}")
    run(FF + ["-i", tmp, "-af", ln, "-ar", str(SR), "-ac", "1", "-c:a", "pcm_s16le", out])
    tmp.unlink()
    after = _measure(["-i", str(out)])
    lufs_after = round(float(after["input_i"]), 1) if after else None
    noise_after = _level(out, nw[0], nw[1]) if nw else None
    stats = {"src": rel(resolve(src)), "lufs_before": round(in_lufs, 1), "lufs_after": lufs_after,
             "noise_window": [nw[0], nw[1]] if nw else None, "noise_before": nw[2] if nw else None,
             "noise_after": noise_after, "lag_samples": lag,
             # how far the room sits under the voice, before and after
             "snr_before": round(in_lufs - nw[2], 1) if nw else None,
             "snr_after": round(lufs_after - noise_after, 1) if nw and lufs_after is not None and noise_after else None,
             "chain": {k: cfg[k] for k in KEYS}}
    write_json(meta, stats)
    return out, stats


def source(src, cfg, kind):
    """The file to read a voice from: the cleaned wav when cleaning is on for this kind, else the original."""
    return clean(src, cfg)[0] if wanted(cfg, kind) else resolve(src)


def summary(stats):
    bits = []
    if stats.get("snr_before") is not None and stats.get("snr_after") is not None:
        bits.append(f"background noise {stats['snr_before']:.0f} -> {stats['snr_after']:.0f} dB under the voice")
    bits.append(f"loudness {stats['lufs_before']:.0f} -> {stats['lufs_after']:.0f} LUFS")
    c = stats["chain"]
    bits.append(f"denoise {c['voice_denoise_db']:g} dB, de-ess {c['voice_deess']:g}, comp {c['voice_comp_ratio']:g}:1")
    return ", ".join(bits)


def preview(src, keeps, out, cfg):
    """The voiceover as it will sound in the edit (cleaned, fillers and silences cut) -> wav to listen to."""
    x = _decode(source(src, cfg, "vo"))
    f = int(0.01 * SR)
    parts = []
    for k in keeps:
        c = x[int(k["in"] * SR):int(k["out"] * SR)].copy()
        if len(c) > 2 * f:
            c[:f] *= np.linspace(0, 1, f)
            c[-f:] *= np.linspace(1, 0, f)
        parts.append(c)
    y = np.concatenate(parts) if parts else np.zeros(1, np.float32)
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(y, -1, 1) * 32767).astype(np.int16).tobytes())
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+")
    ap.add_argument("--force", action="store_true", help="clean again even if cached")
    ap.add_argument("--no-show", action="store_true", help="don't print the transcript")
    a = ap.parse_args()
    cfg = load_brand()
    for f in a.files:
        if not resolve(f).exists():
            die(f"not found: {f}")
        print(f"VOICE {f}  [{describe(ffprobe(f))}]")
        path, stats = clean(f, cfg, a.force)
        print(f"  cleaned -> {rel(path)}\n  {summary(stats)}")
        if stats.get("noise_window"):
            print(f"  noise profile from the pause at {tc(stats['noise_window'][0])}")
        subprocess.run([str(PY), str(SCRIPTS / "transcribe.py"), f] + ([] if a.no_show else ["--show"]), check=True)


if __name__ == "__main__":
    main()
