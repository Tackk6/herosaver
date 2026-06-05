#!/usr/bin/env python3
"""
midi_to_chart.py — Convert a drum MIDI file into a Clone Hero chart.

Unlike audio analysis, this is exact: General MIDI standardizes drum
note numbers (kick=36, snare=38, hi-hat=42, ...), so each note maps
deterministically to a Clone Hero lane. No guessing, no classification.

USAGE:
  python3 midi_to_chart.py SONG.mid --title "Song" --artist "Artist"
  python3 midi_to_chart.py SONG.mid --title "Song" --artist "Artist" --pro
  python3 midi_to_chart.py SONG.mid --title "Song" --artist "Artist" --audio song.ogg

Requires: pip install mido
OUTPUT:
  ./charts/<Artist> - <Title>/  with notes.chart, song.ini, and (if given) audio.
"""

import argparse
import sys
import shutil
from pathlib import Path

try:
    import mido
except ImportError:
    sys.exit("Missing dependency. Run: pip install mido")

RESOLUTION = 192  # Clone Hero ticks per beat

# General MIDI percussion note -> (voice, standard_lane, is_cymbal)
# standard_lane is used in non-pro mode; pro mode adds cymbal markers.
# Lanes: 0=kick 1=red 2=yellow 3=blue 4=green ; cymbal markers 66/67/68
GM_DRUM = {
    35: ("kick", 0, False), 36: ("kick", 0, False),         # bass drums
    37: ("snare", 1, False),                                 # side stick
    38: ("snare", 1, False), 40: ("snare", 1, False),        # snares
    42: ("hat", 2, True), 44: ("hat", 2, True), 46: ("hat", 2, True),  # hi-hats
    48: ("tom_hi", 2, False), 50: ("tom_hi", 2, False),      # high toms -> yellow
    45: ("tom_mid", 3, False), 47: ("tom_mid", 3, False),    # mid toms -> blue
    41: ("tom_lo", 4, False), 43: ("tom_lo", 4, False),      # low/floor toms -> green
    49: ("crash", 3, True), 57: ("crash", 3, True),          # crashes -> blue cymbal
    55: ("crash", 3, True), 52: ("crash", 3, True),          # splash, china -> blue cym
    51: ("ride", 4, True), 53: ("ride", 4, True), 59: ("ride", 4, True),  # rides -> green cym
}
CYMBAL_MARKER = {2: 66, 3: 67, 4: 68}

# Per-difficulty design (layer-based reduction, not blind time-gap).
# Real charts get easier by stripping LAYERS, not by random spacing:
#   - snare is the protected backbone; it survives at all difficulties
#   - kick can be grid-thinned on easy levels (busy kicks -> basic beat)
#   - timekeeping (hi-hat/cymbals) is reduced or quantized to main beats
#   - decoration (toms, fast fills) is simplified first
#
# Fields:
#   voices         = allowed voices (None = all)
#   hat_grid       = keep hi-hats/cymbals only on this beat subdivision
#                    (1.0 = quarter notes, 0.5 = eighths, 0.25 = sixteenths).
#                    None = keep all hats untouched.
#   kick_grid      = same idea for KICKS: collapse busy kicks to one per slot
#                    (1.0 = one kick per beat = basic boom beat). None = keep all.
#   tom_grid       = same idea for TOMS: keep tom fills to basic beats (one tom
#                    hit per slot). None = keep all toms (full rolls).
#   collapse_fills = runs of >=3 decoration notes faster than this (seconds)
#                    apart collapse to their first note. None = leave intact.
#   kick_with_others = drop a kick only when it collides with a pad note.
#   max_pads       = at any tick, cap simultaneous PAD notes (non-kick) to this
#                    many (kick is a foot pedal and doesn't count). None = no cap.
DIFF_SPEC = {
    "Easy":   {"voices": {"kick", "snare", "hat"},
               "hat_grid": 1.0,  "kick_grid": 1.0,  "collapse_fills": 0.22,
               "kick_with_others": False, "max_pads": 2},
    "Medium": {"voices": {"kick", "snare", "hat", "tom_lo", "tom_mid"},
               "hat_grid": 1.0,  "kick_grid": 0.5,  "tom_grid": 1.0,
               "collapse_fills": 0.16, "kick_with_others": False, "max_pads": 2},
    "Hard":   {"voices": None,
               "hat_grid": 0.25, "kick_grid": None, "collapse_fills": 0.07,
               "kick_with_others": True, "max_pads": 2},
    "Expert": {"voices": None,
               "hat_grid": None, "kick_grid": None, "collapse_fills": None,
               "kick_with_others": True, "max_pads": 2},
}
DIFFICULTY_ORDER = ("Easy", "Medium", "Hard", "Expert")
HAT_VOICES = {"hat", "crash", "ride"}
BACKBONE = {"kick", "snare"}


def parse_midi(midi_path: Path, track_index=None):
    """Return (notes, ticks_per_beat). notes = list of (abs_tick, voice, lane, is_cymbal).

    If track_index is given, only that track is read (and its drum notes are
    trusted regardless of channel). Otherwise only channel-10 notes are used.
    """
    mid = mido.MidiFile(str(midi_path))
    tpb = mid.ticks_per_beat
    notes = []
    # mido gives delta times per track; accumulate absolute ticks per track.
    for i, track in enumerate(mid.tracks):
        # If a specific track index was requested, skip all others.
        if track_index is not None and i != track_index:
            continue
        abs_tick = 0
        for msg in track:
            abs_tick += msg.time
            if msg.type == "note_on" and msg.velocity > 0:
                # Strict: drums live on channel 9 (GM "channel 10").
                # When a track is explicitly chosen, trust it and accept any
                # GM-drum note even if the channel isn't tagged 9.
                on_drum_channel = getattr(msg, "channel", None) == 9
                if on_drum_channel or (track_index is not None):
                    mapping = GM_DRUM.get(msg.note)
                    if mapping:
                        voice, lane, is_cym = mapping
                        notes.append((abs_tick, voice, lane, is_cym))
    notes.sort(key=lambda n: n[0])
    return notes, tpb


def list_tracks(midi_path: Path):
    """Print every track with its name and note activity, to find the drums."""
    mid = mido.MidiFile(str(midi_path))
    print(f"\n{midi_path.name} — {len(mid.tracks)} track(s):\n")
    for i, track in enumerate(mid.tracks):
        name = ""
        note_count = 0
        channels = set()
        drum_hits = 0
        for msg in track:
            if msg.type == "track_name":
                name = msg.name
            if msg.type == "note_on" and msg.velocity > 0:
                note_count += 1
                ch = getattr(msg, "channel", None)
                if ch is not None:
                    channels.add(ch)
                if ch == 9:
                    drum_hits += 1
        ch_str = ",".join(str(c) for c in sorted(channels)) if channels else "-"
        flag = "  <-- DRUMS (channel 10)" if drum_hits > 0 else ""
        print(f"  [{i}] {name or '(unnamed)':<24} notes={note_count:<5} "
              f"channels={ch_str}{flag}")
    print("\nUse --track N to chart a specific track.\n")


def thin_for(notes, diff, sec_per_tick, tpb):
    """Reduce notes for a difficulty by stripping layers, preserving the groove.
    notes = (abs_tick, voice, lane, is_cymbal), sorted by tick.

    Order of operations (each step sees the prior step's output):
      1. Voice filter.
      2. Collapse fast fills (decoration only; snare/kick backbone immune).
      3. Drop kicks that collide with a pad note (Easy only).
      4. Quantize hi-hat/cymbal layer to a beat grid.
      4b. Quantize KICKS to a beat grid (busy kicks -> basic beat) on easy levels.
      5. Cap simultaneous pad notes per tick (max two hands + free kick foot)."""
    spec = DIFF_SPEC[diff]
    voices = spec["voices"]
    hat_grid = spec["hat_grid"]
    kick_grid = spec.get("kick_grid")
    collapse_fills = spec["collapse_fills"]
    keep_kick_with_others = spec["kick_with_others"]
    max_pads = spec.get("max_pads")

    # 1. voice filter
    ns = [n for n in notes if voices is None or n[1] in voices]
    if not ns:
        return []

    # 2. collapse fast fills — decoration only, backbone is immune
    if collapse_fills:
        deco = [n for n in ns if n[1] not in BACKBONE]
        back = [n for n in ns if n[1] in BACKBONE]
        collapsed, run = [], []
        def flush(r):
            return [r[0]] if len(r) >= 3 else r
        prev_t = None
        for n in deco:
            t = n[0] * sec_per_tick
            if prev_t is not None and (t - prev_t) < collapse_fills:
                run.append(n)
            else:
                collapsed.extend(flush(run)); run = [n]
            prev_t = t
        collapsed.extend(flush(run))
        ns = sorted(back + collapsed, key=lambda n: n[0])

    # 3. drop colliding kicks (Easy): remove the kick only when it lands with
    #    another *pad* note (snare/tom) — i.e. a real two-hand hit. A kick that
    #    merely coincides with a hi-hat is fine and stays (that's normal play).
    if not keep_kick_with_others:
        by_tick = {}
        for n in ns:
            by_tick.setdefault(n[0], []).append(n)
        out = []
        for tick in sorted(by_tick):
            moment = by_tick[tick]
            has_pad = any(n[1] not in ("kick",) and n[1] not in HAT_VOICES
                          for n in moment)
            if has_pad and any(n[1] == "kick" for n in moment):
                moment = [n for n in moment if n[1] != "kick"]
            out.extend(moment)
        ns = out

    # 4. quantize hat/cymbal layer to a grid; keep backbone & toms as-is
    if hat_grid is not None:
        grid_ticks = hat_grid * tpb
        kept, seen_slots = [], set()
        for n in ns:
            if n[1] in HAT_VOICES:
                slot = round(n[0] / grid_ticks)
                if slot in seen_slots:
                    continue
                seen_slots.add(slot)
            kept.append(n)
        ns = sorted(kept, key=lambda n: n[0])

    # 4b. quantize KICKS to a grid — collapses busy/double kicks into a basic
    #     one-per-slot beat. Snare is untouched, so the backbone groove stays.
    if kick_grid is not None:
        grid_ticks = kick_grid * tpb
        kept, seen_slots = [], set()
        for n in ns:
            if n[1] == "kick":
                slot = round(n[0] / grid_ticks)
                if slot in seen_slots:
                    continue
                seen_slots.add(slot)
            kept.append(n)
        ns = sorted(kept, key=lambda n: n[0])

    # 4c. quantize TOMS to a grid — keeps tom fills to basic beats (one tom hit
    #     per slot) instead of full fast rolls. All tom voices share the grid.
    tom_grid = spec.get("tom_grid")
    if tom_grid is not None:
        grid_ticks = tom_grid * tpb
        kept, seen_slots = [], set()
        for n in ns:
            if n[1] in ("tom_hi", "tom_mid", "tom_lo"):
                slot = round(n[0] / grid_ticks)
                if slot in seen_slots:
                    continue
                seen_slots.add(slot)
            kept.append(n)
        ns = sorted(kept, key=lambda n: n[0])

    # 5. cap simultaneous pads per tick. A kick is a foot pedal (free), so it
    #    never counts toward the limit; we keep up to `max_pads` hand notes plus
    #    the kick. 3+ stacked pads are impossible to hit, so trim to max_pads.
    if max_pads is not None:
        by_tick = {}
        for n in ns:
            by_tick.setdefault(n[0], []).append(n)
        out = []
        for tick in sorted(by_tick):
            moment = by_tick[tick]
            kicks = [n for n in moment if n[1] == "kick"]
            pads = [n for n in moment if n[1] != "kick"]
            if len(pads) > max_pads:
                # Priority when trimming: snare > toms > cymbals/hats.
                def pad_priority(n):
                    v = n[1]
                    if v == "snare": return 0
                    if v in ("tom_hi", "tom_mid", "tom_lo"): return 1
                    return 2  # hat/crash/ride
                pads = sorted(pads, key=pad_priority)[:max_pads]
            out.extend(kicks + pads)
        ns = sorted(out, key=lambda n: n[0])

    return ns




def write_chart(notes, tpb, bpm, title, artist, pro, out_dir: Path):
    # Rescale MIDI ticks (tpb per beat) to Clone Hero resolution (192 per beat).
    scale = RESOLUTION / tpb
    # Seconds per MIDI tick, for time-based density thinning.
    sec_per_tick = (60.0 / bpm) / tpb

    def to_tick(t):
        return int(round(t * scale))

    expert_count = 0
    song_len_sec = (max(n[0] for n in notes) * sec_per_tick) if notes else 1.0

    with open(out_dir / "notes.chart", "w") as f:
        f.write("[Song]\n{\n")
        f.write(f'  Name = "{title}"\n')
        f.write(f'  Artist = "{artist}"\n')
        f.write('  Charter = "midi_to_chart"\n')
        f.write(f"  Resolution = {RESOLUTION}\n")
        f.write("  Offset = 0\n}\n")
        f.write("[SyncTrack]\n{\n  0 = TS 4\n")
        f.write(f"  0 = B {int(round(bpm * 1000))}\n}}\n")
        f.write("[Events]\n{\n}\n")

        for diff in DIFFICULTY_ORDER:
            f.write(f"[{diff}Drums]\n{{\n")
            kept = thin_for(notes, diff, sec_per_tick, tpb)
            if diff == "Expert":
                expert_count = len(kept)
            lines = []
            for abs_tick, voice, lane, is_cym in kept:
                tick = to_tick(abs_tick)
                lines.append((tick, f"  {tick} = N {lane} 0\n"))
                if pro and is_cym and lane in CYMBAL_MARKER:
                    lines.append((tick, f"  {tick} = N {CYMBAL_MARKER[lane]} 0\n"))
            for _, line in sorted(lines, key=lambda x: x[0]):
                f.write(line)
            f.write("}\n")

    # Difficulty rating from note density (notes per second of Expert chart).
    nps = expert_count / max(song_len_sec, 1.0)
    diff_number = density_to_diff_number(nps)
    return diff_number, nps, expert_count


def density_to_diff_number(nps):
    """Map notes-per-second to Clone Hero's 0-6 difficulty intensity scale.
    Thresholds are rough but reasonable for drums: a sparse pop beat sits
    low, a dense metal chart sits high."""
    if nps < 2.0:   return 1
    if nps < 3.5:   return 2
    if nps < 5.0:   return 3
    if nps < 6.5:   return 4
    if nps < 8.0:   return 5
    return 6


def get_bpm(midi_path: Path, override):
    if override:
        return override
    mid = mido.MidiFile(str(midi_path))
    for track in mid.tracks:
        for msg in track:
            if msg.type == "set_tempo":
                return mido.tempo2bpm(msg.tempo)
    return 120.0  # GM default if none specified


def write_ini(title, artist, pro, out_dir: Path, diff_number=3):
    with open(out_dir / "song.ini", "w") as f:
        f.write("[Song]\n")
        f.write(f"name = {title}\n")
        f.write(f"artist = {artist}\n")
        f.write("charter = midi_to_chart\n")
        f.write("delay = 0\n")
        f.write(f"pro_drums = {'True' if pro else 'False'}\n")
        f.write("five_lane_drums = False\n")
        # Clone Hero difficulty intensity (0-6). -1 means "no chart for that
        # instrument". We set the drum lines; others stay unset.
        f.write(f"diff_drums = {diff_number}\n")
        f.write(f"diff_drums_real = {diff_number}\n")


def main():
    p = argparse.ArgumentParser(description="Convert drum MIDI to a Clone Hero chart.")
    p.add_argument("midi")
    p.add_argument("--title", default=None)
    p.add_argument("--artist", default="Unknown")
    p.add_argument("--bpm", type=float, default=None, help="Override BPM (else read from MIDI).")
    p.add_argument("--pro", action="store_true", help="Pro drums (cymbal markers).")
    p.add_argument("--audio", default=None, help="Optional audio file to copy in as song.<ext>.")
    p.add_argument("--list-tracks", action="store_true",
                   help="Print the tracks in the MIDI and exit (find the drum track).")
    p.add_argument("--track", type=int, default=None,
                   help="Chart only this track index (see --list-tracks).")
    args = p.parse_args()

    midi_path = Path(args.midi).expanduser().resolve()
    if not midi_path.exists():
        sys.exit(f"MIDI not found: {midi_path}")

    if args.list_tracks:
        list_tracks(midi_path)
        return

    title = args.title or midi_path.stem

    notes, tpb = parse_midi(midi_path, track_index=args.track)
    if not notes:
        sys.exit("No drum notes found. Try --list-tracks to find the drum track, "
                 "then pass --track N.")
    bpm = get_bpm(midi_path, args.bpm)

    out_dir = Path("./charts").resolve() / f"{args.artist} - {title}"
    out_dir.mkdir(parents=True, exist_ok=True)
    diff_number, nps, expert_count = write_chart(
        notes, tpb, bpm, title, args.artist, args.pro, out_dir)
    write_ini(title, args.artist, args.pro, out_dir, diff_number)
    if args.audio:
        ap = Path(args.audio).expanduser().resolve()
        if ap.exists():
            shutil.copy(ap, out_dir / ("song" + ap.suffix))
        else:
            print(f"  (warning: audio file {ap} not found, skipping)")

    stars = "★" * diff_number + "☆" * (6 - diff_number)
    print(f"Parsed {len(notes)} drum notes at {bpm:.1f} BPM "
          f"({'PRO' if args.pro else 'standard'} drums).")
    print(f"Difficulty: {diff_number}/6  {stars}  "
          f"({nps:.1f} notes/sec, {expert_count} on Expert)")
    print(f"Song folder: {out_dir}")
    if not args.audio:
        print("No --audio given: add a song.ogg/mp3 to the folder before playing.")


if __name__ == "__main__":
    main()
