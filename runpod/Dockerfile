# MISO 8B runs here, on RunPod's GPU. Build via RunPod's GitHub integration --
# no local Docker needed. Ubuntu 22.04's default python3 is 3.10 (what MisoTTS wants).
FROM nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
        git python3 python3-pip ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/bin/python3 /usr/bin/python

WORKDIR /app
RUN git clone --depth 1 https://github.com/MisoLabsAI/MisoTTS.git
WORKDIR /app/MisoTTS
RUN python -m pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir runpod boto3

COPY handler.py /app/MisoTTS/handler.py

# Persist the ~16GB weights on a RunPod network volume so cold starts don't re-download.
ENV HF_HOME=/runpod-volume/hf
ENV PYTHONUNBUFFERED=1

CMD ["python", "-u", "handler.py"]
