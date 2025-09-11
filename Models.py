"""
Baloot Data Models
Player, Room, and Game State management
"""
from enum import Enum
from typing import Dict, Optional, List
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class GameState(Enum):
    """Game state enumeration"""
    WAITING = "waiting"
    READY = "ready"
    IN_PROGRESS = "in_progress"
    FINISHED = "finished"

class Player:
    """Player model"""
    def __init__(self, session_id: str, name: str):
        self.session_id = session_id
        self.name = name
        self.is_ready = False
        self.is_connected = True
        self.seat = None
        self.team = None  # 'A' or 'B'
        self.last_activity = datetime.now()
    
    def to_dict(self) -> Dict:
        """Convert player to dictionary"""
        return {
            'name': self.name,
            'is_ready': self.is_ready,
            'is_connected': self.is_connected,
            'seat': self.seat,
            'team': self.team
        }

class Room:
    """Room model for game sessions"""
    def __init__(self, room_id: str):
        self.room_id = room_id
        self.players = {0: None, 1: None, 2: None, 3: None}  # Seat -> Player
        self.game = None
        self.game_state = GameState.WAITING
        self.created_at = datetime.now()
        self.round_count = 0
        self.total_scores = {'team_a': 0, 'team_b': 0}
        
    def add_player(self, player: Player) -> Optional[int]:
        """
        Add player to room and assign seat
        Returns seat number or None if full
        """
        # Find first empty seat
        for seat in range(4):
            if self.players[seat] is None:
                self.players[seat] = player
                player.seat = seat
                # Assign team (0,2 = Team A, 1,3 = Team B)
                player.team = 'A' if seat in [0, 2] else 'B'
                logger.info(f"Player {player.name} joined room {self.room_id} at seat {seat}")
                return seat
        return None
    
    def remove_player(self, session_id: str) -> bool:
        """Remove player from room"""
        for seat, player in self.players.items():
            if player and player.session_id == session_id:
                self.players[seat] = None
                logger.info(f"Player removed from seat {seat} in room {self.room_id}")
                return True
        return False
    
    def is_full(self) -> bool:
        """Check if room is full"""
        return all(player is not None for player in self.players.values())
    
    def all_ready(self) -> bool:
        """Check if all players are ready"""
        if not self.is_full():
            return False
        return all(player.is_ready for player in self.players.values() if player)
    
    def start_game(self):
        """Start a new game"""
        if not self.all_ready():
            logger.warning("Cannot start game - not all players ready")
            return False
        
        from game import Game  # Import here to avoid circular dependency
        
        # Rotate dealer each round
        dealer = self.round_count % 4
        self.game = Game(dealer=dealer)
        self.game_state = GameState.IN_PROGRESS
        self.round_count += 1
        
        logger.info(f"Game started in room {self.room_id}, round {self.round_count}")
        return True
    
    def end_round(self):
        """End current round and update scores"""
        if not self.game:
            return
        
        # Get final scores for this round
        round_scores = self.game.calculate_final_scores()
        
        # Add to total scores
        self.total_scores['team_a'] += round_scores['team_a']
        self.total_scores['team_b'] += round_scores['team_b']
        
        # Check if game is won (152 points)
        if self.total_scores['team_a'] >= 152 or self.total_scores['team_b'] >= 152:
            self.game_state = GameState.FINISHED
            logger.info(f"Game finished in room {self.room_id}")
        else:
            # Reset for next round
            self.game_state = GameState.READY
            for player in self.players.values():
                if player:
                    player.is_ready = False
        
        self.game = None
    
    def get_players_info(self) -> Dict:
        """Get information about all players"""
        info = {}
        for seat, player in self.players.items():
            if player:
                info[seat] = player.to_dict()
            else:
                info[seat] = None
        return info
    
    def get_state(self) -> Dict:
        """Get current room state"""
        state = {
            'room_id': self.room_id,
            'game_state': self.game_state.value,
            'player_count': sum(1 for p in self.players.values() if p),
            'round_count': self.round_count,
            'total_scores': self.total_scores
        }
        
        if self.game:
            state['game'] = self.game.get_game_state()
        
        return state
    
    def handle_disconnect(self, session_id: str):
        """Handle player disconnect"""
        for seat, player in self.players.items():
            if player and player.session_id == session_id:
                player.is_connected = False
                player.last_activity = datetime.now()
                logger.info(f"Player {player.name} disconnected from room {self.room_id}")
                return True
        return False
    
    def handle_reconnect(self, session_id: str) -> Optional[int]:
        """Handle player reconnect"""
        for seat, player in self.players.items():
            if player and player.session_id == session_id:
                player.is_connected = True
                player.last_activity = datetime.now()
                logger.info(f"Player {player.name} reconnected to room {self.room_id}")
                return seat
        return None

class GameHistory:
    """Track game history and statistics"""
    def __init__(self):
        self.tricks = []  # List of all tricks played
        self.rounds = []  # List of round results
        
    def add_trick(self, trick_data: Dict):
        """Record a completed trick"""
        self.tricks.append({
            'timestamp': datetime.now(),
            'cards': trick_data.get('cards', []),
            'winner': trick_data.get('winner'),
            'points': trick_data.get('points', 0)
        })
    
    def add_round(self, round_data: Dict):
        """Record a completed round"""
        self.rounds.append({
            'timestamp': datetime.now(),
            'final_scores': round_data.get('final_scores', {}),
            'trick_count': round_data.get('trick_count', 0),
            'winner': round_data.get('winner')
        })
    
    def get_statistics(self) -> Dict:
        """Get game statistics"""
        return {
            'total_tricks': len(self.tricks),
            'total_rounds': len(self.rounds),
            'tricks_history': self.tricks[-10:],  # Last 10 tricks
            'rounds_history': self.rounds
        }
