#!/usr/bin/env python3
"""Generate flashcard slideshow videos with stroke order animations.

Usage: slideshow_animated.py INPUT.tsv [OUTPUT.mp4]

Each character shows:
  - Stroke animation with audio repeating every 2.5 seconds
  - Pinyin appears at 1/3 through animation
  - English appears at 2/3 through animation
  - Final frame (completed character + all text) holds for 2 seconds
"""

import csv
import json
import re
import sys
import unicodedata
from pathlib import Path
from xml.etree import ElementTree as ET

import cairosvg
import numpy as np
from moviepy import (
    AudioFileClip,
    CompositeAudioClip,
    CompositeVideoClip,
    ImageClip,
    VideoClip,
    concatenate_videoclips,
)
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
WIDTH, HEIGHT = 480, 720
BG_COLOR = (255, 255, 255)
TEXT_COLOR = (0, 0, 0)
PINYIN_COLOR = (100, 100, 100)
ENGLISH_COLOR = (80, 80, 80)
FPS = 30

AUDIO_INTERVAL = 2.5  # seconds between audio plays
ANIM_DURATION = 2.5   # total animation time (strokes scaled to fit)
CYCLE_DURATION = 5.0  # one full cycle (animation + hold, or hold with text)
TOTAL_DURATION = 10.0 # total time per character (2 cycles)

CJK_FONT_PATH = "/usr/share/fonts/chromeos/notocjk/NotoSansCJK-Regular.ttc"
LATIN_FONT_PATH = "/usr/share/fonts/chromeos/noto/NotoSans-Regular.ttf"

AUDIO_DIR = Path("/home/steven/git/zh_clones/Chinese-Pinyin-Audio/Pinyin-Female")
ANIM_SVG_DIR = Path("/home/steven/git/zh_clones/animCJK/svgsZhHans")

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
# SVG Animation Rendering
# ---------------------------------------------------------------------------
def get_svg_path(character: str) -> Path | None:
    """Get the SVG path for a character."""
    codepoint = ord(character)
    svg_path = ANIM_SVG_DIR / f"{codepoint}.svg"
    if svg_path.exists():
        return svg_path
    return None


def parse_svg_strokes(svg_path: Path) -> tuple[str, list[dict]]:
    """Parse SVG to extract stroke information.

    Returns (base_svg_content, strokes) where strokes is a list of dicts with:
      - delay: animation delay in seconds
      - path_length: the pathLength attribute
    """
    content = svg_path.read_text()

    # Find all animated paths (those with style="--d:...")
    # Pattern: <path style="--d:1s;" pathLength="3333" clip-path="..." d="..."/>
    stroke_pattern = re.compile(
        r'<path\s+style="--d:([0-9.]+)s;"\s+pathLength="(\d+)"[^>]*/>',
        re.DOTALL
    )

    strokes = []
    for match in stroke_pattern.finditer(content):
        delay = float(match.group(1))
        path_length = int(match.group(2))
        strokes.append({
            'delay': delay,
            'path_length': path_length,
            'full_match': match.group(0),
        })

    return content, strokes


def get_animation_params(strokes: list[dict]) -> tuple[float, float]:
    """Calculate animation parameters from SVG stroke delays.

    Returns (min_delay, actual_duration) where:
      - min_delay: the initial delay before first stroke (to be removed)
      - actual_duration: time from first stroke start to last stroke end
    """
    if not strokes:
        return 0.0, 1.0
    min_delay = min(s['delay'] for s in strokes)
    max_delay = max(s['delay'] for s in strokes)
    # Original SVG uses 0.8s per stroke
    # Actual duration is from first stroke start to last stroke end
    actual_duration = (max_delay - min_delay) + 0.8
    return min_delay, actual_duration


def render_svg_frame(svg_content: str, strokes: list[dict], time: float,
                     min_delay: float, actual_duration: float, size: int = 256) -> Image.Image:
    """Render SVG at a specific animation time.

    Removes initial delay and scales stroke timing to fill ANIM_DURATION.
    """
    modified_svg = svg_content

    # Remove the entire <style> block - cairosvg can't parse the complex CSS
    modified_svg = re.sub(
        r'<style>.*?</style>',
        '',
        modified_svg,
        flags=re.DOTALL
    )

    # Add fill to background stroke paths (those with id attributes)
    modified_svg = re.sub(
        r'<path id="([^"]+)"',
        r'<path id="\1" fill="#ccc"',
        modified_svg
    )

    # Scale factor to stretch animation to fill ANIM_DURATION
    scale = ANIM_DURATION / actual_duration if actual_duration > 0 else 1.0

    for stroke in strokes:
        # Remove initial delay and scale to fit in ANIM_DURATION
        original_delay = stroke['delay']
        original_stroke_dur = 0.8  # Original SVG uses 0.8s per stroke

        # Shift delay so first stroke starts at 0, then scale
        adjusted_delay = (original_delay - min_delay) * scale
        scaled_stroke_dur = original_stroke_dur * scale

        path_length = stroke['path_length']

        # Calculate progress for this stroke
        stroke_start = adjusted_delay
        stroke_end = adjusted_delay + scaled_stroke_dur

        if time < stroke_start:
            # Stroke hasn't started - fully hidden
            progress = 0.0
        elif time >= stroke_end:
            # Stroke complete - fully visible
            progress = 1.0
        else:
            # Stroke in progress
            progress = (time - stroke_start) / scaled_stroke_dur

        # stroke-dashoffset: 0 = fully visible, larger = more hidden
        # Use 2x path_length to ensure full range of animation is visible
        max_offset = path_length * 2
        dashoffset = int(max_offset * (1 - progress))

        # Replace the path with explicit dashoffset (inline styles)
        old_path = stroke['full_match']
        new_style = f'stroke-dasharray:{max_offset};stroke-dashoffset:{dashoffset};stroke-width:128;stroke-linecap:round;fill:none;stroke:#000;'
        new_path = re.sub(r'style="[^"]*"', f'style="{new_style}"', old_path)
        modified_svg = modified_svg.replace(old_path, new_path)

    # Render to PNG
    png_data = cairosvg.svg2png(
        bytestring=modified_svg.encode(),
        output_width=size,
        output_height=size,
    )

    return Image.open(BytesIO(png_data)).convert('RGBA')


# ---------------------------------------------------------------------------
# Frame composition
# ---------------------------------------------------------------------------
MARGIN_TOP = 60
CHAR_SIZE = 240  # Size of the character animation area
CHAR_Y = MARGIN_TOP
PINYIN_FONT_SIZE = 64
ENGLISH_FONT_SIZE = 48
PINYIN_Y = CHAR_Y + CHAR_SIZE + 40
ENGLISH_Y = PINYIN_Y + PINYIN_FONT_SIZE + 30


def _center_x(draw, text, font):
    bbox = draw.textbbox((0, 0), text, font=font)
    return (WIDTH - (bbox[2] - bbox[0])) // 2


def compose_frame(
    char_img: Image.Image,
    pinyin: str | None = None,
    english: str | None = None,
) -> np.ndarray:
    """Compose a frame with character image and optional text."""
    img = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # Center the character image
    char_x = (WIDTH - char_img.width) // 2
    img.paste(char_img, (char_x, CHAR_Y), char_img if char_img.mode == 'RGBA' else None)

    # Add pinyin if provided
    if pinyin:
        latin_md = ImageFont.truetype(LATIN_FONT_PATH, PINYIN_FONT_SIZE)
        draw.text((_center_x(draw, pinyin, latin_md), PINYIN_Y),
                  pinyin, fill=PINYIN_COLOR, font=latin_md)

    # Add english if provided
    if english:
        latin_sm = ImageFont.truetype(LATIN_FONT_PATH, ENGLISH_FONT_SIZE)
        draw.text((_center_x(draw, english, latin_sm), ENGLISH_Y),
                  english, fill=ENGLISH_COLOR, font=latin_sm)

    return np.array(img)


def make_fallback_char_image(character: str, size: int = 256) -> Image.Image:
    """Create a simple character image when no SVG is available."""
    img = Image.new("RGBA", (size, size), (255, 255, 255, 0))
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(CJK_FONT_PATH, int(size * 0.8))
    bbox = draw.textbbox((0, 0), character, font=font)
    x = (size - (bbox[2] - bbox[0])) // 2
    y = (size - (bbox[3] - bbox[1])) // 2
    draw.text((x, y), character, fill=(0, 0, 0, 255), font=font)
    return img


# ---------------------------------------------------------------------------
# Video clip generation
# ---------------------------------------------------------------------------
def make_frame_func(svg_content: str, strokes: list[dict],
                    pinyin: str, english: str,
                    min_delay: float, actual_duration: float):
    """Create a frame function for moviepy that handles animation + text reveal.

    Timeline (10 seconds total):
      0-2.5s:   Animation plays (audio at 0s)
      2.5-5s:   Hold with pinyin (audio at 2.5s)
      5-7.5s:   Hold with pinyin + english (audio at 5s)
      7.5-10s:  Hold with all text (audio at 7.5s)
    """
    # Cache rendered frames to avoid re-rendering
    frame_cache = {}

    def make_frame(t):
        # Quantize time to reduce re-renders (to nearest 1/FPS)
        t_key = round(t * FPS) / FPS

        if t_key in frame_cache:
            return frame_cache[t_key]

        # Animation time (capped at ANIM_DURATION after animation completes)
        anim_t = min(t, ANIM_DURATION)

        # Render character at current animation state
        char_img = render_svg_frame(svg_content, strokes, anim_t, min_delay, actual_duration, CHAR_SIZE)

        # Determine which text to show based on timing
        # Pinyin appears at 2.5s (after first animation cycle)
        # English appears at 5s (after first full cycle)
        show_pinyin = t >= ANIM_DURATION
        show_english = t >= CYCLE_DURATION

        frame = compose_frame(
            char_img,
            pinyin if show_pinyin else None,
            english if show_english else None,
        )

        frame_cache[t_key] = frame
        return frame

    return make_frame, TOTAL_DURATION


def make_fallback_frame_func(character: str, pinyin: str, english: str):
    """Create frame function for characters without SVG animation.

    Uses same 10-second timeline as animated version.
    """
    char_img = make_fallback_char_image(character, CHAR_SIZE)

    def make_frame(t):
        show_pinyin = t >= ANIM_DURATION
        show_english = t >= CYCLE_DURATION
        return compose_frame(
            char_img,
            pinyin if show_pinyin else None,
            english if show_english else None,
        )

    return make_frame, TOTAL_DURATION


def create_audio_track(audio_path: Path, total_duration: float) -> CompositeAudioClip | None:
    """Create an audio track that repeats every AUDIO_INTERVAL seconds."""
    if not audio_path:
        return None

    audio = AudioFileClip(str(audio_path))
    clips = []

    t = 0
    while t < total_duration:
        clips.append(audio.with_start(t))
        t += AUDIO_INTERVAL

    return CompositeAudioClip(clips)


def slides_for_card(character: str, pinyin: str, english: str) -> list:
    """Generate the animated clip for one flashcard."""
    svg_path = get_svg_path(character)

    if svg_path:
        svg_content, strokes = parse_svg_strokes(svg_path)
        min_delay, actual_duration = get_animation_params(strokes)
        make_frame, total_duration = make_frame_func(
            svg_content, strokes, pinyin, english, min_delay, actual_duration
        )
    else:
        # Fallback for characters without SVG
        print(f"    (no SVG found for {character}, using fallback)")
        make_frame, total_duration = make_fallback_frame_func(character, pinyin, english)

    # Create video clip
    clip = VideoClip(make_frame, duration=total_duration).with_fps(FPS)

    # Add audio track
    audio_path = find_audio(pinyin)
    if audio_path:
        audio_track = create_audio_track(audio_path, total_duration)
        if audio_track:
            clip = clip.with_audio(audio_track)

    return [clip]


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

    print(f"Concatenating {len(all_clips)} clips...")
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
    import argparse
    parser = argparse.ArgumentParser(description="Generate flashcard slideshow videos")
    parser.add_argument("input", help="Input TSV file")
    parser.add_argument("output", nargs="?", help="Output MP4 file (or directory with --batch)")
    parser.add_argument("--batch", type=int, metavar="N",
                        help="Split into videos of N records each, output to directory")
    args = parser.parse_args()

    records = load_tsv(args.input)
    stem = Path(args.input).stem

    if args.batch:
        out_dir = Path(args.output) if args.output else Path(args.input).parent
        out_dir.mkdir(parents=True, exist_ok=True)
        for start in range(0, len(records), args.batch):
            batch = records[start:start + args.batch]
            batch_num = start // args.batch + 1
            out_path = str(out_dir / f"{stem}_{batch_num:02d}.mp4")
            print(f"\n=== Batch {batch_num} ({len(batch)} cards) → {out_path} ===")
            generate_video(batch, out_path)
    else:
        output = args.output or str(Path(args.input).with_suffix(".mp4"))
        generate_video(records, output)


if __name__ == "__main__":
    main()
