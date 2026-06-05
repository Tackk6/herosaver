# Clone Hero Auto-Charter

Automatically generate **Clone Hero drum charts** from any song using ML drum
transcription. Feed it an audio file; get back a ready-to-play song folder with
four difficulties (Easy / Medium / Hard / Expert), pro-drums support, and an
auto-computed difficulty rating.

## How it works

The pipeline has three stages:

```
song.mp3
  -> [Demucs]   isolate the drum stem from the full mix
  -> [ADTOF]    ML model transcribes the drum stem into a MIDI of drum hits
  -> [chart]    MIDI -> notes.chart (4 difficulties) + song.ini + audio
```

- **[Demucs](https://github.com/facebookresearch/demucs)** separates the drums
  from everything else, so the transcriber hears a clean drum track.
- **[ADTOF-pytorch](https://github.com/xavriley/ADTOF-pytorch)** is a deep
  learning automatic-drum-transcription model trained on real (non-synthetic)
  music. It outputs labeled hits (kick, snare, hi-hat, toms, cymbals).
- The **chart writer** maps those hits to Clone Hero lanes, builds four
  difficulties by intelligently stripping layers (not blind thinning), enforces
  playability rules, and writes a complete song folder.

Two entry points:

- **`chart_song.py`** — the full one-command pipeline (audio in, chart out).
- **`midi_to_chart.py`** — just the MIDI→chart stage, if you already have a
  drum MIDI (supports `--list-tracks` / `--track` for full-song MIDIs).

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
git clone https://github.com/<you>/clone-hero-autocharter.git
cd clone-hero-autocharter
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
git clone https://github.com/<you>/clone-hero-autocharter.git
cd clone-hero-autocharter

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
which python      # -> /path/to/clone-hero-autocharter/venv/bin/python
```

That path is what you pass as `--adtof-python` below (it's just your venv's
Python, since ADTOF installs into the same environment).

## Usage

### Full pipeline (audio → chart)

```bash
python src/chart_song.py path/to/song.mp3 \
    --title "Song Name" \
    --artist "Artist Name" \
    --adtof-python ./venv/bin/python \
    --pro
```

Options:

| Flag | Meaning |
|------|---------|
| `--title` | Song title (defaults to filename) |
| `--artist` | Artist name (defaults to "Unknown") |
| `--bpm` | Override BPM (otherwise read from the transcribed MIDI) |
| `--pro` | Generate pro drums (cymbal markers + toms) |
| `--adtof-python` | Path to the Python where ADTOF is installed (**required**) |
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

## Difficulty rating

The chart's notes-per-second (on Expert) is mapped to Clone Hero's 0–6
intensity scale and written into `song.ini` as `diff_drums`.

## Limitations

- Transcription quality depends on the song; dense, heavily distorted, or
  multi-kit drumming is harder and may need manual cleanup in
  [Moonscraper](https://github.com/FireFox2000000/Moonscraper-Chart-Editor).
- BPM detection can occasionally land on half/double tempo; pass `--bpm` to fix.
- Pro-drums cymbal-vs-tom distinctions come from the model and aren't perfect.

## Credits

Built on [Demucs](https://github.com/facebookresearch/demucs) (Meta) and
[ADTOF](https://github.com/MZehren/ADTOF) /
[ADTOF-pytorch](https://github.com/xavriley/ADTOF-pytorch). See those projects
for their respective licenses and papers.

## License

MIT — see [LICENSE](LICENSE).
