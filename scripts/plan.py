#!/usr/bin/env python3
"""Show an edit plan as a short timeline (timestamp -> what happens). Nothing is rendered.

  plan.py my-video          # timeline + problems
  plan.py my-video --cuts   # + everything removed from the raw clips, and why

Voiceover blocks show the match-up: each B-roll shot with the words heard over it and why it was picked.
"""
import argparse

import edl as E
import voice
from common import resolve, style_for, tc


def zoom_desc(z):
    if isinstance(z, (int, float)):
        return "" if z == 1 else f"zoom {z:g}x"
    if not z:
        return ""
    return "zoom " + " > ".join(f"{k[1]:g}x@{k[0]:g}s" + (" cut" if len(k) > 2 else "") for k in z)


def ramp_name(curve):
    return next((k for k, v in E.RAMPS.items() if v == curve and isinstance(k, str)), "custom")


def side(sub):
    return f"{sub['src']}" + (f" @{tc(sub.get('in', 0))}" if "in" in sub else "")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("name")
    ap.add_argument("--cuts", action="store_true")
    a = ap.parse_args()
    edl = E.load(a.name)
    cfg = style_for(edl)
    problems = E.validate(edl)
    if problems:
        print("PROBLEMS:\n  - " + "\n  - ".join(problems))
        return
    items, grid = E.build_timeline(edl, cfg)
    total = items[-1]["end"]

    rows = []
    for it in items:
        seg = it["seg"]
        lab = f"[{it['label']}] " if it["label"] and it["kind"] != "endcard" else ""
        tr = f"{it['trans_in']} > " if it["trans_in"] else ""
        d = f"({it['end'] - it['start']:.2f}s{', on beat' if it['beat_synced'] else ''})"
        bits = []
        if it["kind"] == "clip":
            bits.append(f"{it['src']} {tc(it['in'], 2)}-{tc(it['out'], 2)}")
            if it["speed"] != 1:
                bits.append(f"{it['speed']:g}x" + (" slow-mo" if it["speed"] < 1 else ""))
            if it["ramp"]:
                bits.append(f"ramp {ramp_name(it['ramp'])}")
            if seg.get("fit") == "blur":
                bits.append("full frame on blur")
            role = E.seg_role(it, edl, cfg)
            if it.get("vo") is not None:
                bits.append("real sound under VO" if role == "ambient" else "B-roll")
            else:
                bits.append({"voice": "talking", "ambient": "real sound", "mute": "muted"}[role])
        elif it["kind"] == "image":
            bits.append(f"photo {it['src']}" + (f" kb-{seg['kb']}" if seg.get("kb") else ""))
        elif it["kind"] == "compare":
            mode = seg.get("mode", cfg["compare_mode"])
            bits.append(f"{mode.upper()} before {side(seg['a'])} | after {side(seg['b'])}")
            if seg.get("labels"):
                bits.append(f"labels {seg['labels'][0]!r} / {seg['labels'][1]!r}")
        elif it["kind"] == "color":
            bits.append(f"{seg.get('color', '#000')} card")
        else:
            ec = it["endcard"]
            bits.append(f"END CARD {ec['handle']}" + (f" + {ec['text']!r}" if ec["text"] else "") + f" ({ec['background']})")
        zd = zoom_desc(seg.get("zoom", 1.0)) if it["kind"] != "endcard" else ""
        if zd:
            bits.append(zd)
        say = f'  "{seg["text"]}"' if seg.get("text") else ""
        blk = it.get("vo")
        if blk is not None:
            heard = " ".join(w["w"] for w in blk["words"] if it["start"] - 0.02 <= w["s"] < it["end"] - 0.02)
            why = seg.get("why") or (f'cue "{seg["cue"]}"' if seg.get("cue") else "")
            say = f'  VO "{heard}"' + (f"  <- {why}" if why else "")
            if it is next(i for i in items if i.get("vo") is blk):
                rows.append((it["start"], -1, f"   == VOICEOVER {blk['src']}{' [' + blk['label'] + ']' if blk['label'] else ''}"
                                              f": {len(blk['pieces'])} piece(s), {blk['dur']:.1f}s =="))
        warn = f"  !! {it['warn']}" if it.get("warn") else ""
        rows.append((it["start"], 0, f"{tr}#{it['idx']} {lab}{', '.join(bits)} {d}{say}{warn}"))
    for b in edl.get("broll", []):
        span = dict(b)
        if "out" in b and "dur" not in b and "end" not in b:
            span["dur"] = (float(b["out"]) - float(b.get("in", 0))) / float(b.get("speed", 1))
        s, e = E.resolve_span(span, items)
        rows.append((s, 1, f"   B-ROLL over voice: {b['src']} from {tc(b.get('in', 0))} until {tc(e)}"
                           + (f'  <- cue "{b["cue"]}"' if b.get("cue") else "")))
    for x in edl.get("text", []):
        s, e = E.resolve_span(x, items)
        what = x.get("text", "")
        if x.get("sub"):
            what += f" / {x['sub']}"
        if x.get("items"):
            what += " " + ", ".join(i if isinstance(i, str) else " ".join(i) for i in x["items"])
        if x.get("lines"):
            what += " " + " | ".join(x["lines"])
        rows.append((s, 2, f"   {x.get('style', 'big').upper()} \"{what.strip()}\" until {tc(e)}"))
    for g in edl.get("graphics", []):
        s, e = E.resolve_span(g, items)
        rows.append((s, 2, f"   GRAPHIC {g['src']} until {tc(e)}"))
    for f in edl.get("flash", []):
        s = E.resolve_span(f, items)[0] if isinstance(f, dict) else float(f)
        rows.append((s, 3, "   FLASH"))
    for s in edl.get("sfx", []):
        t, _ = E.resolve_span(s, items)
        rows.append((t, 3, f"   SFX {resolve(s['src']).stem} ({s.get('gain_db', -6)} dB)"))
    if grid:
        for d in grid["drops"]:
            if d <= total:
                rows.append((d, 4, "   ~~ music drop ~~"))

    print(f"\nPLAN {a.name}: {total:.1f}s" + (f" (target {edl['target_length']:g}s)" if edl.get("target_length") else "")
          + f", {sum(1 for i in items if i['kind'] != 'endcard')} shots"
          + (f", preset {edl['preset']}" if edl.get("preset") else "") + f", grade {cfg['grade']}"
          + (f", grain {cfg['grain']}" if cfg["grain"] else "") + "\n")
    for t, _, txt in sorted(rows, key=lambda r: (r[0], r[1])):
        print(f"{tc(t):>7}  {txt}")
    print(f"{tc(total):>7}  END")

    if E.captions_enabled(edl, cfg):
        ec = next((i for i in items if i["kind"] == "endcard"), None)
        words = E.caption_words(edl, items, cfg)
        pages = E.caption_pages(words, cfg, ec["start"] if ec else total)
        print(f"\nCAPTIONS: {'talking + voiceover' if E.vo_blocks(items) else 'talking parts only'}, "
              f"{len(words)} words in {len(pages)} pops "
              f"({cfg['caption_font']} {cfg['caption_weight']}, {cfg['caption_case']})")
        cap = edl.get("captions") or {}
        if cap.get("replace"):
            print("  fixes: " + ", ".join(f"{k} -> {v}" for k, v in cap["replace"].items()))
    else:
        print("\nCAPTIONS: off")
    blocks = E.vo_blocks(items)
    if blocks:
        srcs = ", ".join(dict.fromkeys(b["src"] for b in blocks))
        c = {k: cfg[k] for k in voice.KEYS}
        print(f"VOICEOVER: {srcs}, {sum(b['dur'] for b in blocks):.1f}s in {len(blocks)} block(s), "
              + (f"cleaned (denoise {c['voice_denoise_db']:g} dB, de-ess {c['voice_deess']:g}, "
                 f"comp {c['voice_comp_ratio']:g}:1, -16 LUFS)" if voice.wanted(cfg, "vo") else "not cleaned")
              + "; B-roll muted under it unless \"ambient\"")
    m = edl.get("music") or {}
    if m.get("src"):
        bs = edl.get("beat_sync") or {}
        every = bs.get("every", cfg["beat_every"])
        print(f"MUSIC: {m['src']}, {grid['bpm']} BPM, starts at {tc(grid['start'], 2)} of the track"
              + (f" (requested {m.get('start')})" if isinstance(m.get("start"), str) else "")
              + (f", cuts every {every} beat(s)" if every else "")
              + (f", every {cfg['beat_every_after_drop']} after the drop" if cfg["beat_every_after_drop"] else "")
              + f", mode {cfg['music_mode']}"
              + (", ducks under voice" if cfg["duck"] and (blocks or any(E.seg_role(i, edl, cfg) == "voice" for i in items))
                 else ""))
    else:
        print("MUSIC: none")
    if edl.get("notes"):
        print("\nNOTES:\n  - " + "\n  - ".join(edl["notes"]))
    if a.cuts:
        rep = E.removed_report(edl)
        print(f"\nREMOVED FROM RAW ({sum(r['out'] - r['in'] for r in rep):.1f}s total):")
        for r in rep:
            print(f"  {r['src']} {tc(r['in'], 2)}-{tc(r['out'], 2)}  {r['why']}")


if __name__ == "__main__":
    main()
