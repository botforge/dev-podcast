# Base on fish-speech's OFFICIAL image -- exact, full-fidelity environment, all deps
# already correct (no pip-from-scratch dependency war). fish-speech code lives at /app.
FROM fishaudio/fish-speech:server-cuda

# Only our worker glue (pure-python wheels, no native builds). Most are already present.
RUN pip install --no-cache-dir runpod boto3 ormsgpack huggingface_hub

COPY handler.py /app/handler.py

# s2-pro weights download to the attached network volume on first boot.
ENV HF_HOME=/runpod-volume/hf
WORKDIR /app
# Override the image's server entrypoint with our RunPod handler.
ENTRYPOINT []
CMD ["python", "-u", "/app/handler.py"]
