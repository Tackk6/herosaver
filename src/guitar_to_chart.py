#!/usr/bin/env python3
"""
guitar_to_chart.py — Convert a pitched MIDI (e.g. from Basic Pitch) into a
Clone Hero 5-fret guitar chart.

Guitar charting differs fundamentally from drums: the 5 frets are NOT pitches,
they're an abstraction a human designs for playability. We map notes to frets
by INTERVAL MOTION — when the melody rises we step to a higher fret, when it
falls we step down, when it repeats we stay. This mirrors what the music is
doing and plays naturally regardless of absolute pitch.

Guitar .chart lanes (section [ExpertSingle]):
    0=green 1=red 2=yellow 3=blue 4=orange ; 7=open note (no fret)

USAGE:
    python3 guitar_to_chart.py SONG.mid --title "Song" --artist "Artist"
    python3 guitar_to_chart.py SONG.mid --title "Song" --artist "Artist" --audio song.ogg

Requires: pip install mido
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
NUM_FRETS = 5     # green, red, yellow, blue, orange = lanes 0-4

# How big a pitch jump (in semitones) maps to how many fret steps.
# Small moves shift one fret; bigger leaps shift more, so runs feel melodic.
def interval_to_fret_step(semitones):
    a = abs(semitones)
    if a == 0:
        return 0
    sign = 1 if semitones > 0 else -1
    if a <= 2:
        return sign * 1     # step / half-step -> one fret
    if a <= 4:
        return sign * 2     # third -> two frets
    if a <= 7:
        return sign * 3     # fourth/fifth -> three frets
    return sign * 4         # big leap -> jump across the neck


# Difficulty design for guitar: thin by time-gap (note density) and, on easier
# levels, simplify chords to single notes. Guitar has no "backbone voice" like
# drums, so density control is the main lever.
DIFF_SPEC = {
    "Easy":   {"min_gap": 0.30, "max_chord": 1},
    "Medium": {"min_gap": 0.16, "max_chord": 1},
    "Hard":   {"min_gap": 0.08, "max_chord": 2},
    "Expert": {"min_gap": 0.0,  "max_chord": 6},
}
DIFFICULTY_ORDER = ("Easy", "Medium", "Hard", "Expert")


def parse_pitched_midi(midi_path, track_index=None):
    """Return (events, tpb). events = list of (abs_tick, [pitches]) grouped by
    onset tick — a chord is multiple pitches at the same tick."""
    mid = mido.MidiFile(str(midi_path))
    tpb = mid.ticks_per_beat
    raw = []
    for i, track in enumerate(mid.tracks):
        if track_index is not None and i != track_index:
            continue
        abs_tick = 0
        for msg in track:
            abs_tick += msg.time
            # skip the percussion channel; this is a melodic instrument
            if msg.type == "note_on" and msg.velocity > 0:
                if getattr(msg, "channel", None) == 9:
                    continue
                raw.append((abs_tick, msg.note))
    if not raw:
        return [], tpb
    raw.sort(key=lambda x: x[0])
    # group simultaneous notes (same tick, or within a tiny window) into chords
    events, cur_tick, cur = [], None, []
    tol = max(1, tpb // 32)
    for tick, pitch in raw:
        if cur_tick is None or abs(tick - cur_tick) <= tol:
            cur_tick = tick if cur_tick is None else cur_tick
            cur.append(pitch)
        else:
            events.append((cur_tick, sorted(cur)))
            cur_tick, cur = tick, [pitch]
    if cur:
        events.append((cur_tick, sorted(cur)))
    return events, tpb


def map_intervals_to_frets(events):
    """Walk the melody, tracking up/down motion to assign frets.
    Returns list of (abs_tick, [lanes]). Uses the lowest note of each chord as
    the melodic anchor; chord width spreads extra notes onto adjacent frets."""
    out = []
    cur_fret = 2          # start in the middle (yellow)
    prev_anchor = None
    pinned = 0            # how many consecutive notes we've sat at an edge
    for tick, pitches in events:
        anchor = pitches[0]  # lowest note drives melodic motion
        if prev_anchor is None:
            cur_fret = 2
        else:
            step = interval_to_fret_step(anchor - prev_anchor)
            cur_fret += step
            # If we run off the neck, clamp — but if we KEEP pushing past an
            # edge, the melody is still moving while the fret can't. Re-anchor
            # back toward the middle so a long run doesn't flatten to one fret.
            if cur_fret < 0:
                pinned += 1
                cur_fret = 1 if pinned >= 2 else 0
            elif cur_fret > NUM_FRETS - 1:
                pinned += 1
                cur_fret = NUM_FRETS - 2 if pinned >= 2 else NUM_FRETS - 1
            else:
                pinned = 0
        prev_anchor = anchor

        # chord: spread additional notes onto frets above the anchor fret
        n = len(pitches)
        if n == 1:
            lanes = [cur_fret]
        else:
            lanes = []
            for k in range(n):
                f = cur_fret + k
                if f > NUM_FRETS - 1:
                    break
                lanes.append(f)
            if not lanes:
                lanes = [NUM_FRETS - 1]
        out.append((tick, sorted(set(lanes))))
    return out


def thin_for(notes, diff, sec_per_tick):
    """notes = (abs_tick, [lanes]). Enforce min gap and chord-size cap."""
    spec = DIFF_SPEC[diff]
    min_gap = spec["min_gap"]
    max_chord = spec["max_chord"]
    out, last_t = [], None
    for tick, lanes in notes:
        t = tick * sec_per_tick
        if last_t is not None and (t - last_t) < min_gap:
            continue
        capped = lanes[:max_chord]
        out.append((tick, capped))
        last_t = t
    return out


def density_to_diff_number(nps):
    if nps < 1.5: return 1
    if nps < 3.0: return 2
    if nps < 4.5: return 3
    if nps < 6.0: return 4
    if nps < 7.5: return 5
    return 6


def write_chart(events_by_fret, tpb, bpm, title, artist, out_dir):
    scale = RESOLUTION / tpb
    sec_per_tick = (60.0 / bpm) / tpb

    def to_tick(t):
        return int(round(t * scale))

    expert_count = 0
    song_len = (max(e[0] for e in events_by_fret) * sec_per_tick
                if events_by_fret else 1.0)

    with open(out_dir / "notes.chart", "w") as f:
        f.write("[Song]\n{\n")
        f.write(f'  Name = "{title}"\n')
        f.write(f'  Artist = "{artist}"\n')
        f.write('  Charter = "guitar_to_chart"\n')
        f.write(f"  Resolution = {RESOLUTION}\n")
        f.write("  Offset = 0\n}\n")
        f.write("[SyncTrack]\n{\n  0 = TS 4\n")
        f.write(f"  0 = B {int(round(bpm * 1000))}\n}}\n")
        f.write("[Events]\n{\n}\n")

        for diff in DIFFICULTY_ORDER:
            f.write(f"[{diff}Single]\n{{\n")
            kept = thin_for(events_by_fret, diff, sec_per_tick)
            if diff == "Expert":
                expert_count = sum(len(lanes) for _, lanes in kept)
            lines = []
            for tick, lanes in kept:
                ct = to_tick(tick)
                for lane in lanes:
                    lines.append((ct, f"  {ct} = N {lane} 0\n"))
            for _, line in sorted(lines, key=lambda x: x[0]):
                f.write(line)
            f.write("}\n")

    nps = expert_count / max(song_len, 1.0)
    return density_to_diff_number(nps), nps, expert_count


def write_ini(title, artist, out_dir, diff_number=3):
    with open(out_dir / "song.ini", "w") as f:
        f.write("[Song]\n")
        f.write(f"name = {title}\n")
        f.write(f"artist = {artist}\n")
        f.write("charter = guitar_to_chart\n")
        f.write("delay = 0\n")
        f.write(f"diff_guitar = {diff_number}\n")


def get_bpm(midi_path, override):
    if override:
        return override
    mid = mido.MidiFile(str(midi_path))
    for track in mid.tracks:
        for msg in track:
            if msg.type == "set_tempo":
                return mido.tempo2bpm(msg.tempo)
    return 120.0


def build_from_midi(midi_path, bpm_override=None, track_index=None):
    """Shared entry used by chart_song.py: MIDI path -> (events_by_fret, tpb, bpm)."""
    events, tpb = parse_pitched_midi(midi_path, track_index)
    if not events:
        return None, tpb, None
    by_fret = map_intervals_to_frets(events)
    bpm = get_bpm(midi_path, bpm_override)
    return by_fret, tpb, bpm


def main():
    p = argparse.ArgumentParser(description="Convert a pitched MIDI to a Clone Hero guitar chart.")
    p.add_argument("midi")
    p.add_argument("--title", default=None)
    p.add_argument("--artist", default="Unknown")
    p.add_argument("--bpm", type=float, default=None)
    p.add_argument("--track", type=int, default=None)
    p.add_argument("--audio", default=None)
    args = p.parse_args()

    midi_path = Path(args.midi).expanduser().resolve()
    if not midi_path.exists():
        sys.exit(f"MIDI not found: {midi_path}")
    title = args.title or midi_path.stem

    by_fret, tpb, bpm = build_from_midi(midi_path, args.bpm, args.track)
    if not by_fret:
        sys.exit("No melodic notes found in MIDI.")

    out_dir = Path("./charts").resolve() / f"{args.artist} - {title}"
    out_dir.mkdir(parents=True, exist_ok=True)
    diff_number, nps, count = write_chart(by_fret, tpb, bpm, title, args.artist, out_dir)
    write_ini(title, args.artist, out_dir, diff_number)
    if args.audio:
        ap = Path(args.audio).expanduser().resolve()
        if ap.exists():
            shutil.copy(ap, out_dir / ("song" + ap.suffix))

    stars = "★" * diff_number + "☆" * (6 - diff_number)
    print(f"Mapped {len(by_fret)} note-events at {bpm:.1f} BPM.")
    print(f"Difficulty: {diff_number}/6  {stars}  ({nps:.1f} notes/sec)")
    print(f"Song folder: {out_dir}")


if __name__ == "__main__":
    main()
