🎯 Baloot - Traditional Saudi Card Game
A real-time multiplayer implementation of Baloot, a traditional Saudi Arabian card game similar to Bridge. Built as a distributed systems project demonstrating client-server architecture, real-time state synchronization, and persistent user management.


🎮 Gameplay

4-Player Multiplayer: Team-based card game (2v2)
Real-time Synchronization: All players see game state updates instantly
Turn-based System: Enforced turn order with server-side validation
Card Rules: Follow-suit enforcement, trick-based scoring
Multiple Rounds: First team to 152 points wins

👥 Social Features

User Accounts: Secure registration and authentication
Persistent Sessions: Stay logged in for 7 days
Friend System: Add friends and see online status
Real-time Chat: Communicate with other players in your room
Leaderboard: Global rankings by level and win rate

📊 Statistics & Progression

Player Stats: Games played, won, win rate automatically tracked
Level System: Gain XP and level up (500 XP per level)
Profile Customization: Display name, bio, avatar URL
Persistent Progress: All data saved to database

🏗️ Technical Features

Distributed Architecture: Client-server model with HTTP polling
Concurrency Control: Thread-safe operations with locks
State Replication: Event broadcasting to all clients
Database Persistence: SQLite with SQLAlchemy ORM
Cloud Deployment: Ready for Render.com deployment

🎲 Game Rules
Teams

Team A: Players in seats 1 & 3
Team B: Players in seats 2 & 4

Card Values
CardPoints: 
Ace = 11
10 = 10
King = 4
Queen = 3
Jack = 2
9,8,7 = 0
How to Play

Each player receives 8 cards
Players take turns playing cards (clockwise)
Must follow suit if able
Highest card of lead suit wins the trick
Trick winner leads next trick
After 8 tricks, round ends and scores are calculated
First team to reach 152 points wins the game

🚀 Quick Start
Prerequisites

Python 3.9 or higher
pip package manager
Git

Local
# Clone the repository
git clone https://github.com/Abo-Ali125/baloot-distributed.git
cd baloot-game

# Create virtual environment
python -m venv venv
# Activate virtual environment

# Install dependencies
pip install -r requirements.txt

# Initialize database
python -c "from server import app, db; app.app_context().push(); db.create_all()"

# Run the server
python server.py
