#!/usr/bin/env python3
"""
Automated demo client for baloot-distributed.

Usage:
  python play_demo.py [--url BASE_URL] [--room ROOM_ID]

Defaults:
  BASE_URL = http://localhost:5000
  ROOM_ID = demo-room

This script will:
- Create 4 players in the same room
- Mark them ready (to trigger dealing)
- Attempt to fetch their hands via /api/reconnect
- Automatically play cards when it's a player's turn until the round finishes
- Print actions and server responses to the console
"""
import requests
import time
import random
import argparse
import sys

def api_post(base, path, json):
    url = base.rstrip('/') + path
    try:
        r = requests.post(url, json=json, timeout=10)
    except Exception as e:
        return None, f"request-error: {e}"
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, r.text

def api_get(base, path):
    url = base.rstrip('/') + path
    try:
        r = requests.get(url, timeout=10)
    except Exception as e:
        return None, f"request-error: {e}"
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, r.text

def join_players(base, room, names):
    sessions = []
    for name in names:
        status, body = api_post(base, '/api/join', {'room_id': room, 'player_name': name})
        if status != 200:
            raise RuntimeError(f"Join failed for {name}: {status} {body}")
        sessions.append({
            'name': name,
            'session_id': body['session_id'],
            'seat': body['seat'],
            'hand': []
        })
        print(f"[join] {name} -> seat {body['seat']} session {body['session_id']}")
        time.sleep(0.12)
    return sessions

def send_ready(base, sessions):
    for s in sessions:
        status, body = api_post(base, '/api/ready', {'session_id': s['session_id']})
        print(f"[ready] seat {s['seat']} status {status} res={body}")
        time.sleep(0.08)

def fetch_hands_if_available(base, sessions):
    # call reconnect to fetch hand if server returns it
    for s in sessions:
        status, body = api_post(base, '/api/reconnect', {'session_id': s['session_id']})
        if status == 200 and isinstance(body, dict):
            hand = body.get('hand')
            if hand:
                s['hand'] = hand.copy()
                print(f"[reconnect] seat {s['seat']} got hand ({len(hand)} cards)")
            else:
                print(f"[reconnect] seat {s['seat']} reconnect ok, no full hand returned")
        else:
            print(f"[reconnect] seat {s['seat']} failed reconnect: {status} {body}")

def demo_run(base, room):
    names = [f"Bot{i+1}" for i in range(4)]
    print("[demo] joining players...")
    sessions = join_players(base, room, names)
    time.sleep(0.5)
    print("[demo] sending ready for all players...")
    send_ready(base, sessions)

    # wait for game to start
    print("[demo] waiting for game to start and cards to be dealt...")
    start_time = time.time()
    started = False
    last_room_body = None
    while time.time() - start_time < 20:
        status, room_body = api_get(base, f'/api/room/{room}')
        last_room_body = room_body
        if status == 200 and isinstance(room_body, dict):
            state = room_body.get('state', {})
            # server uses keys like 'game_state' or similar — accept several variants
            gs = state.get('game_state') or (state.get('game') and 'in_progress')
            if gs and gs == 'in_progress':
                started = True
                break
        time.sleep(0.6)

    if not started:
        print("[demo] game didn't start within 20s. Dumping room response:")
        print(last_room_body)
        return

    # fetch full hands via reconnect
    fetch_hands_if_available(base, sessions)

    print("[demo] entering play loop...")
    finished = False
    loop_start = time.time()
    while time.time() - loop_start < 180 and not finished:
        status, room_body = api_get(base, f'/api/room/{room}')
        if status != 200 or not isinstance(room_body, dict):
            time.sleep(0.5)
            continue
        state = room_body.get('state', {})
        game = state.get('game') or {}
        game_state = state.get('game_state') or game.get('game_state')
        if game_state == 'finished':
            print("[demo] game_state finished.")
            finished = True
            break
        current_player = game.get('current_player')
        if current_player is None:
            time.sleep(0.4)
            continue

        # find bot for this seat
        for s in sessions:
            if s['seat'] == current_player:
                # ensure we have a hand; attempt reconnect if not
                if not s['hand']:
                    st, rb = api_post(base, '/api/reconnect', {'session_id': s['session_id']})
                    if st == 200 and isinstance(rb, dict) and rb.get('hand'):
                        s['hand'] = rb['hand']
                        print(f"[reconnect-fetch] seat {s['seat']} got hand ({len(s['hand'])})")
                # attempt to play a card
                if s['hand']:
                    random.shuffle(s['hand'])
                    played = False
                    for card in list(s['hand']):
                        st, res = api_post(base, '/api/play_card', {'session_id': s['session_id'], 'card': card})
                        if st == 200:
                            print(f"[play] seat {s['seat']} played {card}")
                            s['hand'].remove(card)
                            played = True
                            break
                        else:
                            # server rejected; try next card
                            print(f"[play-reject] seat {s['seat']} card {card}: {st} {res}")
                    if not played:
                        time.sleep(0.25)
                else:
                    time.sleep(0.25)
        # endpoint might eventually show final results
        if all(len(s['hand']) == 0 for s in sessions):
            print("[demo] all local hands empty, finishing.")
            finished = True
            break
        time.sleep(0.3)

    print("[demo] finished demo run. Final room state:")
    st, rb = api_get(base, f'/api/room/{room}')
    print(rb)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='http://localhost:5000', help='Base URL for server (default http://localhost:5000)')
    parser.add_argument('--room', default='demo-room', help='Room id to use (default demo-room)')
    args = parser.parse_args()
    try:
        demo_run(args.url, args.room)
    except KeyboardInterrupt:
        print("Interrupted by user", file=sys.stderr)
        sys.exit(0)
    except Exception as e:
        print("Demo failed:", e, file=sys.stderr)
        sys.exit(1)