import random
from typing import Dict, List, Tuple, Optional

# Simple Baloot-like game engine (lightweight)
# - 32-card deck: ranks 7,8,9,10,J,Q,K,A and suits H,D,S,C
# - 8 cards per player (4 players)
# - Trick resolution: follow lead suit, highest rank wins (no trump mechanic implemented)
# - Basic point values for scoring (10/A high value), accumulates team scores

RANKS = ['7', '8', '9', '10', 'J', 'Q', 'K', 'A']
SUITS = ['H', 'D', 'S', 'C']

# Points mapping (simple approximation)
POINTS = {
    '7': 0,
    '8': 0,
    '9': 0,
    '10': 10,
    'J': 2,
    'Q': 3,
    'K': 4,
    'A': 11
}

class Game:
    def __init__(self, dealer: int = 0):
        """
        dealer: seat index (0-3)
        The first player to play the trick is (dealer + 1) % 4
        """
        self.dealer = dealer % 4
        self.current_player = (self.dealer + 1) % 4
        self.trick_count = 0
        self.team_scores = {'team_a': 0, 'team_b': 0}
        self.hands: Dict[int, List[str]] = {}
        self.current_trick: List[Tuple[int, str]] = []  # list of (seat, card)
        self._create_and_deal()
    
    def _create_and_deal(self):
        deck = [rank + suit for rank in RANKS for suit in SUITS]
        random.shuffle(deck)
        # 8 cards per player (32 cards)
        for seat in range(4):
            self.hands[seat] = deck[seat*8:(seat+1)*8]
    
    def play_card(self, seat: int, card: str) -> Tuple[bool, str]:
        """
        Attempt to play `card` from `seat`.
        Returns (success, message). On success, card is removed from hand and added to current_trick.
        """
        # Basic validations
        if seat not in self.hands:
            return False, "Invalid seat"
        if self.current_player != seat:
            return False, "Not your turn"
        if card not in self.hands[seat]:
            return False, "Card not in hand"
        
        # Enforce following lead suit if possible
        if self.current_trick:
            lead_card = self.current_trick[0][1]
            lead_suit = lead_card[-1]
            # if player has any card of lead suit but played different suit, reject
            has_lead_suit = any(c[-1] == lead_suit for c in self.hands[seat])
            if has_lead_suit and card[-1] != lead_suit:
                return False, "Must follow suit"
        
        # Play the card
        self.hands[seat].remove(card)
        self.current_trick.append((seat, card))
        
        # Advance current_player to next seat who still has cards (or next seat modulo 4)
        self.current_player = (seat + 1) % 4
        # If next player has no cards left (round over), still set to next modulo seat; resolution will handle end of trick/round.
        return True, "Card played"
    
    def _card_rank_index(self, card: str) -> int:
        # card like '10H' or 'AS'; rank is all chars except last (suit)
        rank = card[:-1]
        return RANKS.index(rank)
    
    def resolve_trick(self) -> Tuple[int, int]:
        """
        Resolve the current trick (called when current_trick has 4 cards).
        Returns (winner_seat, points_won_this_trick)
        Updates team_scores and trick_count, clears current_trick, and sets current_player to winner.
        """
        if len(self.current_trick) != 4:
            raise ValueError("Cannot resolve trick until 4 cards have been played")
        
        # Lead suit is suit of first played card
        lead_suit = self.current_trick[0][1][-1]
        # Filter cards that follow lead suit
        candidates = [
            (seat, card) for (seat, card) in self.current_trick
            if card[-1] == lead_suit
        ]
        # Determine highest by rank index
        winner_seat, winner_card = max(
            candidates,
            key=lambda sc: self._card_rank_index(sc[1])
        )
        
        # Calculate points for the trick (sum of individual card points)
        points = sum(POINTS[c[1][:-1]] for c in self.current_trick)
        
        # Assign to winner's team
        if winner_seat in (0, 2):
            self.team_scores['team_a'] += points
        else:
            self.team_scores['team_b'] += points
        
        self.trick_count += 1
        # Clear trick and set next current_player to winner
        self.current_trick = []
        self.current_player = winner_seat
        
        return winner_seat, points
    
    def calculate_final_scores(self) -> Dict[str, int]:
        """
        Return final scores for the round/game as dict {'team_a': int, 'team_b': int}
        """
        '''
        score = {"team_a": 0, "team_b": 0}
        for winner, cards in tricks:
            trick_piont = sum(san_card_values[card] for card in cards)
            scores[winner] += trick_points

            # last trick bonus
            scores[last_trick_winner] += 10

        '''
        return {
            'team_a': self.team_scores['team_a'],
            'team_b': self.team_scores['team_b']
        }
    
    def get_game_state(self) -> Dict:
        """
        Return a serializable view of the current game state.
        Note: hands are returned as counts (so server can decide to reveal full hands when appropriate).
        """
        return {
            'dealer': self.dealer,
            'current_player': self.current_player,
            'trick_count': self.trick_count,
            'team_scores': self.team_scores.copy(),
            'hand_counts': {seat: len(hand) for seat, hand in self.hands.items()},
            'current_trick': [{'seat': s, 'card': c} for s, c in self.current_trick]
        }
