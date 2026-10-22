"""Montage reels: fast cuts that land on the beat of a bassy bed, with varied transitions.

Two modes share one engine: "visual" (silent Creative Commons shots, the music up front) and "speech"
(rapid fire one-liners from a podcast, captions on, the music under the voices).
"""
import json
import math
import random
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

from engine import clipper

TEMPLATE = clipper.SKILL_DIR / "assets" / "reel" / "montage.html"
SR, N_FFT, HOP = 22050, 1024, 256
FPS = 30
BPM_RANGE = (70, 180)
ONSET_LAG = 0.012  # spectral flux peaks ~12 ms before the hit (measured on click tracks); a calibration knob
LOW_HZ = 150  # the bass band: kick and 808
VISUAL_BEATS = (2, 8)  # shot length in beats, visual montages
REEL_SECONDS = (15, 30)
HOOK_MIN = 1.5  # the opening shot holds the headline at least this long; the drop lands on its cut
TEXT_BEAT_WORDS = 5
LEAD, TAIL = 0.2, 0.3  # air around a spoken line, so no word starts or ends clipped
# mix levels (HyperFrames volumes; the beds are mastered to -14 LUFS, the whole mix is normalised after)
VISUAL_MUSIC, VISUAL_FOOTAGE = 1.0, 0.12  # the music carries a visual montage; machines and ambience stay faint
SPEECH_MUSIC, SPEECH_DUCK = 0.60, 0.45  # level B: the bass stays clearly audible under the voices
SPEECH_FOOTAGE = 1.0
TARGET_LUFS = -14
EASE_IN, EASE_OUT = 0.3, 0.7  # seconds the reel fades in from black and out at the end, picture and sound
TRANSITIONS = {"visual": ("whip", "zoom", "flash", "glitch", "shake", "ramp"),
               "speech": ("zoomblur", "whip", "glitchzoom")}  # every rapid fire cut is a clean hit with a sound
SMALL_FACE, WIDE_SHOT_KEEP = 0.06, 0.55  # a face under 6% of the width is a wide shot: crop to 55% of the height
OUT_W, OUT_H = clipper.OUT_W, clipper.OUT_H
SFX_GAP = 2.0  # seconds between transition sound effects


# --- beats ---

def decode(path, sr=SR):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32)


def onsets(x, sr=SR):
    """Spectral flux (all bands) and bass energy per hop."""
    x = np.concatenate([x, np.zeros(N_FFT, dtype=np.float32)])
    frames = np.lib.stride_tricks.sliding_window_view(x, N_FFT)[::HOP] * np.hanning(N_FFT).astype(np.float32)
    mag = np.abs(np.fft.rfft(frames, axis=1))
    flux = np.concatenate([[0.0], np.maximum(0, np.diff(np.log1p(100 * mag), axis=0)).sum(axis=1)])
    low = mag[:, 1:int(LOW_HZ * N_FFT / sr) + 1].sum(axis=1)
    return flux, low


def beat_grid(path=None, samples=None, sr=SR):
    """Tempo, beat times, downbeats and bass energy of a music bed: autocorrelation picks the tempo, then a fine
    comb search sets the exact period and phase so the grid stays on the beat for the whole reel."""
    x = decode(path, sr) if samples is None else samples
    flux, low = onsets(x, sr)
    fps = sr / HOP
    env = flux - np.convolve(flux, np.ones(16) / 16, "same")  # local mean removed: peaks are onsets
    env = np.maximum(env, 0)
    e = env - env.mean()
    ac = np.correlate(e, e, "full")[len(e) - 1:]
    lo, hi = int(fps * 60 / BPM_RANGE[1]), int(fps * 60 / BPM_RANGE[0]) + 1
    lags = np.arange(lo, hi)
    peak = lambda n: ac[max(0, n - 1):n + 2].max() if n + 1 < len(ac) else 0.0  # noqa: E731
    # a 4/4 beat also repeats at 2 and 4 beats (half and whole bars), which a triplet feel (2/3 tempo) does not
    comb = np.array([peak(n) + peak(2 * n) + peak(4 * n) for n in lags])
    prior = np.exp(-0.5 * (np.log2(60 * fps / lags / 120)) ** 2)  # octave errors lean to ~120 BPM
    lag = lags[np.argmax(comb * prior)]
    times = (np.arange(len(env)) * HOP + N_FFT / 2) / sr  # a frame's time is its window's centre
    seconds = len(x) / sr
    best = (-1.0, 0.0, 0.0)
    for period in np.arange((lag - 1) / fps, (lag + 1) / fps, 0.0005):
        phases = np.arange(0, period, 0.004)
        grid = phases[:, None] + np.arange(int(seconds / period))[None, :] * period
        score = np.interp(grid, times, env).mean(axis=1)
        i = int(np.argmax(score))
        if score[i] > best[0]:
            best = (float(score[i]), float(period), float(phases[i]))
    _, period, phase = best
    beats = np.arange(phase + ONSET_LAG, seconds - 0.05, period)
    at = lambda t: int(round((t * sr - N_FFT / 2) / HOP))  # noqa: E731  the frame centred on t
    bass = np.array([low[max(0, at(t) - 2):max(1, at(t) + 3)].max() for t in beats])
    bar = int(np.argmax([bass[j::4].sum() for j in range(4)]))
    return {"bpm": round(60 / period, 2), "period": period, "beats": beats.tolist(), "bass": bass.tolist(),
            "downbeats": beats[bar::4].tolist(), "seconds": seconds}


def find_drop(grid, after):
    """The first strong downbeat at or after `after` seconds of the file: the bass comes in hard there."""
    bass = dict(zip(grid["beats"], grid["bass"]))
    downs = [t for t in grid["downbeats"] if t >= after - 1e-6]
    if not downs:
        return None
    strong = 0.7 * np.percentile([bass[t] for t in grid["downbeats"]], 90)
    return next((t for t in downs if bass[t] >= strong), downs[0])


# --- plan ---

def shot_beats(lengths, period, mode):
    """Beats per shot: visual shots 2 to 8 beats near their picked length; a spoken line gets enough beats to finish."""
    if mode == "speech":
        return [max(2, math.ceil((n + LEAD + TAIL) / period - 0.05)) for n in lengths]
    lo, hi = VISUAL_BEATS
    counts = [min(hi, max(lo, round(n / period))) for n in lengths]
    counts[0] = min(hi, max(counts[0], math.ceil(HOOK_MIN / period)))
    return counts


def plan(lengths, grid, mode):
    """Cut times on the beat. Returns offset (where the music starts in its file), cuts (reel seconds, first 0 and
    last the end), counts (beats per shot), downbeats (reel seconds) and drop (reel seconds, the first cut)."""
    period = grid["period"]
    counts = shot_beats(lengths, period, mode)
    lo, hi = REEL_SECONDS
    while len(counts) > 2 and sum(counts) * period > hi:
        counts.pop()
    if mode == "visual":
        i = 1
        while sum(counts) * period < lo and any(c < VISUAL_BEATS[1] for c in counts):
            if counts[i % len(counts)] < VISUAL_BEATS[1]:
                counts[i % len(counts)] += 1
            i += 1
    elif sum(counts) * period < lo:
        counts[-1] += math.ceil((lo - sum(counts) * period) / period)
    drop = find_drop(grid, counts[0] * period)
    if drop is None:  # a bed too short for its drop: start on its first beat
        drop = grid["beats"][0] + counts[0] * period
    offset = drop - counts[0] * period
    first_bar = counts[0] % 4  # reel beat indices that are downbeats
    extra = (-sum(counts) + first_bar) % 4  # end the reel on a bar line
    if (sum(counts) + extra) * period > hi:
        extra -= 4  # shorten the last shot to the bar line before instead
    if (mode == "speech" and extra >= 0) or (mode == "visual" and VISUAL_BEATS[0] <= counts[-1] + extra <= VISUAL_BEATS[1]):
        counts[-1] += extra
    edges = np.cumsum([0] + counts)
    cuts = [round(round(k * period * FPS) / FPS, 4) for k in edges]
    downbeats = [round(k * period, 4) for k in range(first_bar, edges[-1] + 1, 4)]
    return {"offset": round(offset, 4), "period": period, "counts": counts, "cuts": cuts, "downbeats": downbeats,
            "drop": cuts[1]}


def pick_transitions(n, mode, counts, seed=0):
    """A transition for each inner cut: the drop first, then a varied mix that never repeats back to back.
    A speed ramp needs the shot before the cut to run 3 beats or more."""
    rng = random.Random(seed)
    kinds = ["drop"]
    for i in range(2, n):
        options = [k for k in TRANSITIONS[mode] if k != kinds[-1] and (k != "ramp" or counts[i - 1] >= 3)]
        kinds.append(rng.choice(options))
    return kinds[:max(0, n - 1)]


def text_beat_times(texts, downbeats, hook_end, total):
    """Each text beat pops on a downbeat after the headline, spread across the reel, and leaves before the next."""
    slots = [t for t in downbeats if hook_end + 0.3 <= t <= total - 1.5]
    if not texts or not slots:
        return []
    picks = [slots[round(i * (len(slots) - 1) / max(1, len(texts)))] for i in range(len(texts))] if len(slots) > len(texts) \
        else slots[:len(texts)]
    picks = sorted(dict.fromkeys(picks))
    out = []
    for i, t in enumerate(picks):
        end = min(t + 2.4, picks[i + 1] - 0.15 if i + 1 < len(picks) else total - 0.4)
        out.append({"t": t, "out": round(end, 3), "text": texts[i]})
    return out


def sfx_cues(cuts, kinds):
    """Impact on the drop, whoosh on whips; never closer than SFX_GAP, so not every cut gets a sound."""
    cues, last = [], -SFX_GAP
    for t, kind in zip(cuts, kinds):
        name = {"drop": "impact", "zoomblur": "impact", "glitchzoom": "impact", "whip": "whoosh"}.get(kind)
        if name and t - last >= SFX_GAP:
            at = max(0.0, t - (0.12 if name == "whoosh" else 0.0))
            cues.append((name, round(at, 3)))
            last = t
    return cues


# --- render ---

def has_audio(video):
    out = clipper.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0",
                       str(video)]).stdout
    return bool(out.strip())


def speaker(video, detector, start, end):
    """(centre x, centre y, width) of the biggest face across a shot, in source pixels; None when none shows."""
    import cv2

    capture, found = cv2.VideoCapture(str(video)), []
    for fraction in (0.2, 0.5, 0.8):
        capture.set(cv2.CAP_PROP_POS_MSEC, (start + (end - start) * fraction) * 1000)
        ok, frame = capture.read()
        if not ok:
            continue
        scale = 960 / frame.shape[1]
        small = cv2.resize(frame, (960, round(frame.shape[0] * scale)))
        detector.setInputSize((small.shape[1], small.shape[0]))
        _, faces = detector.detect(small)
        face = clipper.main_face(faces if faces is not None else [])
        if face is not None:
            x, y, w, h = face[:4]
            found.append(((x + w / 2) / scale, (y + h / 2) / scale, w / scale))
    capture.release()
    return tuple(float(np.median([f[k] for f in found])) for k in range(3)) if found else None


def fill_frame(src_w, src_h, face=None):
    """The ffmpeg crop to a full 9:16 frame: full height around the face, or a closer crop when the face is small
    (a wide stage shot), so a speaker never shrinks to a dot. Never letterboxed."""
    keep = 1.0 if face is None or face[2] >= SMALL_FACE * src_w else WIDE_SHOT_KEEP
    crop_h = round(src_h * keep / 2) * 2
    crop_w = min(src_w, round(crop_h * 9 / 16 / 2) * 2)
    x = clipper.crop_x(face[0] if face else None, src_w, crop_w)
    y = 0 if keep == 1.0 else int(max(0, min(src_h - crop_h, face[1] - crop_h * 0.32)))
    return f"crop={crop_w}:{crop_h}:{x}:{y},scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=increase,crop={OUT_W}:{OUT_H}"


def build_base(segments, p, kinds, out, mode):
    """Cut every shot to its beat length (frame exact), fill 9:16, and join them: base.mp4 with the source audio."""
    detector = clipper.face_detector() if mode == "speech" else None
    beat = p["period"]
    inputs, parts = [], []
    for i, seg in enumerate(segments[:len(p["counts"])]):
        frames = round(p["cuts"][i + 1] * FPS) - round(p["cuts"][i] * FPS)
        dur = frames / FPS
        ramp = i + 1 < len(p["cuts"]) - 1 and kinds[i] == "ramp"
        start = max(0.0, seg["start"] - (LEAD if mode == "speech" else 0.0))
        need = dur + (beat if ramp else 0.0)
        src_w, src_h = clipper.probe_size(seg["video"])
        face = speaker(seg["video"], detector, start, start + dur) if detector is not None else None
        frame = fill_frame(src_w, src_h, face)
        k = len(inputs) // 6  # six arguments per input
        inputs += ["-ss", f"{start:.3f}", "-t", f"{need + 1:.3f}", "-i", str(seg["video"])]
        if ramp:  # the last beat plays at double speed
            slow = dur - beat
            video = (f"[{k}:v]split[s{i}a][s{i}b];[s{i}a]trim=0:{slow:.4f},setpts=PTS-STARTPTS[s{i}c];"
                     f"[s{i}b]trim={slow:.4f}:{slow + 2 * beat:.4f},setpts=(PTS-STARTPTS)/2[s{i}d];"
                     f"[s{i}c][s{i}d]concat=n=2:v=1:a=0,")
        else:
            video = f"[{k}:v]"
        parts.append(f"{video}{frame},fps={FPS},setsar=1,tpad=stop_mode=clone:stop_duration=2,"
                     f"trim=end_frame={frames},setpts=PTS-STARTPTS[v{i}]")
        if has_audio(seg["video"]):
            audio = (f"[{k}:a]atrim=0:{dur - beat:.4f},asetpts=PTS-STARTPTS[r{i}a];[{k}:a]atrim={dur - beat:.4f}:"
                     f"{dur + beat:.4f},asetpts=PTS-STARTPTS,atempo=2[r{i}b];[r{i}a][r{i}b]concat=n=2:v=0:a=1,"
                     if ramp else f"[{k}:a]")
            parts.append(f"{audio}aresample=48000,aformat=channel_layouts=stereo,apad,atrim=0:{dur:.4f},"
                         f"asetpts=PTS-STARTPTS,afade=t=in:d=0.06,afade=t=out:st={max(0, dur - 0.12):.4f}:d=0.12[a{i}]")
        else:
            parts.append(f"anullsrc=r=48000:cl=stereo,atrim=0:{dur:.4f}[a{i}]")
    n = len(p["counts"])
    parts.append("".join(f"[v{i}][a{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=1[vo][ao]")
    clipper.run(["ffmpeg", "-y", *inputs, "-filter_complex", ";".join(parts), "-map", "[vo]", "-map", "[ao]",
                 *clipper.fast_encoder(), "-r", str(FPS), "-c:a", "aac", "-b:a", "192k", str(out)])


def speech_words(segments, p):
    """Each line's words moved onto the reel timeline; a new line starts a new caption group."""
    timeline = []
    for i, seg in enumerate(segments[:len(p["counts"])]):
        start = max(0.0, seg["start"] - LEAD)
        cut, end = p["cuts"][i], p["cuts"][i + 1]
        line = [{"word": w["word"], "start": round(cut + w["start"] - start, 3), "end": round(min(cut + w["end"] - start, end), 3)}
                for w in seg.get("words") or [] if seg["start"] - 0.05 <= w["start"] < seg["end"]]
        if line and timeline:
            line[0]["cut"] = True
        timeline += line
    return timeline


def normalise(src, out, target=TARGET_LUFS):
    """Two pass EBU R128 loudness normalisation of the mix; the video stream is copied."""
    probe = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(src), "-af",
                            f"loudnorm=I={target}:TP=-1.0:LRA=11:print_format=json", "-f", "null", "-"],
                           capture_output=True, text=True).stderr
    m = json.loads(probe[probe.rindex("{"):probe.rindex("}") + 1])
    clipper.run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-c:v", "copy", "-af",
                 f"loudnorm=I={target}:TP=-1.0:LRA=11:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
                 f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true,"
                 f"aresample=48000,alimiter=limit=0.84:level=false,afade=t=in:d={EASE_IN},"
                 f"afade=t=out:st={max(0, clipper.duration_of(src) - EASE_OUT):.3f}:d={EASE_OUT}", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)])


def render_montage(segments, out, *, music, theme=None, hook_style="headline", brand_tag="", headline="", accent=(),
                   text_beats=(), mode="visual", seed=0):
    """A 15 to 30 s 1080x1920 montage cut on the beats of `music`. segments: [{video, start, end, words?}] in the
    order they play. The headline (always the headline style, so hook_style is kept only for the callers' symmetry)
    opens the reel and leaves on the drop. Also writes out.jpg, the cover frame. Engine exits become errors."""
    try:
        return _render_montage(segments, Path(out), music, theme, brand_tag, headline, list(accent), list(text_beats), mode, seed)
    except SystemExit as e:
        raise RuntimeError(str(e.code)) from None


def _render_montage(segments, out, music, theme, brand_tag, headline, accent, text_beats, mode, seed):
    if mode not in TRANSITIONS:
        raise ValueError(f"mode must be visual or speech, not {mode}")
    if not music:
        raise ValueError("a montage needs a music bed")
    grid = beat_grid(music)
    p = plan([s["end"] - s["start"] for s in segments], grid, mode)
    kinds = pick_transitions(len(p["cuts"]) - 1, mode, p["counts"], seed)
    project = clipper.work_root() / "montage" / out.stem
    if project.exists():
        shutil.rmtree(project)
    (project / "fonts").mkdir(parents=True)
    for font in clipper.FONTS.glob("*.ttf"):
        shutil.copy(font, project / "fonts" / font.name)
    shutil.copytree(clipper.SFX, project / "sfx", ignore=shutil.ignore_patterns("*.md"))
    shutil.copy(music, project / ("music" + Path(music).suffix))
    build_base(segments, p, kinds, project / "base.mp4", mode)
    total = p["cuts"][-1]
    duration = round(min(total, clipper.duration_of(project / "base.mp4")), 3)
    inner = p["cuts"][1:-1]
    hook_end = min(p["drop"], 2.6)
    timeline = speech_words(segments, p) if mode == "speech" else []
    groups, index = [], 0
    for chunk in clipper.caption_chunks(timeline, size=4):
        groups.append([index, index + len(chunk) - 1])
        index += len(chunk)
    reel = {"duration": duration, "hook": headline, "hook_accent": accent, "emphasis": [], "hook_style": "headline",
            "brand_tag": brand_tag, "hook_end": hook_end, "beat": round(p["period"], 4), "bpm": grid["bpm"],
            "cuts": [{"t": t, "kind": k} for t, k in zip(inner, kinds)],
            "text_beats": text_beat_times(text_beats, p["downbeats"], hook_end, duration),
            "words": [{"t": w["word"], "s": w["start"], "e": w["end"]} for w in timeline], "groups": groups}
    footage = SPEECH_FOOTAGE if mode == "speech" else VISUAL_FOOTAGE
    tags = (f'<audio id="bg-audio" src="base.mp4" data-start="0" data-duration="{duration}" data-track-index="10" '
            f'data-volume="{footage}"></audio>')
    src = f"music{Path(music).suffix}"
    if mode == "speech":
        bed = clipper.music_bed(src, reel, duration, SPEECH_MUSIC, low=SPEECH_DUCK)
    else:
        bed = (f'<audio id="music" src="{src}" data-start="0" data-duration="{duration}" data-track-index="11" '
               f'data-volume="{VISUAL_MUSIC}"></audio>')
    tags += bed.replace('data-start="0"', f'data-start="0" data-media-start="{p["offset"]}"', 1)
    for i, (name, t) in enumerate(c for c in sfx_cues(inner, kinds) if c[1] < duration - 0.2):
        tags += (f'<audio id="sfx-{i}" src="sfx/{name}.mp3" data-start="{t}" data-duration="{min(clipper.sfx_seconds(name), round(duration - t, 3))}" '
                 f'data-track-index="{20 + i}" data-volume="{clipper.SFX_VOLUME[name]}"></audio>')
    reel["ease"] = [EASE_IN, EASE_OUT]
    html = clipper.reel_page(reel, TEMPLATE, duration, duration, tags, theme)
    (project / "index.html").write_text(encoding="utf-8", data=html)
    (project / "plan.json").write_text(encoding="utf-8", data=json.dumps({**p, "bpm": grid["bpm"], "kinds": kinds}))
    out.parent.mkdir(parents=True, exist_ok=True)
    mixed = project / "mixed.mp4"
    command = [clipper.npx(), "--yes", clipper.HYPERFRAMES, "render", str(project), "-o", str(mixed),
               "--crf", "20", "--fps", str(FPS), "--quiet"]
    done = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if done.returncode != 0 or not mixed.exists():
        sys.exit(f"hyperframes render failed for the montage {out.stem}:\n{(done.stderr or done.stdout)[-1500:]}")
    normalise(mixed, out)
    clipper.cover_frame(out, out.with_suffix(".jpg"))
    return out
