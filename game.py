import random
from typing import Dict, List, Tuple

# Minimal playable logic to support UI events
SUITS = ['S','H','D','C']
RANKS = ['A','K','Q','J','10','9','8','7']
CARD_POINTS = {'A':11,'K':4,'Q':3,'J':2,'10':10,'9':0,'8':0,'7':0}

class Game:
    def __init__(self):
        self.dealer = 0
        self.current_player = 0
        self.hands: Dict[int, List[str]] = {0:[],1:[],2:[],3:[]}
        self.current_trick: List[Tuple[int,str]] = []  # list of (seat, card)
        self.trick_count = 0
        self.team_scores = {'team_a':0, 'team_b':0}
        self._deal()

    def _deal(self):
        deck = [r+s for s in SUITS for r in RANKS]
        random.shuffle(deck)
        for i in range(4):
            self.hands[i] = sorted(deck[i*8:(i+1)*8])
        self.current_player = (self.dealer + 1) % 4
        # Tell client hands are dealt by emitting events server-side. Here we just maintain state.

    def play_card(self, seat: int, card: str):
        hand = self.hands.get(seat, [])
        if card not in hand:
            return False, 'Card not in hand'
        # Simple follow-suit rule
        if self.current_trick:
            lead_suit = self.current_trick[0][1][-1]
            if any(c.endswith(lead_suit) for c in hand) and not card.endswith(lead_suit):
                return False, 'Must follow suit'
        hand.remove(card)
        self.current_trick.append((seat, card))
        if len(self.current_trick) < 4:
            # next player clockwise
            self.current_player = (self.current_player + 1) % 4
        return True, 'OK'

    def resolve_trick(self):
        lead_suit = self.current_trick[0][1][-1]
        playable = [(seat, card) for seat, card in self.current_trick if card.endswith(lead_suit)]
        # Highest rank wins per RANKS order
        rank_index = {r:i for i,r in enumerate(RANKS)}
        winner_seat, winner_card = max(playable, key=lambda sc: -rank_index[sc[1][:-1]])
        points = sum(CARD_POINTS[card[:-1]] for _, card in self.current_trick)
        self.trick_count += 1
        # assign points to team
        if winner_seat in (0,2):
            self.team_scores['team_a'] += points
        else:
            self.team_scores['team_b'] += points
        self.current_trick = []
        self.current_player = winner_seat
        return winner_seat, points

    def calculate_final_scores(self):
        # At end of round, whatever is in team_scores counts
        return dict(self.team_scores)
