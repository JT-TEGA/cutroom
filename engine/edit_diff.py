"""What the creator changed in Claude's plan, as general rules ("edit notes").

``diff(proposed, final)`` compares the plan Claude proposed with the one the creator approved and returns one
``Edit`` per habit it shows: the rule in plain words ("Shortens the intro shots to under 2 s"), a stable key so the
same habit adds up across videos, the topic (so a brief field can override it) and what happened in this video.
Pure functions over Timelines (and their resolved views, for timing); no brain call.
"""
from __future__ import annotations

import math
import re

from pydantic import BaseModel

from .media import is_image
from .timeline import Segment, TextOverlay, Timeline, TimelineView

INTRO_S = 3.0           # segments that start before this are "the intro"
MIN_RATIO = 0.15        # a length change under 15% ...
MIN_DELTA = 0.25        # ... or under 0.25 s is noise

NOUN = {"voiceover": "voiceover part", "photo": "photo", "before/after": "before/after", "colour card": "colour card",
        "talking": "talking shot", "B-roll": "B-roll shot", "clip": "clip"}
PLURAL = {k: v + "s" for k, v in NOUN.items()}
A_NOUN = {k: ("an " if v[0] in "aeiou" else "a ") + v for k, v in NOUN.items()}


class Edit(BaseModel):
    key: str            # stable id of the general rule: "timing.intro-shorter"
    topic: str          # order | hook | timing | length | shots | footage | text | captions | transitions | end_card
    rule: str           # the general rule, for the brain and the creator
    instance: str       # what happened in this video


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def kind(seg: Segment, talky: bool) -> str:
    t = seg.type or ("image" if seg.src and is_image(seg.src) else "clip")
    if t != "clip":
        return {"vo": "voiceover", "image": "photo", "compare": "before/after", "color": "colour card"}[t]
    if seg.talk or seg.text:
        return "talking"
    return "B-roll" if talky else "clip"


def _talky(tl: Timeline) -> bool:
    return any(s.type == "vo" or s.talk or s.text for s in tl.segments)


def _ident(seg: Segment) -> tuple:
    if seg.type == "compare":
        return ("compare", seg.a.src if seg.a else None, seg.b.src if seg.b else None)
    if seg.type == "color":
        return ("color", seg.color)
    return (seg.type or "", seg.src)


def match(p: list[Segment], f: list[Segment]) -> tuple[list[tuple[int, int]], list[tuple[int, int]], list[int]]:
    """(kept pairs, swapped pairs, deleted P indexes) as (P index, F index). A segment is the same one when it shows
    the same file (in the same place first: a trimmed shot is still that shot, even when its new start is nearer
    another shot from the clip); what's left on both sides pairs up by position as a swap."""
    used: set[int] = set()
    kept: list[tuple[int, int]] = []
    same_place = {i for i in range(min(len(p), len(f))) if _ident(p[i]) == _ident(f[i])}
    for fi, fs in enumerate(f):
        cands = [pi for pi, ps in enumerate(p) if pi not in used and _ident(ps) == _ident(fs)]
        if fi in same_place and fi in cands:
            cands = [fi]
        if cands:
            pi = min(cands, key=lambda i: (abs((p[i].in_ or 0) - (fs.in_ or 0)), abs(i - fi)))
            used.add(pi)
            kept.append((pi, fi))
    matched_f = {fi for _, fi in kept}
    swaps: list[tuple[int, int]] = []
    for fi in (i for i in range(len(f)) if i not in matched_f):
        left = [pi for pi in range(len(p)) if pi not in used]
        if not left:
            break
        pi = min(left, key=lambda i: abs(i - fi))
        used.add(pi)
        swaps.append((pi, fi))
    return kept, swaps, [pi for pi in range(len(p)) if pi not in used]


def _lis(seq: list[int]) -> set[int]:
    """Positions in seq that form a longest increasing run (what stayed in order)."""
    if not seq:
        return set()
    best = [1] * len(seq)
    prev = [-1] * len(seq)
    for i in range(len(seq)):
        for j in range(i):
            if seq[j] < seq[i] and best[j] + 1 > best[i]:
                best[i], prev[i] = best[j] + 1, j
    i = max(range(len(seq)), key=lambda k: best[k])
    out = set()
    while i >= 0:
        out.add(i)
        i = prev[i]
    return out


def _spans(view: TimelineView | None) -> dict[tuple[int, int | None], tuple[float, float]]:
    """(segment index, shot index in a voiceover block or None) -> (output start, duration) from a resolved view."""
    return {(s.segment, s.shot): (s.start, s.duration) for s in (view.shots if view else [])}


def _timed(P: list[Segment], F: list[Segment], pi: int, fi: int) -> list[tuple[int | None, int | None]]:
    """The shots of a kept pair whose length to compare. A voiceover block is as long as the voiceover, so its B-roll
    shots count one by one, and only those the creator re-timed (the editor pins the next shot's start: its "at"
    changed); the shots around them just share out the rest of the block."""
    if P[pi].type == "vo" and F[fi].type == "vo":
        ps, fs = P[pi].shots or [], F[fi].shots or []
        return [(j, j) for j in range(min(len(ps), len(fs)) - 1) if fs[j + 1].at != ps[j + 1].at]
    return [(None, None)]


def _trans(x: object) -> str:
    return getattr(x, "transition", None) or "cut"


def _words(t: str | None) -> int:
    return len((t or "").split())


def _text_of(x: TextOverlay) -> str:
    return " / ".join(filter(None, [x.text, x.sub]))


def diff(proposed: Timeline, final: Timeline, pv: TimelineView | None = None,
         fv: TimelineView | None = None) -> list[Edit]:
    """The creator's changes from ``proposed`` to ``final`` as general edit notes (one per key)."""
    P, F = proposed.segments, final.segments
    tp, tf = _talky(proposed), _talky(final)
    kp = [kind(s, tp) for s in P]
    kf = [kind(s, tf) for s in F]
    out: dict[str, Edit] = {}

    def add(key: str, topic: str, rule: str, instance: str) -> None:
        if key in out:
            out[key].instance += "; " + instance
        else:
            out[key] = Edit(key=key, topic=topic, rule=rule, instance=instance)

    kept, swaps, deleted = match(P, F)
    pairs = sorted(kept + swaps, key=lambda x: x[1])

    # --- order: what left its place, and which kinds of shot it now comes before
    stayed = _lis([pi for pi, _ in pairs])
    befores: set[tuple[str, str]] = set()
    for n, (pi, fi) in enumerate(pairs):
        if n in stayed:
            continue
        for pj, fj in pairs:
            a, b = None, None
            if pj < pi and fj > fi:
                a, b = kf[fi], kf[fj]
            elif pj > pi and fj < fi:
                a, b = kf[fj], kf[fi]
            if a and b and a != b:
                befores.add((a, b))
        for a, b in sorted(befores - {(b, a) for a, b in befores}):
            add(f"order.{slug(a)}-before-{slug(b)}", "order", f"Puts {PLURAL[a]} before {PLURAL[b]}",
                f"moved shot {pi + 1} ({NOUN[kf[fi]]}) to position {fi + 1}")
        befores.clear()

    # --- the hook: a different first shot than Claude's
    first = next((pi for pi, fi in pairs if fi == 0), None)
    if F and (first != 0 or (0, 0) in swaps):
        if kf[0] != kp[0]:
            add(f"hook.{slug(kf[0])}", "hook", f"Opens on {A_NOUN[kf[0]]}",
                f"opened on {F[0].src or NOUN[kf[0]]} instead of Claude's {NOUN[kp[0]]}")
        else:
            add("hook.different", "hook", "Often changes Claude's opening shot: pick the hook with extra care (the "
                "brief's hook, else the single most striking moment)",
                f"opened on {F[0].src or NOUN[kf[0]]} instead of {P[0].src or NOUN[kp[0]]}")

    # --- deleted segments
    middle = [pi for pi in deleted if 0 < pi < len(P) - 1]
    for pi in deleted:
        if pi == len(P) - 1 and len(P) > 1:
            add(f"shots.drop-closing-{slug(kp[pi])}", "shots", f"Drops the closing {NOUN[kp[pi]]}",
                f"cut the last shot ({P[pi].src or NOUN[kp[pi]]})")
    if len(middle) >= 2 or (middle and (len(P) - len(F)) / len(P) >= 0.25):
        add("shots.fewer", "shots", "Uses fewer shots than Claude plans", f"{len(P)} shots → {len(F)}")
    elif middle:
        k = kp[middle[0]]
        add(f"shots.fewer-{slug(k)}", "shots", f"Uses fewer {PLURAL[k]} than Claude plans",
            f"cut {P[middle[0]].src or NOUN[k]}")

    # --- swapped footage
    for pi, fi in swaps:
        if kp[pi] != kf[fi]:
            add(f"footage.{slug(kf[fi])}-over-{slug(kp[pi])}", "footage",
                f"Prefers {PLURAL[kf[fi]]} over {PLURAL[kp[pi]]}", f"{P[pi].src} → {F[fi].src}")
        elif fi != 0:
            add("footage.swaps", "footage", "Replaces some of Claude's clip picks with other footage: weigh which "
                "take or angle fits each moment", f"{P[pi].src} → {F[fi].src}")

    # --- voiceover B-roll: re-picked or fewer shots
    for pi, fi in kept:
        ps, fs = P[pi].shots or [], F[fi].shots or []
        if P[pi].type != "vo":
            continue
        if len(fs) < len(ps):
            add("shots.fewer-vo-broll", "shots", "Uses fewer B-roll shots under the voiceover",
                f"{len(ps)} → {len(fs)} shots")
        changed = [f"{a.src} → {b.src}" for a, b in zip(ps, fs) if a.src != b.src]
        if changed and len(fs) == len(ps):
            add("footage.vo-broll", "footage", "Often re-picks the B-roll under the voiceover: check each shot shows "
                "what is being said", ", ".join(changed))

    # --- timing (needs the laid-out views)
    sp, sf = _spans(pv), _spans(fv)
    intro: list[tuple[float, float]] = []
    rest: list[tuple[float, float]] = []
    timed = [((pi, pj), (fi, fj)) for pi, fi in pairs for pj, fj in _timed(P, F, pi, fi)]
    for kp, kf in timed:
        if kp not in sp or kf not in sf:
            continue
        (start, dp), (_, df) = sp[kp], sf[kf]
        if dp <= 0 or abs(df - dp) < MIN_DELTA or abs(df - dp) / dp < MIN_RATIO:
            continue
        (intro if start < INTRO_S else rest).append((dp, df))
    if intro:
        how = ", ".join(f"{dp:.1f} s → {df:.1f} s" for dp, df in intro)
        if all(df < dp for dp, df in intro):
            cap = math.ceil((max(df for _, df in intro) + 0.01) * 2) / 2
            add("timing.intro-shorter", "timing", f"Shortens the intro shots to under {cap:g} s", how)
        elif all(df > dp for dp, df in intro):
            avg = sum(df for _, df in intro) / len(intro)
            add("timing.intro-longer", "timing", f"Holds the intro shots longer (about {avg:.1f} s each)", how)
    if len(rest) >= 2:
        ratio = sum(df / dp for dp, df in rest) / len(rest)
        avg = sum(df for _, df in rest) / len(rest)
        how = f"{len(rest)} shots, now about {avg:.1f} s each"
        if ratio < 1 - MIN_RATIO:
            add("timing.shorter", "timing", f"Cuts shots shorter than Claude plans (about {avg:.1f} s each)", how)
        elif ratio > 1 + MIN_RATIO:
            add("timing.longer", "timing", f"Lets shots run longer than Claude plans (about {avg:.1f} s each)", how)
    if pv and fv and pv.duration > 0 and abs(fv.duration - pv.duration) >= 2:
        r = fv.duration / pv.duration
        how = f"{pv.duration:.0f} s → {fv.duration:.0f} s"
        if r < 1 - MIN_RATIO:
            add("length.shorter", "length", "Keeps edits shorter than Claude plans", how)
        elif r > 1 + MIN_RATIO:
            add("length.longer", "length", "Lets edits run longer than Claude plans", how)

    # --- end card
    if pv and fv:
        had, has = pv.end_card is not None, fv.end_card is not None
    else:
        had = bool(proposed.end_card and proposed.end_card.enabled)
        has = bool(final.end_card and final.end_card.enabled)
    if had and not has:
        add("end_card.off", "end_card", "Turns the end card off", "removed the end card")
    elif has and not had:
        add("end_card.on", "end_card", "Adds the handle end card", "turned the end card on")

    # --- captions: the whole edit, then per shot
    if pv and fv and pv.captions.get("enabled") is not None and fv.captions.get("enabled") is not None:
        before, after = bool(pv.captions["enabled"]), bool(fv.captions["enabled"])
    else:
        before = proposed.captions.enabled is not False
        after = final.captions.enabled is not False
    if before and not after:
        add("captions.off", "captions", "Turns captions off", "captions off for the whole edit")
    elif after and not before:
        add("captions.on", "captions", "Turns captions on", "captions on for the whole edit")
    for pi, fi in pairs:
        was, now = P[pi].captions is not False, F[fi].captions is not False
        hook = fi == 0 or F[fi].label == "hook"
        if was and not now:
            if hook:
                add("captions.off-hook", "captions", "No captions on the hook", f"hid captions on shot {fi + 1}")
            else:
                add("captions.off-shots", "captions", "Hides captions on some talking shots",
                    f"hid captions on shot {fi + 1}")
        elif now and not was:
            add("captions.on-shots", "captions", "Wants captions on every talking shot", f"shot {fi + 1}")

    # --- transitions (into each shot, and into each B-roll shot of a voiceover block)
    changes: list[tuple[str, str, int]] = []
    for pi, fi in pairs:
        changes.append((_trans(P[pi]), _trans(F[fi]), fi))
        for a, b in zip(P[pi].shots or [], F[fi].shots or []):
            changes.append((_trans(a), _trans(b), fi))
    for old, new, fi in changes:
        if old == new:
            continue
        if new == "cut":
            add("transitions.fewer", "transitions", "Prefers straight cuts: fewer transitions",
                f"took the {old} off shot {fi + 1}")
        elif old == "cut":
            add(f"transitions.add-{new}", "transitions", f"Adds {new} transitions between shots",
                f"{new} into shot {fi + 1}")
        else:
            add(f"transitions.{new}-over-{old}", "transitions", f"Prefers {new} transitions over {old}",
                f"shot {fi + 1}")

    # --- text on screen
    _text_diff(proposed, final, pv, add)
    return list(out.values())


def _on_hook(x: TextOverlay, tl: Timeline, view: TimelineView | None, i: int) -> bool:
    first = tl.segments[0].label
    if x.on in ("#1", "hook") or (first and x.on == first):
        return True
    o = next((o for o in (view.overlays if view else []) if o.kind == "text" and o.index == i), None)
    return bool(o and o.start < 1.0)


def _text_diff(proposed: Timeline, final: Timeline, pv: TimelineView | None, add) -> None:
    pt, ft = proposed.text, final.text
    used_p: set[int] = set()
    used_f: set[int] = set()
    for fi, x in enumerate(ft):              # unchanged: same words, same style
        pi = next((i for i, y in enumerate(pt) if i not in used_p and _text_of(y) == _text_of(x)
                   and y.style == x.style), None)
        if pi is not None:
            used_p.add(pi)
            used_f.add(fi)
    def likeness(a: TextOverlay, b: TextOverlay) -> tuple[float, bool]:
        wa, wb = set(_text_of(a).lower().split()), set(_text_of(b).lower().split())
        return len(wa & wb) / max(1, len(wa | wb)), a.style == b.style

    edited: list[tuple[int, int]] = []
    for fi in (i for i in range(len(ft)) if i not in used_f):     # edited: the most alike leftover (words, style)
        left = [i for i in range(len(pt)) if i not in used_p and any(likeness(pt[i], ft[fi]))]
        if not left:
            continue
        pi = max(left, key=lambda i: (*likeness(pt[i], ft[fi]), -abs(i - fi)))
        used_p.add(pi)
        used_f.add(fi)
        edited.append((pi, fi))
    added = [fi for fi in range(len(ft)) if fi not in used_f]
    removed = [pi for pi in range(len(pt)) if pi not in used_p]

    longest = max((_words(x.text) for x in ft), default=0)
    for pi, fi in edited:
        a, b = pt[pi], ft[fi]
        if (a.style or "default") != (b.style or "default"):
            add(f"text.{slug(b.style or 'default')}-over-{slug(a.style or 'default')}", "text",
                f"Prefers the {b.style or 'default'} text style over {a.style or 'default'}",
                f'"{_text_of(b)}" as {b.style}')
        if _text_of(a) == _text_of(b):
            continue
        how = f'"{_text_of(a)}" → "{_text_of(b)}"'
        ta, tb = a.text or "", b.text or ""
        if "*" in ta and "*" not in tb:
            add("text.no-emphasis", "text", "Leaves the emphasis colour off on-screen text", how)
        elif tb and tb == ta.lower() and tb != ta:
            add("text.lowercase", "text", "Writes on-screen text in lowercase", how)
        elif tb and tb == ta.upper() and tb != ta:
            add("text.uppercase", "text", "Writes on-screen text in capitals", how)
        elif _words(tb) <= _words(ta) - 2 or (_words(ta) and _words(tb) / _words(ta) <= 0.7):
            add("text.shorter", "text", f"Keeps on-screen text short (at most {max(longest, 1)} words)", how)
        else:
            add("text.rewrite", "text", "Rewrites Claude's on-screen text in their own words", how)

    if removed and len(removed) == len(pt) and not ft:
        add("text.none", "text", "Prefers no text on screen beyond what the brief asks for",
            ", ".join(f'"{_text_of(pt[i])}"' for i in removed))
    else:
        for pi in removed:
            x = pt[pi]
            if _on_hook(x, proposed, pv, pi):
                add("text.none-on-hook", "text", "Keeps text off the hook (the first 1-2 s)", f'"{_text_of(x)}"')
            else:
                st = x.style or "default"
                add(f"text.fewer-{slug(st)}", "text", f"Uses fewer {st} labels than Claude adds", f'"{_text_of(x)}"')
    for fi in added:
        x = ft[fi]
        if x.on in ("#1", "hook") or (final.segments[0].label and x.on == final.segments[0].label):
            add("text.title-on-hook", "text", "Puts a title on the hook", f'"{_text_of(x)}"')
        else:
            st = x.style or "default"
            add(f"text.add-{slug(st)}", "text", f"Adds {st} labels Claude didn't plan", f'"{_text_of(x)}"')


# ---------------------------------------------------------------- notes that contradict each other

OPPOSITE = {frozenset(p) for p in [
    ("timing.intro-shorter", "timing.intro-longer"), ("timing.shorter", "timing.longer"),
    ("length.shorter", "length.longer"), ("end_card.off", "end_card.on"), ("captions.off", "captions.on"),
    ("captions.off-shots", "captions.on-shots"), ("text.none-on-hook", "text.title-on-hook"),
    ("text.lowercase", "text.uppercase")]}


def opposes(a: str, b: str) -> bool:
    """Whether edit note ``b`` goes against note ``a`` (turning the end card back on, after "Turns the end card
    off"): the creator undoing or contradicting that habit."""
    if a == b:
        return False
    if frozenset((a, b)) in OPPOSITE:
        return True
    ta, _, ra = a.partition(".")
    tb, _, rb = b.partition(".")
    if ta != tb:
        return False
    for sep in ("-over-", "-before-"):          # clips over photos <-> photos over clips; order the other way
        if sep in ra and sep in rb and ra.split(sep)[::-1] == rb.split(sep):
            return True
    if ta == "hook":                            # opens on a talking shot <-> opens on B-roll
        return "different" not in (ra, rb)
    pair = {ra, rb}
    if ta == "text":                            # fewer stickers <-> adds stickers; no text <-> adds text
        return (any(r.startswith("fewer-") and "add-" + r[6:] in pair for r in pair)
                or ("none" in pair and any(r.startswith("add-") or r == "title-on-hook" for r in pair)))
    if ta == "transitions":                     # straight cuts <-> adds flash transitions
        return "fewer" in pair and any(r.startswith("add-") for r in pair)
    return False
