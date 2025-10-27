import time
from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, Optional

class GameState(Enum):
    WAITING = 'WAITING'
    READY = 'READY'
    IN_PROGRESS = 'IN_PROGRESS'
    FINISHED = 'FINISHED'

@dataclass
class Player:
    session_id: str
    name: str
    is_ready: bool = False
    is_connected: bool = True
    user_id: Optional[int] = None
    last_activity: float = field(default_factory=time.time)

    def update_activity(self):
        self.last_activity = time.time()

    def is_disconnected(self, timeout: int = 60) -> bool:
        """Check if player hasn't been active for timeout seconds"""
        return time.time() - self.last_activity > timeout

@dataclass
class Room:
    room_id: str
    players: Dict[int, Optional[Player]] = field(default_factory=lambda: {0:None,1:None,2:None,3:None})
    game_state: GameState = GameState.WAITING
    game: Optional[object] = None
    total_scores: Dict[str,int] = field(default_factory=lambda: {'team_a':0,'team_b':0})
    round_count: int = 0

    def is_full(self) -> bool:
        return all(self.players.values())

    def add_player(self, player: Player) -> Optional[int]:
        for seat in range(4):
            if self.players[seat] is None:
                self.players[seat] = player
                return seat
        return None

    def remove_player(self, session_id: str) -> None:
        for seat, p in list(self.players.items()):
            if p and p.session_id == session_id:
                self.players[seat] = None

    def all_ready(self) -> bool:
        if not self.is_full():
            return False
        return all(p and p.is_ready for p in self.players.values())

    def start_game(self) -> bool:
        if not self.all_ready():
            return False
        from game import Game
        self.game = Game()
        self.game_state = GameState.IN_PROGRESS
        self.round_count += 1
        return True

    def get_players_info(self):
        info = {}
        for seat in range(4):
            p = self.players.get(seat)
            if p:
                info[seat] = {
                    'name': p.name,
                    'is_ready': p.is_ready,
                    'team': 'A' if seat in (0,2) else 'B',
                }
            else:
                info[seat] = None
        return info

    def get_state(self):
        return {
            'room_id': self.room_id,
            'players': self.get_players_info(),
            'game_state': self.game_state.value,
            'total_scores': self.total_scores,
            'round_count': self.round_count,
        }
