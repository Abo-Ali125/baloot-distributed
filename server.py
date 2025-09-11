"""
Baloot Game Server
HTTP server with long-polling for real-time game updates
"""
import json
import uuid
import time
import logging
import os
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from threading import Lock
from collections import deque
from datetime import datetime, timedelta

from game import Game
from models import Player, Room, GameState

# Serve static files from ./static (so visiting / serves the UI if index.html exists)
app = Flask(__name__, static_folder='static', static_url_path='')
CORS(app)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global storage
rooms = {}
rooms_lock = Lock()
player_sessions = {}  # Maps session_id to player data
events_queue = {}  # Maps room_id to deque of events

# Configuration
MAX_PLAYERS_PER_ROOM = 4
LONG_POLL_TIMEOUT = 30  # seconds
MAX_EVENTS_PER_ROOM = 100

def create_session_id():
    """Generate unique session ID for players"""
    return str(uuid.uuid4())

def get_or_create_room(room_id):
    """Get existing room or create new one"""
    with rooms_lock:
        if room_id not in rooms:
            rooms[room_id] = Room(room_id)
            events_queue[room_id] = deque(maxlen=MAX_EVENTS_PER_ROOM)
            logger.info(f"Created new room: {room_id}")
        return rooms[room_id]

def broadcast_event(room_id, event_type, data):
    """Send event to all players in room"""
    if room_id in events_queue:
        event = {
            'type': event_type,
            'data': data,
            'timestamp': time.time()
        }
        events_queue[room_id].append(event)
        logger.info(f"Broadcasting {event_type} to room {room_id}")

@app.route('/', methods=['GET', 'HEAD'])
def root():
    """Serve the frontend HTML if present; otherwise return JSON health."""
    index_path = os.path.join(app.static_folder or '', 'index.html')
    if index_path and os.path.exists(index_path):
        # Serve the static index.html (so visiting the Render URL shows the UI)
        return send_from_directory(app.static_folder, 'index.html')
    # Fallback: keep returning the JSON health payload (keeps health check behavior)
    return jsonify({'status': 'healthy', 'rooms': len(rooms)}), 200

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint for Render"""
    return jsonify({'status': 'healthy', 'rooms': len(rooms)}), 200

@app.route('/api/join', methods=['POST'])
def join_room():
    """Join a room and get assigned a seat"""
    try:
        data = request.json
        room_id = data.get('room_id')
        player_name = data.get('player_name', 'Player')
        
        if not room_id:
            return jsonify({'error': 'room_id required'}), 400
        
        room = get_or_create_room(room_id)
        
        # Check if room is full
        if room.is_full():
            return jsonify({'error': 'Room is full'}), 400
        
        # Create session and player
        session_id = create_session_id()
        player = Player(session_id, player_name)
        
        # Add player to room
        seat = room.add_player(player)
        if seat is None:
            return jsonify({'error': 'Could not join room'}), 400
        
        # Store session
        player_sessions[session_id] = {
            'player': player,
            'room_id': room_id,
            'seat': seat
        }
        
        # Broadcast join event
        broadcast_event(room_id, 'player_joined', {
            'player_name': player_name,
            'seat': seat,
            'players': room.get_players_info()
        })
        
        return jsonify({
            'session_id': session_id,
            'seat': seat,
            'room_state': room.get_state(),
            'players': room.get_players_info()
        }), 200
        
    except Exception as e:
        logger.error(f"Error in join_room: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/ready', methods=['POST'])
def player_ready():
    """Mark player as ready to start"""
    try:
        data = request.json
        session_id = data.get('session_id')
        
        if session_id not in player_sessions:
            return jsonify({'error': 'Invalid session'}), 401
        
        session = player_sessions[session_id]
        room_id = session['room_id']
        room = rooms.get(room_id)
        
        if not room:
            return jsonify({'error': 'Room not found'}), 404
        
        player = session['player']
        player.is_ready = True
        
        # Check if all players ready
        ready_count = sum(1 for p in room.players.values() if p and p.is_ready)
        
        broadcast_event(room_id, 'player_ready', {
            'player_name': player.name,
            'seat': session['seat'],
            'ready_count': ready_count,
            'all_ready': ready_count == MAX_PLAYERS_PER_ROOM
        })
        
        # Start game if all ready
        if ready_count == MAX_PLAYERS_PER_ROOM and not room.game:
            room.start_game()
            broadcast_event(room_id, 'game_started', {
                'dealer': room.game.dealer,
                'current_player': room.game.current_player
            })
            
            # Send cards to each player
            for seat, p in room.players.items():
                if p:
                    broadcast_event(room_id, 'cards_dealt', {
                        'seat': seat,
                        'cards': room.game.hands[seat]
                    })
        
        return jsonify({'success': True, 'all_ready': ready_count == MAX_PLAYERS_PER_ROOM}), 200
        
    except Exception as e:
        logger.error(f"Error in player_ready: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/play_card', methods=['POST'])
def play_card():
    """Play a card during your turn"""
    try:
        data = request.json
        session_id = data.get('session_id')
        card = data.get('card')  # e.g., "7H", "AS", "10D"
        
        if session_id not in player_sessions:
            return jsonify({'error': 'Invalid session'}), 401
        
        session = player_sessions[session_id]
        room_id = session['room_id']
        seat = session['seat']
        room = rooms.get(room_id)
        
        if not room or not room.game:
            return jsonify({'error': 'Game not started'}), 400
        
        # Validate turn
        if room.game.current_player != seat:
            return jsonify({'error': 'Not your turn'}), 400
        
        # Try to play card
        success, message = room.game.play_card(seat, card)
        
        if not success:
            return jsonify({'error': message}), 400
        
        # Broadcast card played
        broadcast_event(room_id, 'card_played', {
            'seat': seat,
            'card': card,
            'trick': room.game.current_trick,
            'next_player': room.game.current_player
        })
        
        # Check if trick complete
        if len(room.game.current_trick) == 4:
            winner, points = room.game.resolve_trick()
            broadcast_event(room_id, 'trick_complete', {
                'winner': winner,
                'points': points,
                'team_scores': room.game.team_scores,
                'trick_count': room.game.trick_count
            })
            
            # Check if round complete
            if room.game.trick_count >= 8:
                final_scores = room.game.calculate_final_scores()
                broadcast_event(room_id, 'round_complete', {
                    'final_scores': final_scores,
                    'winner': 'Team A' if final_scores['team_a'] > final_scores['team_b'] else 'Team B'
                })
                room.game_state = GameState.FINISHED
        
        return jsonify({
            'success': True,
            'game_state': room.get_state()
        }), 200
        
    except Exception as e:
        logger.error(f"Error in play_card: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/poll', methods=['GET'])
def long_poll():
    """Long polling endpoint for real-time updates"""
    try:
        session_id = request.args.get('session_id')
        last_timestamp = float(request.args.get('last_timestamp', 0))
        
        if session_id not in player_sessions:
            return jsonify({'error': 'Invalid session'}), 401
        
        session = player_sessions[session_id]
        room_id = session['room_id']
        
        if room_id not in events_queue:
            return jsonify({'events': []}), 200
        
        # Wait for new events or timeout
        start_time = time.time()
        while time.time() - start_time < LONG_POLL_TIMEOUT:
            new_events = [
                e for e in events_queue[room_id]
                if e['timestamp'] > last_timestamp
            ]
            
            if new_events:
                return jsonify({
                    'events': new_events,
                    'last_timestamp': new_events[-1]['timestamp']
                }), 200
            
            time.sleep(0.5)  # Check every 500ms
        
        # Timeout - return empty
        return jsonify({'events': [], 'last_timestamp': last_timestamp}), 200
        
    except Exception as e:
        logger.error(f"Error in long_poll: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/reconnect', methods=['POST'])
def reconnect():
    """Reconnect to existing session"""
    try:
        data = request.json
        session_id = data.get('session_id')
        
        if session_id not in player_sessions:
            return jsonify({'error': 'Session not found'}), 404
        
        session = player_sessions[session_id]
        room_id = session['room_id']
        room = rooms.get(room_id)
        
        if not room:
            return jsonify({'error': 'Room no longer exists'}), 404
        
        # Mark player as connected
        player = session['player']
        player.is_connected = True
        
        # Get current game state
        response = {
            'room_state': room.get_state(),
            'seat': session['seat'],
            'players': room.get_players_info()
        }
        
        # Include hand if game is active
        if room.game and room.game_state == GameState.IN_PROGRESS:
            response['hand'] = room.game.hands.get(session['seat'], [])
            response['current_trick'] = room.game.current_trick
            response['current_player'] = room.game.current_player
            response['team_scores'] = room.game.team_scores
        
        broadcast_event(room_id, 'player_reconnected', {
            'player_name': player.name,
            'seat': session['seat']
        })
        
        return jsonify(response), 200
        
    except Exception as e:
        logger.error(f"Error in reconnect: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/room/<room_id>', methods=['GET'])
def get_room_state(room_id):
    """Get current room state"""
    try:
        room = rooms.get(room_id)
        if not room:
            return jsonify({'error': 'Room not found'}), 404
        
        return jsonify({
            'room_id': room_id,
            'state': room.get_state(),
            'players': room.get_players_info(),
            'player_count': sum(1 for p in room.players.values() if p)
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting room state: {e}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
