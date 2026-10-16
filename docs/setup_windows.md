# Setup from a Windows PC (no Linux needed)

The model runs on an AMD Instinct MI300X on **AMD Developer Cloud**: a Linux machine in the cloud
that you control from Windows over SSH. The app runs on your Windows PC. You never install Linux.

```
Windows PC                         AMD Developer Cloud droplet (Linux, MI300X)
  LedgerPilot app (Streamlit)        vLLM serving Qwen2.5-32B-Instruct on port 8000
        |                                     ^
        v                                     |
  Evolus workspace (cloud) -------------------+   the Evolus agent calls your endpoint
```

## Why not my own Radeon GPU?

The hackathon track asks for the model to be served from **your vLLM endpoint on AMD Developer Cloud**,
so a model on a home GPU would not meet it. There are practical reasons too: vLLM runs on Linux, Evolus
has to reach the endpoint over the internet (a home PC would need its port opened to the world), and
Qwen2.5-32B needs about 64 GB of GPU memory in float16. Use the cloud MI300X for the submission.

## 1. SSH key (once, in PowerShell)

```powershell
ssh-keygen -t ed25519
```

Press Enter at each question. Then print the public key and copy the whole line:

```powershell
type $env:USERPROFILE\.ssh\id_ed25519.pub
```

## 2. Create the droplet

In AMD Developer Cloud: create a GPU droplet, **1x MI300X**, image **vLLM** (Quick Start), paste the
public key from step 1, create. Copy its public IP address. The droplet is billed while it exists,
including when it is powered off; check your credits.

## 3. Start the model (PowerShell, then on the droplet)

```powershell
ssh root@<DROPLET_IP>
```

Now you are on the droplet. Run the commands from the README's "Model on AMD Developer Cloud" block.
Copy the long key printed by `echo $VLLM_API_KEY`; that is your `VLLM_API_KEY`. Loading the model takes
a few minutes. Watch it with:

```bash
tail -f /tmp/vllm.log
```

When the log says the server is running, press Ctrl+C (the server keeps running) and type `exit` twice.

## 4. Check it from Windows (PowerShell)

```powershell
curl.exe http://<DROPLET_IP>:8000/v1/models -H "Authorization: Bearer <VLLM_API_KEY>"
```

You should see `ledgerpilot-model`. If it times out, allow inbound TCP port 8000 in the droplet's
firewall settings. The endpoint is plain HTTP protected by the key: never share the key, and destroy
the droplet when judging is over.

## 5. Evolus

Follow [evolus_setup.md](evolus_setup.md): add your endpoint as a model, create the agent on it, the
three extractors, the library and the workflow, and copy every ID.

## 6. Settings file (PowerShell, in the `ledgerpilot-ai` folder)

```powershell
copy .env.example .env
notepad .env
```

Fill in the values and save. Check the name: `dir .env` must list `.env`, not `.env.txt`.

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
.venv\Scripts\python.exe eval\run_eval.py --label "Qwen2.5-32B"
.venv\Scripts\python.exe scripts\benchmark_amd.py --label "Qwen2.5-32B" --gpu-price <your $/GPU-hour>
```

Go past the smoke test only when it ends with `ALL GOOD`.

## 9. Run the app

```powershell
.venv\Scripts\python.exe -m streamlit run app.py
```

It opens at http://localhost:8501. The header should say the model is served on AMD Developer Cloud.
If the services are down on demo day, open http://localhost:8501/?demo=1 to replay the recorded runs.
