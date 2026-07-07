FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libsndfile1 ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt requirements-sortformer.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY scripts/ scripts/
# onnxruntime-gpu enables CUDA for local ASR (onnx-asr auto-selects the provider)
ARG ONNX_GPU=false
RUN if [ "$ONNX_GPU" = "true" ]; then pip install --no-cache-dir onnxruntime-gpu; fi
# "auto" resolves to CPU wheels during image builds (no GPU is visible at
# build time); pass PYTORCH_INDEX_URL=cu130 to bake NVIDIA CUDA wheels in.
ARG INSTALL_SORTFORMER=true
ARG PYTORCH_INDEX_URL=auto
ENV INSTALL_SORTFORMER=${INSTALL_SORTFORMER}
ENV PYTORCH_INDEX_URL=${PYTORCH_INDEX_URL}
RUN python scripts/install_sortformer.py
RUN python scripts/download_models.py

COPY . .

CMD ["python", "scripts/start_backend.py"]
