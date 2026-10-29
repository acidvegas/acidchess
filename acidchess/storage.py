#!/usr/bin/env python3
# acidchess - Developed by acidvegas in Python (https://github.com/acidvegas)
# acidchess/storage.py

import json
import os
import sqlite3
import threading
import time


DATA_DIR       = os.environ.get('ACIDCHESS_DATA_DIR', os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data'))
DB_PATH        = os.path.join(DATA_DIR, 'acidchess.db')
DB_LOCK        = threading.RLock()
START_RATING   = 1200
PROVISIONAL    = 30   # games played before K drops from 40 to 20
MASTER_RATING  = 2400 # peak rating where K drops to 10
LEADERBOARD_N  = 50

os.makedirs(DATA_DIR, exist_ok=True)


def db_connect() -> sqlite3.Connection:
	'''Open a connection to the database.'''

	conn = sqlite3.connect(DB_PATH)
	conn.row_factory = sqlite3.Row
	return conn


def delete_room(rid: str):
	'''Remove a persisted room.'''

	with DB_LOCK, db_connect() as c:
		c.execute('DELETE FROM rooms WHERE id=?', (rid,))


def elo_k(row: sqlite3.Row) -> int:
	'''Return the FIDE-style K factor for a player.'''

	if row['peak_rating'] >= MASTER_RATING:
		return 10
	if row['games'] < PROVISIONAL:
		return 40
	return 20


def get_user(user_id: int) -> dict:
	'''Return a user's public profile, ratings per mode and recent games, or None.'''

	with db_connect() as c:
		row = c.execute('SELECT id, username, created_at FROM users WHERE id=?', (user_id,)).fetchone()
		if not row:
			return None
		user = dict(row)
		user['ratings'] = {r['mode']: rounded(r) for r in c.execute('SELECT * FROM ratings WHERE user_id=?', (user_id,)).fetchall()}
		user['bot']     = [dict(r) for r in c.execute('SELECT level, wins, losses, draws FROM bot_stats WHERE user_id=? ORDER BY level', (user_id,)).fetchall()]
		user['recent']  = [dict(r) for r in c.execute('SELECT room_id, mode, white, black, white_id, black_id, result, reason, rated, tc, ended_at FROM games WHERE white_id=? OR black_id=? ORDER BY ended_at DESC LIMIT 10', (user_id, user_id)).fetchall()]
	return user


def init_db():
	'''Create tables.'''

	with DB_LOCK, db_connect() as c:
		c.execute('''CREATE TABLE IF NOT EXISTS users (
			id            INTEGER PRIMARY KEY AUTOINCREMENT,
			username      TEXT NOT NULL UNIQUE COLLATE NOCASE,
			password_hash TEXT NOT NULL,
			created_at    INTEGER NOT NULL
		)''')
		c.execute('''CREATE TABLE IF NOT EXISTS ratings (
			user_id     INTEGER NOT NULL,
			mode        TEXT NOT NULL,
			rating      REAL NOT NULL,
			peak_rating REAL NOT NULL,
			games       INTEGER NOT NULL DEFAULT 0,
			wins        INTEGER NOT NULL DEFAULT 0,
			losses      INTEGER NOT NULL DEFAULT 0,
			draws       INTEGER NOT NULL DEFAULT 0,
			streak      INTEGER NOT NULL DEFAULT 0,
			best_streak INTEGER NOT NULL DEFAULT 0,
			PRIMARY KEY (user_id, mode)
		)''')
		c.execute('CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, user_id INTEGER NOT NULL, expires_at INTEGER NOT NULL)')
		c.execute('''CREATE TABLE IF NOT EXISTS games (
			id       INTEGER PRIMARY KEY AUTOINCREMENT,
			room_id  TEXT NOT NULL,
			mode     TEXT NOT NULL DEFAULT 'classic',
			white    TEXT NOT NULL,
			black    TEXT NOT NULL,
			white_id INTEGER,
			black_id INTEGER,
			result   TEXT NOT NULL,
			reason   TEXT NOT NULL,
			rated    INTEGER NOT NULL,
			tc       TEXT,
			pgn      TEXT NOT NULL,
			ended_at INTEGER NOT NULL
		)''')
		c.execute('CREATE TABLE IF NOT EXISTS rooms (id TEXT PRIMARY KEY, data TEXT NOT NULL, updated_at INTEGER NOT NULL)')
		c.execute('CREATE TABLE IF NOT EXISTS games4 (id INTEGER PRIMARY KEY AUTOINCREMENT, room_id TEXT NOT NULL, mode TEXT NOT NULL, players TEXT NOT NULL, places TEXT NOT NULL, result TEXT NOT NULL, reason TEXT NOT NULL, rated INTEGER NOT NULL, tc TEXT, ended_at INTEGER NOT NULL)')
		# Databases from before game modes existed
		if 'mode' not in {r['name'] for r in c.execute('PRAGMA table_info(games)').fetchall()}:
			c.execute("ALTER TABLE games ADD COLUMN mode TEXT NOT NULL DEFAULT 'classic'")
		c.execute('CREATE TABLE IF NOT EXISTS bot_stats (user_id INTEGER NOT NULL, level INTEGER NOT NULL, wins INTEGER NOT NULL DEFAULT 0, losses INTEGER NOT NULL DEFAULT 0, draws INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (user_id, level))')


def leaderboard(mode: str) -> list:
	'''Return the top rated players in a mode who have finished at least one rated game in it.'''

	with db_connect() as c:
		rows = c.execute('SELECT u.id, u.username, r.* FROM ratings r JOIN users u ON u.id = r.user_id WHERE r.mode=? AND r.games > 0 ORDER BY r.rating DESC LIMIT ?', (mode, LEADERBOARD_N)).fetchall()
	return [rounded(r) for r in rows]


def load_rooms() -> dict:
	'''Load every persisted room.'''

	out = {}
	with DB_LOCK, db_connect() as c:
		for row in c.execute('SELECT id, data FROM rooms').fetchall():
			try:
				out[row['id']] = json.loads(row['data'])
			except ValueError as e:
				print(f'skipping corrupt room {row["id"]}: {e}')
	return out


def prune_sessions():
	'''Delete expired sessions.'''

	with DB_LOCK, db_connect() as c:
		c.execute('DELETE FROM sessions WHERE expires_at < ?', (int(time.time()),))


def rating_of(user_id: int, mode: str) -> int:
	'''Return a user's rounded rating in a mode, or the starting rating if they have not played it.'''

	with db_connect() as c:
		row = c.execute('SELECT rating FROM ratings WHERE user_id=? AND mode=?', (user_id, mode)).fetchone()
	return round(row['rating']) if row else START_RATING


def record_bot_game(user_id: int, level: int, score: float):
	'''Add a finished game against the computer to a player's record for that level.

	:param score: 1 for a win, 0 for a loss, 0.5 for a draw
	'''

	col = 'wins' if score == 1 else 'losses' if score == 0 else 'draws'
	with DB_LOCK, db_connect() as c:
		c.execute(f'INSERT INTO bot_stats(user_id, level, {col}) VALUES(?, ?, 1) ON CONFLICT(user_id, level) DO UPDATE SET {col}={col}+1', (user_id, level))


def record_four(room_id: str, mode: str, names: dict, ids: dict, places: dict, result: str, reason: str, rated: bool, tc: str) -> dict:
	'''Store a finished 4-player game and, if rated, update Elo pairwise. Returns the rating change per color.

	Every pair of players who finished in different places counts as a game the better placed one won, with K split over the three opponents.

	:param places: color -> finishing place, 1 is best
	'''

	diff = {}
	with DB_LOCK, db_connect() as c:
		c.execute('INSERT INTO games4(room_id, mode, players, places, result, reason, rated, tc, ended_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)', (room_id, mode, json.dumps({k: [names[k], ids[k]] for k in names}), json.dumps(places), result, reason, int(rated), tc, int(time.time())))
		if not rated or not all(ids.values()) or len(set(ids.values())) != len(ids):
			return diff
		rows = {}
		for color, user_id in ids.items():
			c.execute('INSERT OR IGNORE INTO ratings(user_id, mode, rating, peak_rating) VALUES(?, ?, ?, ?)', (user_id, mode, START_RATING, START_RATING))
			rows[color] = c.execute('SELECT * FROM ratings WHERE user_id=? AND mode=?', (user_id, mode)).fetchone()
		change = {color: 0.0 for color in rows}
		for a in rows:
			for b in rows:
				if a == b or places[a] == places[b]:
					continue
				expected   = 1 / (1 + 10 ** ((rows[b]['rating'] - rows[a]['rating']) / 400))
				change[a] += elo_k(rows[a]) / (len(rows) - 1) * ((1.0 if places[a] < places[b] else 0.0) - expected)
		for color, row in rows.items():
			new    = row['rating'] + change[color]
			won    = places[color] == 1
			col    = 'wins' if won else 'losses'
			streak = row['streak'] + 1 if won else 0
			c.execute(f'UPDATE ratings SET rating=?, peak_rating=MAX(peak_rating, ?), games=games+1, {col}={col}+1, streak=?, best_streak=MAX(best_streak, ?) WHERE user_id=? AND mode=?', (new, new, streak, streak, row['user_id'], mode))
			diff[color] = round(new) - round(row['rating'])
	return diff


def record_game(room_id: str, mode: str, white: str, black: str, white_id: int, black_id: int, result: str, reason: str, rated: bool, tc: str, pgn: str) -> dict:
	'''Store a finished game and, for rated games, update both players' Elo and stats in that mode. Returns the rating change per color.

	:param result: 1-0, 0-1 or 1/2-1/2
	'''

	score = {'1-0': 1.0, '0-1': 0.0}.get(result, 0.5)
	diff  = {}
	with DB_LOCK, db_connect() as c:
		c.execute('INSERT INTO games(room_id, mode, white, black, white_id, black_id, result, reason, rated, tc, pgn, ended_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', (room_id, mode, white, black, white_id, black_id, result, reason, int(rated), tc, pgn, int(time.time())))
		if not rated or not white_id or not black_id:
			return diff
		for user_id in (white_id, black_id):
			c.execute('INSERT OR IGNORE INTO ratings(user_id, mode, rating, peak_rating) VALUES(?, ?, ?, ?)', (user_id, mode, START_RATING, START_RATING))
		w = c.execute('SELECT * FROM ratings WHERE user_id=? AND mode=?', (white_id, mode)).fetchone()
		b = c.execute('SELECT * FROM ratings WHERE user_id=? AND mode=?', (black_id, mode)).fetchone()
		expected = 1 / (1 + 10 ** ((b['rating'] - w['rating']) / 400))
		for color, row, actual, exp in (('w', w, score, expected), ('b', b, 1 - score, 1 - expected)):
			new    = row['rating'] + elo_k(row) * (actual - exp)
			col    = 'wins' if actual == 1 else 'losses' if actual == 0 else 'draws'
			streak = row['streak'] + 1 if actual == 1 else 0 if actual == 0 else row['streak']
			c.execute(f'UPDATE ratings SET rating=?, peak_rating=MAX(peak_rating, ?), games=games+1, {col}={col}+1, streak=?, best_streak=MAX(best_streak, ?) WHERE user_id=? AND mode=?', (new, new, streak, streak, row['user_id'], mode))
			diff[color] = round(new) - round(row['rating'])
	return diff


def rounded(row: sqlite3.Row) -> dict:
	'''Return a ratings row as a dict with whole-number ratings.'''

	out = dict(row)
	out['rating']      = round(out['rating'])
	out['peak_rating'] = round(out['peak_rating'])
	return out


def save_room(rid: str, room: dict):
	'''Persist a room so it survives a restart.'''

	try:
		with DB_LOCK, db_connect() as c:
			c.execute('INSERT OR REPLACE INTO rooms(id, data, updated_at) VALUES(?, ?, ?)', (rid, json.dumps(room), int(time.time())))
	except (sqlite3.Error, TypeError, ValueError) as e:
		print(f'save_room({rid}) failed: {e}')
