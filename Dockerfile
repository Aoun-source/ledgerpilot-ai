FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
# Fast offline sanity check of the rules engine (the full suite runs in CI)
RUN python scripts/make_samples.py && python -m pytest -q -p no:cacheprovider tests/test_rules.py tests/test_edge_cases.py

# Run as a normal user; the audit DB lives on a volume it owns, so it survives restarts
RUN useradd --create-home --uid 10001 app && mkdir -p /data && chown app /data
USER app
ENV AUDIT_DB=/data/ledgerpilot_audit.db
VOLUME ["/data"]

EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health', timeout=4)"
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0", "--browser.gatherUsageStats=false"]
