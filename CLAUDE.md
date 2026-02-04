# zh project

## Environment

- Python venv: `/home/steven/git/.venv` (shared across projects)
  - Activate: `source /home/steven/git/.venv/bin/activate`
  - Run scripts: `/home/steven/git/.venv/bin/python`
- Key dependencies: moviepy, Pillow, reportlab

## Paths

- Pinyin audio: `/home/steven/git/zh_clones/Chinese-Pinyin-Audio/`
  - `Pinyin-Female/` and `Pinyin-Male/` (mp3), `Pinyin-Female-Wav/` and `Pinyin-Male-Wav/`
  - Filename format: `{pinyin}{tone_number}.mp3` (e.g., `yi1.mp3`, `zhong1.mp3`)
- Stroke order repos: `/home/steven/git/zh_clones/` (animCJK, makemeahanzi, etc.)
- CJK font: `/usr/share/fonts/chromeos/notocjk/NotoSansCJK-Regular.ttc`
- Latin font: `/usr/share/fonts/chromeos/noto/NotoSans-Regular.ttf`

## Data format

- Input: TSV files with columns like `radical`, `pinyin`, `english`, etc.
- Example: `radicals/kangxi.tsv`
- Pinyin in TSV uses tonal marks (e.g., `yī`); audio files use numbered tones (e.g., `yi1`)

## Commits

- Do NOT include Co-Authored-By or any Claude attribution in commit messages
