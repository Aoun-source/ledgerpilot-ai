# Setup from a Windows PC (no Linux needed)

The app runs on your Windows PC. The model runs on AMD GPUs in the cloud. There are two ways to reach it:

- **Option A, AMD Token Factory (default):** a free model API run by AMD. Nothing to rent or start;
  you only need your team's API key.
- **Option B, your own vLLM droplet:** an AMD Instinct MI300X on **AMD Developer Cloud** that you
  control over SSH. Use this if your hackathon track requires the model on your own vLLM endpoint.

```
Windows PC                         AMD (cloud)
  LedgerPilot app (Streamlit)        Option A: Token Factory, DeepSeek-V4-Flash
        |                            Option B: your droplet, vLLM serving Qwen2.5-32B on port 8000
        v                                     ^
  Evolus workspace (cloud) -------------------+   the Evolus agent calls the model
```

## Why not my own Radeon GPU?

Evolus has to reach the model over the internet (a home PC would need its port opened to the world),
vLLM runs on Linux, and Qwen2.5-32B needs about 64 GB of GPU memory in float16. Token Factory or the
cloud MI300X avoid all of that.

## Option A: AMD Token Factory

### A1. Redeem the team key (in your browser)

1. Open **https://notebooks.amd.com/tokenfactory** and sign in with your AMD AI Developer Program
   account (the email your team registered with).
2. Click **Redeem API Key**. The key stays hidden until **every** teammate has done the same; click
   **Check Status** to see who is still pending.
3. When it appears, click **Copy to clipboard**. It looks like `rc-` followed by 48 characters.

If no key shows up at all, your account may still be in review; check its status on the same page.

### A2. Check it from Windows (PowerShell)

```powershell
curl.exe https://developer.amd.com.cn/radeon/api/v1/models -H "Authorization: Bearer <YOUR_RC_KEY>"
```

You should see a list that includes `DeepSeek-V4-Flash`.

Keep in mind:

- Your whole team shares this one key and its limits: about 20 requests a minute, 8 at once, and a
  daily cap. Don't run the evaluation or benchmark at the same time as a teammate.
- Send only the fictional sample invoices. Token Factory's terms forbid sensitive financial data and
  prompts are kept for about 2 days.
- Never paste the key into chat, screenshots or GitHub. It goes only in `.env`.

Then go to step 5.

## Option B: your own vLLM droplet

### B1. SSH key (once, in PowerShell)

```powershell
ssh-keygen -t ed25519
```

Press Enter at each question. Then print the public key and copy the whole line:

```powershell
type $env:USERPROFILE\.ssh\id_ed25519.pub
```

### B2. Create the droplet

In AMD Developer Cloud: create a GPU droplet, **1x MI300X**, image **vLLM** (Quick Start), paste the
public key from B1, create. Copy its public IP address. The droplet is billed while it exists,
including when it is powered off; check your credits.

### B3. Start the model (PowerShell, then on the droplet)

```powershell
ssh root@<DROPLET_IP>
```

Now you are on the droplet. Run the commands from the README's "Option B" block.
Copy the long key printed by `echo $VLLM_API_KEY`; that is your `AMD_API_KEY`. Loading the model takes
a few minutes. Watch it with:

```bash
tail -f /tmp/vllm.log
```

When the log says the server is running, press Ctrl+C (the server keeps running) and type `exit` twice.

### B4. Check it from Windows (PowerShell)

```powershell
curl.exe http://<DROPLET_IP>:8000/v1/models -H "Authorization: Bearer <VLLM_API_KEY>"
```

You should see `ledgerpilot-model`. If it times out, allow inbound TCP port 8000 in the droplet's
firewall settings. The endpoint is plain HTTP protected by the key: never share the key, and destroy
the droplet when judging is over.

## 5. Evolus

Follow [evolus_setup.md](evolus_setup.md): add the model (Token Factory or your droplet), create the
agent on it, the three extractors, the library and the workflow, and copy every ID.

## 6. Settings file (PowerShell, in the `ledgerpilot-ai` folder)

```powershell
copy .env.example .env
notepad .env
```

Fill in the values and save. For Token Factory, paste your key after `AMD_API_KEY=` and leave
`AMD_BASE_URL` and `AMD_MODEL` as they are. For your droplet, change those three as the comments in the
file show. Check the name: `dir .env` must list `.env`, not `.env.txt`.

## 7. Python environment (once)

Install Python 3.11 (`winget install Python.Python.3.11`), open a **new** PowerShell window, then in
the `ledgerpilot-ai` folder (skip this step on the PC where `.venv` already exists):

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m pytest -q
```

## 8. Live checks and results

```powershell
.venv\Scripts\python.exe scripts\upload_library.py
.venv\Scripts\python.exe scripts\smoke_test.py
.venv\Scripts\python.exe eval\run_eval.py --label "DeepSeek-V4-Flash"
.venv\Scripts\python.exe scripts\benchmark_amd.py --label "DeepSeek-V4-Flash"
```

Go past the smoke test only when it ends with `ALL GOOD`. On a droplet, use your model's label and add
`--requests 40 --concurrency 1 4 16 --gpu-price <your $/GPU-hour>` to the benchmark.

## 9. Run the app

```powershell
.venv\Scripts\python.exe -m streamlit run app.py
```

It opens at http://localhost:8501. The header should say the model is served on AMD Token Factory
(or AMD Developer Cloud for a droplet). If the services are down on demo day, open
http://localhost:8501/?demo=1 to replay the recorded runs.
