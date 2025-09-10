import asyncio
import time
import uuid
from typing import Dict, List, Optional


from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel


from game import GameRoom, Card, ABNAT


app = FastAPI()
app.add_middleware(
CORSMiddleware,
allow_origins=["*"],
allow_credentials=True,
allow_methods=["*"],
allow_headers=["*"],
)


# In-memory registry of rooms and per-player event queues
ROOMS: Dict[str, GameRoom] = {}
EVENT_QUEUES: Dict[str, asyncio.Queue] = {} # key = player_id


POLL_TIMEOUT = 25 # seconds for long-poll hold


class JoinReq(BaseModel):
room_id: str
name: str
player_id: Optional[str] = None

class ReadyReq(BaseModel):
room_id: str
player_id: str

class PlayReq(BaseModel):
room_id: str
player_id: str
suit: str
rank: str
action_id: str
class EventsResp(BaseModel):
events: List[dict]
cursor: int
# ------------- helpers -------------


def q(player_id: str) -> asyncio.Queue:
if player_id not in EVENT_QUEUES:
EVENT_QUEUES[player_id] = asyncio.Queue()
return EVENT_QUEUES[player_id]


async def broadcast(room: GameRoom, payload: dict):
# send to all connected players in the room
for seat in room.players:
if seat.player_id:
await q(seat.player_id).put({"ts": time.time(), **payload})


# ------------- routes -------------


@app.post("/join")
async def join(req: JoinReq):
room = ROOMS.get(req.room_id)
if room is None:
room = GameRoom(room_id=req.room_id)
ROOMS[req.room_id] = room


player_id = req.player_id or str(uuid.uuid4())
seat_index = room.join(player_id=player_id, name=req.name)
await q(player_id).put({"type": "room_state", "room": room.snapshot(player_id)})
await broadcast(room, {"type": "presence", "seats": room.seat_summary()})
return {"player_id": player_id, "seat": seat_index, "room": room.snapshot(player_id)}


@app.post("/ready")
async def ready(req: ReadyReq):
room = ROOMS.get(req.room_id)
if not room:
raise HTTPException(404, "ROOM_NOT_FOUND")
seat = room.seat_of(req.player_id)
if seat is None:
raise HTTPException(403, "NOT_IN_ROOM")
await room.on_ready(seat)
await broadcast(room, {"type": "room_state", "room": room.snapshot(req.player_id)})
return {"ok": True}


@app.post("/play")
async def play(req: PlayReq):
room = ROOMS.get(req.room_id)
if not room:
raise HTTPException(404, "ROOM_NOT_FOUND")
seat = room.seat_of(req.player_id)
if seat is None:
raise HTTPException(403, "NOT_IN_ROOM")


try:
await room.on_play_card(seat, Card(suit=req.suit, rank=req.rank), req.action_id)
except ValueError as e:
# domain errors map to HTTP 400 with code in message
raise HTTPException(400, str(e))


# announce updates
await broadcast(room, {"type": "turn_update", "room": room.public_snapshot()})


# if trick finished, announce result
if room._just_finished_trick:
await broadcast(room, {
"type": "trick_result",
"trick_index": room.trick_index - 1,
"winner_seat": room.completed_tricks[-1].winner_seat,
"team_abnat": room.team_abnat,
})
room._just_finished_trick = False


# if round done, send score
if room.status == 'DONE':
await broadcast(room, {
"type": "score_update",
"team_abnat": room.team_abnat,
"round_points": room.round_points(),
})


return {"ok": True}


@app.get("/events", response_model=EventsResp)
async def events(room_id: str, player_id: str, cursor: int = 0):
# Long-poll for up to POLL_TIMEOUT or until one event queued
queue = q(player_id)
collected: List[dict] = []
try:
item = await asyncio.wait_for(queue.get(), timeout=POLL_TIMEOUT)
collected.append(item)
# flush any burst
while not queue.empty():
collected.append(queue.get_nowait())
except asyncio.TimeoutError:
pass


# cursor is a dumb increment here for demo; clients store last seen
cursor += len(collected)
return {"events": collected, "cursor": cursor}

