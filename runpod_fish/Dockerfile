# Base on fish-speech's OFFICIAL image -- exact, full-fidelity environment, all deps
# already correct (no pip-from-scratch dependency war). fish-speech code lives at /app.
FROM fishaudio/fish-speech:server-cuda

# fish uses a uv venv at /app/.venv -- install our glue INTO it (system python is
# PEP668 externally-managed). Most of these are already present from fish.
RUN uv pip install --python /app/.venv/bin/python --no-cache-dir \
        runpod boto3 ormsgpack huggingface_hub

COPY handler.py /app/handler.py

# s2-pro weights download to the attached network volume on first boot.
ENV HF_HOME=/runpod-volume/hf
WORKDIR /app
# Override the image's server entrypoint; run our handler with the venv python.
ENTRYPOINT []
CMD ["/app/.venv/bin/python", "-u", "/app/handler.py"]
