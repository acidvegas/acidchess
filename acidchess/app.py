#!/usr/bin/env python3
# acidchess - Developed by acidvegas in Python (https://github.com/acidvegas)
# acidchess/app.py

import atexit
import functools
import json
import os
import queue
import random
import re
import secrets
import threading
import time

from flask import Flask, Response, jsonify, render_template, request, send_from_directory
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

import ai
import arcade
import engine
import fourgame
import game as chess_game
import toggles
from auth import SEEN, USERNAME_RE, attempt, blocked, captcha_create, captcha_verify, create_session, delete_session, request_token, request_user
from storage import DB_LOCK, db_connect, delete_room, delete_user, get_user, init_db, leaderboard, load_rooms, mirror_user, prune_sessions, rating_of, save_room, summary


app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 64 * 1024 # no request needs more than a few KB
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1) # https links in the page metadata behind nginx

CACHE_VERSION     = int(time.time())
ROOMS_LOCK        = threading.RLock()
SUBSCRIBERS       = {}
SUBSCRIBERS_LOCK  = threading.Lock()
STREAMS           = {} # ip -> open /events streams, guarded by SUBSCRIBERS_LOCK
MAX_IP_ROOMS      = 5  # unfinished rooms one IP may have created
MAX_IP_STREAMS    = 20 # concurrent /events streams per IP
MISSES            = {} # ip -> times of recent lookups of room ids that don't exist
MAX_IP_MISSES     = 30 # unknown room ids one IP may look up a minute, so private rooms can't be found by scanning
MAX_ROOMS         = 500
ROOM_TIMEOUT      = 24 * 60 * 60
ROOM_ID_CHARS     = 'abcdefghjkmnpqrstuvwxyz23456789'
ROOM_ID_LEN       = 4
NAME_RE           = re.compile(r'[^A-Za-z0-9_\- ]')
CHAT_RATE_WINDOW  = 1.0
CHAT_RATE_MAX     = 2
CHAT_TIMES        = {}
BOT_THINKING      = set()
PUBLIC_URL        = os.environ.get('ACIDCHESS_PUBLIC_URL', '').rstrip('/') # e.g. https://chess.acid.vegas, the one address crawlers and share cards use when the site answers on several
DESCRIPTION       = 'Play chess online for free: quick play, 8 computer levels, Reconnaissance Blind, big boards, 4-player and 2v2, plus twists like king of the hill, three-check and drops. Open source, no install.'

init_db()
rooms = load_rooms()
# Spectator streams don't survive a restart
for _room in rooms.values():
	_room['spectators'] = {}
	# No one has a stream open right after a restart either, so every player gets the full wait to reconnect before anyone can claim against them
	for _p in _room['players'].values():
		if _p:
			_p['seen'] = time.time()


def announce(room: dict):
	'''Post a finished game's wins and new Classic Elo hundreds to the acid-arcade-db activity feed from a background thread.'''

	game    = room['game']
	winners = list(game['result']) if chess_game.is_four(room) else {'1-0': ['w'], '0-1': ['b']}.get(game['result'], [])
	diff    = game['rating_diff'] or {}
	lines   = []
	for color, p in room['players'].items():
		if not p or not p['user_id']:
			continue
		if color in winners and room.get('bot'):
			lines.append((p['user_id'], 'win', f'beat the level {room["bot"]} computer'))
		elif color in winners and color in diff:
			lines.append((p['user_id'], 'win', f'won a rated {chess_game.MODES[chess_game.mode(room)]["name"]} game ({diff[color]:+d} Elo)'))
		peak = game.get('old_peaks', {}).get(color)
		if peak is not None:
			hundred = rating_of(p['user_id'], 'classic') // 100 * 100
			if hundred >= 1500 and peak < hundred:
				lines.append((p['user_id'], 'record', f'reached {hundred} Classic Elo'))

	def send():
		for user_id, kind, text in lines:
			try:
				arcade.event(user_id, kind, text)
			except Exception as e:
				print(f'event({user_id}, {kind}) failed: {e}')

	if lines:
		threading.Thread(target=send, daemon=True).start()


def api_error(message: str, status: int = 400) -> tuple:
	'''Return a JSON error response.'''

	return jsonify({'error': message}), status


def arcade_presence():
	'''Background loop: every 30 seconds, tell acid-arcade-db which signed in players have the game open.

	That is anyone whose session was checked in the last minute (the home page asks every few seconds), plus players seated in a room with an open event stream.
	'''

	while True:
		try:
			now = time.time()
			for user_id in [u for u, at in list(SEEN.items()) if now - at > 60]:
				SEEN.pop(user_id, None)
			ids = set(SEEN)
			with ROOMS_LOCK, SUBSCRIBERS_LOCK:
				for room in rooms.values():
					if SUBSCRIBERS.get(room['id']):
						ids.update(p['user_id'] for p in room['players'].values() if p and p['user_id'])
			arcade.presence(sorted(ids))
		except Exception as e:
			print(f'arcade presence error: {e}')
		time.sleep(30)


def arcade_reply(reply: dict) -> Response:
	'''Answer a sign-in from acid-arcade-db and share it with the other sites on this domain.'''

	resp = jsonify(reply)
	arcade.set_cookie(resp, request.host, reply['token'])
	return resp


def arcade_sync():
	'''Background loop: every minute, pick up renamed and deleted accounts from acid-arcade-db.'''

	since = 0
	while True:
		try:
			data  = arcade.changes(since)
			since = data['now']
			for user in data['changed']:
				mirror_user(user['user_id'], user['username'], create=False)
				with ROOMS_LOCK:
					for room in rooms.values():
						seats = [p for p in room['players'].values() if p and p['user_id'] == user['user_id']]
						lines = [m for m in room['chat'] if m.get('user_id') == user['user_id']]
						if not seats and not lines:
							continue
						for item in seats + lines:
							item['name'] = user['username']
						save_room(room['id'], room)
						notify(room['id'])
			for user_id in data['deleted']:
				delete_user(user_id)
		except Exception as e:
			print(f'arcade sync error: {e}')
		time.sleep(60)


def bot_activity(room: dict):
	'''Report a finished game against the computer to acid-arcade-db from a background thread, for casino chip rewards.

	A win the computer gave away is not reported: it ran out of time, or the engine failed and it played a random move.
	'''

	game   = room['game']
	human  = 'b' if room['players']['w'].get('bot') else 'w'
	player = room['players'][human]
	if not player['user_id'] or game['result'] not in ('1-0', '0-1', '1/2-1/2'):
		return
	won = game['result'] == ('1-0' if human == 'w' else '0-1')
	if won and (game['reason'] == 'timeout' or game.get('bot_random')):
		return
	result = 'win' if won else 'draw' if game['result'] == '1/2-1/2' else 'loss'
	data   = {'result': result, 'level': room['bot'], 'moves': sum(1 for m in game['moves'] if m['color'] == human), 'variant': chess_game.mode(room), 'twists': bool(room.get('toggles'))}
	ref    = f'{room["id"]}-{int(game["ended_at"] * 1000)}' # a rematch plays on in the same room

	def send():
		try:
			arcade.activity(player['user_id'], 'bot_game', ref, room.get('creator_ip') or '', data)
		except Exception as e:
			print(f'activity({player["user_id"]}, bot_game) failed: {e}')

	threading.Thread(target=send, daemon=True).start()


def bot_turn(rid: str, game: dict, color: str, level: int):
	'''Background thread: get the computer's move and play it, unless the game moved on meanwhile.'''

	try:
		ply = len(game['moves'])
		uci = ai.best_move(engine.START_FEN, [m['uci'] for m in game['moves']], level)
		with ROOMS_LOCK:
			room = rooms.get(rid)
			if not room or room['game'] is not game or len(game['moves']) != ply or game['result']:
				return
			legal = [engine.move_to_uci(m) for m in engine.legal_moves(engine.Position(game['fen']))]
			if uci not in legal:
				print(f'engine gave {uci!r} in room {rid}, playing a random move')
				uci = random.choice(legal)
				game['bot_random'] = True # a win against a computer that played blind earns no reward
			chess_game.make_move(room, color, uci)
			changed(room)
	finally:
		BOT_THINKING.discard(rid)


def changed(room: dict):
	'''Save a room and push the change to everyone watching it.'''

	room['last_activity'] = time.time()
	game = room['game']
	# Rated and computer games change a player's acid-arcade-db summary, so send it once when they end
	if arcade.enabled() and game['result'] and game['result'] != '*' and (room['rated'] or room.get('bot')) and not game.get('stats_pushed'):
		game['stats_pushed'] = True
		push_stats([p['user_id'] for p in room['players'].values() if p and p['user_id']])
		announce(room)
		if room.get('bot'):
			bot_activity(room)
	save_room(room['id'], room)
	notify(room['id'])


def clean_name(name: str) -> str:
	'''Return a safe guest display name.'''

	name = NAME_RE.sub('', (name or '').strip())[:16].strip()
	return name or f'Guest{random.randint(1000, 9999)}'


def find_room(rid: str) -> dict:
	'''Return the room with this id, or None. An IP that keeps asking for rooms that don't exist gets None for every room for a minute.'''

	now    = time.time()
	misses = [t for t in MISSES.get(request.remote_addr, []) if t > now - 60]
	if len(misses) >= MAX_IP_MISSES:
		return None
	room = rooms.get(rid)
	if room is None:
		for ip in [ip for ip, times in MISSES.items() if times[-1] <= now - 60]:
			del MISSES[ip]
		MISSES[request.remote_addr] = misses + [now]
	return room


def get_room() -> tuple:
	'''Return (room, color) for the request's room id and player token. Color is None for spectators.'''

	if request.method == 'GET':
		rid   = (request.args.get('room_id') or '').lower()
		token = request.headers.get('X-Player-Token') or ''
	else:
		data  = request.get_json(silent=True) or {}
		rid   = (data.get('room_id') or '').lower()
		token = data.get('player_token') or ''
	room = find_room(rid)
	if room is None:
		return None, None
	color = next((c for c in chess_game.seats(room) if token and room['players'][c] and room['players'][c]['token'] == token), None)
	return room, color


def is_open(room: dict) -> bool:
	'''Return whether a room is waiting for an opponent and its creator is still connected.'''

	if room['game']['moves'] or room['game']['result']:
		return False
	if all(room['players'].values()):
		return False
	with SUBSCRIBERS_LOCK:
		return bool(SUBSCRIBERS.get(room['id']))


def join_seat(room: dict, name: str, user_id: int) -> tuple:
	'''Seat a player in the empty seat. Returns (token, color) or (None, error).'''

	color = next((c for c in chess_game.seats(room) if room['players'][c] is None), None)
	if color is None:
		return None, 'room is full'
	if room['rated']:
		if not user_id:
			return None, 'sign in to play rated games'
		if any(p and p['user_id'] == user_id for p in room['players'].values()):
			return None, 'you cannot play yourself in a rated game'
	token = secrets.token_urlsafe(16)
	chess_game.seat(room, color, token, name, user_id)
	return token, color


def make_room_id() -> str:
	'''Return an unused room id.'''

	while True:
		rid = ''.join(random.choices(ROOM_ID_CHARS, k=ROOM_ID_LEN))
		if rid not in rooms:
			return rid


def mark_seen(rid: str, token: str):
	'''Note that the player holding this token has the room's event stream open, for claims against players who left.'''

	with ROOMS_LOCK:
		room = rooms.get(rid)
		for p in room['players'].values() if room and token else []:
			if p and p['token'] == token:
				p['seen'] = time.time()


def maybe_bot(room: dict):
	'''Start the computer thinking if it is its turn.'''

	game = room['game']
	if not room.get('bot') or game['result'] or room['id'] in BOT_THINKING:
		return
	color  = engine.Position(game['fen']).turn
	player = room['players'][color]
	if player and player.get('bot'):
		BOT_THINKING.add(room['id'])
		threading.Thread(target=bot_turn, args=(room['id'], game, color, player['bot']), daemon=True).start()


def notify(rid: str):
	'''Wake every event stream watching a room.'''

	with SUBSCRIBERS_LOCK:
		subs = list(SUBSCRIBERS.get(rid, []))
	for q in subs:
		try:
			q.put_nowait('change')
		except queue.Full:
			pass


def open_room(tc: str, public: bool, quick: bool, rated: bool, color: str, name: str, user_id: int, bot: int = None, game_mode: str = 'classic', options: dict = None) -> tuple:
	'''Create a room with the caller seated, and the computer opposite them if bot is a level. Returns (room, token, color).'''

	rid  = make_room_id()
	room = chess_game.new_room(rid, tc, public, quick, rated, bot, game_mode, options)
	room['creator_ip'] = request.remote_addr
	if color not in chess_game.seats(room):
		color = random.choice(chess_game.seats(room))
	token = secrets.token_urlsafe(16)
	chess_game.seat(room, color, token, name, user_id)
	if bot:
		chess_game.seat(room, chess_game.opponent(color), None, f'Computer level {bot}', None, bot)
	rooms[rid] = room
	changed(room)
	maybe_bot(room)
	return room, token, color


def player_name() -> tuple:
	'''Return (display name, user id) for the request.'''

	user_id, username = request_user()
	if user_id:
		return username, user_id
	return clean_name((request.get_json(silent=True) or {}).get('name')), None


def public_root() -> str:
	'''Return the site's address with a trailing slash: ACIDCHESS_PUBLIC_URL if set, otherwise the request's.'''

	return f'{PUBLIC_URL}/' if PUBLIC_URL else request.url_root


def push_stats(user_ids: list):
	'''Send players' summaries to acid-arcade-db from a background thread, so a failed push never holds up a game.'''

	def send():
		names = {k: m['name'] for k, m in chess_game.MODES.items()}
		for user_id in user_ids:
			try:
				arcade.push_stats(user_id, *summary(user_id, names))
			except Exception as e:
				print(f'push_stats({user_id}) failed: {e}')

	threading.Thread(target=send, daemon=True).start()


def reap():
	'''Drop rooms nobody has touched in a day, and finished or never-started rooms after an hour.'''

	now = time.time()
	for rid, room in list(rooms.items()):
		idle = now - room['last_activity']
		if idle > ROOM_TIMEOUT or (idle > 3600 and (room['game']['result'] or not room['game']['moves'])):
			if not room['game']['result'] and len(room['game']['moves']) >= 2:
				chess_game.finish(room, '*', 'abandoned')
			rooms.pop(rid, None)
			delete_room(rid)


def room_refusal() -> tuple:
	'''Return an error response if no new room can be opened for the request's IP, otherwise None.'''

	if len(rooms) >= MAX_ROOMS:
		reap()
		if len(rooms) >= MAX_ROOMS:
			return api_error('server full, try again later', 503)
	if sum(1 for r in rooms.values() if r.get('creator_ip') == request.remote_addr and not r['game']['result']) >= MAX_IP_ROOMS:
		return api_error(f'you already have {MAX_IP_ROOMS} open rooms, finish or leave one first', 429)
	return None


def rooms_locked(fn):
	'''Run a route while holding ROOMS_LOCK.'''

	@functools.wraps(fn)
	def wrapper(*args, **kwargs):
		with ROOMS_LOCK:
			return fn(*args, **kwargs)
	return wrapper


def ticker():
	'''Background loop: end games on flag fall every half second, reap stale rooms every five minutes.'''

	last_reap = 0
	while True:
		time.sleep(0.5)
		try:
			with ROOMS_LOCK:
				for room in list(rooms.values()):
					if chess_game.check_flag(room):
						changed(room)
					maybe_bot(room)
				if time.time() - last_reap > 300:
					last_reap = time.time()
					reap()
					prune_sessions()
		except Exception as e:
			print(f'ticker error: {e}')


@app.route('/')
@app.route('/<rid>')
def index(rid: str = None):
	'''Serve the single page app.'''

	if rid and (len(rid) != ROOM_ID_LEN or not all(c in ROOM_ID_CHARS for c in rid.lower())):
		return 'Not found', 404

	url = public_root()
	ld  = {
		'@context'           : 'https://schema.org',
		'@type'              : ['VideoGame', 'WebApplication'],
		'name'               : 'acidchess',
		'url'                : url,
		'description'        : DESCRIPTION,
		'image'              : f'{url}static/og.png',
		'applicationCategory': 'GameApplication',
		'operatingSystem'    : 'Any',
		'genre'              : ['Chess', 'Board game', 'Strategy'],
		'gamePlatform'       : 'Web browser',
		'playMode'           : ['SinglePlayer', 'MultiPlayer'],
		'isAccessibleForFree': True,
		'offers'             : {'@type': 'Offer', 'price': '0', 'priceCurrency': 'USD'},
		'author'             : {'@type': 'Person', 'name': 'acidvegas', 'url': 'https://github.com/acidvegas'},
	}
	# < is escaped so nothing in the data can end the script tag
	return render_template('index.html', cache_v=CACHE_VERSION, url=url, room=bool(rid), arcade=arcade.public_url(request.host) if arcade.enabled() else '', description=DESCRIPTION, ld=json.dumps(ld).replace('<', '\\u003c'))


@app.route('/abort', methods=['POST'])
@rooms_locked
def abort():
	'''Abort a game before both sides have moved, or close an unanswered room.'''

	room, color = get_room()
	if not room or not color:
		return api_error('not a player in this room', 403)
	if room['game']['result'] or len(room['game']['moves']) >= len(room['players']):
		return api_error('too late to abort')
	chess_game.finish(room, '*', 'aborted')
	changed(room)
	return jsonify({'ok': True})


@app.route('/active', methods=['POST'])
@rooms_locked
def active():
	'''List the unfinished games the caller has a seat in: by account when signed in, and by the room tokens this browser kept.'''

	user_id, _ = request_user()
	tokens     = (request.get_json(silent=True) or {}).get('tokens')
	tokens     = tokens if isinstance(tokens, dict) else {}
	out        = []
	for room in rooms.values():
		if room['game']['result']:
			continue
		for color in chess_game.seats(room):
			seat = room['players'][color]
			if seat and seat['token'] and ((user_id and seat['user_id'] == user_id) or tokens.get(room['id']) == seat['token']):
				out.append({'room_id': room['id'], 'player_token': seat['token'], 'mode': chess_game.MODES[chess_game.mode(room)]['name'], 'tc': room['tc'], 'opponents': [p['name'] for c, p in room['players'].items() if p and c != color]})
				break
	return jsonify({'rooms': out})


@app.errorhandler(arcade.ArcadeDown)
def arcade_down(e: arcade.ArcadeDown) -> tuple:
	'''Answer 503 while acid-arcade-db is unreachable, there is no fallback to guest.'''

	return api_error('account server is down', 503)


@app.errorhandler(arcade.ArcadeError)
def arcade_error(e: arcade.ArcadeError) -> tuple:
	'''Pass on an error acid-arcade-db gave.'''

	return api_error(str(e), e.status)


@app.route('/auth/captcha')
def auth_captcha():
	'''Return a new captcha.'''

	if arcade.enabled():
		return jsonify(arcade.captcha())
	if blocked('captcha', request.remote_addr):
		return api_error('too many captchas, wait a minute', 429)
	attempt('captcha', request.remote_addr)
	return jsonify(captcha_create())


@app.route('/auth/login', methods=['POST'])
def auth_login():
	'''Log in with username and password.'''

	data = request.get_json(silent=True) or {}
	if arcade.enabled():
		return arcade_reply(arcade.login(data.get('username') or '', data.get('password') or '', request.remote_addr))
	name = (data.get('username') or '').lower()
	if blocked('account', name) or blocked('ip', request.remote_addr):
		return api_error('too many failed logins, try again in 15 minutes', 429)
	with db_connect() as c:
		row = c.execute('SELECT id, username, password_hash FROM users WHERE username=?', (data.get('username') or '',)).fetchone()
	if not row or not check_password_hash(row['password_hash'], data.get('password') or ''):
		attempt('account', name)
		attempt('ip', request.remote_addr)
		return api_error('wrong username or password', 401)
	return jsonify({'token': create_session(row['id']), 'username': row['username'], 'user_id': row['id']})


@app.route('/auth/logout', methods=['POST'])
def auth_logout():
	'''Log out the current session.'''

	if not arcade.enabled():
		delete_session(request_token())
		return jsonify({'ok': True})
	if request_token():
		arcade.logout(request_token())
	resp = jsonify({'ok': True})
	arcade.clear_cookie(resp, request.host)
	return resp


@app.route('/auth/me')
def auth_me():
	'''Return the signed in user, if any.'''

	user_id, _ = request_user()
	resp       = jsonify({'user': get_user(user_id) if user_id else None})
	# Players signed in before shared sign-in existed start sharing it here
	if arcade.enabled() and user_id and not request.cookies.get(arcade.COOKIE):
		arcade.set_cookie(resp, request.host, request_token())
	return resp


@app.route('/auth/signup', methods=['POST'])
def auth_signup():
	'''Create an account.'''

	data     = request.get_json(silent=True) or {}
	username = (data.get('username') or '').strip()
	password = data.get('password') or ''
	if arcade.enabled():
		return arcade_reply(arcade.signup(username, password, data.get('captcha_id') or '', data.get('captcha') or '', request.remote_addr))
	if not captcha_verify(data.get('captcha_id'), data.get('captcha')):
		return api_error('wrong captcha')
	if not USERNAME_RE.match(username):
		return api_error('username must be 3-16 letters, numbers or _')
	if len(password) < 8 or len(password) > 128:
		return api_error('password must be 8-128 characters')
	with DB_LOCK, db_connect() as c:
		if c.execute('SELECT 1 FROM users WHERE username=?', (username,)).fetchone():
			return api_error('username taken')
		user_id = c.execute('INSERT INTO users(username, password_hash, created_at) VALUES(?, ?, ?)', (username, generate_password_hash(password), int(time.time()))).lastrowid
	return jsonify({'token': create_session(user_id), 'username': username, 'user_id': user_id})


@app.route('/auth/sso')
def auth_sso():
	'''Swap the shared sign-in cookie set by any acid-arcade-db site on this domain for a session here.'''

	if not arcade.enabled():
		return 'Not found', 404 # standalone sites have no shared sign-in
	reply = arcade.sso(request.cookies.get(arcade.COOKIE))
	if not reply:
		resp = jsonify({'error': 'not signed in'})
		arcade.clear_cookie(resp, request.host)
		return resp, 401
	return jsonify(reply)


@app.route('/chat', methods=['POST'])
@rooms_locked
def chat():
	'''Post a chat message to a room.'''

	room, color = get_room()
	if not room or not color:
		return api_error('not a player in this room', 403)
	text = ' '.join(((request.get_json(silent=True) or {}).get('text') or '').split())[:chess_game.CHAT_TEXT_MAX]
	if not text:
		return api_error('empty message')
	key   = (room['id'], color)
	now   = time.time()
	times = [t for t in CHAT_TIMES.get(key, []) if now - t < CHAT_RATE_WINDOW]
	if len(times) >= CHAT_RATE_MAX:
		return api_error('slow down')
	CHAT_TIMES[key] = times + [now]
	room['chat'].append({'name': room['players'][color]['name'], 'user_id': room['players'][color]['user_id'], 'color': color, 'text': text, 'at': now})
	room['chat'] = room['chat'][-chess_game.CHAT_MAX:]
	changed(room)
	return jsonify({'ok': True})


@app.route('/claim', methods=['POST'])
@rooms_locked
def claim():
	'''Claim against a player who has had no event stream open for five minutes: the win in 2-player, knocking them out in 4-player.'''

	room, color = get_room()
	if not room or not color:
		return api_error('not a player in this room', 403)
	due = [c for c, wait in chess_game.claim_in(room).items() if wait == 0 and c != color]
	if chess_game.is_four(room):
		target = (request.get_json(silent=True) or {}).get('color')
		if color not in room['game']['state']['alive'] or target not in due:
			return api_error('nothing to claim')
		fourgame.resign(room, target, 'left the game')
	else:
		if chess_game.opponent(color) not in due:
			return api_error('nothing to claim')
		chess_game.finish(room, '1-0' if color == 'w' else '0-1', 'opponent left')
	changed(room)
	return jsonify({'ok': True})


@app.route('/create', methods=['POST'])
@rooms_locked
def create():
	'''Create a room and take a seat in it.'''

	data           = request.get_json(silent=True) or {}
	name, user_id  = player_name()
	rated          = bool(data.get('rated'))
	bot            = data.get('bot')
	game_mode      = data.get('mode') or 'classic'
	options        = toggles.clean(data.get('toggles'))
	if game_mode not in chess_game.MODES:
		return api_error('unknown mode')
	if game_mode in ('recon', 'four', 'teams') or bot is not None:
		options = {} # these games have no twists yet, so any left ticked from another mode are dropped
	# Twisted games are casual so each mode's rating stays comparable
	rated = rated and not options
	if bot is not None:
		if game_mode != 'classic':
			return api_error('the computer only plays classic for now')
		if type(bot) is not int or bot not in ai.LEVELS: # True and 8.0 equal levels but are not one
			return api_error('level must be 1-8')
		if not ai.available():
			return api_error('the computer is not available')
		if refusal := room_refusal():
			return refusal
		room, token, color = open_room(data.get('tc'), False, False, False, data.get('color'), name, user_id, bot)
		return jsonify({'room_id': room['id'], 'player_token': token, 'color': color})
	if rated and not user_id:
		return api_error('sign in to play rated games')
	if refusal := room_refusal():
		return refusal
	room, token, color = open_room(data.get('tc'), bool(data.get('public')), False, rated, data.get('color'), name, user_id, None, game_mode, options)
	return jsonify({'room_id': room['id'], 'player_token': token, 'color': color})


@app.route('/draw', methods=['POST'])
@rooms_locked
def draw():
	'''Offer, accept or decline a draw.'''

	room, color = get_room()
	if not room or not color:
		return api_error('not a player in this room', 403)
	game   = room['game']
	action = (request.get_json(silent=True) or {}).get('action')
	if game['result']:
		return api_error('game is over')
	if room.get('bot'):
		return api_error('the computer does not take draws')
	if chess_game.is_four(room):
		return api_error('there are no draws in 4-player')
	if action == 'offer':
		if game['draw_offer'] == chess_game.opponent(color):
			chess_game.finish(room, '1/2-1/2', 'agreement')
		else:
			game['draw_offer'] = color
	elif action == 'accept' and game['draw_offer'] == chess_game.opponent(color):
		chess_game.finish(room, '1/2-1/2', 'agreement')
	elif action == 'decline' and game['draw_offer'] == chess_game.opponent(color):
		game['draw_offer'] = None
	else:
		return api_error('no draw offer to answer')
	changed(room)
	return jsonify({'ok': True})


@app.route('/events')
def events():
	'''Server-Sent Events stream that fires whenever a room changes.'''

	rid = (request.args.get('room_id') or '').lower()
	with ROOMS_LOCK:
		if not find_room(rid):
			return Response('event: error\ndata: invalid_room\n\n', mimetype='text/event-stream', status=404)
	ip    = request.remote_addr
	q     = queue.Queue(maxsize=64)
	watch = secrets.token_hex(8) if request.args.get('watch') else None
	token = request.args.get('player_token') or ''
	with SUBSCRIBERS_LOCK:
		if STREAMS.get(ip, 0) >= MAX_IP_STREAMS:
			return Response('event: error\ndata: too_many_streams\n\n', mimetype='text/event-stream', status=429)
		STREAMS[ip] = STREAMS.get(ip, 0) + 1
		SUBSCRIBERS.setdefault(rid, []).append(q)
	if watch:
		with ROOMS_LOCK:
			if rid in rooms:
				rooms[rid]['spectators'][watch] = True
		notify(rid)
	mark_seen(rid, token)

	def stream():
		try:
			yield ': ' + (' ' * 2048) + '\n\nretry: 3000\n\nevent: connected\ndata: ok\n\n'
			while True:
				try:
					yield f'event: state\ndata: {q.get(timeout=10)}\n\n'
				except queue.Empty:
					yield ': ping\n\n'
				mark_seen(rid, token) # at least every 10 seconds while the stream is open
		finally:
			mark_seen(rid, token)
			with SUBSCRIBERS_LOCK:
				subs = SUBSCRIBERS.get(rid, [])
				if q in subs:
					subs.remove(q)
				if not subs:
					SUBSCRIBERS.pop(rid, None)
			if watch:
				with ROOMS_LOCK:
					if rid in rooms:
						rooms[rid]['spectators'].pop(watch, None)
				notify(rid)

	def release():
		with SUBSCRIBERS_LOCK:
			STREAMS[ip] -= 1
			if not STREAMS[ip]:
				STREAMS.pop(ip)

	resp = Response(stream(), mimetype='text/event-stream', headers={'Cache-Control': 'no-cache, no-transform, no-store', 'X-Accel-Buffering': 'no'})
	resp.call_on_close(release) # runs once however the stream ends, even if the generator never started
	return resp


@app.route('/favicon.ico')
def favicon():
	'''Serve the PNG icon for clients that only look for /favicon.ico.'''

	return send_from_directory(app.static_folder, 'icon-192.png', mimetype='image/png')


@app.route('/join', methods=['POST'])
@rooms_locked
def join():
	'''Take the empty seat in a room, or watch it if full.'''

	data = request.get_json(silent=True) or {}
	room = find_room((data.get('room_id') or '').lower())
	if not room:
		return api_error('room not found', 404)
	if data.get('watch') or room['game']['result'] or all(room['players'].values()):
		return jsonify({'room_id': room['id'], 'player_token': None, 'color': None})
	name, user_id = player_name()
	token, color  = join_seat(room, name, user_id)
	if token is None:
		return api_error(color)
	changed(room)
	return jsonify({'room_id': room['id'], 'player_token': token, 'color': color})


@app.route('/leaderboard')
def leaderboard_route():
	'''Return the rating leaderboard.'''

	game_mode = request.args.get('mode') or 'classic'
	if game_mode not in chess_game.MODES:
		return api_error('unknown mode')
	return jsonify({'players': leaderboard(game_mode)})


@app.route('/lobby')
@rooms_locked
def lobby():
	'''List public rooms waiting for an opponent.'''

	out = []
	for room in rooms.values():
		if not room['public'] or not is_open(room):
			continue
		color = next(c for c, p in room['players'].items() if p)
		host  = room['players'][color]
		out.append({'room_id': room['id'], 'mode': chess_game.mode(room), 'toggles': room.get('toggles', {}), 'name': host['name'], 'user_id': host['user_id'], 'rating': host['rating'], 'host_color': color, 'seated': sum(1 for p in room['players'].values() if p), 'seats': len(room['players']), 'tc': room['tc'], 'rated': room['rated'], 'created_at': room['created_at']})
	out.sort(key=lambda r: r['created_at'], reverse=True)
	return jsonify({'rooms': out, 'time_controls': list(chess_game.TIME_CONTROLS), 'bot': ai.available(), 'modes': [[k, m['name']] for k, m in chess_game.MODES.items()], 'swaps': [[k, s[0]] for k, s in toggles.SWAPS.items()]})


@app.route('/move', methods=['POST'])
@rooms_locked
def move():
	'''Play a move.'''

	room, color = get_room()
	if not room or not color:
		return api_error('not a player in this room', 403)
	result = room['game']['result']
	error  = chess_game.make_move(room, color, (request.get_json(silent=True) or {}).get('uci'))
	if error:
		if room['game']['result'] != result: # only a clock that ran out changes anything on a refused move
			changed(room)
		return api_error(error)
	changed(room)
	maybe_bot(room)
	return jsonify(chess_game.state(room, room['players'][color]['token']))


@app.route('/online')
def online():
	'''Count the live room connections (players and spectators) and the rooms they are in.'''

	if arcade.enabled():
		request_user() # the home page asks every few seconds, which keeps a signed in visitor present
	with SUBSCRIBERS_LOCK:
		return jsonify({'players': sum(len(qs) for qs in SUBSCRIBERS.values()), 'rooms': sum(1 for qs in SUBSCRIBERS.values() if qs)})


@app.route('/quickplay', methods=['POST'])
@rooms_locked
def quickplay():
	'''Join the oldest waiting quick play room with the same settings, or open one.'''

	data          = request.get_json(silent=True) or {}
	name, user_id = player_name()
	tc            = data.get('tc') if data.get('tc') in chess_game.TIME_CONTROLS else None
	rated         = bool(data.get('rated'))
	game_mode     = data.get('mode') or 'classic'
	if game_mode not in chess_game.MODES:
		return api_error('unknown mode')
	if rated and not user_id:
		return api_error('sign in to play rated games')
	waiting = [r for r in rooms.values() if r['quick'] and chess_game.mode(r) == game_mode and r['tc'] == tc and r['rated'] == rated and is_open(r)]
	for room in sorted(waiting, key=lambda r: r['created_at']):
		if user_id and any(p and p['user_id'] == user_id for p in room['players'].values()):
			continue
		token, color = join_seat(room, name, user_id)
		if token:
			changed(room)
			return jsonify({'room_id': room['id'], 'player_token': token, 'color': color})
	if refusal := room_refusal():
		return refusal
	room, token, color = open_room(tc, True, True, rated, None, name, user_id, None, game_mode)
	return jsonify({'room_id': room['id'], 'player_token': token, 'color': color})


@app.route('/rematch', methods=['POST'])
@rooms_locked
def rematch():
	'''Ask for a rematch. When both players ask, colors swap and a new game starts.'''

	room, color = get_room()
	if not room or not color:
		return api_error('not a player in this room', 403)
	if not room['game']['result'] or not all(room['players'].values()):
		return api_error('no rematch available')
	if color not in room['rematch']:
		room['rematch'].append(color)
	if chess_game.is_four(room):
		# Once everyone agrees, every player moves one seat clockwise
		if len(room['rematch']) == len(room['players']):
			seated = [room['players'][c] for c in chess_game.seats(room)]
			chess_game.new_game(room)
			for c, p in zip(chess_game.seats(room), seated[-1:] + seated[:-1]):
				chess_game.seat(room, c, p['token'], p['name'], p['user_id'])
		changed(room)
		return jsonify({'ok': True})
	if room.get('bot') and chess_game.opponent(color) not in room['rematch']:
		room['rematch'].append(chess_game.opponent(color))
	if len(room['rematch']) == 2:
		w, b = room['players']['w'], room['players']['b']
		chess_game.new_game(room)
		chess_game.seat(room, 'w', b['token'], b['name'], b['user_id'], b.get('bot'))
		chess_game.seat(room, 'b', w['token'], w['name'], w['user_id'], w.get('bot'))
	changed(room)
	maybe_bot(room)
	return jsonify({'ok': True})


@app.route('/resign', methods=['POST'])
@rooms_locked
def resign():
	'''Resign the game.'''

	room, color = get_room()
	if not room or not color:
		return api_error('not a player in this room', 403)
	if chess_game.is_four(room):
		error = fourgame.resign(room, color)
		if error:
			return api_error(error)
		changed(room)
		return jsonify({'ok': True})
	if room['game']['result'] or not room['players'][chess_game.opponent(color)]:
		return api_error('nothing to resign')
	chess_game.finish(room, '0-1' if color == 'w' else '1-0', 'resignation')
	changed(room)
	return jsonify({'ok': True})


@app.route('/healthz')
def healthz():
	'''Answer ok when the app and its database respond, for the Docker healthcheck and uptime monitors.'''

	with db_connect() as c:
		c.execute('SELECT 1')
	return Response('ok\n', mimetype='text/plain')


@app.route('/robots.txt')
def robots():
	'''Let crawlers in and point them at the sitemap.'''

	return Response(f'User-agent: *\nAllow: /\nSitemap: {public_root()}sitemap.xml\n', mimetype='text/plain')


@app.route('/sense', methods=['POST'])
@rooms_locked
def sense():
	'''Reconnaissance Blind: look at the 3x3 window around a square, or skip sensing this turn.'''

	room, color = get_room()
	if not room or not color:
		return api_error('not a player in this room', 403)
	error = chess_game.recon_sense(room, color, (request.get_json(silent=True) or {}).get('square'))
	if error:
		return api_error(error)
	changed(room)
	return jsonify(chess_game.state(room, room['players'][color]['token']))


@app.route('/sitemap.xml')
def sitemap():
	'''List the home page, the only page worth indexing.'''

	return Response(f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>{public_root()}</loc></url></urlset>\n', mimetype='application/xml')


@app.route('/state')
@rooms_locked
def state():
	'''Return the room state for a player or spectator.'''

	room, color = get_room()
	if not room:
		return api_error('room not found', 404)
	if chess_game.check_flag(room):
		changed(room)
	return jsonify(chess_game.state(room, room['players'][color]['token'] if color else None))


@app.route('/user/<int:user_id>')
def user_profile(user_id: int):
	'''Return a player's profile and recent games.'''

	user = get_user(user_id)
	if not user:
		return api_error('user not found', 404)
	return jsonify({'user': user})


atexit.register(lambda: [save_room(rid, room) for rid, room in list(rooms.items())])
threading.Thread(target=ticker, daemon=True).start()
if arcade.enabled():
	threading.Thread(target=arcade_sync, daemon=True).start()
	threading.Thread(target=arcade_presence, daemon=True).start()



if __name__ == '__main__':
	app.run(host='127.0.0.1', port=20001, threaded=True)
