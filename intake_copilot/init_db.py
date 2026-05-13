"""
CLI script to initialize the Supabase database table.

Usage:
    python -m intake_copilot.init_db
"""

from intake_copilot.persistence import init_db

if __name__ == "__main__":
    init_db()
