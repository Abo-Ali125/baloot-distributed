# server.py (Render-ready)
# Baloot server with WebSocket + simple HTTP healthcheck for Render.com
import asyncio
import json
import os
import random
from collections import defaultdict, deque

import websockets
from websockets.server import serve

SUITS = ["S", "H", "D", "C"]
RANKS = ["7", "8", "9", "J", "Q", "K", "10", "A"]
SAN_ORDER = {"7":0,"8":1,"9":2,"J":3,"Q":4,"K":5,"10":6,"A":7}
TRUMP_ORDER = {"7":0,"8":1,"Q":2,"K":3,"10":4,"A":5,"9":6,"J":7}

def make_deck():
    return [{"suit": s, "rank": r} for s in SUITS for r in RANKS]

def card_to_str(card):
    return f"{card['suit']}-{card['rank']}"

def str_to_card(s: str):
    suit, rank = s.split("-")
    return {"suit": suit, "rank": rank}

class Room:
    def __init__(self, room_id):
        self.id = room_id
        self.clients = []  # [(ws, name)]
        self.started = False
        self.hands = {}  # seat -> [cards]
        self.turn = 0
        self.leader = 0
        self.trick = []
        self.scores = [0,0]  # team0 seats (0,2) vs team1 (1,3)
        self.trump = None
        self.deck = []

    def player_team(self, seat):
        return 0 if seat in (0,2) else 1

    def broadcast(self, payload):
        return [send_json(ws, payload) for (ws, _) in self.clients]

    def deal(self):
        self.deck = make_deck()
        random.shuffle(self.deck)
        self.hands = {
            i: sorted(self.deck[i*8:(i+1)*8], key=lambda c:(c['suit'], SAN_ORDER[c['rank']]))
            for i in range(4)
        }
        self.leader = 0
        self.turn = self.leader
        self.trick = []

    def legal_card(self, seat, card):
        if not self.trick:
            return True
        lead_suit = self.trick[0][1]['suit']
        hand = self.hands[seat]
        has_lead = any(c['suit']==lead_suit for c in hand)
        if has_lead and card['suit'] != lead_suit:
            return False
        return True

    def trick_winner(self):
        lead_suit = self.trick[0][1]['suit']
        trump = self.trump
        def card_value(c):
            if trump and c['suit']==trump:
                return (2, TRUMP_ORDER[c['rank']])
            if c['suit']==lead_suit:
                return (1, SAN_ORDER[c['rank']])
            return (0, -1)
        best = max(self.trick, key=lambda sc: card_value(sc[1]))
        return best[0]

    def game_over(self):
        return any(s>=16 for s in self.scores)

ROOMS = {}
SEAT_OF = {}
NAMES = {}

async def send_json(ws, payload):
    await ws.send(json.dumps(payload))

async def handle_join(ws, data):
    room_id = data.get("room")
    name = data.get("name","Player")
    if room_id not in ROOMS:
        ROOMS[room_id] = Room(room_id)
    room = ROOMS[room_id]
    if room.started:
        return await send_json(ws, {"type":"error","msg":"Room already started"})
    if len(room.clients) >= 4:
        return await send_json(ws, {"type":"error","msg":"Room full"})
    seat = len(room.clients)
    room.clients.append((ws, name))
    SEAT_OF[ws] = (room_id, seat)
    NAMES[ws] = name
    await room.broadcast({"type":"room_state","room":room_id,"players":[n for _,n in room.clients]})
    if len(room.clients) == 4:
        await room.broadcast({"type":"ready","msg":"4 players joined. Host can /start to deal."})

async def handle_start(ws, data):
    room_id, seat = SEAT_OF[ws]
    room = ROOMS[room_id]
    if room.started:
        return
    if len(room.clients) < 4:
        return await send_json(ws, {"type":"error","msg":"Need 4 players"})
    room.started = True
    room.trump = None
    room.deal()
    for s,(w,n) in enumerate(room.clients):
        await send_json(w, {"type":"hand","seat":s,"hand":[card_to_str(c) for c in room.hands[s]],"trump":room.trump})
    await room.broadcast({"type":"trick_state","leader":room.leader,"turn":room.turn,"played":[],"trump":room.trump})

async def handle_play(ws, data):
    card_str = data.get("card")
    if ws not in SEAT_OF:
        return await send_json(ws, {"type":"error","msg":"Not seated"})
    room_id, seat = SEAT_OF[ws]
    room = ROOMS[room_id]
    if seat != room.turn:
        return await send_json(ws, {"type":"error","msg":"Not your turn"})
    try:
        card = str_to_card(card_str)
    except Exception:
        return await send_json(ws, {"type":"error","msg":"Bad card format"})
    hand = room.hands[seat]
    match_idx = next((i for i,c in enumerate(hand) if c['suit']==card['suit'] and c['rank']==card['rank']), None)
    if match_idx is None:
        return await send_json(ws, {"type":"error","msg":"You don't have that card"})
    if not room.legal_card(seat, card):
        return await send_json(ws, {"type":"error","msg":"Must follow suit if possible"})
    played = hand.pop(match_idx)
    room.trick.append((seat, played))
    await room.broadcast({"type":"played","seat":seat,"card":card_str})
    if len(room.trick) < 4:
        room.turn = (room.turn + 1) % 4
        await room.broadcast({"type":"turn","turn":room.turn})
        return
    winner = room.trick_winner()
    team = room.player_team(winner)
    room.scores[team] += 1
    await room.broadcast({"type":"trick_won","winner":winner,"scores":room.scores})
    room.leader = winner
    room.turn = winner
    room.trick = []
    if all(len(h)==0 for h in room.hands.values()):
        if room.game_over():
            await room.broadcast({"type":"game_over","scores":room.scores})
            room.started = False
            return
        room.deal()
        for s,(w,n) in enumerate(room.clients):
            await send_json(w, {"type":"hand","seat":s,"hand":[card_to_str(c) for c in room.hands[s]],"trump":room.trump})
    await room.broadcast({"type":"trick_state","leader":room.leader,"turn":room.turn,"played":[],"trump":room.trump})

async def ws_handler(ws):
    await send_json(ws, {"type":"hello","msg":"Welcome to Baloot server"})
    async for raw in ws:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            await send_json(ws, {"type":"error","msg":"JSON required"})
            continue
        t = data.get("type")
        if t == "join":
            await handle_join(ws, data)
        elif t == "start":
            await handle_start(ws, data)
        elif t == "play":
            await handle_play(ws, data)
        else:
            await send_json(ws, {"type":"error","msg":f"Unknown type: {t}"})

# Render healthcheck via HTTP response on non-WS requests
async def process_request(path, request_headers):
    # Respond OK for health checks at /healthz
    if path in ("/", "/healthz"):
        body = b"OK"
        headers = [
            ("Content-Type", "text/plain; charset=utf-8"),
            ("Content-Length", str(len(body))),
        ]
        return (200, headers, body)
    return None  # continue with normal WS handshake

async def main():
    host = "0.0.0.0"
    port = int(os.environ.get("PORT", "8765"))
    async with serve(ws_handler, host, port, process_request=process_request):
        print(f"Baloot server on ws://{host}:{port}")
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
