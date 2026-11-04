FROM python:3.12-slim
RUN pip install --no-cache-dir httpx==0.28.1 pydantic==2.13.4 av==19.0.2 pillow==13.0.0
COPY media_probe.py speech_probe.wav /qos/
ENTRYPOINT ["python3", "/qos/media_probe.py"]
