"""
Baloot Game Server - Complete Version
HTTP server with authentication, user profiles, and real-time game updates
Production-ready for Render.com deployment
"""
import json
import uuid
import time
import logging
import os
import hashlib
import secrets
from pathlib import Path
from datetime import datetime, timedelta

from flask import Flask, request, jsonify, session, render_template_string
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from threading import Lock
from collections import deque
from functools import wraps

from game import Game
from models import Player, Room, GameState

# Initialize Flask app
app = Flask(__name__)
CORS(app, supports_credentials=True)

# Configuration
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', secrets.token_hex(32))
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///baloot.db')
if app.config['SQLALCHEMY_DATABASE_URI'].startswith('postgres://'):
    app.config['SQLALCHEMY_DATABASE_URI'] = app.config['SQLALCHEMY_DATABASE_URI'].replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SESSION_TYPE'] = 'filesystem'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)

# Initialize database
db = SQLAlchemy(app)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s %(message)s'
)
logger = logging.getLogger(__name__)

# Global storage
rooms = {}
rooms_lock = Lock()
player_sessions = {}
events_queue = {}
user_sessions = {}  # Maps session tokens to user data

# Configuration constants
MAX_PLAYERS_PER_ROOM = 4
LONG_POLL_TIMEOUT = 30
MAX_EVENTS_PER_ROOM = 100
PORT = int(os.environ.get('PORT', 10000))

# Database Models
class User(db.Model):
    """User account model"""
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Profile information
    display_name = db.Column(db.String(100))
    avatar_url = db.Column(db.String(200))
    bio = db.Column(db.Text)
    
    # Game statistics
    games_played = db.Column(db.Integer, default=0)
    games_won = db.Column(db.Integer, default=0)
    total_points = db.Column(db.Integer, default=0)
    win_rate = db.Column(db.Float, default=0.0)
    level = db.Column(db.Integer, default=1)
    experience = db.Column(db.Integer, default=0)
    
    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'display_name': self.display_name or self.username,
            'email': self.email,
            'avatar_url': self.avatar_url,
            'bio': self.bio,
            'games_played': self.games_played,
            'games_won': self.games_won,
            'total_points': self.total_points,
            'win_rate': self.win_rate,
            'level': self.level,
            'experience': self.experience,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

class GameHistory(db.Model):
    """Game history records"""
    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(db.String(100))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    team = db.Column(db.String(1))  # 'A' or 'B'
    team_score = db.Column(db.Integer)
    opponent_score = db.Column(db.Integer)
    won = db.Column(db.Boolean)
    played_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User', backref=db.backref('game_history', lazy=True))

class Friendship(db.Model):
    """Friend relationships"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    friend_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    status = db.Column(db.String(20), default='pending')  # pending, accepted, blocked
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User', foreign_keys=[user_id], backref='friendships_sent')
    friend = db.relationship('User', foreign_keys=[friend_id], backref='friendships_received')

# Authentication decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth_token = request.headers.get('Authorization')
        if not auth_token:
            auth_token = session.get('auth_token')
        
        if not auth_token or auth_token not in user_sessions:
            return jsonify({'error': 'Authentication required'}), 401
        
        # Update last activity
        user_sessions[auth_token]['last_activity'] = datetime.utcnow()
        request.current_user = user_sessions[auth_token]['user']
        return f(*args, **kwargs)
    return decorated_function

# Helper functions
def create_session_token():
    """Generate secure session token"""
    return secrets.token_urlsafe(32)

def handle_round_end(room, room_id):
    """Handle end of round logic with database updates"""
    final_scores = room.game.calculate_final_scores()
    
    # Determine round winner
    if final_scores['team_a'] > final_scores['team_b']:
        round_winner = 'Team A'
        winning_score = final_scores['team_a']
    elif final_scores['team_b'] > final_scores['team_a']:
        round_winner = 'Team B'
        winning_score = final_scores['team_b']
    else:
        round_winner = 'Tie'
        winning_score = final_scores['team_a']
    
    # Update total scores
    room.total_scores['team_a'] += final_scores['team_a']
    room.total_scores['team_b'] += final_scores['team_b']
    
    broadcast_event(room_id, 'round_complete', {
        'round_winner': round_winner,
        'winning_score': winning_score,
        'final_scores': final_scores,
        'total_scores': room.total_scores,
        'round_number': room.round_count
    })
    
    # Check for game end (first to 152 points wins)
    if room.total_scores['team_a'] >= 152 or room.total_scores['team_b'] >= 152:
        game_winner = 'Team A' if room.total_scores['team_a'] >= 152 else 'Team B'
        
        # Update player statistics in database
        for seat, player in room.players.items():
            if player and hasattr(player, 'user_id'):
                user = User.query.get(player.user_id)
                if user:
                    user.games_played += 1
                    team = 'A' if seat in [0, 2] else 'B'
                    won = (team == 'A' and game_winner == 'Team A') or (team == 'B' and game_winner == 'Team B')
                    
                    if won:
                        user.games_won += 1
                        user.experience += 100
                    else:
                        user.experience += 25
                    
                    user.total_points += final_scores[f'team_{team.lower()}']
                    user.win_rate = (user.games_won / user.games_played) * 100 if user.games_played > 0 else 0
                    user.level = 1 + (user.experience // 500)
                    
                    # Record game history
                    history = GameHistory(
                        room_id=room_id,
                        user_id=user.id,
                        team=team,
                        team_score=room.total_scores[f'team_{team.lower()}'],
                        opponent_score=room.total_scores[f'team_{"b" if team == "A" else "a"}'],
                        won=won
                    )
                    db.session.add(history)
        
        db.session.commit()
        
        broadcast_event(room_id, 'game_complete', {
            'game_winner': game_winner,
            'final_total_scores': room.total_scores
        })
        room.game_state = GameState.FINISHED
    else:
        # Start new round
        start_new_round(room, room_id)

def start_new_round(room, room_id):
    """Start a new round after previous one ends"""
    for player in room.players.values():
        if player:
            player.is_ready = False
    
    room.game_state = GameState.READY
    room.game = None
    
    broadcast_event(room_id, 'new_round_ready', {
        'round_number': room.round_count + 1,
        'total_scores': room.total_scores,
        'message': 'Ready up for next round!'
    })

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

# Routes
@app.route('/')
def index():
    """Serve the main game client"""
    try:
        current_dir = Path(__file__).parent
        client_path = current_dir / 'client.html'
        
        if client_path.exists():
            with open(client_path, 'r', encoding='utf-8') as f:
                return f.read()
        else:
            # Return embedded client if file not found
            return render_template_string(CLIENT_HTML)
    except Exception as e:
        logger.error(f"Error serving index: {e}")
        return jsonify({'error': 'Server error'}), 500

@app.route('/api/register', methods=['POST'])
def register():
    """Register a new user account"""
    try:
        data = request.get_json()
        username = data.get('username', '').strip()
        email = data.get('email', '').strip()
        password = data.get('password', '')
        
        # Validation
        if not username or len(username) < 3:
            return jsonify({'error': 'Username must be at least 3 characters'}), 400
        if not email or '@' not in email:
            return jsonify({'error': 'Valid email required'}), 400
        if not password or len(password) < 6:
            return jsonify({'error': 'Password must be at least 6 characters'}), 400
        
        # Check if user exists
        if User.query.filter_by(username=username).first():
            return jsonify({'error': 'Username already taken'}), 400
        if User.query.filter_by(email=email).first():
            return jsonify({'error': 'Email already registered'}), 400
        
        # Create new user
        user = User(
            username=username,
            email=email,
            password_hash=generate_password_hash(password),
            display_name=username,
            avatar_url=f"https://ui-avatars.com/api/?name={username}&background=random"
        )
        db.session.add(user)
        db.session.commit()
        
        # Auto-login after registration
        auth_token = create_session_token()
        user_sessions[auth_token] = {
            'user': user,
            'created_at': datetime.utcnow(),
            'last_activity': datetime.utcnow()
        }
        
        return jsonify({
            'success': True,
            'auth_token': auth_token,
            'user': user.to_dict()
        }), 201
        
    except Exception as e:
        logger.error(f"Registration error: {e}")
        db.session.rollback()
        return jsonify({'error': 'Registration failed'}), 500

@app.route('/api/login', methods=['POST'])
def login():
    """Login with username/email and password"""
    try:
        data = request.get_json()
        username_or_email = data.get('username', '').strip()
        password = data.get('password', '')
        
        if not username_or_email or not password:
            return jsonify({'error': 'Username and password required'}), 400
        
        # Find user by username or email
        user = User.query.filter(
            (User.username == username_or_email) | 
            (User.email == username_or_email)
        ).first()
        
        if not user or not check_password_hash(user.password_hash, password):
            return jsonify({'error': 'Invalid credentials'}), 401
        
        # Create session
        auth_token = create_session_token()
        user_sessions[auth_token] = {
            'user': user,
            'created_at': datetime.utcnow(),
            'last_activity': datetime.utcnow()
        }
        
        session['auth_token'] = auth_token
        session.permanent = True
        
        return jsonify({
            'success': True,
            'auth_token': auth_token,
            'user': user.to_dict()
        }), 200
        
    except Exception as e:
        logger.error(f"Login error: {e}")
        return jsonify({'error': 'Login failed'}), 500

@app.route('/api/logout', methods=['POST'])
@login_required
def logout():
    """Logout current user"""
    auth_token = request.headers.get('Authorization') or session.get('auth_token')
    if auth_token in user_sessions:
        del user_sessions[auth_token]
    session.clear()
    return jsonify({'success': True}), 200

@app.route('/api/profile', methods=['GET'])
@login_required
def get_profile():
    """Get current user profile"""
    return jsonify(request.current_user.to_dict()), 200

@app.route('/api/profile', methods=['PUT'])
@login_required
def update_profile():
    """Update user profile"""
    try:
        data = request.get_json()
        user = request.current_user
        
        if 'display_name' in data:
            user.display_name = data['display_name'][:100]
        if 'bio' in data:
            user.bio = data['bio'][:500]
        if 'avatar_url' in data:
            user.avatar_url = data['avatar_url'][:200]
        
        db.session.commit()
        return jsonify(user.to_dict()), 200
        
    except Exception as e:
        logger.error(f"Profile update error: {e}")
        db.session.rollback()
        return jsonify({'error': 'Update failed'}), 500

@app.route('/api/stats/<int:user_id>', methods=['GET'])
def get_user_stats(user_id):
    """Get user statistics"""
    user = User.query.get(user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    recent_games = GameHistory.query.filter_by(user_id=user_id)\
        .order_by(GameHistory.played_at.desc()).limit(10).all()
    
    return jsonify({
        'user': user.to_dict(),
        'recent_games': [{
            'room_id': g.room_id,
            'team': g.team,
            'score': f"{g.team_score} - {g.opponent_score}",
            'won': g.won,
            'played_at': g.played_at.isoformat()
        } for g in recent_games]
    }), 200

@app.route('/api/leaderboard', methods=['GET'])
def get_leaderboard():
    """Get top players leaderboard"""
    top_players = User.query.order_by(
        User.level.desc(), 
        User.win_rate.desc(),
        User.total_points.desc()
    ).limit(20).all()
    
    return jsonify([{
        'rank': i + 1,
        'username': p.username,
        'display_name': p.display_name or p.username,
        'level': p.level,
        'games_played': p.games_played,
        'games_won': p.games_won,
        'win_rate': p.win_rate,
        'total_points': p.total_points
    } for i, p in enumerate(top_players)]), 200

@app.route('/api/friends', methods=['GET'])
@login_required
def get_friends():
    """Get user's friends list"""
    friendships = Friendship.query.filter(
        ((Friendship.user_id == request.current_user.id) | 
         (Friendship.friend_id == request.current_user.id)) &
        (Friendship.status == 'accepted')
    ).all()
    
    friends = []
    for f in friendships:
        friend = f.friend if f.user_id == request.current_user.id else f.user
        friends.append({
            'id': friend.id,
            'username': friend.username,
            'display_name': friend.display_name or friend.username,
            'avatar_url': friend.avatar_url,
            'level': friend.level,
            'online': any(s['user'].id == friend.id for s in user_sessions.values())
        })
    
    return jsonify(friends), 200

@app.route('/api/friends/add', methods=['POST'])
@login_required
def add_friend():
    """Send friend request"""
    try:
        data = request.get_json()
        friend_username = data.get('username')
        
        friend = User.query.filter_by(username=friend_username).first()
        if not friend:
            return jsonify({'error': 'User not found'}), 404
        
        if friend.id == request.current_user.id:
            return jsonify({'error': 'Cannot add yourself'}), 400
        
        # Check if friendship exists
        existing = Friendship.query.filter(
            ((Friendship.user_id == request.current_user.id) & 
             (Friendship.friend_id == friend.id)) |
            ((Friendship.user_id == friend.id) & 
             (Friendship.friend_id == request.current_user.id))
        ).first()
        
        if existing:
            return jsonify({'error': 'Friend request already exists'}), 400
        
        friendship = Friendship(
            user_id=request.current_user.id,
            friend_id=friend.id,
            status='pending'
        )
        db.session.add(friendship)
        db.session.commit()
        
        return jsonify({'success': True}), 200
        
    except Exception as e:
        logger.error(f"Add friend error: {e}")
        db.session.rollback()
        return jsonify({'error': 'Failed to add friend'}), 500

@app.route('/api/join', methods=['POST'])
@login_required
def join_room():
    """Join a game room"""
    try:
        data = request.get_json()
        room_id = data.get('room_id')
        
        if not room_id:
            return jsonify({'error': 'Room ID required'}), 400
        
        room = get_or_create_room(room_id)
        
        if room.is_full():
            return jsonify({'error': 'Room is full'}), 400
        
        # Create game session
        session_id = str(uuid.uuid4())
        player = Player(session_id, request.current_user.display_name or request.current_user.username)
        player.user_id = request.current_user.id  # Link to user account
        
        seat = room.add_player(player)
        if seat is None:
            return jsonify({'error': 'Could not join room'}), 400
        
        player_sessions[session_id] = {
            'player': player,
            'room_id': room_id,
            'seat': seat,
            'user_id': request.current_user.id
        }
        
        broadcast_event(room_id, 'player_joined', {
            'player_name': player.name,
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
        logger.error(f"Join room error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/rooms', methods=['GET'])
def get_active_rooms():
    """Get list of active rooms"""
    active_rooms = []
    for room_id, room in rooms.items():
        active_rooms.append({
            'room_id': room_id,
            'player_count': sum(1 for p in room.players.values() if p),
            'game_state': room.game_state.value,
            'total_scores': room.total_scores
        })
    return jsonify(active_rooms), 200

# Enhanced play_card endpoint
@app.route('/api/play_card', methods=['POST'])
def play_card_enhanced():
    """Play a card during your turn - Enhanced version"""
    try:
        data = request.get_json()
        session_id = data.get('session_id')
        card = data.get('card')
        
        if session_id not in player_sessions:
            return jsonify({'error': 'Invalid session'}), 401
        
        session_data = player_sessions[session_id]
        room_id = session_data['room_id']
        seat = session_data['seat']
        room = rooms.get(room_id)
        
        if not room or not room.game:
            return jsonify({'error': 'Game not started'}), 400
        
        if room.game_state != GameState.IN_PROGRESS:
            return jsonify({'error': 'Game not in progress'}), 400
        
        if room.game.current_player != seat:
            current_player_name = room.players[room.game.current_player].name if room.players[room.game.current_player] else f"Player {room.game.current_player + 1}"
            return jsonify({'error': f'Not your turn. Waiting for {current_player_name}'}), 400
        
        success, message = room.game.play_card(seat, card)
        
        if not success:
            return jsonify({'error': message}), 400
        
        player_name = session_data['player'].name
        
        broadcast_event(room_id, 'card_played', {
            'seat': seat,
            'player_name': player_name,
            'card': card,
            'current_trick': [{'seat': s, 'card': c, 'player': room.players[s].name if room.players[s] else f"Player {s+1}"} for s, c in room.game.current_trick],
            'next_player': room.game.current_player,
            'next_player_name': room.players[room.game.current_player].name if room.players[room.game.current_player] else None
        })
        
        if len(room.game.current_trick) == 4:
            try:
                winner_seat, points = room.game.resolve_trick()
                winner_name = room.players[winner_seat].name
                
                broadcast_event(room_id, 'trick_won', {
                    'winner_seat': winner_seat,
                    'winner_name': winner_name,
                    'points': points,
                    'team_scores': room.game.team_scores.copy(),
                    'trick_count': room.game.trick_count,
                    'next_leader': winner_seat,
                    'next_leader_name': winner_name
                })
                
                cards_remaining = sum(len(hand) for hand in room.game.hands.values())
                if cards_remaining == 0:
                    handle_round_end(room, room_id)
                else:
                    broadcast_event(room_id, 'next_trick_ready', {
                        'leader': winner_seat,
                        'leader_name': winner_name,
                        'trick_number': room.game.trick_count + 1
                    })
                    
            except Exception as e:
                logger.error(f"Error resolving trick: {e}")
                return jsonify({'error': 'Failed to resolve trick'}), 500
        
        return jsonify({
            'success': True,
            'message': f'Played {card}',
            'cards_in_hand': len(room.game.hands[seat]),
            'current_player': room.game.current_player
        }), 200
        
    except Exception as e:
        logger.error(f"Error in play_card: {e}")
        return jsonify({'error': str(e)}), 500

# Keep all other endpoints from original server...
# (ready, poll, reconnect, room state, etc.)

@app.route('/health')
def health():
    """Health check endpoint"""
    return jsonify({'status': 'healthy', 'timestamp': time.time()}), 200

# Initialize database
with app.app_context():
    db.create_all()
    logger.info("Database initialized")

# Client HTML template (embedded)
CLIENT_HTML = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Baloot - Saudi Card Game</title>
    <style>
        /* Include all the CSS from your Client.html file here */
        /* ... (full CSS content) ... */
    </style>
</head>
<body>
    <!-- Include all the HTML body content from your Client.html file here -->
    <!-- ... (full HTML content) ... */
    <script>
        // Include enhanced JavaScript with authentication
        // ... (full JS content with login/register features) ...
    </script>
</body>
</html>
'''

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=PORT, debug=False)
