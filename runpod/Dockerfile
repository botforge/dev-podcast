# MISO 8B runs here on RunPod's GPU. Built by RunPod's GitHub integration -- no local Docker.
# Base off the official PyTorch image: torch 2.4.0 + CUDA are already inside, so the build
# skips the slow from-scratch torch/CUDA install (the thing that wedged the first build).
FROM pytorch/pytorch:2.4.0-cuda12.1-cudnn9-runtime

ENV DEBIAN_FRONTEND=noninteractive PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends git ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN git clone --depth 1 https://github.com/MisoLabsAI/MisoTTS.git
WORKDIR /app/MisoTTS
# torch==2.4.0 in requirements is already satisfied by the base image -> pip skips it.
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir runpod boto3

COPY handler.py /app/MisoTTS/handler.py

# Persist the ~16GB weights on the attached network volume so cold starts don't re-download.
ENV HF_HOME=/runpod-volume/hf

CMD ["python", "-u", "handler.py"]
