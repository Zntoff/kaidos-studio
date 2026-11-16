FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg fontconfig fonts-inter \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . .
# Editable install: the code looks for assets/, config/ and the prompts next to the package.
RUN pip install --no-cache-dir --upgrade "pip>=26.2" \
    && pip install --no-cache-dir -e ".[postgres]"

ENV CLIPPER_DATA_DIR=/data \
    CLIPPER_HOST=0.0.0.0 \
    CLIPPER_INPUT_DIR=/input \
    HF_HOME=/data/hf \
    PYTHONUNBUFFERED=1
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD python -c "import urllib.request as u;u.urlopen('http://localhost:8000/healthz')"
ENTRYPOINT ["python", "-m", "clipper"]
CMD ["web", "--host", "0.0.0.0", "--port", "8000"]
