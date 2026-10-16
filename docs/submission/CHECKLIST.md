# Submission checklist

Deadline: **Saturday 17 October 2026, 17:00 UTC** (22:00 in Pakistan, UTC+5). Aim to submit by 15:00 UTC.

## 1. Live run (Phase 3), in the `ledgerpilot-ai` folder

First time? Set up the AMD droplet and Evolus from Windows with [../setup_windows.md](../setup_windows.md).

1. Save the filled-in settings as `ledgerpilot-ai\.env` (exactly that name: in Notepad choose
   "All files", or it saves as `.env.txt`). Never commit it; `git status` must not list it.
2. Run these in order and keep each one's full output:

   ```bash
   .venv\Scripts\python.exe scripts\upload_library.py
   ```

   ```bash
   .venv\Scripts\python.exe scripts\smoke_test.py
   ```

   Go on only when it ends with `ALL GOOD`.

   ```bash
   .venv\Scripts\python.exe eval\run_eval.py --label "Qwen2.5-32B"
   ```

   ```bash
   .venv\Scripts\python.exe scripts\benchmark_amd.py --label "Qwen2.5-32B" --gpu-price <your $/GPU-hour>
   ```

   The eval makes up to 6 Evolus calls per case (about 130 in all; clean invoices skip the email) and writes `docs/evaluation.md`,
   `docs/evaluation.json` and one demo recording per case in `data/recordings/`. The benchmark writes
   `docs/benchmark.md` and `docs/benchmark.json`.
3. Paste the four outputs to Claude. It will check them, link the two result files from the README,
   write the README's Business value section and fill every `[__]` in the deck, script and descriptions
   from these files only.
4. Check the per-case table in `docs/evaluation.md`. Any `(miss)` gets a sentence in the README's
   Limitations rather than a re-run until it passes.

## 2. Things only you can provide

- [ ] The manual time per invoice to compare against, **with a source** (a published survey or your own
      measurement). Without one, the Business value section reports measured time and fraud caught only.
- [ ] The GPU price you actually pay per hour on AMD Developer Cloud (for `--gpu-price`).
- [ ] Team name, for the deck cover.
- [ ] In the Evolus workspace, check which model the three extractors and the email AI Tool use. The
      rules require the main agent to run on your AMD endpoint (it does by design, via the agent's model
      setting). Note in the README if the extractors use a different model.

## 3. Repository

- [ ] Create a **public** GitHub repo and push `main` (`git remote add origin <url>`, then `git push -u origin main`).
- [ ] On GitHub, confirm both workflows pass: **tests** and **docker** (the Docker build has only been
      checked by reading it until this runs).
- [ ] Replace `<your-account>` in the README's clone command with the real URL.
- [ ] Confirm `.env` is absent from the repo page and `.env.example` holds no real values.
- [ ] Commit `docs/evaluation.md`, `docs/benchmark.md` and `data/recordings/` from the live run.

## 4. Assets

- [ ] Deck: fill the brackets, then share it and export a PDF from its Share menu
      (Share › Export). The deck is private until you share it.
- [ ] Demo video, about 3 minutes, from `docs/submission/video_script.md`. Upload it (YouTube unlisted or
      the form's upload) and test the link in a private window.
- [ ] Cover image: `docs/submission/cover.png` (1920×1080). Regenerate with `python scripts/make_cover.py`.
- [ ] Short and long descriptions and tags: `docs/submission/descriptions.md`, numbers filled in.

## 5. Final checks before submitting

- [ ] `python -m pytest -q` passes on a fresh clone of the public repo.
- [ ] The app opens with `?demo=1&case=case_15` and shows the "Recorded run" banner (needs the recordings).
- [ ] Rehearse the demo once live: cases 01, 07, 15. Click **Clear demo history** first, or re-checks
      are flagged as duplicates.
- [ ] Search the deck, script and descriptions for `[__` and `[` placeholders: none left.
- [ ] Submit on the hackathon page under the **Evolus Business Agents on AMD** track, then open the
      submission and check every link.
