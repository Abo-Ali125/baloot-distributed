"""
game.py
This file contains the basic structure for the Baloot Distributed Game.

The game.py file is designed to serve as the entry point for the game logic,
including initialization, player management, and the game loop.
"""

class Game:
    def __init__(self):
        """Initialize the game with default settings."""
        self.players = []
        self.is_running = False

    def add_player(self, player_name):
        """Add a player to the game."""
        self.players.append(player_name)
        print(f"Player {player_name} has joined the game.")

    def start(self):
        """Start the game."""
        if len(self.players) < 2:
            print("Not enough players to start the game. Minimum 2 players required.")
            return
        self.is_running = True
        print("The game has started!")

    def game_loop(self):
        """Main game loop."""
        while self.is_running:
            print("Game is running...")
            # Placeholder for game logic
            self.end()

    def end(self):
        """End the game."""
        self.is_running = False
        print("The game has ended!")


if __name__ == "__main__":
    game = Game()
    
    # Add players
    game.add_player("Player1")
    game.add_player("Player2")
    
    # Start the game
    game.start()
    
    # Run the game loop
    game.game_loop()
