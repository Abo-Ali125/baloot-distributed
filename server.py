"""
Baloot Game Server
HTTP server with long-polling for real-time game updates
Production-ready for Render.com deployment
"""
import json
import uuid
import time
import logging
import os
from pathlib import Path

from flask import Flask, request, jsonify, send_from_directory, render_template_string
from flask_cors import CORS
from threading import Lock
from collections import deque
from datetime import datetime, timedelta

from game import Game
from models import Player, Room, GameState

# Initialize Flask app
app = Flask(__name__)
CORS(app)

# Configure logging for production
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s %(message)s'
)
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
PORT = int(os.environ.get('PORT', 10000))

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
    """Serve the main game client"""
    try:
        # Try to serve Client.html from current directory
        current_dir = Path(__file__).parent
        client_path = current_dir / 'Client.html'
        
        if client_path.exists():
            logger.info("Serving Client.html from file system")
            with open(client_path, 'r', encoding='utf-8') as f:
                html_content = f.read()
            return html_content, 200, {'Content-Type': 'text/html; charset=utf-8'}
        else:
            logger.warning("Client.html not found, serving embedded game interface")
            # Embedded game interface as fallback
            return render_template_string("""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Baloot Card Game</title>
    <style>
        body { 
            font-family: 'Segoe UI', -apple-system, sans-serif; 
            background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
            color: #e2e8f0; 
            margin: 0; 
            padding: 20px; 
            min-height: 100vh;
        }
        .container { 
            max-width: 1200px; 
            margin: 0 auto; 
        }
        .header {
            text-align: center;
            margin-bottom: 30px;
            padding: 30px;
            background: rgba(15, 23, 42, 0.8);
            border-radius: 15px;
            backdrop-filter: blur(10px);
            border: 1px solid rgba(148, 163, 184, 0.1);
        }
        .header h1 {
            font-size: 3rem;
            background: linear-gradient(135deg, #3b82f6, #8b5cf6);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 15px;
        }
        .panel {
            background: rgba(15, 23, 42, 0.95);
            border: 1px solid rgba(148, 163, 184, 0.2);
            border-radius: 12px;
            padding: 25px;
            margin-bottom: 20px;
            backdrop-filter: blur(10px);
        }
        .panel h3 {
            color: #3b82f6;
            margin-bottom: 15px;
            font-size: 1.3rem;
        }
        .form-group {
            margin-bottom: 20px;
        }
        .form-group label {
            display: block;
            margin-bottom: 8px;
            color: #cbd5e1;
            font-weight: 500;
        }
        .form-group input {
            width: 100%;
            padding: 12px;
            border: 1px solid rgba(148, 163, 184, 0.3);
            border-radius: 8px;
            background: rgba(30, 41, 59, 0.8);
            color: #e2e8f0;
            font-size: 1rem;
        }
        .btn {
            padding: 12px 24px;
            border: none;
            border-radius: 8px;
            font-size: 1rem;
            font-weight: 600;
            cursor: pointer;
            margin-right: 10px;
            margin-bottom: 10px;
            transition: all 0.3s ease;
        }
        .btn-primary {
            background: linear-gradient(135deg, #3b82f6, #2563eb);
            color: white;
        }
        .btn-success {
            background: linear-gradient(135deg, #10b981, #059669);
            color: white;
        }
        .btn:hover {
            transform: translateY(-2px);
        }
        .btn:disabled {
            opacity: 0.6;
            cursor: not-allowed;
            transform: none;
        }
        .status {
            padding: 12px 18px;
            border-radius: 8px;
            margin: 15px 0;
            font-weight: 500;
        }
        .status.connected {
            background: rgba(16, 185, 129, 0.2);
            color: #10b981;
            border: 1px solid rgba(16, 185, 129, 0.3);
        }
        .status.disconnected {
            background: rgba(239, 68, 68, 0.2);
            color: #ef4444;
            border: 1px solid rgba(239, 68, 68, 0.3);
        }
        .game-area {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
            margin-top: 20px;
        }
        .players, .events {
            background: rgba(30, 41, 59, 0.8);
            padding: 20px;
            border-radius: 12px;
            border: 1px solid rgba(148, 163, 184, 0.2);
        }
        .player-list {
            max-height: 300px;
            overflow-y: auto;
        }
        .events-log {
            max-height: 400px;
            overflow-y: auto;
            font-family: monospace;
            font-size: 0.9rem;
        }
        .event-item {
            padding: 8px 0;
            border-bottom: 1px solid rgba(148, 163, 184, 0.1);
        }
        .hand {
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
            margin-top: 20px;
        }
        .card {
            background: #f8fafc;
            color: #1e293b;
            padding: 12px 16px;
            border-radius: 8px;
            border: 2px solid #cbd5e1;
            cursor: pointer;
            transition: all 0.3s ease;
            font-weight: bold;
        }
        .card:hover {
            transform: translateY(-4px);
            box-shadow: 0 8px 20px rgba(0,0,0,0.3);
        }
        .card.hearts, .card.diamonds { color: #dc2626; }
        .card.clubs, .card.spades { color: #1f2937; }
        @media (max-width: 768px) {
            .game-area { grid-template-columns: 1fr; }
            .header h1 { font-size: 2rem; }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🎯 Baloot Card Game</h1>
            <p style="font-size: 1.2rem; color: #94a3b8;">Saudi Traditional Card Game - Live on Render!</p>
        </div>

        <div class="panel">
            <h3>🔗 Join Game</h3>
            <div id="status" class="status disconnected">Not Connected</div>
            
            <div class="form-group">
                <label for="roomId">Room ID</label>
                <input type="text" id="roomId" value="demo-room" placeholder="Enter room ID">
            </div>
            
            <div class="form-group">
                <label for="playerName">Your Name</label>
                <input type="text" id="playerName" value="Player" placeholder="Enter your name">
            </div>
            
            <button id="joinBtn" class="btn btn-primary">Join Room</button>
            <button id="readyBtn" class="btn btn-success" disabled>Ready to Play</button>
            <button id="refreshBtn" class="btn btn-primary">Refresh</button>
        </div>

        <div class="panel">
            <h3>🎮 Game Status</h3>
            <div id="gameInfo">
                <p><strong>Your Seat:</strong> <span id="seatInfo">-</span></p>
                <p><strong>Your Team:</strong> <span id="teamInfo">-</span></p>
                <p><strong>Current Turn:</strong> <span id="turnInfo">-</span></p>
            </div>
        </div>

        <div class="panel">
            <h3>🎴 Your Hand</h3>
            <div id="hand" class="hand">
                <p style="color: #94a3b8;">Cards will appear here when the game starts</p>
            </div>
        </div>

        <div class="game-area">
            <div class="players">
                <h3>👥 Players</h3>
                <div id="playersList" class="player-list">
                    <div>Waiting for players...</div>
                </div>
            </div>
            
            <div class="events">
                <h3>📝 Game Events</h3>
                <div id="eventsLog" class="events-log">
                    <div class="event-item">Welcome to Baloot! Join a room to start playing.</div>
                </div>
            </div>
        </div>
    </div>

    <script>
        class BalootClient {
            constructor() {
                this.sessionId = null;
                this.seat = null;
                this.polling = false;
                this.lastTimestamp = 0;
                this.init();
            }

            init() {
                document.getElementById('joinBtn').onclick = () => this.joinRoom();
                document.getElementById('readyBtn').onclick = () => this.sendReady();
                document.getElementById('refreshBtn').onclick = () => this.refreshState();
            }

            async apiCall(endpoint, method = 'GET', body = null) {
                const options = { method, headers: { 'Content-Type': 'application/json' } };
                if (body) options.body = JSON.stringify(body);

                try {
                    const response = await fetch(endpoint, options);
                    const data = await response.json();
                    return { ok: response.ok, data };
                } catch (error) {
                    this.log(`Network error: ${error.message}`);
                    return { ok: false, data: { error: error.message } };
                }
            }

            async joinRoom() {
                const roomId = document.getElementById('roomId').value.trim();
                const playerName = document.getElementById('playerName').value.trim();

                if (!roomId || !playerName) {
                    alert('Please enter both room ID and player name');
                    return;
                }

                const response = await this.apiCall('/api/join', 'POST', {
                    room_id: roomId,
                    player_name: playerName
                });

                if (response.ok) {
                    this.sessionId = response.data.session_id;
                    this.seat = response.data.seat;
                    
                    document.getElementById('status').className = 'status connected';
                    document.getElementById('status').textContent = 'Connected!';
                    document.getElementById('seatInfo').textContent = this.seat + 1;
                    document.getElementById('teamInfo').textContent = [0,2].includes(this.seat) ? 'A' : 'B';
                    document.getElementById('readyBtn').disabled = false;
                    
                    this.log(`Joined as ${playerName} in seat ${this.seat + 1}`);
                    this.startPolling();
                } else {
                    alert(`Failed to join: ${response.data.error}`);
                }
            }

            async sendReady() {
                if (!this.sessionId) return;
                const response = await this.apiCall('/api/ready', 'POST', { session_id: this.sessionId });
                if (response.ok) {
                    document.getElementById('readyBtn').disabled = true;
                    this.log('Marked as ready!');
                }
            }

            async refreshState() {
                this.log('Refreshing game state...');
                if (this.sessionId) {
                    const response = await this.apiCall('/api/reconnect', 'POST', { session_id: this.sessionId });
                    if (response.ok && response.data.hand) {
                        this.renderHand(response.data.hand);
                    }
                }
            }

            async startPolling() {
                if (this.polling) return;
                this.polling = true;

                while (this.polling && this.sessionId) {
                    try {
                        const url = `/api/poll?session_id=${this.sessionId}&last_timestamp=${this.lastTimestamp}`;
                        const response = await fetch(url);
                        const data = await response.json();
                        
                        if (data.events) {
                            data.events.forEach(event => this.handleEvent(event));
                            if (data.events.length > 0) {
                                this.lastTimestamp = data.last_timestamp;
                            }
                        }
                    } catch (error) {
                        this.log(`Polling error: ${error.message}`);
                        await new Promise(resolve => setTimeout(resolve, 2000));
                    }
                }
            }

            handleEvent(event) {
                switch (event.type) {
                    case 'player_joined':
                        this.log(`${event.data.player_name} joined seat ${event.data.seat + 1}`);
                        break;
                    case 'player_ready':
                        this.log(`${event.data.player_name} is ready (${event.data.ready_count}/4)`);
                        break;
                    case 'game_started':
                        this.log('Game started! Cards being dealt...');
                        break;
                    case 'cards_dealt':
                        if (event.data.seat === this.seat) {
                            this.renderHand(event.data.cards);
                            this.log(`You received ${event.data.cards.length} cards`);
                        }
                        break;
                    case 'card_played':
                        this.log(`Player ${event.data.seat + 1} played ${event.data.card}`);
                        break;
                    case 'trick_complete':
                        this.log(`Player ${event.data.winner + 1} wins trick! (+${event.data.points} points)`);
                        break;
                    case 'round_complete':
                        this.log(`GAME OVER! ${event.data.winner} wins the round!`);
                        this.log(`Final: Team A: ${event.data.final_scores.team_a}, Team B: ${event.data.final_scores.team_b}`);
                        break;
                }
            }

            renderHand(cards) {
                const handEl = document.getElementById('hand');
                handEl.innerHTML = '';

                cards.forEach(card => {
                    const cardEl = document.createElement('div');
                    cardEl.className = 'card ' + this.getCardClass(card);
                    cardEl.textContent = this.formatCard(card);
                    cardEl.onclick = () => this.playCard(card);
                    handEl.appendChild(cardEl);
                });
            }

            async playCard(card) {
                if (!this.sessionId) return;
                const confirmed = confirm(`Play ${this.formatCard(card)}?`);
                if (!confirmed) return;

                const response = await this.apiCall('/api/play_card', 'POST', {
                    session_id: this.sessionId,
                    card: card
                });

                if (!response.ok) {
                    alert(`Cannot play card: ${response.data.error}`);
                }
            }

            getCardClass(card) {
                const suit = card.slice(-1);
                return suit === 'H' || suit === 'D' ? 'hearts' : 'clubs';
            }

            formatCard(card) {
                const suit = card.slice(-1);
                const rank = card.slice(0, -1);
                const symbols = { 'H': '♥️', 'D': '♦️', 'C': '♣️', 'S': '♠️' };
                return rank + symbols[suit];
            }

            log(message) {
                const eventsLog = document.getElementById('eventsLog');
                const eventEl = document.createElement('div');
                eventEl.className = 'event-item';
                eventEl.textContent = `${new Date().toLocaleTimeString()} - ${message}`;
                eventsLog.insertBefore(eventEl, eventsLog.firstChild);
                
                // Keep only last 20 events
                while (eventsLog.children.length > 20) {
                    eventsLog.removeChild(eventsLog.lastChild);
                }
            }
        }

        // Initialize the game client
        const game = new BalootClient();
        game.log('🚀 Baloot client loaded! Ready to play.');
    </script>
</body>
</html>
            """)
    except Exception as e:
        logger.error(f"Error serving root: {e}")
        return jsonify({'status': 'healthy', 'message': 'Baloot Game Server', 'rooms': len(rooms)}), 200

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint for Render"""
    return jsonify({
        'status': 'healthy', 
        'rooms': len(rooms),
        'sessions': len(player_sessions),
        'timestamp': time.time()
    }), 200

@app.route('/api/status', methods=['GET'])
def server_status():
    """Get detailed server status"""
    return jsonify({
        'server': 'Baloot Game Server',
        'status': 'running',
        'rooms': len(rooms),
        'active_sessions': len(player_sessions),
        'endpoints': [
            'POST /api/join',
            'POST /api/ready', 
            'POST /api/play_card',
            'GET /api/poll',
            'POST /api/reconnect',
            'GET /api/room/<room_id>'
        ]
    }), 200

@app.route('/api/join', methods=['POST'])
def join_room():
    """Join a room and get assigned a seat"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'JSON body required'}), 400
            
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
        data = request.get_json()
        if not data:
            return jsonify({'error': 'JSON body required'}), 400
            
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
        data = request.get_json()
        if not data:
            return jsonify({'error': 'JSON body required'}), 400
            
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
        data = request.get_json()
        if not data:
            return jsonify({'error': 'JSON body required'}), 400
            
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
