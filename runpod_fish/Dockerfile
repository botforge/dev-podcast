# Fish Speech S2 worker. Built in CI -> ghcr, run on RunPod. torch is in the base image.
FROM pytorch/pytorch:2.4.0-cuda12.1-cudnn9-runtime

ENV DEBIAN_FRONTEND=noninteractive PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends \
        git ffmpeg build-essential libsox-dev portaudio19-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN git clone --depth 1 https://github.com/fishaudio/fish-speech.git
WORKDIR /app/fish-speech
RUN pip install --no-cache-dir -e . \
    && pip install --no-cache-dir runpod boto3 ormsgpack huggingface_hub

COPY handler.py /app/fish-speech/handler.py

# s2-pro weights download to the attached network volume on first boot.
ENV HF_HOME=/runpod-volume/hf
CMD ["python", "-u", "handler.py"]
