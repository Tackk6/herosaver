# HeroSaver

Automatically generate **Clone Hero charts** from any song using ML
transcription. Feed it an audio file; get back a ready-to-play song folder with
four difficulties (Easy / Medium / Hard / Expert) and an auto-computed
difficulty rating. Supports **drums** and **guitar**.

## How it works

The pipeline shape is shared; the transcription model and note-mapping differ
per instrument:

```
DRUMS:
  song.mp3 -> [Demucs: drums stem] -> [ADTOF]       -> drum chart (kick/snare/toms/cymbals)
GUITAR:
  song.mp3 -> [Demucs: other stem] -> [Basic Pitch] -> guitar chart (interval-mapped frets)
```

- **[Demucs](https://github.com/facebookresearch/demucs)** isolates the target
  instrument's stem so the transcriber hears a clean signal.
- **Drums** use **[ADTOF-pytorch](https://github.com/xavriley/ADTOF-pytorch)**,
  a model trained on real music that outputs labeled drum hits. These map
  directly to Clone Hero lanes (kick is always lane 0, etc.).
- **Guitar** uses **[Basic Pitch](https://github.com/spotify/basic-pitch)**
  (Spotify) for polyphonic note detection, then maps notes to the 5 frets by
  **interval motion** — rising melody steps to higher frets, falling steps
  lower, repeats stay. Frets are an abstraction, not pitches, so this mirrors
  what the music *does* and plays naturally.

Entry points:

- **`chart_song.py`** — the full one-command pipeline. Pick `--instrument
  drums` or `--instrument guitar`.
- **`midi_to_chart.py`** — drum MIDI -> chart (with `--list-tracks`/`--track`).
- **`guitar_to_chart.py`** — pitched MIDI -> guitar chart.

## Requirements

- **Python 3.10** is strongly recommended for the ADTOF transcription step.
  Newer Python (3.13+) often lacks compatible wheels for the audio/ML stack.
- An NVIDIA GPU is recommended (Demucs and ADTOF both use it) but CPU works,
  just slower.
- `ffmpeg` available on your system (Demucs uses it for audio I/O).

## Installation

### Quick setup (recommended)

A `setup.sh` automates everything — venv, PyTorch (GPU auto-detected),
requirements, and ADTOF:

```bash
git clone https://github.com/Tackk6/herosaver.git
cd herosaver
chmod +x setup.sh
./setup.sh                 # auto-detects GPU; use ./setup.sh --cpu to force CPU
```

It prints the exact `--adtof-python` path and a ready-to-run example when it
finishes. If you don't have `python3.10`, run with another interpreter via
`PYTHON_BIN=python3.11 ./setup.sh` (3.10 is recommended for the ML stack).

Then activate the env before using the tool:

```bash
source venv/bin/activate
```

### Manual setup

If you'd rather do it by hand:

```bash
# 1. Clone your repo
git clone https://github.com/Tackk6/herosaver.git
cd herosaver

# 2. Create a Python 3.10 environment
python3.10 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate

# 3. Install PyTorch (GPU build shown; see pytorch.org for your CUDA version)
pip install torch --index-url https://download.pytorch.org/whl/cu121

# 4. Install the rest
pip install -r requirements.txt

# 5. Install ADTOF-pytorch (the transcription model)
git clone https://github.com/xavriley/ADTOF-pytorch.git
pip install -e ./ADTOF-pytorch
```

After this, the `adtof` command lives in your venv. Find its python with:

```bash
which python      # -> /path/to/herosaver/venv/bin/python
```

That path is what you pass as `--adtof-python` below (it's just your venv's
Python, since ADTOF installs into the same environment).

## Usage

### Full pipeline (audio → chart)

**Drums:**

```bash
python src/chart_song.py path/to/song.mp3 \
    --instrument drums \
    --title "Song Name" --artist "Artist Name" \
    --adtof-python ./venv/bin/python \
    --pro
```

**Guitar:**

```bash
python src/chart_song.py path/to/song.mp3 \
    --instrument guitar \
    --title "Song Name" --artist "Artist Name"
```

(Guitar uses Basic Pitch, which runs in the main environment, so it needs no
`--adtof-python`.)

Options:

| Flag | Meaning |
|------|---------|
| `--instrument` | `drums` (default) or `guitar` |
| `--title` | Song title (defaults to filename) |
| `--artist` | Artist name (defaults to "Unknown") |
| `--bpm` | Override BPM (otherwise read from the transcribed MIDI) |
| `--pro` | Pro drums (cymbal markers + toms) — drums only |
| `--adtof-python` | Path to the Python where ADTOF is installed (**required for drums**) |
| `--device` | `cuda` (default) or `cpu` |
| `--keep-intermediate` | Keep the work folder (stem + MIDI) for debugging |

Output lands in `./charts/<Artist> - <Title>/` containing `notes.chart`,
`song.ini`, and the audio as `song.<ext>`. Copy that folder into your Clone
Hero `songs` directory.

### From an existing MIDI

```bash
# inspect the tracks of a full-song MIDI
python src/midi_to_chart.py song.mid --list-tracks

# chart a specific track
python src/midi_to_chart.py song.mid --track 3 \
    --title "Song" --artist "Artist" --pro --audio song.ogg
```

## Difficulty design

Lower difficulties are made by **stripping layers**, not by randomly dropping
notes, so each one still feels like the song:

- **Easy** — kick + snare + sparse hi-hats; busy kicks collapse to a basic
  one-per-beat pattern; no two-pad collisions.
- **Medium** — adds blue/green toms (kept to basic beats) and a steadier
  hi-hat; kicks thinned to one per half-beat.
- **Hard** — nearly the full chart with fills slightly simplified.
- **Expert** — true to the transcription.

Every difficulty caps simultaneous hand-notes at two (plus the free kick foot),
since 3+ stacked pads are unplayable.

All of this is tunable in the `DIFF_SPEC` table at the top of
`src/midi_to_chart.py`.

For **guitar**, difficulties are controlled by note density (minimum gap
between notes) and chord size — Easy/Medium reduce chords to single notes,
Hard allows two-note chords, Expert keeps full chords. Tunable in `DIFF_SPEC`
at the top of `src/guitar_to_chart.py`.

## Difficulty rating

The chart's notes-per-second (on Expert) is mapped to Clone Hero's 0–6
intensity scale and written into `song.ini` as `diff_drums`.

## Limitations

- Transcription quality depends on the song; dense, heavily distorted, or
  multi-kit drumming is harder and may need manual cleanup in
  [Moonscraper](https://github.com/FireFox2000000/Moonscraper-Chart-Editor).
- BPM detection can occasionally land on half/double tempo; pass `--bpm` to fix.
- Pro-drums cymbal-vs-tom distinctions come from the model and aren't perfect.
- **Guitar is harder than drums and less polished.** Polyphonic note detection
  on distorted guitar is imperfect, and the interval-based fret mapping is a
  heuristic — it produces playable, musically-sensible charts but not what a
  skilled human charter would craft. Expect to refine guitar charts by hand.
  Cleanly recorded or less-distorted guitar transcribes noticeably better.

## Credits

Built on [Demucs](https://github.com/facebookresearch/demucs) (Meta) and
[ADTOF](https://github.com/MZehren/ADTOF) /
[ADTOF-pytorch](https://github.com/xavriley/ADTOF-pytorch). See those projects
for their respective licenses and papers.

## License

MIT — see [LICENSE](LICENSE).
