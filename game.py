"""
Baloot Game Logic
Implements San-only rules for MVP
"""
import random
import logging
from typing import List, Tuple, Dict, Optional

logger = logging.getLogger(__name__)

class Game:
    """Core game logic for Baloot (San rules only)"""
    
    # Card values for San scoring
    CARD_VALUES = {
        '7': 0, '8': 0, '9': 0,
        'J': 2, 'Q': 3, 'K': 4,
        '10': 10, 'A': 11
    }
    
    # Card strength order (for winning tricks)
    CARD_STRENGTH = {
        '7': 1, '8': 2, '9': 3,
        'J': 4, 'Q': 5, 'K': 6,
        '10': 7, 'A': 8
    }
    
    SUITS = ['H', 'D', 'C', 'S']  # Hearts, Diamonds, Clubs, Spades
    RANKS = ['7', '8', '9', 'J', 'Q', 'K', '10', 'A']
    
    def __init__(self, dealer: int = 0):
        """Initialize game with dealer position"""
        self.dealer = dealer
        self.current_player = (dealer + 1) % 4  # Player after dealer leads
        self.hands = {0: [], 1: [], 2: [], 3: []}  # Player hands by seat
        self.current_trick = []  # Cards in current trick
        self.trick_leader = self.current_player
        self.trick_count = 0
        self.team_scores = {'team_a': 0, 'team_b': 0}  # Teams: 0,2 vs 1,3
        self.abnat_scores = {'team_a': 0, 'team_b': 0}  # Card value points
        self.last_trick_winner = None
        self.deck = []
        self.played_cards = []  # Track all played cards
        
        self._create_and_deal()
    
    def _create_and_deal(self):
        """Create deck and deal cards"""
        # Create 32-card deck
        self.deck = []
        for suit in self.SUITS:
            for rank in self.RANKS:
                self.deck.append(f"{rank}{suit}")
        
        # Shuffle
        random.shuffle(self.deck)
        
        # Deal 8 cards to each player
        for i in range(32):
            player = i % 4
            self.hands[player].append(self.deck[i])
        
        # Sort hands for easier play
        for player in range(4):
            self.hands[player] = self._sort_hand(self.hands[player])
        
        logger.info(f"Dealt cards. Dealer: {self.dealer}, First player: {self.current_player}")
    
    def _sort_hand(self, hand: List[str]) -> List[str]:
        """Sort hand by suit and rank"""
        def card_sort_key(card):
            rank = card[:-1]
            suit = card[-1]
            suit_order = {'H': 0, 'D': 1, 'C': 2, 'S': 3}
            rank_order = {'7': 0, '8': 1, '9': 2, 'J': 3, 'Q': 4, 'K': 5, '10': 6, 'A': 7}
            return (suit_order[suit], rank_order[rank])
        
        return sorted(hand, key=card_sort_key)
    
    def get_card_suit(self, card: str) -> str:
        """Extract suit from card string"""
        return card[-1]
    
    def get_card_rank(self, card: str) -> str:
        """Extract rank from card string"""
        return card[:-1]
    
    def play_card(self, player: int, card: str) -> Tuple[bool, str]:
        """
        Play a card from player's hand
        Returns (success, message)
        """
        # Check if it's player's turn
        if player != self.current_player:
            return False, "Not your turn"
        
        # Check if player has the card
        if card not in self.hands[player]:
            return False, "Card not in hand"
        
        # Check if move is legal
        if not self._is_legal_play(player, card):
            return False, "Must follow suit"
        
        # Play the card
        self.hands[player].remove(card)
        self.current_trick.append({
            'player': player,
            'card': card
        })
        self.played_cards.append(card)
        
        # Move to next player
        self.current_player = (self.current_player + 1) % 4
        
        # Check if trick is complete
        if len(self.current_trick) == 4:
            self._process_trick_end()
        
        return True, "Card played successfully"
    
    def _is_legal_play(self, player: int, card: str) -> bool:
        """Check if playing this card is legal"""
        # First card of trick - anything is legal
        if len(self.current_trick) == 0:
            return True
        
        # Get led suit
        led_suit = self.get_card_suit(self.current_trick[0]['card'])
        card_suit = self.get_card_suit(card)
        
        # If playing led suit, always legal
        if card_suit == led_suit:
            return True
        
        # Check if player has any cards of led suit
        player_suits = [self.get_card_suit(c) for c in self.hands[player]]
        has_led_suit = led_suit in player_suits
        
        # Must follow suit if able
        if has_led_suit:
            return False
        
        # Can play any card if no led suit
        return True
    
    def _process_trick_end(self):
        """Process end of trick - determine winner and award points"""
        # This is called internally, actual processing happens in resolve_trick
        pass
    
    def resolve_trick(self) -> Tuple[int, int]:
        """
        Resolve completed trick
        Returns (winner_seat, points_earned)
        """
        if len(self.current_trick) != 4:
            return None, 0
        
        # Get led suit
        led_suit = self.get_card_suit(self.current_trick[0]['card'])
        
        # Find highest card in led suit
        winner = None
        highest_strength = 0
        
        for play in self.current_trick:
            card = play['card']
            player = play['player']
            
            if self.get_card_suit(card) == led_suit:
                rank = self.get_card_rank(card)
                strength = self.CARD_STRENGTH[rank]
                
                if strength > highest_strength:
                    highest_strength = strength
                    winner = player
        
        # Calculate abnat (card values) for this trick
        trick_abnat = 0
        for play in self.current_trick:
            rank = self.get_card_rank(play['card'])
            trick_abnat += self.CARD_VALUES[rank]
        
        # Add to team score
        if winner in [0, 2]:  # Team A
            self.abnat_scores['team_a'] += trick_abnat
        else:  # Team B (seats 1, 3)
            self.abnat_scores['team_b'] += trick_abnat
        
        # Track for last trick bonus
        self.trick_count += 1
        if self.trick_count == 8:
            self.last_trick_winner = winner
            # Add last trick bonus
            if winner in [0, 2]:
                self.abnat_scores['team_a'] += 10
            else:
                self.abnat_scores['team_b'] += 10
        
        # Clear trick and set next leader
        self.current_trick = []
        self.trick_leader = winner
        self.current_player = winner
        
        logger.info(f"Trick won by player {winner}, abnat: {trick_abnat}")
        
        return winner, trick_abnat
    
    def calculate_final_scores(self) -> Dict[str, int]:
        """
        Calculate final round scores from abnat
        San scoring: round to nearest 10, ×2, ÷10
        """
        final_scores = {}
        
        for team in ['team_a', 'team_b']:
            abnat = self.abnat_scores[team]
            # Round to nearest 10
            rounded = round(abnat / 10) * 10
            # Calculate points
            points = (rounded * 2) // 10
            final_scores[team] = points
        
        logger.info(f"Final scores - Team A: {final_scores['team_a']}, Team B: {final_scores['team_b']}")
        
        return final_scores
    
    def get_legal_cards(self, player: int) -> List[str]:
        """Get list of legal cards player can play"""
        if player != self.current_player:
            return []
        
        legal_cards = []
        for card in self.hands[player]:
            if self._is_legal_play(player, card):
                legal_cards.append(card)
        
        return legal_cards
    
    def get_game_state(self) -> Dict:
        """Get current game state"""
        return {
            'dealer': self.dealer,
            'current_player': self.current_player,
            'trick_count': self.trick_count,
            'current_trick': self.current_trick,
            'team_scores': self.team_scores,
            'abnat_scores': self.abnat_scores,
            'cards_remaining': {i: len(self.hands[i]) for i in range(4)}
        }
