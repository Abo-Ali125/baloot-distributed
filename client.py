# client.py
# Simple CLI client; for Render deploy, set SERVER to your onrender URL.
import asyncio
import json
import os
import websockets

# Locally: ws://127.0.0.1:8765
# Render:  wss://<your-service-name>.onrender.com
SERVER = os.environ.get("SERVER_URL", "ws://127.0.0.1:8765")

async def recv_loop(ws):
    while True:
        msg = await ws.recv()
        data = json.loads(msg)
        t = data.get("type")
        if t == "hand":
            print(f"\nYour seat: {data['seat']} | Trump: {data['trump']}")
            print("Your hand:", ", ".join(data["hand"]))
        elif t == "room_state":
            print("Room players:", data["players"])
        elif t == "ready":
            print(data["msg"])
        elif t == "played":
            print(f"Seat {data['seat']} played {data['card']}")
        elif t == "turn":
            print(f"Turn: seat {data['turn']}")
        elif t == "trick_won":
            print(f"Trick winner: seat {data['winner']} | Scores (T0-T1): {data['scores']}")
        elif t == "trick_state":
            print(f"New trick. Leader: {data['leader']} | Turn: {data['turn']} | Trump: {data['trump']}")
        elif t == "game_over":
            print(f"GAME OVER. Final scores: {data['scores']}")
        elif t == "error":
            print("ERROR:", data.get("msg"))
        elif t == "hello":
            print(data.get("msg"))
        else:
            print("EVENT:", data)

async def input_loop(ws):
    print("""
Commands:
  /join <room> <name>     - join or create a room (need 4 players total)
  /start                  - start game (when 4 joined)
  /play <S-7|H-10|...>    - play a card, e.g., /play S-A
  /help                   - show this help
""")
    loop = asyncio.get_event_loop()
    while True:
        try:
            line = await loop.run_in_executor(None, input, "> ")
        except EOFError:
            break
        if not line.strip():
            continue
        if line.startswith("/join"):
            try:
                _, room, name = line.split(maxsplit=2)
            except ValueError:
                print("Usage: /join <room> <name>")
                continue
            await ws.send(json.dumps({"type":"join","room":room,"name":name}))
        elif line.startswith("/start"):
            await ws.send(json.dumps({"type":"start"}))
        elif line.startswith("/play"):
            try:
                _, card = line.split(maxsplit=1)
            except ValueError:
                print("Usage: /play <S-7|H-10|...>")
                continue
            await ws.send(json.dumps({"type":"play","card":card.strip()}))
        elif line.startswith("/help"):
            print("See commands above.")
        else:
            print("Unknown command. Type /help.")

async def main():
    async with websockets.connect(SERVER) as ws:
        await asyncio.gather(recv_loop(ws), input_loop(ws))

if __name__ == "__main__":
    asyncio.run(main())
