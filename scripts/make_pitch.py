"""Build the pitch deck (PDF) and a silent slideshow video (MP4) for the submission.

    python scripts/make_pitch.py [voice_dir]
"""
from __future__ import annotations

import subprocess
import sys
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "submission"
W, H = 1920, 1080
BG, INK, MUTED, RULE, ACCENT = "#141618", "#ECEDEA", "#9AA09B", "#2C3033", "#10B981"
FONTS = Path("C:/Windows/Fonts")


def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / name), size)


SERIF, SERIF_B = "georgia.ttf", "georgiab.ttf"
SANS, SANS_B, MONO = "segoeui.ttf", "segoeuib.ttf", "consola.ttf"

SLIDES = [
    ("LedgerPilot AI",
     "Stops wrong and fraudulent supplier payments before they go out.",
     ["An accounts-payable agent built on Evolus, running an open model on AMD GPUs.",
      "AMD Developer Hackathon: ACT III  ·  Evolus Business Agents on AMD"]),
    ("The problem",
     "Invoices are still matched to purchase orders and delivery notes by hand.",
     ["Overbilling: a higher price than agreed, units that never arrived, totals that don't add up.",
      "Payment diversion: a perfect-looking invoice asks for payment to a new bank account.",
      "Duplicates: the same invoice arrives twice, sometimes with a look-alike number."]),
    ("How it works",
     "Documents in, a routed decision out, with a person in charge.",
     ["1  Evolus extractors read the purchase order, goods-received note and invoice.",
      "2  Python validates every field and runs the checks with Decimal maths.",
      "3  Detective Clerk, an Evolus agent on DeepSeek-V4-Flash via AMD Token Factory,",
      "    explains the evidence, cites the vendor master and proposes a route.",
      "4  An Evolus AI Tool drafts the supplier query or fraud alert.",
      "5  An Evolus workflow routes the case; a clerk approves or rejects."]),
    ("What it checks",
     "Every finding shows its code, the rule that fired and the amount at risk.",
     ["Three-way match on price and quantity",
      "Arithmetic and tax",
      "Vendor master and bank details",
      "PO balance",
      "Exact and look-alike duplicates"]),
    ("Safe by design",
     "The model explains. Code decides the money.",
     ["Code does every number; the agent never recomputes one.",
      "The agent can make a route stricter, never looser, so it cannot approve fraud.",
      "No answer, or an unreadable value, sends the invoice to a person with the reason.",
      "The model never sees the full bank account."]),
    ("Built to be checked",
     "Open model on AMD, Evolus agents, and a test suite behind it.",
     ["Over 200 offline tests and a Docker image built in CI",
      "Evaluation and benchmark scripts over 24 synthetic cases",
      "Demo mode that replays recorded runs, clearly labelled",
      "Python · Pydantic · Streamlit · SQLite · Evolus · AMD Token Factory"]),
    ("Thank you",
     "LedgerPilot AI  ·  team Bygest",
     ["Every invoice matched. Every risky payment stopped and explained."]),
]


def wrap(draw: ImageDraw.ImageDraw, text: str, f, width: int) -> list[str]:
    words, lines, line = text.split(" "), [], ""
    for w in words:
        trial = f"{line} {w}".strip()
        if draw.textlength(trial, font=f) <= width:
            line = trial
        else:
            lines.append(line)
            line = w
    lines.append(line)
    return lines


def render(i: int, title: str, lede: str, points: list[str]) -> Image.Image:
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    x = 140
    d.text((x, 96), "LEDGERPILOT AI", font=font(MONO, 26), fill=ACCENT)
    d.text((W - 140, 96), f"{i + 1:02d} / {len(SLIDES):02d}", font=font(MONO, 26), fill=MUTED, anchor="ra")
    d.line((x, 150, W - 140, 150), fill=RULE, width=2)

    big = i in (0, len(SLIDES) - 1)
    tf = font(SERIF_B, 132 if big else 96)
    y = 250 if big else 210
    d.text((x, y), title, font=tf, fill=INK)
    y += 170 if big else 130
    d.rectangle((x, y, x + 120, y + 8), fill=ACCENT)
    y += 50
    lf = font(SERIF, 46)
    for ln in wrap(d, lede, lf, W - 2 * x):
        d.text((x, y), ln, font=lf, fill=INK)
        y += 64
    y += 40
    pf = font(SANS, 38)
    for p in points:
        if not big and not p[:1].isdigit() and not p.startswith("    "):
            d.ellipse((x, y + 20, x + 14, y + 34), fill=ACCENT)
            px = x + 40
        else:
            px = x
        for ln in wrap(d, p, pf, W - px - 140):
            d.text((px, y), ln, font=pf, fill=MUTED if big else INK)
            y += 56
        y += 12

    d.line((x, H - 120, W - 140, H - 120), fill=RULE, width=2)
    d.text((x, H - 95), "Evolus  ·  AMD Token Factory  ·  DeepSeek-V4-Flash", font=font(SANS, 26), fill=MUTED)
    return im


def main() -> None:
    import imageio_ffmpeg

    frames = [render(i, *s) for i, s in enumerate(SLIDES)]
    pdf = OUT / "LedgerPilot_pitch.pdf"
    frames[0].save(pdf, save_all=True, append_images=frames[1:], resolution=150)

    # Optional voice-over: one WAV per slide (s0.wav, s1.wav, ...) in the folder given as argv[1].
    voice = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    fps, pad = 24, 0.8
    durations, audio = [8.0] * len(frames), None
    if voice:
        chunks, rate = [], None
        for i in range(len(frames)):
            with wave.open(str(voice / f"s{i}.wav")) as w:
                rate = w.getframerate()
                pcm = w.readframes(w.getnframes())
            silence = b"\x00\x00" * int(rate * pad)
            chunks.append(silence + pcm + silence)
            durations[i] = len(chunks[-1]) / 2 / rate
        audio = voice / "narration.wav"
        with wave.open(str(audio), "wb") as w:
            w.setnchannels(1), w.setsampwidth(2), w.setframerate(rate)
            w.writeframes(b"".join(chunks))

    silent = OUT / "_silent.mp4"
    writer = imageio_ffmpeg.write_frames(str(silent), (W, H), fps=fps, codec="libx264",
                                         pix_fmt_out="yuv420p", macro_block_size=8)
    writer.send(None)
    for f, secs in zip(frames, durations):
        buf = np.asarray(f, dtype=np.uint8).tobytes()
        for _ in range(round(fps * secs)):
            writer.send(buf)
    writer.close()

    mp4 = OUT / "LedgerPilot_demo.mp4"
    if audio:
        subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-i", str(silent),
                        "-i", str(audio), "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-shortest",
                        str(mp4)], check=True)
        silent.unlink()
    else:
        silent.replace(mp4)
    print(pdf, pdf.stat().st_size)
    print(mp4, mp4.stat().st_size, f"{sum(durations):.1f}s")


if __name__ == "__main__":
    main()
