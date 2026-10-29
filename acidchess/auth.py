#!/usr/bin/env python3
# acidchess - Developed by acidvegas in Python (https://github.com/acidvegas)
# acidchess/auth.py

import random
import re
import secrets
import threading
import time

from flask import request

from storage import DB_LOCK, db_connect


CAPTCHA_TTL    = 300
SESSION_TTL    = 30 * 24 * 60 * 60
CAPTCHAS       = {}
CAPTCHA_LOCK   = threading.Lock()
USERNAME_RE    = re.compile(r'^[A-Za-z0-9_]{3,16}$')
CAPTCHA_CHARS  = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789' # no I/O/0/1
CAPTCHA_COLORS = ['#ff7da0', '#ffae41', '#4dd17a', '#5fa8ff', '#b07dff', '#ffd86a', '#ff5e8a', '#7da0ff']


def captcha_create() -> dict:
	'''Create a captcha and return its id and SVG.'''

	cid  = secrets.token_urlsafe(12)
	text = ''.join(secrets.choice(CAPTCHA_CHARS) for _ in range(5))
	now  = time.time()
	with CAPTCHA_LOCK:
		for k in [k for k, (_, exp) in CAPTCHAS.items() if exp < now]:
			del CAPTCHAS[k]
		CAPTCHAS[cid] = (text, now + CAPTCHA_TTL)
	return {'captcha_id': cid, 'svg': captcha_render_svg(text)}


def captcha_render_svg(text: str) -> str:
	'''Render captcha text as a noisy SVG.'''

	w, h  = 220, 80
	parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}">', f'<rect width="{w}" height="{h}" fill="#1a1a28" rx="8"/>']
	for _ in range(8):
		parts.append(f'<line x1="{random.randint(0, w)}" y1="{random.randint(0, h)}" x2="{random.randint(0, w)}" y2="{random.randint(0, h)}" stroke="{random.choice(CAPTCHA_COLORS)}" stroke-opacity="0.18" stroke-width="1.5"/>')
	for _ in range(40):
		parts.append(f'<circle cx="{random.randint(0, w)}" cy="{random.randint(0, h)}" r="{random.uniform(0.6, 1.8):.1f}" fill="{random.choice(CAPTCHA_COLORS)}" fill-opacity="0.4"/>')
	slot = (w - 30) / len(text)
	for i, ch in enumerate(text):
		cx = 18 + slot * (i + 0.5) + random.uniform(-4, 4)
		cy = h / 2 + random.uniform(-6, 6)
		parts.append(f'<text x="{cx:.1f}" y="{cy:.1f}" font-family="Courier New, monospace" font-weight="{random.choice([700, 800, 900])}" font-size="{random.randint(30, 40)}" fill="{random.choice(CAPTCHA_COLORS)}" text-anchor="middle" dominant-baseline="middle" transform="rotate({random.uniform(-25, 25):.1f} {cx:.1f} {cy:.1f})">{ch}</text>')
	pts = ' '.join(f'{x},{h / 2 + random.uniform(-18, 18):.1f}' for x in range(0, w + 1, 12))
	parts.append(f'<polyline points="{pts}" stroke="{random.choice(CAPTCHA_COLORS)}" stroke-opacity="0.5" stroke-width="2" fill="none"/></svg>')
	return ''.join(parts)


def captcha_verify(cid: str, answer: str) -> bool:
	'''Check a captcha answer. Each captcha can only be tried once.'''

	if not cid or answer is None:
		return False
	with CAPTCHA_LOCK:
		rec = CAPTCHAS.pop(cid, None)
	if rec is None or time.time() > rec[1]:
		return False
	return str(answer).strip().upper() == rec[0]


def create_session(user_id: int) -> str:
	'''Create a login session and return its token.'''

	token = secrets.token_urlsafe(32)
	with DB_LOCK, db_connect() as c:
		c.execute('INSERT INTO sessions(token, user_id, expires_at) VALUES(?, ?, ?)', (token, user_id, int(time.time()) + SESSION_TTL))
	return token


def delete_session(token: str):
	'''Log a session out.'''

	with DB_LOCK, db_connect() as c:
		c.execute('DELETE FROM sessions WHERE token=?', (token,))


def request_token() -> str:
	'''Return the auth token sent with the current request.'''

	return request.headers.get('X-Auth-Token') or ''


def request_user() -> tuple:
	'''Return (user id, username) for the current request, or (None, None) for guests.'''

	token = request_token()
	if not token:
		return None, None
	with db_connect() as c:
		row = c.execute('SELECT u.id, u.username FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token=? AND s.expires_at > ?', (token, int(time.time()))).fetchone()
	return (row['id'], row['username']) if row else (None, None)
