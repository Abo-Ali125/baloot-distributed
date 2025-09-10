from dataclasses import dataclass
from typing import List, Optional


SAN_ORDER = ['7','8','9','J','Q','K','10','A']
ABNAT = {'7':0,'8':0,'9':0,'J':2,'Q':3,'K':4,'10':10,'A':11}
SUITS = ['S','H','D','C']


@dataclass(frozen=True)
class Card:
suit: str
rank: str


@dataclass
class Play:
seat: int
card: Card


@dataclass
class Trick:
led_suit: Optional[str] = None
plays: List[Play] = None
winner_seat: Optional[int] = None

def __post_init__(self):
if self.plays is None:
self.plays = []

@dataclass
class PlayerSeat:
seat: int
player_id: Optional[str] = None
name: Optional[str] = None
connected: bool = True
hand: List[Card] = None

                                                                                                                                                                                                                                                                                                                                                                           #----------------H
def __post_init__(self):
if self.hand is None:
self.hand = []
