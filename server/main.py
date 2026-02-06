"""
DomDrawGuess - Skribbl/Gartic-style multiplayer drawing & guessing game.
FastAPI + WebSockets backend for self-hosting (Hugging Face Spaces, Docker, etc.).
"""
import asyncio
import json
import random
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

app = FastAPI(title="DomDrawGuess", version="1.0.0")

# In-memory state (per-process; use Redis for multi-instance)
ROOMS: dict[str, dict] = {}
WORD_LIST: list[str] = []


def load_words() -> list[str]:
    global WORD_LIST
    if WORD_LIST:
        return WORD_LIST
    words_path = Path(__file__).parent.parent / "words.txt"
    if not words_path.exists():
        WORD_LIST = ["cat", "dog", "sun", "moon", "star", "fish", "house", "tree", "apple", "bird"]
        return WORD_LIST
    words = []
    for line in words_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        words.extend(w.strip().lower() for w in line.split(",") if w.strip())
    WORD_LIST = list(dict.fromkeys(words)) or ["cat", "dog", "sun"]
    return WORD_LIST


def get_random_word() -> str:
    return random.choice(load_words())


class ConnectionManager:
    def __init__(self):
        self.connections: dict[str, list[WebSocket]] = {}
        self.ws_to_player: dict[str, dict[WebSocket, str]] = {}  # room_id -> { ws: player_id }

    async def connect(self, room_id: str, websocket: WebSocket, player_name: str) -> str:
        """Register a connection (caller must accept the WebSocket first)."""
        if room_id not in self.connections:
            self.connections[room_id] = []
            self.ws_to_player[room_id] = {}
        player_id = f"p{len(self.connections[room_id])}_{random.randint(1000, 9999)}"
        self.connections[room_id].append(websocket)
        self.ws_to_player[room_id][websocket] = player_id
        if room_id not in ROOMS:
            ROOMS[room_id] = {
                "players": {},
                "drawer_index": 0,
                "word": None,
                "round_time": 80,
                "scores": {},
                "strokes": [],
                "started": False,
                "round_start": None,
            }
        ROOMS[room_id]["players"][player_id] = {"name": player_name}
        ROOMS[room_id]["scores"][player_id] = ROOMS[room_id]["scores"].get(player_id, 0)
        return player_id

    def disconnect(self, room_id: str, websocket: WebSocket, player_id: str):
        if room_id in self.ws_to_player:
            self.ws_to_player[room_id].pop(websocket, None)
            if not self.ws_to_player[room_id]:
                del self.ws_to_player[room_id]
        if room_id in self.connections:
            self.connections[room_id] = [c for c in self.connections[room_id] if c != websocket]
            if not self.connections[room_id]:
                del self.connections[room_id]
        if room_id in ROOMS and player_id in ROOMS[room_id]["players"]:
            del ROOMS[room_id]["players"][player_id]
            if ROOMS[room_id]["players"]:
                ROOMS[room_id]["scores"] = {k: v for k, v in ROOMS[room_id]["scores"].items() if k in ROOMS[room_id]["players"]}
            else:
                del ROOMS[room_id]

    async def broadcast_room(self, room_id: str, message: dict, exclude_ws: WebSocket | None = None):
        if room_id not in self.connections:
            return
        payload = json.dumps(message)
        for ws in self.connections[room_id]:
            if ws != exclude_ws and ws.client_state.name == "CONNECTED":
                try:
                    await ws.send_text(payload)
                except Exception:
                    pass

    async def send_personal(self, websocket: WebSocket, message: dict):
        try:
            await websocket.send_text(json.dumps(message))
        except Exception:
            pass

    async def send_to_guessers(self, room_id: str, drawer_ws: WebSocket | None, message: dict):
        """Send message to all in room except the drawer."""
        if room_id not in self.connections:
            return
        payload = json.dumps(message)
        for ws in self.connections[room_id]:
            if ws != drawer_ws and ws.client_state.name == "CONNECTED":
                try:
                    await ws.send_text(payload)
                except Exception:
                    pass


manager = ConnectionManager()


def _get_drawer_ws(room_id: str, drawer_id: str):
    for ws, pid in manager.ws_to_player.get(room_id, {}).items():
        if pid == drawer_id:
            return ws
    return None


async def _hint_loop(room_id: str, drawer_id: str, word: str, round_time: float):
    """Every ~15s reveal a random letter to guessers. Stops when round ends."""
    room = ROOMS.get(room_id)
    if not room or room.get("word") != word:
        return
    room["hint_revealed"] = room.get("hint_revealed") or set()
    n = len(word)
    drawer_ws = _get_drawer_ws(room_id, drawer_id)
    interval = max(12, round_time / 4)
    try:
        for _ in range(int(round_time / interval)):
            await asyncio.sleep(interval)
            room = ROOMS.get(room_id)
            if not room or room.get("word") != word:
                break
            revealed = room.get("hint_revealed") or set()
            unrevealed = [i for i in range(n) if i not in revealed]
            if not unrevealed:
                break
            i = random.choice(unrevealed)
            revealed.add(i)
            room["hint_revealed"] = revealed
            await manager.send_to_guessers(room_id, drawer_ws, {"type": "hint", "index": i, "letter": word[i]})
    except asyncio.CancelledError:
        pass


static_dir = Path(__file__).parent.parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/")
async def index():
    index_path = static_dir / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return {"app": "domdrawguess", "message": "Add static/index.html to serve the game."}


@app.get("/health")
async def health():
    return {"status": "ok", "app": "domdrawguess"}


@app.websocket("/ws/{room_id}")
async def websocket_endpoint(websocket: WebSocket, room_id: str):
    player_id = None
    try:
        await websocket.accept()
        first = await websocket.receive_text()
        data = json.loads(first)
        player_name = (data.get("name") or "Player").strip()[:24] or "Player"
        player_id = await manager.connect(room_id, websocket, player_name)
        room = ROOMS.get(room_id, {})
        players_list = [
            {"id": pid, "name": room["players"][pid]["name"], "score": room["scores"].get(pid, 0)}
            for pid in room.get("players", {})
        ]
        await manager.send_personal(websocket, {
            "type": "joined",
            "playerId": player_id,
            "roomId": room_id,
            "players": players_list,
            "scores": room.get("scores", {}),
            "started": room.get("started", False),
            "word": None,  # word only sent on round_start to drawer
            "drawerId": list(room.get("players", {}).keys())[room.get("drawer_index", 0)] if room.get("players") else None,
            "strokes": room.get("strokes", []),
            "roundTime": room.get("round_time", 80),
        })
        await manager.broadcast_room(room_id, {
            "type": "player_joined",
            "playerId": player_id,
            "name": player_name,
            "players": players_list,
            "scores": room.get("scores", {}),
        }, exclude_ws=websocket)
        while True:
            raw = await websocket.receive_text()
            msg = json.loads(raw)
            t = msg.get("type")
            if t == "stroke":
                room = ROOMS.get(room_id)
                if room and room.get("strokes") is not None:
                    stroke = msg.get("stroke")
                    if stroke:
                        room["strokes"].append(stroke)
                        await manager.broadcast_room(room_id, {"type": "stroke", "stroke": stroke}, exclude_ws=websocket)
            elif t == "clear":
                room = ROOMS.get(room_id)
                if room:
                    room["strokes"] = []
                    await manager.broadcast_room(room_id, {"type": "clear"})
            elif t == "guess":
                room = ROOMS.get(room_id)
                word = (room or {}).get("word")
                guess = (msg.get("guess") or "").strip().lower()
                if word and guess == word:
                    correct_guessers = room.get("correct_guessers") or set()
                    if player_id in correct_guessers:
                        pass
                    else:
                        correct_guessers.add(player_id)
                        room["correct_guessers"] = correct_guessers
                        count = len(correct_guessers)
                        guesser_points = max(10, 100 - (count - 1) * 25)
                        drawer_id_round = room.get("drawer_id")
                        drawer_reward = 25
                        room["scores"][player_id] = room["scores"].get(player_id, 0) + guesser_points
                        if drawer_id_round and drawer_id_round != player_id:
                            room["scores"][drawer_id_round] = room["scores"].get(drawer_id_round, 0) + drawer_reward
                        pl = list(room["players"].keys())
                        players_list = [{"id": p, "name": room["players"][p]["name"], "score": room["scores"].get(p, 0)} for p in pl]
                        await manager.broadcast_room(room_id, {
                            "type": "correct",
                            "playerId": player_id,
                            "name": ROOMS[room_id]["players"].get(player_id, {}).get("name", "?"),
                            "scores": room["scores"],
                            "players": players_list,
                            "guessOrder": count,
                            "points": guesser_points,
                        })
                else:
                    await manager.broadcast_room(room_id, {
                        "type": "guess",
                        "playerId": player_id,
                        "name": ROOMS[room_id]["players"].get(player_id, {}).get("name", "?"),
                        "guess": msg.get("guess", ""),
                    })
            elif t == "start":
                room = ROOMS.get(room_id)
                if not room or room.get("started"):
                    continue
                pl = list(room["players"].keys())
                if len(pl) < 1:
                    continue
                room["started"] = True
                room["drawer_index"] = room.get("drawer_index", 0) % len(pl)
                drawer_id = pl[room["drawer_index"]]
                room["drawer_id"] = drawer_id
                room["word"] = get_random_word()
                room["strokes"] = []
                room["hint_revealed"] = set()
                room["drawing_started"] = False
                room["correct_guessers"] = set()
                if room.get("hint_task"):
                    room["hint_task"].cancel()
                round_time = room.get("round_time", 80)
                word_len = len(room["word"])
                w2p = manager.ws_to_player.get(room_id, {})
                for ws in manager.connections.get(room_id, []):
                    pid = w2p.get(ws)
                    if pid == drawer_id:
                        await manager.send_personal(ws, {"type": "round_start", "word": room["word"], "youDraw": True, "roundTime": round_time, "drawerIntro": True})
                    else:
                        await manager.send_personal(ws, {"type": "round_start", "word": None, "youDraw": False, "roundTime": round_time, "wordLength": word_len, "drawerIntro": True})
                players_list = [{"id": p, "name": room["players"][p]["name"], "score": room["scores"].get(p, 0)} for p in pl]
                await manager.broadcast_room(room_id, {"type": "round_start_broadcast", "drawerId": drawer_id, "players": players_list})
            elif t == "start_drawing":
                room = ROOMS.get(room_id)
                if not room or room.get("drawing_started") or room.get("drawer_id") != player_id:
                    continue
                if room.get("word") is None:
                    continue
                room["drawing_started"] = True
                room["round_start"] = asyncio.get_event_loop().time()
                round_time = room.get("round_time", 80)
                room["hint_task"] = asyncio.create_task(_hint_loop(room_id, room["drawer_id"], room["word"], round_time))
                await manager.broadcast_room(room_id, {"type": "drawing_started", "roundTime": round_time})
            elif t == "next_round":
                room = ROOMS.get(room_id)
                if not room or not room.get("players"):
                    continue
                if room.get("hint_task"):
                    room["hint_task"].cancel()
                    room["hint_task"] = None
                pl = list(room["players"].keys())
                room["drawer_index"] = (room.get("drawer_index", 0) + 1) % len(pl)
                drawer_id = pl[room["drawer_index"]]
                room["drawer_id"] = drawer_id
                room["word"] = get_random_word()
                room["strokes"] = []
                room["hint_revealed"] = set()
                room["drawing_started"] = False
                room["correct_guessers"] = set()
                round_time = room.get("round_time", 80)
                word_len = len(room["word"])
                w2p = manager.ws_to_player.get(room_id, {})
                for ws in manager.connections.get(room_id, []):
                    pid = w2p.get(ws)
                    if pid == drawer_id:
                        await manager.send_personal(ws, {"type": "round_start", "word": room["word"], "youDraw": True, "roundTime": round_time, "drawerIntro": True})
                    else:
                        await manager.send_personal(ws, {"type": "round_start", "word": None, "youDraw": False, "roundTime": round_time, "wordLength": word_len, "drawerIntro": True})
                players_list = [{"id": p, "name": room["players"][p]["name"], "score": room["scores"].get(p, 0)} for p in pl]
                await manager.broadcast_room(room_id, {"type": "round_start_broadcast", "drawerId": drawer_id, "players": players_list})
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        if player_id and room_id in ROOMS:
            manager.disconnect(room_id, websocket, player_id)
            room = ROOMS.get(room_id)
            if room and room.get("players"):
                players_list = [{"id": p, "name": room["players"][p]["name"], "score": room["scores"].get(p, 0)} for p in room["players"]]
                await manager.broadcast_room(room_id, {"type": "player_left", "playerId": player_id, "players": players_list, "scores": room["scores"]})


if __name__ == "__main__":
    import uvicorn
    load_words()
    uvicorn.run(app, host="0.0.0.0", port=7860)
