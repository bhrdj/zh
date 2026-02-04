#!/usr/bin/env python3
"""Generate flashcard slideshow videos from a TSV file.

Usage: slideshow.py INPUT.tsv [OUTPUT.mp4]

Each character gets 6 slides (1s each):
  1. Character (silent)
  2. Character (with pronunciation)
  3. Smaller character + pinyin (silent)
  4. Character + pinyin + english (silent)
  5. Character + pinyin + english (with pronunciation)
  6. Character + pinyin + english (silent, review)
"""

import csv
import sys
import unicodedata
from pathlib import Path

import numpy as np
from moviepy import (
    AudioFileClip,
    ImageClip,
    concatenate_videoclips,
)
from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
WIDTH, HEIGHT = 480, 720
BG_COLOR = (255, 255, 255)
TEXT_COLOR = (0, 0, 0)
PINYIN_COLOR = (100, 100, 100)
ENGLISH_COLOR = (80, 80, 80)
FPS = 1

SLIDE_DURATION = 1.0  # seconds per slide

CJK_FONT_PATH = "/usr/share/fonts/chromeos/notocjk/NotoSansCJK-Regular.ttc"
LATIN_FONT_PATH = "/usr/share/fonts/chromeos/noto/NotoSans-Regular.ttf"

AUDIO_DIR = Path("/home/steven/git/zh_clones/Chinese-Pinyin-Audio/Pinyin-Female")

# ---------------------------------------------------------------------------
# Tonal pinyin → numbered pinyin conversion
# ---------------------------------------------------------------------------
_TONE_CHARS = {
    "ā": ("a", 1), "á": ("a", 2), "ǎ": ("a", 3), "à": ("a", 4),
    "ē": ("e", 1), "é": ("e", 2), "ě": ("e", 3), "è": ("e", 4),
    "ī": ("i", 1), "í": ("i", 2), "ǐ": ("i", 3), "ì": ("i", 4),
    "ō": ("o", 1), "ó": ("o", 2), "ǒ": ("o", 3), "ò": ("o", 4),
    "ū": ("u", 1), "ú": ("u", 2), "ǔ": ("u", 3), "ù": ("u", 4),
    "ǖ": ("ü", 1), "ǘ": ("ü", 2), "ǚ": ("ü", 3), "ǜ": ("ü", 4),
}


def tonal_to_numbered(pinyin: str) -> str:
    """Convert tonal pinyin like 'yī' to numbered like 'yi1'."""
    pinyin = unicodedata.normalize("NFC", pinyin.strip().lower())
    tone = 5  # neutral tone default
    result = []
    for ch in pinyin:
        if ch in _TONE_CHARS:
            base, t = _TONE_CHARS[ch]
            tone = t
            result.append(base)
        else:
            result.append(ch)
    return "".join(result) + str(tone)


def find_audio(pinyin: str) -> Path | None:
    """Find audio file for a tonal pinyin string."""
    numbered = tonal_to_numbered(pinyin)
    path = AUDIO_DIR / f"{numbered}.mp3"
    if path.exists():
        return path
    if numbered.endswith("5"):
        path = AUDIO_DIR / f"{numbered[:-1]}.mp3"
        if path.exists():
            return path
    return None


# ---------------------------------------------------------------------------
# Frame rendering
# ---------------------------------------------------------------------------
MARGIN_TOP = 80
CHAR_FONT_SIZE = 202
PINYIN_FONT_SIZE = 74
ENGLISH_FONT_SIZE = 58
CHAR_Y = MARGIN_TOP
PINYIN_Y = CHAR_Y + CHAR_FONT_SIZE + 62
ENGLISH_Y = PINYIN_Y + PINYIN_FONT_SIZE + 47


def _center_x(draw, text, font):
    bbox = draw.textbbox((0, 0), text, font=font)
    return (WIDTH - (bbox[2] - bbox[0])) // 2


def make_frame_char(character: str) -> np.ndarray:
    """Character only, top-aligned."""
    img = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img)
    cjk = ImageFont.truetype(CJK_FONT_PATH, CHAR_FONT_SIZE)
    draw.text((_center_x(draw, character, cjk), CHAR_Y),
              character, fill=TEXT_COLOR, font=cjk)
    return np.array(img)


def make_frame_char_pinyin(character: str, pinyin: str) -> np.ndarray:
    """Character with pinyin below, same positions."""
    img = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img)
    cjk = ImageFont.truetype(CJK_FONT_PATH, CHAR_FONT_SIZE)
    latin = ImageFont.truetype(LATIN_FONT_PATH, PINYIN_FONT_SIZE)
    draw.text((_center_x(draw, character, cjk), CHAR_Y),
              character, fill=TEXT_COLOR, font=cjk)
    draw.text((_center_x(draw, pinyin, latin), PINYIN_Y),
              pinyin, fill=PINYIN_COLOR, font=latin)
    return np.array(img)


def make_frame_all(character: str, pinyin: str, english: str) -> np.ndarray:
    """Character + pinyin + english, same positions."""
    img = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img)
    cjk = ImageFont.truetype(CJK_FONT_PATH, CHAR_FONT_SIZE)
    latin_md = ImageFont.truetype(LATIN_FONT_PATH, PINYIN_FONT_SIZE)
    latin_sm = ImageFont.truetype(LATIN_FONT_PATH, ENGLISH_FONT_SIZE)
    draw.text((_center_x(draw, character, cjk), CHAR_Y),
              character, fill=TEXT_COLOR, font=cjk)
    draw.text((_center_x(draw, pinyin, latin_md), PINYIN_Y),
              pinyin, fill=PINYIN_COLOR, font=latin_md)
    draw.text((_center_x(draw, english, latin_sm), ENGLISH_Y),
              english, fill=ENGLISH_COLOR, font=latin_sm)
    return np.array(img)


def make_clip(frame: np.ndarray, duration: float = SLIDE_DURATION,
              audio_path: Path | None = None) -> ImageClip:
    """Create a clip from a frame, optionally with audio."""
    clip = ImageClip(frame, duration=duration)
    if audio_path:
        audio = AudioFileClip(str(audio_path))
        if audio.duration > duration:
            clip = clip.with_duration(audio.duration)
        clip = clip.with_audio(audio)
    return clip


# ---------------------------------------------------------------------------
# Per-character slide sequence
# ---------------------------------------------------------------------------
def slides_for_card(character: str, pinyin: str, english: str) -> list:
    """Generate the 6-slide sequence for one flashcard."""
    audio = find_audio(pinyin)
    f_char = make_frame_char(character)
    f_char_py = make_frame_char_pinyin(character, pinyin)
    f_all = make_frame_all(character, pinyin, english)

    return [
        make_clip(f_char),                              # 1. character, silent
        make_clip(f_char, audio_path=audio),            # 2. character + sound
        make_clip(f_char_py),                           # 3. char + pinyin, silent
        make_clip(f_all),                               # 4. all, silent
        make_clip(f_all, audio_path=audio),             # 5. all + sound
        make_clip(f_all),                               # 6. all, silent (review)
    ]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def load_tsv(path: str) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def generate_video(records: list[dict], output: str, char_col: str = None,
                   pinyin_col: str = "pinyin", english_col: str = "english"):
    headers = list(records[0].keys())
    if char_col is None:
        char_col = headers[0]

    all_clips = []
    for i, rec in enumerate(records):
        character = rec[char_col]
        pinyin = rec.get(pinyin_col, "")
        english = rec.get(english_col, "")
        if not pinyin:
            continue
        print(f"  [{i+1}/{len(records)}] {character} ({pinyin})")
        all_clips.extend(slides_for_card(character, pinyin, english))

    print(f"Concatenating {len(all_clips)} slides...")
    final = concatenate_videoclips(all_clips, method="compose")
    final.write_videofile(
        output,
        fps=FPS,
        codec="libx264",
        audio_codec="aac",
        ffmpeg_params=["-crf", "23"],
        logger="bar",
    )
    print(f"Written {output}")


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} INPUT.tsv [OUTPUT.mp4]")
        sys.exit(1)

    tsv_path = sys.argv[1]
    output = sys.argv[2] if len(sys.argv) >= 3 else str(Path(tsv_path).with_suffix(".mp4"))

    records = load_tsv(tsv_path)
    generate_video(records, output)


if __name__ == "__main__":
    main()
