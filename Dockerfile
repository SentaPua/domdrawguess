# DomDrawGuess - self-hostable Gartic/Skribbl-style game
# Hugging Face Spaces (app_port: 7860) and any Docker host
FROM python:3.11-slim

# HF Spaces: run as user 1000
RUN useradd -m -u 1000 user
ENV HOME=/home/user PATH=/home/user/.local/bin:$PATH
WORKDIR /home/user/app

RUN pip install --no-cache-dir --upgrade pip

COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=user . .

USER user
EXPOSE 7860
CMD ["python", "-m", "uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "7860"]
