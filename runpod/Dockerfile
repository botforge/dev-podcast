# MISO 8B runs here on RunPod's GPU. Built by RunPod's GitHub integration -- no local Docker.
# Base off the official PyTorch image: torch 2.4.0 + CUDA are already inside, so the build
# skips the slow from-scratch torch/CUDA install (the thing that wedged the first build).
FROM pytorch/pytorch:2.4.0-cuda12.1-cudnn9-runtime

ENV DEBIAN_FRONTEND=noninteractive PYTHONUNBUFFERED=1
# build-essential (gcc) lets torch.compile / Triton JIT-compile CUDA kernels at runtime
# (the slim -runtime base omits it). Without it, torch.compile errors out.
RUN apt-get update && apt-get install -y --no-install-recommends git ffmpeg build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN git clone --depth 1 https://github.com/MisoLabsAI/MisoTTS.git
WORKDIR /app/MisoTTS
# MisoTTS pulls the Llama 3.2 tokenizer from the gated meta-llama repo. Redirect to an
# ungated mirror with the identical tokenizer -- no Meta license, no HF token needed.
RUN grep -rl "meta-llama/Llama-3.2-1B" . | xargs -r sed -i \
        's#meta-llama/Llama-3.2-1B#unsloth/Llama-3.2-1B#g' || true
# torch==2.4.0 in requirements is already satisfied by the base image -> pip skips it.
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir runpod boto3

COPY handler.py /app/MisoTTS/handler.py

# Persist the ~16GB weights on the attached network volume so cold starts don't re-download.
ENV HF_HOME=/runpod-volume/hf

CMD ["python", "-u", "handler.py"]
