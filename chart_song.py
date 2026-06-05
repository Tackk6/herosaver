#!/usr/bin/env python3
"""
chart_song.py — One-command Clone Hero charter (ML pipeline).

Full pipeline from a song file to a ready-to-play chart folder. Supports
multiple instruments via --instrument:

USAGE:
  # drums
  python3 chart_song.py song.mp3 --instrument drums --title "Song" --artist "Artist" \
      --adtof-python ./venv/bin/python --pro
  # guitar
  python3 chart_song.py song.mp3 --instrument guitar --title "Song" --artist "Artist"

OUTPUT:
  ./charts/<Artist> - <Title>/  with notes.chart, song.ini, song.<ext>
"""

import argparse
import subprocess
import sys
import shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import midi_to_chart as mtc
import guitar_to_chart as gtc

# Which Demucs stem each instrument needs.
STEM_FOR = {"drums": "drums", "guitar": "other"}


def run_demucs(song_path: Path, stem_name: str, workdir: Path) -> Path:
    print(f"[1/3] Demucs: isolating '{stem_name}' stem (GPU)...")
    cmd = ["demucs", "--two-stems", stem_name, "-d", "cuda",
           "-o", str(workdir), str(song_path)]
    if subprocess.run(cmd).returncode != 0:
        print("      GPU failed; retrying on CPU...")
        cmd[cmd.index("cuda")] = "cpu"
        if subprocess.run(cmd).returncode != 0:
            sys.exit("Demucs failed on both GPU and CPU.")
    stem = workdir / "htdemucs" / song_path.stem / f"{stem_name}.wav"
    if not stem.exists():
        sys.exit(f"Stem not found at {stem}")
    return stem


def run_adtof(adtof_python: str, stem: Path, out_mid: Path, device: str):
    print("[2/3] ADTOF: transcribing drums with ML model...")
    cmds = [
        [adtof_python, "-m", "adtof_pytorch", "--audio", str(stem),
         "--out", str(out_mid), "--device", device],
        [str(Path(adtof_python).parent / "adtof"),
         "--audio", str(stem), "--out", str(out_mid), "--device", device],
    ]
    last_err = None
    for cmd in cmds:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode == 0 and out_mid.exists():
                return
            last_err = r.stderr or r.stdout
        except FileNotFoundError as e:
            last_err = str(e)
    sys.exit(f"ADTOF transcription failed.\nLast error:\n{last_err}\n"
             f"Check that --adtof-python points to the venv where you "
             f"installed ADTOF-pytorch.")


def run_basic_pitch(stem: Path, out_mid: Path):
    print("[2/3] Basic Pitch: transcribing guitar notes with ML model...")
    try:
        from basic_pitch.inference import predict_and_save
        from basic_pitch import ICASSP_2022_MODEL_PATH
    except ImportError:
        sys.exit("Missing dependency for guitar. Run: pip install basic-pitch")
    out_dir = out_mid.parent
    predict_and_save(
        [str(stem)], str(out_dir),
        save_midi=True, sonify_midi=False, save_model_outputs=False,
        save_notes=False, model_or_model_path=ICASSP_2022_MODEL_PATH,
    )
    # Basic Pitch names output "<stem>_basic_pitch.mid"; find and rename it.
    produced = list(out_dir.glob("*_basic_pitch.mid"))
    if not produced:
        sys.exit("Basic Pitch produced no MIDI.")
    produced[0].rename(out_mid)


def main():
    p = argparse.ArgumentParser(description="One-command ML charter for Clone Hero.")
    p.add_argument("song")
    p.add_argument("--instrument", default="drums", choices=list(STEM_FOR.keys()),
                   help="Which instrument to chart (drums or guitar).")
    p.add_argument("--title", default=None)
    p.add_argument("--artist", default="Unknown")
    p.add_argument("--bpm", type=float, default=None,
                   help="Override BPM. If omitted, read from the transcribed MIDI.")
    p.add_argument("--pro", action="store_true", help="Pro drums (drums only).")
    p.add_argument("--adtof-python", default=None,
                   help="Path to the python where ADTOF is installed "
                        "(required for --instrument drums).")
    p.add_argument("--device", default="cuda", choices=["cuda", "cpu"],
                   help="Device for ADTOF (default cuda).")
    p.add_argument("--keep-intermediate", action="store_true",
                   help="Keep the work folder (stem + midi) for debugging.")
    args = p.parse_args()

    song_path = Path(args.song).expanduser().resolve()
    if not song_path.exists():
        sys.exit(f"Song not found: {song_path}")
    if args.instrument == "drums" and not args.adtof_python:
        sys.exit("--adtof-python is required for drums.")
    title = args.title or song_path.stem

    workdir = Path("./_work").resolve()
    workdir.mkdir(exist_ok=True)

    # Stage 1: Demucs (instrument-specific stem)
    stem = run_demucs(song_path, STEM_FOR[args.instrument], workdir)

    # Stage 2 + 3: transcribe, then build the chart for this instrument
    out_mid = workdir / f"{args.instrument}.mid"
    out_dir = Path("./charts").resolve() / f"{args.artist} - {title}"
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.instrument == "drums":
        run_adtof(args.adtof_python, stem, out_mid, args.device)
        print("[3/3] Building drum chart (4 difficulties)...")
        notes, tpb = mtc.parse_midi(out_mid)
        if not notes:
            sys.exit("ADTOF MIDI had no drum notes. Re-run with --keep-intermediate.")
        bpm = mtc.get_bpm(out_mid, args.bpm)
        diff_number, nps, count = mtc.write_chart(
            notes, tpb, bpm, title, args.artist, args.pro, out_dir)
        mtc.write_ini(title, args.artist, args.pro, out_dir, diff_number)
        kind = f"{'PRO' if args.pro else 'standard'} drums"
    else:  # guitar
        run_basic_pitch(stem, out_mid)
        print("[3/3] Building guitar chart (4 difficulties)...")
        by_fret, tpb, bpm = gtc.build_from_midi(out_mid, args.bpm)
        if not by_fret:
            sys.exit("Basic Pitch MIDI had no notes. Re-run with --keep-intermediate.")
        diff_number, nps, count = gtc.write_chart(
            by_fret, tpb, bpm, title, args.artist, out_dir)
        gtc.write_ini(title, args.artist, out_dir, diff_number)
        kind = "guitar"

    shutil.copy(song_path, out_dir / ("song" + song_path.suffix))
    if not args.keep_intermediate:
        shutil.rmtree(workdir, ignore_errors=True)

    stars = "★" * diff_number + "☆" * (6 - diff_number)
    print(f"\nDone. {bpm:.1f} BPM ({kind}).")
    print(f"Difficulty: {diff_number}/6  {stars}  ({nps:.1f} notes/sec)")
    print(f"Song folder: {out_dir}")
    print("Copy it into your Clone Hero 'songs' directory and play.")


if __name__ == "__main__":
    main()
