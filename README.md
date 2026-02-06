---
title: DomDrawGuess
emoji: 🎨
colorFrom: indigo
colorTo: purple
sdk: docker
app_port: 7860
---

# DomDrawGuess

A **Gartic / Skribbl.io–style** multiplayer drawing & guessing game you can self-host. One player draws a secret word; others guess in real time. Works on **Hugging Face Spaces** (Docker) and any server with Docker or Python.

## Features

- **Real-time multiplayer**: WebSocket sync for drawing and chat
- **Turn-based**: One drawer per round, others guess; rotate each round
- **Word list**: Built-in words (edit `words.txt` to customize)
- **Simple UI**: Canvas, brush size/color, clear, chat, scores
- **Self-host friendly**: Single FastAPI app, no DB required (in-memory state)

## Play locally

```bash
# Clone and enter repo
git clone https://github.com/YOUR_USERNAME/domdrawguess.git && cd domdrawguess

# Optional: create venv and install deps
python -m venv .venv
.venv\Scripts\activate   # Windows
# source .venv/bin/activate  # macOS/Linux
pip install -r requirements.txt

# Run (serves at http://localhost:7860)
python -m uvicorn server.main:app --reload --host 0.0.0.0 --port 7860
```

Open http://localhost:7860, enter a name and room ID, then share the room ID so others can join the same room.

## Deploy on Hugging Face Spaces

1. Create a **new Space** at [huggingface.co/new-space](https://huggingface.co/new-space).
2. Choose **Docker** as the SDK.
3. Push this repo to your Space (or copy the files). The Space `README.md` must include the YAML block at the top (see this file) with `sdk: docker` and `app_port: 7860`.
4. Your Space will build the Docker image and run the app. The game will be at:  
   `https://YOUR_USERNAME-domdrawguess.hf.space` (or your Space URL).

No extra config or secrets are required for basic use.

## Deploy with Docker (any host)

```bash
docker build -t domdrawguess .
docker run -p 7860:7860 domdrawguess
```

Then open `http://localhost:7860` (or your server’s host/port).

## Create the GitHub repo

You need to create the repository on GitHub yourself (the API requires your auth). Then push this project:

```bash
cd domdrawguess
git init
git add .
git commit -m "Initial commit: DomDrawGuess multiplayer game"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/domdrawguess.git
git push -u origin main
```

Replace `YOUR_USERNAME` with your GitHub username. If you prefer SSH:

```bash
git remote add origin git@github.com:YOUR_USERNAME/domdrawguess.git
```

## How to play

1. **Lobby**: Enter your name and a room ID. Share the room ID with friends.
2. **Start**: Once at least one player is in the room, click **Start game**.
3. **Draw**: The chosen player sees the secret word and draws on the canvas. Others see the drawing in real time.
4. **Guess**: Others type guesses in the chat. First correct guess gets points.
5. **Next round**: Click **Next round** to pass the turn to the next drawer.

## Tech

- **Backend**: FastAPI, WebSockets, in-memory rooms (no database).
- **Frontend**: Vanilla HTML/CSS/JS, no build step.
- **Words**: `words.txt` (comma-separated; lines starting with `#` are ignored).

## License

MIT.
