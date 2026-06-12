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
    && pip install --no-cache-dir runpod boto3 ormsgpack huggingface_hub \
    # fish's install pulls a torchvision that mismatches the base torch (ABI / _has_ops
    # circular import). Re-pin the matched trio for torch 2.4.0. --no-deps so pip doesn't
    # re-resolve and rebuild other packages (e.g. tokenizers, which needs Rust).
    && pip install --no-cache-dir --no-deps torch==2.4.0 torchvision==0.19.0 torchaudio==2.4.0

COPY handler.py /app/fish-speech/handler.py

# s2-pro weights download to the attached network volume on first boot.
ENV HF_HOME=/runpod-volume/hf
CMD ["python", "-u", "handler.py"]
