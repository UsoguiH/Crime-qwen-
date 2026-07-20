FROM python:3.12-slim-bookworm

# System deps: ffmpeg (keyframes), Pango/HarfBuzz/FriBiDi (WeasyPrint Arabic shaping),
# JetBrains Mono (technical surfaces in the PDF), unzip/curl (font fetch).
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 libfribidi0 \
        shared-mime-info fonts-jetbrains-mono fonts-dejavu-core \
        curl ca-certificates unzip \
    && rm -rf /var/lib/apt/lists/*

# IBM Plex Sans Arabic (OFL-1.1) — embedded in generated PDFs and used by Pillow badges.
RUN mkdir -p /usr/share/fonts/truetype/ibmplexsansarabic && \
    curl -fsSL -o /tmp/plex-arabic.zip \
      "https://github.com/IBM/plex/releases/download/%40ibm%2Fplex-sans-arabic%401.0.0/ibm-plex-sans-arabic.zip" && \
    unzip -j /tmp/plex-arabic.zip "*/fonts/complete/ttf/*.ttf" -d /usr/share/fonts/truetype/ibmplexsansarabic/ && \
    rm /tmp/plex-arabic.zip && fc-cache -f

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app
COPY pyproject.toml ./
RUN uv pip install --system --no-cache -r pyproject.toml --extra dev

# video-search embedder (SigLIP2): CPU-only torch wheel — no CUDA payload
RUN uv pip install --system --no-cache torch --index-url https://download.pytorch.org/whl/cpu \
 && uv pip install --system --no-cache "transformers>=4.53" "safetensors>=0.4"

COPY . .

# run from /app directly (no site-packages copy → no stale-shadow hazard)
# HF_HOME inside the data volume: embedder weights download once, then persist
ENV PYTHONUNBUFFERED=1 DATA_DIR=/data PYTHONPATH=/app HF_HOME=/data/hf-cache
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
