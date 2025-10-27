"""
Baloot Game Server
Simple HTTP server for multiplayer card game
"""
import uuid
import time
import logging
import os
import secrets
from pathlib import Path
from datetime import datetime, timedelta

from flask import Flask, request, jsonify, session
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.exceptions import HTTPException
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

# In-memory game state (rooms, sessions, events)
rooms = {}
rooms_lock = Lock()
player_sessions = {}
events_queue = {}
user_sessions = {}

# Game constants
MAX_PLAYERS_PER_ROOM = 4
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
    display_name = db.Column(db.String(100))
    avatar_url = db.Column(db.String(200))
    bio = db.Column(db.Text)
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

class Friendship(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    friend_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    status = db.Column(db.String(20), default='pending')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User', foreign_keys=[user_id], backref='friendships_sent')
    friend = db.relationship('User', foreign_keys=[friend_id], backref='friendships_received')

# Auth helpers
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth_token = request.headers.get('Authorization') or session.get('auth_token')
        if not auth_token or auth_token not in user_sessions:
            return jsonify({'error': 'Authentication required'}), 401
        user_sessions[auth_token]['last_activity'] = datetime.utcnow()
        request.current_user = user_sessions[auth_token]['user']
        return f(*args, **kwargs)
    return decorated_function

def create_session_token() -> str:
    return secrets.token_urlsafe(32)

# Room helpers
def get_or_create_room(room_id: str) -> Room:
    with rooms_lock:
        if room_id not in rooms:
            rooms[room_id] = Room(room_id)
            events_queue[room_id] = deque(maxlen=MAX_EVENTS_PER_ROOM)
            logger.info(f"Created new room: {room_id}")
        return rooms[room_id]

def broadcast_event(room_id: str, event_type: str, data: dict) -> None:
    if room_id in events_queue:
        event = {'type': event_type, 'data': data, 'timestamp': time.time()}
        events_queue[room_id].append(event)
        logger.info(f"Event: {event_type} in room {room_id}")

# Routes
@app.route('/')
def index():
    """Serve the main game client"""
    try:
        current_dir = Path(__file__).parent
        for candidate in ('Client.html', 'client.html', 'index.html'):
            client_path = current_dir / candidate
            if client_path.exists():
                return client_path.read_text(encoding='utf-8')
        return jsonify({'error': 'Client file not found'}), 404
    except Exception as e:
        logger.error(f"Error serving index: {e}")
        return jsonify({'error': 'Server error'}), 500

@app.route('/api/register', methods=['POST'])
def register():
    try:
        data = request.get_json(force=True)
        username = (data.get('username') or '').strip()
        email = (data.get('email') or '').strip()
        password = data.get('password') or ''
        if not username or len(username) < 3:
            return jsonify({'error': 'Username must be at least 3 characters'}), 400
        if not email or '@' not in email:
            return jsonify({'error': 'Valid email required'}), 400
        if not password or len(password) < 6:
            return jsonify({'error': 'Password must be at least 6 characters'}), 400
        if User.query.filter_by(username=username).first():
            return jsonify({'error': 'Username already taken'}), 400
        if User.query.filter_by(email=email).first():
            return jsonify({'error': 'Email already registered'}), 400
        user = User(
            username=username,
            email=email,
            password_hash=generate_password_hash(password),
            display_name=username,
            avatar_url=f"https://ui-avatars.com/api/?name={username}&background=random",
        )
        db.session.add(user)
        db.session.commit()
        auth_token = create_session_token()
        user_sessions[auth_token] = {'user': user, 'created_at': datetime.utcnow(), 'last_activity': datetime.utcnow()}
        session['auth_token'] = auth_token
        session.permanent = True
        return jsonify({'success': True, 'auth_token': auth_token, 'user': user.to_dict()}), 201
    except Exception as e:
        logger.error(f"Registration error: {e}")
        db.session.rollback()
        return jsonify({'error': 'Registration failed'}), 500

@app.route('/api/login', methods=['POST'])
def login():
    try:
        data = request.get_json(force=True)
        username_or_email = (data.get('username') or '').strip()
        password = data.get('password') or ''
        if not username_or_email or not password:
            return jsonify({'error': 'Username and password required'}), 400
        user = User.query.filter((User.username == username_or_email) | (User.email == username_or_email)).first()
        if not user or not check_password_hash(user.password_hash, password):
            return jsonify({'error': 'Invalid credentials'}), 401
        auth_token = create_session_token()
        user_sessions[auth_token] = {'user': user, 'created_at': datetime.utcnow(), 'last_activity': datetime.utcnow()}
        session['auth_token'] = auth_token
        session.permanent = True
        return jsonify({'success': True, 'auth_token': auth_token, 'user': user.to_dict()}), 200
    except Exception as e:
        logger.error(f"Login error: {e}")
        return jsonify({'error': 'Login failed'}), 500

@app.route('/api/logout', methods=['POST'])
@login_required
def logout():
    auth_token = request.headers.get('Authorization') or session.get('auth_token')
    if auth_token in user_sessions:
        del user_sessions[auth_token]
    session.clear()
    return jsonify({'success': True}), 200

@app.route('/api/profile', methods=['GET'])
@login_required
def get_profile():
    return jsonify(request.current_user.to_dict()), 200

@app.route('/api/profile', methods=['PUT'])
@login_required
def update_profile():
    try:
        data = request.get_json(force=True)
        user = request.current_user
        if 'display_name' in data:
            user.display_name = (data['display_name'] or '')[:100]
        if 'bio' in data:
            user.bio = (data['bio'] or '')[:500]
        if 'avatar_url' in data:
            user.avatar_url = (data['avatar_url'] or '')[:200]
        db.session.commit()
        return jsonify(user.to_dict()), 200
    except Exception as e:
        logger.error(f"Profile update error: {e}")
        db.session.rollback()
        return jsonify({'error': 'Update failed'}), 500

@app.route('/api/leaderboard', methods=['GET'])
def get_leaderboard():
    top_players = User.query.order_by(User.level.desc(), User.win_rate.desc(), User.total_points.desc()).limit(20).all()
    return jsonify([{
        'rank': i + 1,
        'username': p.username,
        'display_name': p.display_name or p.username,
        'level': p.level,
        'games_played': p.games_played,
        'games_won': p.games_won,
        'win_rate': p.win_rate,
        'total_points': p.total_points,
    } for i, p in enumerate(top_players)]), 200

@app.route('/api/friends', methods=['GET'])
@login_required
def get_friends():
    from sqlalchemy import or_, and_
    friendships = Friendship.query.filter(
        and_(
            or_(Friendship.user_id == request.current_user.id, Friendship.friend_id == request.current_user.id),
            Friendship.status == 'accepted',
        )
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
            'online': any(s['user'].id == friend.id for s in user_sessions.values()),
        })
    return jsonify(friends), 200

@app.route('/api/friends/add', methods=['POST'])
@login_required
def add_friend():
    try:
        data = request.get_json(force=True)
        friend_username = data.get('username')
        friend = User.query.filter_by(username=friend_username).first()
        if not friend:
            return jsonify({'error': 'User not found'}), 404
        if friend.id == request.current_user.id:
            return jsonify({'error': 'Cannot add yourself'}), 400
        from sqlalchemy import or_, and_
        existing = Friendship.query.filter(
            or_(
                and_(Friendship.user_id == request.current_user.id, Friendship.friend_id == friend.id),
                and_(Friendship.user_id == friend.id, Friendship.friend_id == request.current_user.id),
            )
        ).first()
        if existing:
            return jsonify({'error': 'Friend request already exists'}), 400
        friendship = Friendship(user_id=request.current_user.id, friend_id=friend.id, status='accepted')
        db.session.add(friendship)
        db.session.commit()
        return jsonify({'success': True}), 200
    except Exception as e:
        logger.error(f"Add friend error: {e}")
        db.session.rollback()
        return jsonify({'error': 'Failed to add friend'}), 500

@app.route('/api/reconnect', methods=['POST'])
@login_required
def reconnect():
    try:
        data = request.get_json(force=True)
        old_session_id = data.get('session_id')
        room_id = data.get('room_id')
        if not room_id or room_id not in rooms:
            return jsonify({'error': 'Room not found'}), 404
        room = rooms[room_id]
        seat = None
        if old_session_id and old_session_id in player_sessions:
            seat = player_sessions[old_session_id]['seat']
        else:
            for s, player in room.players.items():
                if player and player.user_id == request.current_user.id:
                    seat = s
                    break
        if seat is None:
            return jsonify({'error': 'No seat found in this room'}), 404
        new_session_id = str(uuid.uuid4())
        player = room.players[seat]
        player.is_connected = True
        player.session_id = new_session_id
        if old_session_id in player_sessions:
            del player_sessions[old_session_id]
        player_sessions[new_session_id] = {
            'player': player,
            'room_id': room_id,
            'seat': seat,
            'user_id': request.current_user.id
        }
        game_state = {
            'session_id': new_session_id,
            'seat': seat,
            'room_state': room.get_state(),
            'players': room.get_players_info(),
        }
        if room.game:
            game_state.update({
                'hand': room.game.hands[seat],
                'current_trick': [{'seat': s, 'card': c} for s, c in room.game.current_trick],
                'current_player': room.game.current_player,
                'trick_count': room.game.trick_count,
                'team_scores': room.game.team_scores,
            })
        broadcast_event(room_id, 'player_reconnected', {'player_name': player.name, 'seat': seat})
        return jsonify(game_state), 200
    except Exception as e:
        logger.error(f"Reconnect error: {e}")
        return jsonify({'error': 'Reconnection failed'}), 500

@app.route('/api/leave', methods=['POST'])
@login_required
def leave_room():
    try:
        data = request.get_json(force=True)
        session_id = data.get('session_id')
        if not session_id or session_id not in player_sessions:
            return jsonify({'error': 'Invalid session'}), 400
        session_data = player_sessions[session_id]
        room_id = session_data['room_id']
        seat = session_data['seat']
        room = rooms.get(room_id)
        if not room:
            return jsonify({'error': 'Room not found'}), 404
        player_name = session_data['player'].name
        room.remove_player(session_id)
        del player_sessions[session_id]
        broadcast_event(room_id, 'player_left', {
            'player_name': player_name,
            'seat': seat,
            'players': room.get_players_info()
        })
        if all(p is None for p in room.players.values()):
            del rooms[room_id]
            if room_id in events_queue:
                del events_queue[room_id]
            logger.info(f"Removed empty room: {room_id}")
        return jsonify({'success': True}), 200
    except Exception as e:
        logger.error(f"Leave room error: {e}")
        return jsonify({'error': 'Failed to leave room'}), 500

@app.route('/api/rooms', methods=['GET'])
def get_active_rooms():
    active_rooms = []
    for room_id, room in rooms.items():
        active_rooms.append({
            'room_id': room_id,
            'player_count': sum(1 for p in room.players.values() if p),
            'game_state': room.game_state.value,
            'total_scores': room.total_scores,
        })
    return jsonify(active_rooms), 200

@app.route('/api/join', methods=['POST'])
@login_required
def join_room():
    try:
        data = request.get_json(force=True)
        room_id = data.get('room_id')
        if not room_id:
            return jsonify({'error': 'Room ID required'}), 400
        room = get_or_create_room(room_id)
        if room.is_full():
            return jsonify({'error': 'Room is full'}), 400
        session_id = str(uuid.uuid4())
        player = Player(session_id, request.current_user.display_name or request.current_user.username)
        player.user_id = request.current_user.id
        seat = room.add_player(player)
        if seat is None:
            return jsonify({'error': 'Could not join room'}), 400
        player_sessions[session_id] = {'player': player, 'room_id': room_id, 'seat': seat,
        'user_id': request.current_user.id}
        broadcast_event(room_id, 'player_joined', {'player_name': player.name, 'seat': seat, 'players': room.get_players_info()})
        return jsonify({'session_id': session_id, 'seat': seat, 'room_state': room.get_state(), 'players': room.get_players_info()}), 200
    except Exception as e:
        logger.error(f"Join room error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/ready', methods=['POST'])
@login_required
def player_ready():
    try:
        data = request.get_json(force=True)
        session_id = data.get('session_id')
        if not session_id or session_id not in player_sessions:
            return jsonify({'error': 'Invalid session'}), 400
        session_data = player_sessions[session_id]
        room_id = session_data['room_id']
        seat = session_data['seat']
        room = rooms.get(room_id)
        if not room:
            return jsonify({'error': 'Room not found'}), 404
        player = session_data['player']
        player.is_ready = True
        broadcast_event(room_id, 'player_ready', {'seat': seat, 'player_name': player.name, 'ready': True, 'players': room.get_players_info()})
        if room.all_ready():
            if room.start_game():
                broadcast_event(room_id, 'game_started', {
                    'dealer': room.game.dealer,
                    'round_number': room.round_count,
                })
                for s in range(4):
                    if room.players[s]:
                        broadcast_event(room_id,'cards_dealt',{
                            'seat':s,
                            'cards':room.game.hands[s]
                        })
        return jsonify({'success': True}), 200
    except Exception as e:
        logger.error(f"Ready error: {e}")
        return jsonify({'error': 'Failed to set ready status'}), 500

@app.route('/api/chat', methods=['POST'])
@login_required
def send_chat_message():
    try:
        data = request.get_json(force=True)
        session_id = data.get('session_id')
        message = (data.get('message') or '').strip()
        if not message:
            return jsonify({'error': 'Message required'}), 400
        if not session_id or session_id not in player_sessions:
            return jsonify({'error': 'Invalid session'}), 400
        session_data = player_sessions[session_id]
        room_id = session_data['room_id']
        player_name = session_data['player'].name
        broadcast_event(room_id, 'chat_message', {
            'author': player_name,
            'message': message,
            'timestamp': time.time()
        })
        return jsonify({'success': True}), 200
    except Exception as e:
        logger.error(f"Chat error: {e}")
        return jsonify({'error': 'Failed to send message'}), 500

@app.route('/api/poll', methods=['GET'])
@login_required
def poll_events():
    try:
        room_id = request.args.get('room_id')
        since_str = request.args.get('since')
        if not room_id:
            session_id = request.args.get('session_id')
            if session_id and session_id in player_sessions:
                room_id = player_sessions[session_id]['room_id']
        if since_str is None:
            since_str = request.args.get('last_timestamp', '0')
        try:
            since = float(since_str or 0)
        except ValueError:
            since = 0.0
        if not room_id or room_id not in events_queue:
            return jsonify({'events': [], 'latest': since, 'last_timestamp': since}), 200
        events = [e for e in list(events_queue[room_id]) if e['timestamp'] > since]
        latest_ts = events[-1]['timestamp'] if events else since
        return jsonify({'events': events, 'latest': latest_ts, 'last_timestamp': latest_ts}), 200
    except Exception as e:
        logger.error(f"Poll error: {e}")
        return jsonify({'error': 'Failed to poll events'}), 500

@app.route('/api/play_card', methods=['POST'])
@login_required
def play_card_enhanced():
    try:
        data = request.get_json(force=True)
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
            curr_player = room.players[room.game.current_player]
            current_player_name = curr_player.name if curr_player else f"Player {room.game.current_player + 1}"
            return jsonify({'error': f'Not your turn. Waiting for {current_player_name}'}), 400
        success, message = room.game.play_card(seat, card)
        if not success:
            return jsonify({'error': message}), 400
        player_name = session_data['player'].name
        broadcast_event(room_id, 'card_played', {
            'seat': seat,
            'player_name': player_name,
            'card': card,
            'current_trick': [{
                'seat': s,
                'card': c,
                'player': room.players[s].name if room.players[s] else f"Player {s+1}",
            } for s, c in room.game.current_trick],
            'next_player': room.game.current_player,
            'next_player_name': room.players[room.game.current_player].name if room.players[room.game.current_player] else None,
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
                    'next_leader_name': winner_name,
                })
                cards_remaining = sum(len(hand) for hand in room.game.hands.values())
                if cards_remaining == 0:
                    handle_round_end(room, room_id)
                else:
                    broadcast_event(room_id, 'next_trick_ready', {
                        'leader': winner_seat,
                        'leader_name': winner_name,
                        'trick_number': room.game.trick_count + 1,
                    })
            except Exception as e:
                logger.error(f"Error resolving trick: {e}")
                return jsonify({'error': 'Failed to resolve trick'}), 500
        return jsonify({'success': True, 'message': f'Played {card}', 'cards_in_hand': len(room.game.hands[seat]), 'current_player': room.game.current_player}), 200
    except Exception as e:
        logger.error(f"Error in play_card: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/health')
def health():
    return jsonify({'status': 'healthy', 'timestamp': time.time()}), 200

def handle_round_end(room: Room, room_id: str) -> None:
    final_scores = room.game.calculate_final_scores()
    if final_scores['team_a'] > final_scores['team_b']:
        round_winner = 'Team A'
        winning_score = final_scores['team_a']
    elif final_scores['team_b'] > final_scores['team_a']:
        round_winner = 'Team B'
        winning_score = final_scores['team_b']
    else:
        round_winner = 'Tie'
        winning_score = final_scores['team_a']
    room.total_scores['team_a'] += final_scores['team_a']
    room.total_scores['team_b'] += final_scores['team_b']
    broadcast_event(room_id, 'round_complete', {
        'round_winner': round_winner,
        'winning_score': winning_score,
        'final_scores': final_scores,
        'total_scores': room.total_scores,
        'round_number': room.round_count,
    })
    if room.total_scores['team_a'] >= 152 or room.total_scores['team_b'] >= 152:
        game_winner = 'Team A' if room.total_scores['team_a'] >= 152 else 'Team B'
        broadcast_event(room_id, 'game_complete', {
            'game_winner': game_winner, 
            'final_total_scores': room.total_scores
        })
        room.game_state = GameState.FINISHED
        update_player_stats(room, game_winner)
    else:
        start_new_round(room, room_id)

def update_player_stats(room: Room, game_winner: str) -> None:
    """Update player statistics in database after game completes"""
    try:
        winning_team_seats = [0, 2] if game_winner == 'Team A' else [1, 3]
        for seat, player in room.players.items():
            if player and player.user_id:
                user = User.query.get(player.user_id)
                if user:
                    user.games_played += 1
                    if seat in winning_team_seats:
                        user.games_won += 1
                    user.win_rate = (user.games_won / user.games_played * 100) if user.games_played > 0 else 0
                    xp_gained = 100 if seat in winning_team_seats else 50
                    user.experience += xp_gained
                    new_level = (user.experience // 500) + 1
                    if new_level > user.level:
                        user.level = new_level
                    team_key = 'team_a' if seat in [0, 2] else 'team_b'
                    user.total_points += room.total_scores[team_key]
        db.session.commit()
        logger.info(f"Updated stats for game in room {room.room_id}")
    except Exception as e:
        logger.error(f"Error updating player stats: {e}")
        db.session.rollback()

def start_new_round(room: Room, room_id: str) -> None:
    """Prepare for next round - reset ready status and game"""
    for p in room.players.values():
        if p:
            p.is_ready = False
    room.game_state = GameState.READY
    room.game = None
    broadcast_event(room_id, 'new_round_ready', {
        'round_number': room.round_count + 1,
        'total_scores': room.total_scores,
        'message': f'Round {room.round_count} complete! Ready up for Round {room.round_count + 1}!'
    })

@app.errorhandler(404)
def _json_404(e):
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Not found', 'path': request.path}), 404
    return e

@app.errorhandler(405)
def _json_405(e):
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Method not allowed', 'path': request.path}), 405
    return e

@app.errorhandler(Exception)
def _json_500(e):
    if request.path.startswith('/api/'):
        code = 500
        if isinstance(e, HTTPException):
            code = e.code or 500
        return jsonify({'error': 'Server error', 'detail': str(e)}), code
    raise e

with app.app_context():
    db.create_all()
    logger.info("Database initialized")

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=PORT, debug=False)
