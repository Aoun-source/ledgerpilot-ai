"""Build the beginner start-up guide as a PDF.

    python scripts/make_start_guide.py      # -> docs/LedgerPilot_Start_Guide.pdf
"""
from __future__ import annotations

import sys
from pathlib import Path
from xml.sax.saxutils import escape

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ledgerpilot.config import TOKEN_FACTORY_MODEL, TOKEN_FACTORY_SIGN_IN, TOKEN_FACTORY_URL  # noqa: E402
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    KeepTogether, PageBreak, Paragraph, Preformatted, SimpleDocTemplate, Spacer, Table, TableStyle,
)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "LedgerPilot_Start_Guide.pdf"

INK, MUTED, RULE = colors.HexColor("#1D2A36"), colors.HexColor("#4A5560"), colors.HexColor("#D5DCE3")
CODE_BG, TIP_BG, WARN_BG = colors.HexColor("#EEF1F4"), colors.HexColor("#E6F2EA"), colors.HexColor("#FBF0DC")
BLUE, AMBER = colors.HexColor("#1F5FA8"), colors.HexColor("#A86400")


def _fonts() -> tuple[str, str, str]:
    """Arial and Consolas from Windows when present (full character set), else the built-ins."""
    fonts = Path("C:/Windows/Fonts")
    try:
        pdfmetrics.registerFont(TTFont("Body", str(fonts / "arial.ttf")))
        pdfmetrics.registerFont(TTFont("Body-Bold", str(fonts / "arialbd.ttf")))
        pdfmetrics.registerFont(TTFont("Mono", str(fonts / "consola.ttf")))
        pdfmetrics.registerFontFamily("Body", normal="Body", bold="Body-Bold", italic="Body", boldItalic="Body-Bold")
        return "Body", "Body-Bold", "Mono"
    except Exception:  # noqa: BLE001 - not on Windows: fall back to the standard PDF fonts
        return "Helvetica", "Helvetica-Bold", "Courier"


BODY, BOLD, MONO = _fonts()
S = {
    "title": ParagraphStyle("title", fontName=BOLD, fontSize=30, leading=36, textColor=INK, spaceAfter=10),
    "sub": ParagraphStyle("sub", fontName=BODY, fontSize=14, leading=19, textColor=MUTED, spaceAfter=18),
    "h1": ParagraphStyle("h1", fontName=BOLD, fontSize=19, leading=24, textColor=INK, spaceBefore=4, spaceAfter=8),
    "h2": ParagraphStyle("h2", fontName=BOLD, fontSize=12.5, leading=16, textColor=BLUE, spaceBefore=10, spaceAfter=4),
    "p": ParagraphStyle("p", fontName=BODY, fontSize=10.2, leading=14.2, textColor=INK, spaceAfter=5, alignment=TA_LEFT),
    "small": ParagraphStyle("small", fontName=BODY, fontSize=8.8, leading=12, textColor=MUTED, spaceAfter=4),
    "cell": ParagraphStyle("cell", fontName=BODY, fontSize=9.2, leading=12, textColor=INK),
    "cellb": ParagraphStyle("cellb", fontName=BOLD, fontSize=9.2, leading=12, textColor=INK),
    "code": ParagraphStyle("code", fontName=MONO, fontSize=8.6, leading=11.4, textColor=INK),
    "box": ParagraphStyle("box", fontName=BODY, fontSize=9.8, leading=13.6, textColor=INK),
}


def P(text: str, style: str = "p") -> Paragraph:
    """Paragraph; `code` in backticks becomes monospace, **bold** stays bold. Everything else is escaped."""
    out, parts = [], text.split("`")
    for i, part in enumerate(parts):
        part = escape(part)
        if i % 2:
            out.append(f'<font face="{MONO}" size="9">{part}</font>')
        else:
            bits = part.split("**")
            out.append("".join(f"<b>{b}</b>" if j % 2 else b for j, b in enumerate(bits)))
    return Paragraph("".join(out), S[style])


def code(*lines: str) -> Table:
    t = Table([[Preformatted("\n".join(lines), S["code"])]], colWidths=[174 * mm])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), CODE_BG), ("BOX", (0, 0), (-1, -1), 0.6, RULE),
                           ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                           ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    return t


def box(kind: str, text: str) -> Table:
    bg, edge, label = {"tip": (TIP_BG, colors.HexColor("#1F7A4D"), "Tip"),
                       "warn": (WARN_BG, AMBER, "Careful"),
                       "ok": (TIP_BG, colors.HexColor("#1F7A4D"), "You should see")}[kind]
    t = Table([[P(f"**{label}:** {text}", "box")]], colWidths=[174 * mm])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), bg), ("LINEBEFORE", (0, 0), (0, -1), 3, edge),
                           ("LEFTPADDING", (0, 0), (-1, -1), 9), ("RIGHTPADDING", (0, 0), (-1, -1), 9),
                           ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    return t


def table(rows: list[list[str]], widths: list[float], header: bool = True) -> Table:
    data = [[P(c, "cellb" if (r == 0 and header) or (c_i == 0 and not header) else "cell")
             for c_i, c in enumerate(row)] for r, row in enumerate(rows)]
    t = Table(data, colWidths=[w * mm for w in widths], repeatRows=1 if header else 0)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0) if header else (0, -1), CODE_BG),
                           ("GRID", (0, 0), (-1, -1), 0.5, RULE),
                           ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 5),
                           ("RIGHTPADDING", (0, 0), (-1, -1), 5), ("TOPPADDING", (0, 0), (-1, -1), 4),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    return t


def step(n: str, text: str, *extra) -> KeepTogether:
    return KeepTogether([P(f"**{n}.** {text}"), *extra, Spacer(1, 4)])


def gap(h: float = 6) -> Spacer:
    return Spacer(1, h)


PY = r".\.venv\Scripts\python.exe"


def story() -> list:
    s: list = []
    # ------------------------------------------------------------------ cover page
    s += [Spacer(1, 30 * mm), P("LedgerPilot AI", "title"),
          P("Start-up guide for Windows: from the project folder to a live demo and a submitted entry. "
            "No Linux needed on your PC.", "sub"),
          table([["Hackathon", "AMD Developer Hackathon: ACT III · track: Evolus Business Agents on AMD"],
                 ["Deadline", "Saturday 17 October 2026, 17:00 UTC (22:00 in Pakistan)"],
                 ["Project folder", r"C:\Users\madinapc\Pictures\New folder\ledgerpilot001-ai\ledgerpilot-ai"]],
                [32, 142], header=False),
          gap(14), P("How to use this guide", "h2"),
          P("Do the parts in order. Each grey box is a command: copy **one line at a time** into PowerShell and "
            "press Enter."),
          P("Text in angle brackets, like `<YOUR_RC_KEY>`, means **put your own value there**, without the brackets."),
          P("If a command prints red error text, copy all of it and look it up in \"If something goes wrong\" at the end."),
          gap(10), P("The parts", "h2"),
          table([["Part", "What you do", "Rough time"],
                 ["1", "Open the project folder and PowerShell", "5 min"],
                 ["2", "Try the app on your PC without any keys", "10 min"],
                 ["3", "Get your team's AMD Token Factory key", "10 min + teammates"],
                 ["4", "Set up the Evolus workspace", "30 min"],
                 ["5", "Write your settings file (.env)", "10 min"],
                 ["6", "Live checks and results", "30-60 min"],
                 ["7", "Run the app and rehearse the demo", "15 min"],
                 ["8", "Publish on GitHub and submit", "45 min"]], [14, 125, 35]),
          PageBreak()]

    # ------------------------------------------------------------------ big picture
    s += [P("The big picture", "h1"),
          P("Three pieces work together. Your PC only runs the app; the AI model runs on AMD GPUs in the cloud "
            "through **AMD Token Factory**, a free model service run by AMD. There is nothing to rent or start."),
          code("Your Windows PC                    AMD Token Factory (cloud, AMD GPUs)",
               "  LedgerPilot app  ---------->     DeepSeek-V4-Flash, OpenAI-compatible API",
               "        |                                   ^",
               "        v                                   |",
               "  Evolus workspace (website) -------------+  the Evolus agent calls the model"),
          gap(), box("tip", "Your RX 9060 XT is not needed: the model runs in AMD's cloud. If your track rules "
                            "require your own vLLM server instead, follow Option B in `docs\\setup_windows.md`."),
          gap(10), P("Files you will open", "h2"),
          table([["File (inside the project folder)", "What it is", "Open with"],
                 [".env.example", "Template for your settings. You copy it to .env.", "(copied in Part 5)"],
                 [".env", "Your keys and IDs. Never share or upload it.", "Notepad"],
                 [r"docs\evolus_setup.md", "Exact Evolus setup, with the extractor fields to copy", "Notepad"],
                 [r"src\ledgerpilot\agent_client.py", "Lines 21-36: the agent instructions to paste into Evolus",
                  "Notepad"],
                 [r"docs\evaluation.md", "Your measured results (created in Part 6)", "Notepad"],
                 [r"docs\benchmark.md", "AMD model speed results (created in Part 6)", "Notepad"],
                 [r"docs\submission\CHECKLIST.md", "Final submission checklist", "Notepad"],
                 [r"docs\submission\video_script.md", "What to say and show in the video", "Notepad"],
                 [r"docs\submission\descriptions.md", "Text to paste into the submission form", "Notepad"],
                 [r"docs\submission\cover.png", "Cover image for the submission (1920x1080)", "Photos"],
                 ["app.py", "The app itself. You don't need to edit it.", "-"]], [58, 88, 28]),
          gap(), P("To open a file in Notepad from PowerShell, type `notepad` and the file name, for example "
                   r"`notepad docs\evolus_setup.md`."),
          PageBreak()]

    # ------------------------------------------------------------------ part 1
    s += [P("Part 1 · Open the project and PowerShell", "h1"),
          step("1", "Open **File Explorer** and go to the project folder:",
               code(r"C:\Users\madinapc\Pictures\New folder\ledgerpilot001-ai\ledgerpilot-ai")),
          P("Got the project as **ledgerpilot-ai.zip** instead? Right-click it, choose **Extract All**, and open "
            "the `ledgerpilot-ai` folder inside.", "small"),
          step("2", "Click the **address bar** at the top of the File Explorer window, type `powershell` and press "
                    "Enter. A blue or black PowerShell window opens, already in the project folder."),
          step("3", "Check you are in the right place:", code("dir")),
          box("ok", "a list that includes `app.py`, `README.md`, `requirements.txt` and the folders `docs`, "
                    "`scripts` and `src`."),
          gap(),
          box("warn", r"Run every command from the inner `ledgerpilot-ai` folder. If the prompt shows "
                      r"`C:\WINDOWS\system32>` (a PowerShell opened as Administrator) or ends in "
                      r"`ledgerpilot001-ai>` (one folder too high), go to the right folder first with the "
                      "command below. Keep the quotes: the path has a space in `New folder`."),
          gap(4),
          code(r'cd "C:\Users\madinapc\Pictures\New folder\ledgerpilot001-ai\ledgerpilot-ai"'),
          gap(12),
          # ---------------------------------------------------------------- part 2
          P("Part 2 · Try it on your PC (no keys needed)", "h1"),
          P("On **this** PC the Python environment (the `.venv` folder) already exists: skip to step 3. "
            "On a new PC, do steps 1 and 2 once."),
          step("1", "Install Python 3.11, then **close PowerShell and open it again** in the project folder (Part 1):",
               code("winget install Python.Python.3.11")),
          step("2", "Create the environment and install the libraries (takes a few minutes):",
               code("py -3.11 -m venv .venv", rf"{PY} -m pip install -r requirements.txt")),
          step("3", "Run the automatic tests (about one minute):", code(f"{PY} -m pytest -q")),
          box("ok", "a last line like `208 passed, 1 skipped`."),
          gap(),
          step("4", "Start the app:", code(f"{PY} -m streamlit run app.py")),
          box("ok", "your browser opens http://localhost:8501 with the LedgerPilot page. Yellow warnings in the "
                    "left sidebar are normal: there are no keys yet."),
          gap(), step("5", "To stop the app, click the PowerShell window and press **Ctrl+C**."),
          PageBreak()]

    # ------------------------------------------------------------------ part 3
    s += [P("Part 3 · Get your team's AMD Token Factory key", "h1"),
          P("AMD Token Factory gives your team one free API key for its AI models. Menu names on the website may "
            "differ slightly from the ones below."),
          P("3.1 Redeem the key (in your browser)", "h2"),
          step("1", "Open this page and sign in with your **AMD AI Developer Program** account (the email your "
                    "team registered with):", code(TOKEN_FACTORY_SIGN_IN)),
          step("2", "Your team dashboard shows every member and whether they have redeemed. Click "
                    "**Redeem API Key**."),
          step("3", "The key is hidden until **every teammate** has signed in and clicked **Redeem API Key**. "
                    "Message them, then click **Check Status** to refresh."),
          step("4", "When the key appears, click **Copy to clipboard** and paste it into Notepad. It looks like "
                    "`rc-` followed by 48 letters and numbers. This guide calls it `<YOUR_RC_KEY>`."),
          box("warn", "Keep the key secret: it goes only in `.env` (Part 5) and in Evolus (Part 4). Never post it "
                      "in chat, screenshots or GitHub. If no key appears at all, your account may still be in review."),
          gap(),
          KeepTogether([
              P("3.2 Check it from Windows", "h2"),
              step("1", "In PowerShell on your PC (one line):",
                   code(f'curl.exe {TOKEN_FACTORY_URL}/models -H "Authorization: Bearer <YOUR_RC_KEY>"')),
              box("ok", "text that contains `DeepSeek-V4-Flash`. An error with 401 means the key was copied "
                        "wrongly; copy it again.")]),
          gap(),
          box("tip", "Your whole team shares this one key and its limits: about **20 requests a minute** and a "
                     "daily cap. Don't run the Part 6 checks at the same time as a teammate. Send only the "
                     "sample invoices that come with the project, never real company invoices."),
          gap(14)]

    # ------------------------------------------------------------------ part 4
    s += [P("Part 4 · Set up the Evolus workspace", "h1"),
          P("Everything here happens on the Evolus website, in the **event workspace** from the hackathon link. "
            "The full details, including the exact fields for each extractor, are in a file:"),
          code(r"notepad docs\evolus_setup.md"), gap(),
          P("Keep a Notepad page open and write down every ID as you go. You need them all in Part 5."),
          table([["#", "In Evolus", "What to enter", "Write down"],
                 ["1", "Your models › add an OpenAI-compatible model",
                  f"Base URL `{TOKEN_FACTORY_URL}` · Model name `{TOKEN_FACTORY_MODEL}` · API key = "
                  "`<YOUR_RC_KEY>` from Part 3. Click **Test connection**.", "-"],
                 ["2", "Create an agent named LedgerPilot Clerk",
                  "Model: the one from row 1. Instructions: the text of lines 21-36 of "
                  r"`src\ledgerpilot\agent_client.py` (between the triple quotes). Temperature 0 to 0.2.",
                  "Agent ID"],
                 ["3", "Create 3 document extractors (JSON output)",
                  "Invoice, Purchase order, Goods-received note. Copy each field list from `evolus_setup.md` "
                  "exactly.", "3 extractor IDs"],
                 ["4", "Create a knowledge library: Vendor master and AP policy",
                  "Leave it empty for now (Part 6 uploads to it). Attach it to the agent.", "Library ID"],
                 ["5", "Create a workflow: Exception routing",
                  "As in `evolus_setup.md` section 5, with the 5 parameters. **Switch it on.**", "Workflow ID"],
                 ["6", "API keys page", "Create an API key.", "API key and space (app) ID"]],
                [8, 45, 88, 33]),
          gap(), box("tip", "To open the agent instructions: `notepad src\\ledgerpilot\\agent_client.py`, then "
                            "copy from the line after `AGENT_INSTRUCTIONS = \"\"\"` down to the closing `\"\"\"`."),
          PageBreak()]

    # ------------------------------------------------------------------ part 5
    s += [P("Part 5 · Write your settings file (.env)", "h1"),
          step("1", "In PowerShell, in the project folder, copy the template and open it:",
               code("copy .env.example .env", "notepad .env")),
          step("2", "Fill in each value after the `=` sign, with no spaces or quotes:",
               table([["Setting", "Where it comes from"],
                      ["AMD_API_KEY", "`<YOUR_RC_KEY>` from Part 3"],
                      ["AMD_BASE_URL, AMD_MODEL", "Leave as they are"],
                      ["AMD_REASONING_EFFORT", "Leave empty"],
                      ["EVOLUS_API_KEY", "Part 4, row 6"],
                      ["EVOLUS_APP_ID", "Part 4, row 6 (the space ID)"],
                      ["EVOLUS_AGENT_ID", "Part 4, row 2"],
                      ["EVOLUS_EXTRACTOR_AGENT_ID", "Leave empty unless the extractors belong to another agent"],
                      ["EVOLUS_EXTRACTOR_INVOICE_ID, _PO_ID, _GRN_ID", "Part 4, row 3"],
                      ["EVOLUS_WORKFLOW_ID", "Part 4, row 5"],
                      ["EVOLUS_LIBRARY_ID", "Part 4, row 4"],
                      ["PRICE_TOLERANCE, MAX_TAX_RATE, timeouts", "Leave as they are"]], [70, 104])),
          step("3", "Save (**Ctrl+S**) and close Notepad. Check the file name is exactly `.env`:", code("dir .env")),
          box("warn", "If you see `.env.txt` instead, rename it: `ren .env.txt .env`. Never email, upload or "
                      "commit `.env`; the project already tells Git to ignore it."),
          gap(14),
          # ---------------------------------------------------------------- part 6
          P("Part 6 · Live checks and results", "h1"),
          P("Run these one at a time, in this order, in the project folder. Save each window's output in a text "
            "file: you need the numbers for the submission."),
          step("1", "Upload the vendor master to your Evolus library:", code(rf"{PY} scripts\upload_library.py")),
          step("2", "The go/no-go check:", code(rf"{PY} scripts\smoke_test.py")),
          box("ok", "five lines starting with `PASS`, then `ALL GOOD`. If any line says `FAIL`, stop and fix it "
                    "first (see \"If something goes wrong\")."),
          gap(),
          step("3", "The full evaluation on all 24 sample invoices (several minutes, uses Evolus credits):",
               code(rf'{PY} eval\run_eval.py --label "{TOKEN_FACTORY_MODEL}"')),
          box("ok", "one line per case ending in `OK` or `MISS`, then a summary. It creates "
                    r"`docs\evaluation.md` and the demo recordings in `data\recordings`."),
          gap(),
          step("4", "The AMD model speed benchmark. It paces itself to stay under your team's shared limit and "
                    "takes about 3 minutes:",
               code(rf'{PY} scripts\benchmark_amd.py --label "{TOKEN_FACTORY_MODEL}"')),
          box("ok", r"`wrote docs/benchmark.md` at the end."),
          gap(), step("5", r"Copy the real numbers from `docs\evaluation.md` and `docs\benchmark.md` into the README, "
                           "slides, video script and descriptions. Never round them up."),
          gap(14)]

    # ------------------------------------------------------------------ part 7
    s += [P("Part 7 · Run the app and rehearse the demo", "h1"),
          step("1", "Start the app:", code(f"{PY} -m streamlit run app.py")),
          box("ok", "green boxes in the sidebar (AMD model online, Evolus connected) and, under the title, "
                    f"**Model: {TOKEN_FACTORY_MODEL} served on AMD Token Factory**."),
          gap(),
          step("2", "In the sidebar, click **Clear demo history**. Do this before every rehearsal, or re-checked "
                    "invoices are flagged as duplicates."),
          step("3", "Click the three demo buttons at the top of the page, one at a time:",
               table([["Button", "Expected stamp", "What to point at"],
                      ["Clean invoice (case 01)", "READY TO PAY", "High confidence; still waits for a person"],
                      ["Overcharged by $200 (case 07)", "ON HOLD", "PRICE_VARIANCE, $200 at risk, draft email"],
                      ["Bank account changed (case 15)", "PAYMENT BLOCKED", "BANK_MISMATCH, masked account, alert"]],
                     [62, 40, 72])),
          step("4", "Click **Measure model speed** in the sidebar to show tokens per second from the AMD model, "
                    "and **Check team usage** to see how much of today's quota is left."),
          step("5", "If the live services are slow on demo day, use demo mode (it replays your recorded live runs "
                    "and says so on screen). Turn on the sidebar switch, or open:",
               code("http://localhost:8501/?demo=1")),
          step("6", "Stop the app with **Ctrl+C** in PowerShell."),
          PageBreak()]

    # ------------------------------------------------------------------ part 8
    s += [P("Part 8 · Publish on GitHub and submit", "h1"),
          P("8.1 Put the code on GitHub", "h2"),
          step("1", "On github.com: **New repository**, name `ledgerpilot-ai`, choose **Public**, do **not** add a "
                    "README, then **Create repository**."),
          step("2", "In PowerShell, in the project folder. First check that `.env` is **not** listed:",
               code("git status")),
          step("3", "Save the results from Part 6 and send everything to GitHub (a sign-in window opens the first "
                    "time):",
               code("git add -A",
                    'git commit -m "Add live evaluation and benchmark results"',
                    "git remote add origin https://github.com/<YOUR_USERNAME>/ledgerpilot-ai.git",
                    "git push -u origin main")),
          box("ok", "on the GitHub page, your files. Open the **Actions** tab: the **tests** and **docker** checks "
                    "should turn green within a few minutes."),
          P("8.2 Finish the assets", "h2"),
          table([["Asset", "Where", "What to do"],
                 ["Video (about 3 min)", r"docs\submission\video_script.md",
                  "Record the app with the Windows Clipchamp app or OBS, following the script"],
                 ["Slides", "Your team's slide deck",
                  "Fill the [__] numbers, then export as PDF"],
                 ["Cover image", r"docs\submission\cover.png", "Upload as the project image"],
                 ["Descriptions and tags", r"docs\submission\descriptions.md", "Copy into the form"]],
                [36, 66, 72]),
          P("8.3 Submit", "h2"),
          step("1", "On lablab.ai, open the AMD Developer Hackathon: ACT III page and submit to the track "
                    "**Evolus Business Agents on AMD**."),
          step("2", "Add: GitHub link, video, slides PDF, cover image, short and long description, tags."),
          step("3", r"Go through docs\submission\CHECKLIST.md once more, then open your submission and test "
                    "every link."),
          step("4", "Check the GitHub page once more: no `.env` file and no `rc-` key anywhere."),
          PageBreak()]

    # ------------------------------------------------------------------ troubleshooting
    s += [P("If something goes wrong", "h1"),
          table([["What you see", "What to do"],
                 ["`python` or `py` is not recognized", "Close PowerShell and open it again in the project folder. "
                  f"Always start commands with `{PY}`."],
                 [r"`Access is denied: 'C:\WINDOWS\system32\.venv'`",
                  r"PowerShell is in `C:\WINDOWS\system32`, where Windows blocks new folders. Run the `cd` "
                  "command from Part 1 (use a normal, not Administrator, PowerShell), then run "
                  "`py -3.11 -m venv .venv` again."],
                 [r"`.\.venv\Scripts\python.exe` is not recognized",
                  "You are not in the project folder, or the environment was never created. Run the `cd` "
                  "command from Part 1, then Part 2 steps 2 and 3."],
                 ["`Could not open requirements file` or `No module named pytest`",
                  r"You are one folder too high (`ledgerpilot001-ai`). The project is in the inner "
                  r"`ledgerpilot-ai` folder: run the `cd` command from Part 1, create the `.venv` there and "
                  "install the libraries (Part 2 step 2)."],
                 ["`git` is not recognized", "Close PowerShell and open it again (Git was installed recently)."],
                 ["Git says Please tell me who you are",
                  'Run `git config --global user.name "Your Name"` and `git config --global user.email '
                  '"you@example.com"`, then commit again.'],
                 ["The app says settings are missing", "Check `dir .env` shows `.env` (not .env.txt) and that every "
                  "value in Part 5 is filled in. Restart the app after editing .env."],
                 ["Token Factory shows no key yet", "A teammate hasn't clicked Redeem API Key. Click Check Status "
                  "to see who is pending."],
                 ["401 from the AMD model", "AMD_API_KEY is wrong or has a space. Copy the key again (Part 3) and "
                  "restart the app."],
                 ["403 or account_not_verified", "Your AMD account is still in review. Check its status on the "
                  "Token Factory page."],
                 ["429 or Rate limited", "Your team used up the per-minute limit. Wait a minute; make sure only one "
                  "person runs the checks at a time."],
                 ["400 model not supported", "The Token Factory catalog changed. Run the Part 3.2 check, pick a "
                  "name from the list and put it in AMD_MODEL (and in the Evolus model)."],
                 ["Smoke test: FAIL on the AMD endpoint", "Redo the Part 3.2 check. If that works, AMD_API_KEY in "
                  ".env is wrong."],
                 ["Evolus rejected the API key (401/403)", "Check EVOLUS_API_KEY and EVOLUS_APP_ID."],
                 ["Evolus credits are used up (402)", "Ask the hackathon organisers for more credits."],
                 ["Workflow is switched off (409)", "Switch the workflow on in Evolus."],
                 ["Re-checked invoices show PAYMENT BLOCKED as duplicates", "Click Clear demo history in the "
                  "sidebar first."],
                 ["The app page is blank or stuck", "Press Ctrl+C in PowerShell, start the app again, refresh "
                  "the browser."],
                 ["Anything else", "Copy the whole error text, search for it online, or ask a teammate to look."]],
                [62, 112]),
          gap(16), P("Every command in one place", "h2"),
          code(r"cd 'C:\Users\madinapc\Pictures\New folder\ledgerpilot001-ai\ledgerpilot-ai'",
               f"{PY} -m pytest -q",
               "copy .env.example .env",
               "notepad .env",
               rf"{PY} scripts\upload_library.py",
               rf"{PY} scripts\smoke_test.py",
               rf'{PY} eval\run_eval.py --label "{TOKEN_FACTORY_MODEL}"',
               rf'{PY} scripts\benchmark_amd.py --label "{TOKEN_FACTORY_MODEL}"',
               f"{PY} -m streamlit run app.py",
               "git add -A",
               'git commit -m "Add live evaluation and benchmark results"',
               "git push")]
    return s


def _page(canvas, doc) -> None:
    canvas.saveState()
    canvas.setFont(BODY, 8)
    canvas.setFillColor(MUTED)
    if doc.page > 1:
        canvas.drawString(18 * mm, 12 * mm, "LedgerPilot AI · Start-up guide for Windows")
        canvas.drawRightString(A4[0] - 18 * mm, 12 * mm, f"Page {doc.page}")
    canvas.restoreState()


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(OUT), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=18 * mm,
                            bottomMargin=20 * mm, title="LedgerPilot AI: start-up guide for Windows",
                            author="LedgerPilot", subject="Setup, live run and submission steps")
    doc.build(story(), onFirstPage=_page, onLaterPages=_page)
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
