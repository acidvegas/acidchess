// acidchess - Developed by acidvegas in Python (https://github.com/acidvegas)
// utils.js

'use strict';

const $  = (id) => document.getElementById(id);
const FILES = 'abcdefghijklmn';
const UCI_RE = /^([a-n]\d+)([a-n]\d+)([a-z]?)$/;
const DROP_RE = /^([A-Z])@([a-n]\d+)$/;
const FOUR = ['r', 'b', 'y', 'g'];
const FOUR_NAMES = { r: 'Red', b: 'Blue', y: 'Yellow', g: 'Green' };
const LEVEL_NAMES = ['Beginner', 'Novice', 'Casual', 'Club', 'Strong club', 'Expert', 'Master', 'Maximum'];
const REASONS = {
	'checkmate': 'by checkmate',
	'stalemate': 'by stalemate',
	'insufficient material': 'by insufficient material',
	'threefold repetition': 'by threefold repetition',
	'50-move rule': 'by the 50-move rule',
	'timeout': 'on time',
	'timeout vs insufficient material': 'timeout vs insufficient material',
	'resignation': 'by resignation',
	'agreement': 'by agreement',
	'aborted': 'game aborted',
	'abandoned': 'game abandoned',
	'king captured': 'by capturing the king',
	'king of the hill': 'by reaching the hill',
	'three-check': 'by three checks',
	'explosion': 'by blowing up the king',
};

let authToken  = localStorage.getItem('acidchess_auth') || '';
let me         = null;  // signed in user
let rid        = null;  // current room id
let ptoken     = null;  // player token for current room
let st         = null;  // last room state
let fetchedAt  = 0;     // when st arrived, for local clock ticking
let viewPly    = null;  // ply being viewed, null for live
let flipped    = false;
let selected   = null;  // selected square index
let drag       = null;
let events     = null;
let lastResult = null;
let flagPolled = 0;
let lobbyTimer = null;
let captchaId  = null;
let modeNames  = { classic: 'Classic' };
let swapNames  = {};
let senseHover = null;  // square under the pointer while choosing where to sense
let audio      = null;  // AudioContext, created on the first tap since browsers block sound before that
let unread     = 0;     // things that happened while the tab was in the background, shown in the title


// ---------- helpers ----------

async function api(path, body) {
	const headers = { 'X-Auth-Token': authToken };
	if (ptoken) headers['X-Player-Token'] = ptoken;
	const opts = { headers };
	if (body !== undefined) {
		opts.method = 'POST';
		headers['Content-Type'] = 'application/json';
		opts.body = JSON.stringify({ room_id: rid, player_token: ptoken, name: guestName(), ...body });
	}
	const res = await fetch(path, opts);
	const data = await res.json().catch(() => ({ error: 'bad response' }));
	if (!res.ok && !data.error) data.error = 'request failed';
	return data;
}

function icon(name) {
	return `<svg class="ico"><use href="#i-${name}"/></svg>`;
}

function esc(text) {
	const d = document.createElement('div');
	d.textContent = text == null ? '' : String(text);
	return d.innerHTML;
}

function fmtClock(ms) {
	const total = Math.max(0, ms);
	const s = Math.floor(total / 1000);
	const m = Math.floor(s / 60);
	const sec = String(s % 60).padStart(2, '0');
	if (total < 10000) return `${m}:${sec}.${Math.floor((total % 1000) / 100)}`;
	return `${m}:${sec}`;
}

function guestName() {
	return ($('guest-name').value || '').trim();
}

// Board size of the current game, 8x8 until a state arrives
function W() { return st ? st.width : 8; }
function H() { return st ? st.height : 8; }

function parseFen(fen) {
	const board = new Array(W() * H()).fill(null);
	// Drops games carry the hand in brackets and mark promoted pieces with ~, neither belongs on the board
	const rows = fen.split(' ')[0].split('[')[0].replace(/~/g, '').split('/');
	rows.forEach((row, i) => {
		const r = H() - 1 - i;
		let f = 0;
		for (const tok of row.match(/\d+|./g)) {
			if (/\d/.test(tok)) f += +tok;
			else board[r * W() + f++] = tok;
		}
	});
	return board;
}

function parseUci(uci) {
	const d = DROP_RE.exec(uci);
	if (d) return { from: -1, to: sqIndex(d[2]), drop: d[1] };
	const m = UCI_RE.exec(uci);
	return m ? { from: sqIndex(m[1]), to: sqIndex(m[2]), promo: m[3] } : null;
}

function pieceUrl(ch) {
	if (st && st.board4) return `/static/pieces/4/${ch}.svg`;
	const color = ch === ch.toUpperCase() ? 'w' : 'b';
	return `/static/pieces/${color}${ch.toUpperCase()}.svg`;
}

function sqName(i) { return FILES[i % W()] + (Math.floor(i / W()) + 1); }

function sqIndex(name) { return (parseInt(name.slice(1), 10) - 1) * W() + FILES.indexOf(name[0]); }

function toast(text) {
	const t = $('toast');
	t.textContent = text;
	t.classList.remove('hidden');
	clearTimeout(t._timer);
	t._timer = setTimeout(() => t.classList.add('hidden'), 2500);
}

function openModal(html) {
	$('modal-body').innerHTML = html;
	$('modal').classList.remove('hidden');
}

function closeModal() {
	$('modal').classList.add('hidden');
}

function openHelp(game) {
	// In a game, only show what applies to it: its mode, its twists and the new pieces on its board
	const m      = $('help-modal');
	const ctx    = game && st;
	const t      = ctx ? st.toggles || {} : {};
	const pieces = new Set(ctx ? (st.start_fen || '').split(' ')[0].toUpperCase() : []);
	if (t.bonus) ['A', 'C', 'M'].forEach((p) => pieces.add(p));
	m.querySelectorAll('[data-mode]').forEach((el) => el.hidden = ctx && !el.dataset.mode.split(' ').includes(st.mode));
	m.querySelectorAll('[data-twist]').forEach((el) => el.hidden = ctx && !t[el.dataset.twist]);
	m.querySelectorAll('[data-piece]').forEach((el) => el.hidden = ctx && !pieces.has(el.dataset.piece));
	m.querySelectorAll('[data-help]').forEach((sec) => sec.hidden = (ctx && sec.dataset.help === 'basics') || !sec.querySelector('li:not([hidden])'));
	$('help-all').classList.toggle('hidden', !ctx);
	m.querySelector('.modal').scrollTop = 0;
	m.classList.remove('hidden');
}


// ---------- account ----------

async function loadMe() {
	if (!authToken) { me = null; renderAccount(); return; }
	const data = await api('/auth/me');
	me = data.user || null;
	if (!me) { authToken = ''; localStorage.removeItem('acidchess_auth'); }
	renderAccount();
}

function renderAccount() {
	$('account-name').textContent = me ? `${me.username} (${me.ratings.classic ? me.ratings.classic.rating : 1200})` : 'Guest';
	$('btn-signin').classList.toggle('hidden', !!me);
	$('btn-profile').classList.toggle('hidden', !me);
	$('btn-logout').classList.toggle('hidden', !me);
	$('guest-name').classList.toggle('hidden', !!me);
}

async function showAuth(mode) {
	const signup = mode === 'signup';
	openModal(`
		<h2>${signup ? 'Create account' : 'Sign in'}</h2>
		<form id="auth-form">
			<input type="text" id="auth-user" placeholder="Username" maxlength="16" autocomplete="username" required>
			<input type="password" id="auth-pass" placeholder="Password" maxlength="128" autocomplete="${signup ? 'new-password' : 'current-password'}" required>
			${signup ? '<div class="captcha" id="captcha" title="Click for a new one"></div><input type="text" id="auth-captcha" placeholder="Captcha" maxlength="5" autocomplete="off" required>' : ''}
			<div class="error" id="auth-error"></div>
			<button class="btn primary" type="submit">${signup ? 'Sign up' : 'Sign in'}</button>
			<button class="link" type="button" id="auth-switch">${signup ? 'Have an account? Sign in' : 'New here? Create an account'}</button>
		</form>`);
	$('auth-switch').onclick = () => showAuth(signup ? 'login' : 'signup');
	if (signup) {
		await loadCaptcha();
		$('captcha').onclick = loadCaptcha;
	}
	$('auth-user').focus();
	$('auth-form').onsubmit = async (e) => {
		e.preventDefault();
		const body = { username: $('auth-user').value, password: $('auth-pass').value };
		if (signup) Object.assign(body, { captcha_id: captchaId, captcha: $('auth-captcha').value });
		const data = await api(signup ? '/auth/signup' : '/auth/login', body);
		if (data.error) {
			$('auth-error').textContent = data.error;
			if (signup) { $('auth-captcha').value = ''; loadCaptcha(); }
			return;
		}
		authToken = data.token;
		localStorage.setItem('acidchess_auth', authToken);
		closeModal();
		await loadMe();
	};
}

async function loadCaptcha() {
	const data = await api('/auth/captcha');
	captchaId = data.captcha_id;
	$('captcha').innerHTML = data.svg;
}

async function showProfile(userId) {
	const data = await api(`/user/${userId}`);
	const u = data.user;
	if (!u) return toast(data.error || 'not found');
	const recent = u.recent.map((g) => {
		const white = g.white_id === u.id;
		const res = g.result === '1/2-1/2' ? 'Draw' : (g.result === '1-0') === white ? 'Win' : 'Loss';
		return `<tr><td>${res}</td><td>vs ${esc(white ? g.black : g.white)}</td><td>${esc(modeNames[g.mode] || g.mode)}</td><td>${esc(g.tc || '∞')}</td><td>${g.rated ? 'Rated' : 'Casual'}</td></tr>`;
	}).join('');
	const ratings = Object.entries(u.ratings).map(([m, r]) => `<tr><td>${esc(modeNames[m] || m)}</td><td>${r.rating}</td><td>${r.peak_rating}</td><td>${r.wins}/${r.losses}/${r.draws}</td><td>${r.best_streak}</td></tr>`).join('');
	openModal(`
		<h2>${esc(u.username)}</h2>
		<h3>Ratings</h3>
		${ratings ? `<table class="list"><thead><tr><th>Mode</th><th>Rating</th><th>Peak</th><th>W/L/D</th><th>Best streak</th></tr></thead><tbody>${ratings}</tbody></table>` : '<p class="empty">No rated games yet. Everyone starts at 1200.</p>'}
		${u.bot.length ? `<h3>Vs computer</h3><table class="list"><thead><tr><th>Level</th><th>W</th><th>L</th><th>D</th></tr></thead><tbody>${u.bot.map((b) => `<tr><td>${b.level} · ${LEVEL_NAMES[b.level - 1]}</td><td>${b.wins}</td><td>${b.losses}</td><td>${b.draws}</td></tr>`).join('')}</tbody></table>` : ''}
		<h3>Recent games</h3>
		${recent ? `<table class="list"><tbody>${recent}</tbody></table>` : '<p class="empty">No games yet.</p>'}`);
}


// ---------- home ----------

function showHome() {
	rid = null; ptoken = null; st = null;
	if (events) { events.close(); events = null; }
	history.replaceState(null, '', '/');
	$('game').classList.add('hidden');
	$('home').classList.remove('hidden');
	document.title = 'acidchess';
	openTab(document.querySelector('.tab.active').dataset.tab);
}

function openTab(name) {
	document.querySelectorAll('.tab').forEach((t) => t.classList.toggle('active', t.dataset.tab === name));
	document.querySelectorAll('.tab-body').forEach((b) => b.classList.toggle('hidden', b.id !== `tab-${name}`));
	clearInterval(lobbyTimer);
	if (name === 'lobby') { loadLobby(); lobbyTimer = setInterval(loadLobby, 3000); }
	if (name === 'leaders') loadLeaders();
}

async function loadLobby() {
	if (rid) return clearInterval(lobbyTimer);
	const data = await api('/lobby');
	const rows = (data.rooms || []).map((r) => `
		<tr><td>${esc(r.name)}</td><td>${r.rating ?? '-'}</td><td>${esc(modeNames[r.mode] || r.mode)}${r.rated ? ' · Rated' : ''}${twistsText(r.toggles) ? `<br><small>${esc(twistsText(r.toggles))}</small>` : ''}</td><td>${esc(r.tc || '∞')}</td>
		<td><button class="btn small" data-join="${r.room_id}">${icon('enter')}${r.seats > 2 ? `Join ${r.seated}/${r.seats}` : 'Join'}</button></td></tr>`).join('');
	$('lobby-rows').innerHTML = rows;
	$('lobby-empty').classList.toggle('hidden', !!rows);
	$('lobby-rows').querySelectorAll('[data-join]').forEach((b) => b.onclick = () => joinRoom(b.dataset.join));
}

async function loadLeaders() {
	const data = await api(`/leaderboard?mode=${$('leader-mode').value || 'classic'}`);
	const rows = (data.players || []).map((p, i) => `
		<tr class="${me && me.id === p.id ? 'me' : ''}"><td>${i + 1}</td><td><button class="link" data-user="${p.id}">${esc(p.username)}</button></td><td>${p.rating}</td><td>${p.wins}/${p.losses}/${p.draws}</td></tr>`).join('');
	$('leader-rows').innerHTML = rows;
	$('leader-empty').classList.toggle('hidden', !!rows);
	$('leader-rows').querySelectorAll('[data-user]').forEach((b) => b.onclick = () => showProfile(b.dataset.user));
}

async function loadTimeControls() {
	const data = await api('/lobby');
	const tcs = data.time_controls || [];
	// Sent as [key, name] pairs so the order survives JSON
	modeNames = Object.fromEntries(data.modes || Object.entries(modeNames));
	swapNames = Object.fromEntries(data.swaps || []);
	$('swap-list').innerHTML = Object.entries(swapNames).map(([k, n]) => `<label class="check"><input type="checkbox" data-swap="${k}"> <span>${esc(n)}</span></label>`).join('');
	document.querySelectorAll('.mode-select').forEach((s) => s.innerHTML = Object.entries(modeNames).map(([k, n]) => `<option value="${k}">${esc(n)}</option>`).join(''));
	// Untimed first and selected, each timed option labelled with its speed
	$('quick-tc').innerHTML = '<option value="">Untimed</option>' + tcs.map((tc) => {
		const [m, inc] = tc.split('+').map(Number);
		const kind = m * 60 + inc * 40 < 180 ? 'Bullet' : m * 60 + inc * 40 < 480 ? 'Blitz' : m * 60 + inc * 40 < 1500 ? 'Rapid' : 'Classical';
		return `<option value="${tc}">${tc} · ${kind}</option>`;
	}).join('');
	$('create-tc').innerHTML = '<option value="">Untimed</option>' + tcs.map((tc) => `<option value="${tc}">${tc}</option>`).join('');
	$('create-tc').value = '';
	$('bot-tc').innerHTML = $('create-tc').innerHTML;
	$('bot-tc').value = '';
	$('level-grid').innerHTML = data.bot ? LEVEL_NAMES.map((n, i) => `<button class="btn" data-level="${i + 1}">${i + 1}<small>${n}</small></button>`).join('') : '';
	$('bot-missing').classList.toggle('hidden', !!data.bot);
	$('level-grid').querySelectorAll('[data-level]').forEach((b) => b.onclick = () => playComputer(+b.dataset.level));
}

async function playComputer(level) {
	const data = await api('/create', { bot: level, tc: $('bot-tc').value || null });
	if (data.error) return toast(data.error);
	enterRoom(data.room_id, data.player_token);
}

async function quickPlay() {
	const data = await api('/quickplay', { tc: $('quick-tc').value || null, rated: $('quick-rated').checked, mode: $('quick-mode').value });
	if (data.error) return toast(data.error);
	enterRoom(data.room_id, data.player_token);
}

async function createRoom() {
	const data = await api('/create', {
		mode: $('create-mode').value,
		toggles: chosenTwists(),
		tc: $('create-tc').value || null,
		public: $('create-public').checked,
		rated: $('create-rated').checked,
	});
	if (data.error) return toast(data.error);
	enterRoom(data.room_id, data.player_token);
}

function chosenTwists() {
	if ($('create-mode').value === 'recon') return {};
	const out = {};
	document.querySelectorAll('#create-twists [data-toggle]').forEach((c) => { if (c.checked) out[c.dataset.toggle] = true; });
	const swaps = [...document.querySelectorAll('#create-twists [data-swap]')].filter((c) => c.checked).map((c) => c.dataset.swap);
	if (swaps.length) out.swaps = swaps;
	return out;
}

function twistsText(t) {
	const parts = [];
	if (t.holes) parts.push('Holes');
	if (t.armies) parts.push('Random armies');
	if (t.koth) parts.push('King of the hill');
	if (t.threecheck) parts.push('Three-check');
	if (t.atomic) parts.push('Explosive');
	if (t.drops) parts.push('Drops');
	if (t.bonus) parts.push('Bonus squares');
	for (const s of t.swaps || []) parts.push(swapNames[s] || s);
	return parts.join(' · ');
}

async function joinRoom(code, watch) {
	code = (code || '').trim().toLowerCase();
	if (!code) return;
	rid = code;
	ptoken = localStorage.getItem(`acidchess_room_${code}`);
	if (ptoken && !watch) return enterRoom(code, ptoken);
	ptoken = null;
	const data = await api('/join', { watch: !!watch });
	if (data.error) { rid = null; toast(data.error); return showHome(); }
	enterRoom(data.room_id, data.player_token);
}


// ---------- game ----------

function enterRoom(roomId, token) {
	clearInterval(lobbyTimer);
	rid = roomId;
	ptoken = token || null;
	if (token) localStorage.setItem(`acidchess_room_${roomId}`, token);
	history.replaceState(null, '', `/${roomId}`);
	$('home').classList.add('hidden');
	$('game').classList.remove('hidden');
	st = null; viewPly = null; flipped = false; selected = null; lastResult = null;
	$('chat-log').innerHTML = '';
	if (events) events.close();
	events = new EventSource(`/events?room_id=${roomId}${ptoken ? '' : '&watch=1'}`);
	events.addEventListener('state', fetchState);
	events.addEventListener('error', () => { if (events && events.readyState === EventSource.CLOSED) setTimeout(fetchState, 2000); });
	fetchState();
}

async function fetchState() {
	if (!rid) return;
	const data = await api(`/state?room_id=${rid}`);
	if (data.error) { toast(data.error); return showHome(); }
	setState(data);
}

function setState(data) {
	const prev = st;
	const prevMoves = st ? st.moves.length : -1;
	// The chat is capped at 100 messages, so compare the newest message rather than the count
	const lastChat = (chat) => chat.length ? chat[chat.length - 1].at : 0;
	const chatChanged = !st || lastChat(st.chat) !== lastChat(data.chat);
	st = data;
	fetchedAt = performance.now();
	if (viewPly !== null && st.moves.length !== prevMoves) viewPly = null;
	if (st.moves.length !== prevMoves) selected = null;
	render();
	if (chatChanged) renderChat();
	if (prev && prev.id === st.id) announce(prev);
	if (st.result && lastResult === null && prevMoves !== -1) showResult();
	lastResult = st.result;
}

// ---------- sounds & notifications ----------

function soundOn() { return localStorage.getItem('acidchess_sound') !== 'off'; }

// Browsers only allow desktop notifications on HTTPS (or localhost)
function notifyAvailable() { return window.isSecureContext && 'Notification' in window; }

function notifyOn() { return localStorage.getItem('acidchess_notify') === 'on' && notifyAvailable() && Notification.permission === 'granted'; }

function tone(freq, start, length, type, volume, slide) {
	// One short synthesized note: freq in Hz, start and length in seconds from now
	const t = audio.currentTime + start;
	const osc = audio.createOscillator();
	const gain = audio.createGain();
	osc.type = type;
	osc.frequency.setValueAtTime(freq, t);
	if (slide) osc.frequency.exponentialRampToValueAtTime(slide, t + length);
	gain.gain.setValueAtTime(0.0001, t);
	gain.gain.exponentialRampToValueAtTime(volume, t + 0.008);
	gain.gain.exponentialRampToValueAtTime(0.0001, t + length);
	osc.connect(gain).connect(audio.destination);
	osc.start(t);
	osc.stop(t + length + 0.02);
}

function play(name) {
	if (!audio || !soundOn()) return;
	if (audio.state === 'suspended') audio.resume();
	const sounds = {
		move    : () => tone(420, 0, 0.09, 'triangle', 0.35, 260),
		capture : () => { tone(300, 0, 0.12, 'square', 0.18, 120); tone(620, 0.02, 0.08, 'triangle', 0.25, 300); },
		check   : () => { tone(660, 0, 0.12, 'sine', 0.3); tone(880, 0.11, 0.16, 'sine', 0.3); },
		start   : () => [523, 659, 784].forEach((f, i) => tone(f, i * 0.09, 0.18, 'sine', 0.25)),
		win     : () => [523, 659, 784, 1047].forEach((f, i) => tone(f, i * 0.1, 0.25, 'sine', 0.28)),
		lose    : () => [523, 440, 349].forEach((f, i) => tone(f, i * 0.14, 0.28, 'sine', 0.25)),
		draw    : () => [523, 523].forEach((f, i) => tone(f, i * 0.15, 0.2, 'sine', 0.22)),
		chat    : () => { tone(1320, 0, 0.07, 'sine', 0.18); tone(1760, 0.06, 0.09, 'sine', 0.14); },
	};
	sounds[name]();
}

function notify(title, body) {
	// While the tab is in the background: count it in the title, and pop a desktop notification if allowed
	if (!document.hidden) return;
	unread += 1;
	document.title = `(${unread}) ${title} · acidchess`;
	if (notifyOn()) {
		const n = new Notification(title, { body, icon: '/static/favicon.svg', tag: `acidchess-${st.id}` });
		n.onclick = () => { window.focus(); n.close(); };
	}
}

function announce(prev) {
	// Compare the previous state with the new one and play or notify whatever happened
	const mine = st.color;
	const name = (c) => st.players[c] ? st.players[c].name : 'Opponent';
	const seats = (s) => Object.values(s.players).every(Boolean);
	if (!seats(prev) && seats(st) && !st.result) {
		play('start');
		notify('Game started', 'Your opponent is here');
	}
	if (st.moves.length > prev.moves.length) {
		const san = st.moves[st.moves.length - 1].san || '';
		play(/[+#]/.test(san) ? 'check' : /x|@/.test(san) ? 'capture' : 'move');
		if (mine && st.turn === mine && !st.result) notify('Your move', `${name(st.moves[st.moves.length - 1].color || (mine === 'w' ? 'b' : 'w'))} played ${san}`);
	}
	if (st.result && !prev.result) {
		const won = mine && st.result !== '*' && (st.board4 ? st.result.includes(mine) : (st.result === '1-0') === (mine === 'w') && st.result !== '1/2-1/2');
		play(st.result === '1/2-1/2' || st.result === '*' ? 'draw' : !mine || won ? 'win' : 'lose');
		notify('Game over', $('status').textContent);
	}
	const last = st.chat[st.chat.length - 1];
	const prevLast = prev.chat[prev.chat.length - 1];
	if (last && (!prevLast || last.at !== prevLast.at) && last.color !== mine) {
		play('chat');
		notify(`${last.name} says`, last.text);
	}
}

function renderAlerts() {
	$('btn-sound').innerHTML = icon(soundOn() ? 'sound' : 'mute');
	$('btn-sound').classList.toggle('off', !soundOn());
	$('btn-notify').innerHTML = icon(notifyOn() ? 'bell' : 'bell-off');
	$('btn-notify').classList.toggle('off', !notifyOn());
	$('btn-notify').title = !notifyAvailable() ? 'Desktop notifications need the site on HTTPS' : notifyOn() ? 'Desktop notifications on' : 'Desktop notifications off';
}

function orientation() {
	const base = st && st.color === 'b' ? 'b' : 'w';
	return flipped ? (base === 'w' ? 'b' : 'w') : base;
}

function viewedFen() {
	if (viewPly === null || viewPly === st.moves.length) return st.fen;
	if (viewPly === 0) return st.start_fen;
	return st.moves[viewPly - 1].fen || st.fen;
}

function isLive() {
	return viewPly === null || viewPly === st.moves.length;
}

function render() {
	if (!st) return;
	document.title = `${unread ? `(${unread}) ` : ''}acidchess · ${st.id}`;
	$('room-code').textContent = st.id.toUpperCase();
	$('room-mode').innerHTML = esc(`${st.mode_name} · ${st.tc || 'Untimed'} · ${st.bot ? `vs computer ${st.bot}` : st.rated ? 'Rated' : 'Casual'}${twistsText(st.toggles) ? ` · ${twistsText(st.toggles)}` : ''}`) + (st.spectators ? ` · ${icon('eye')} ${st.spectators}` : '');
	renderBoard();
	renderBars();
	renderMoves();
	renderStatus();
	renderRecon();
}

// 4-player squares are drawn as if Red sits at the bottom, then turned a quarter turn per seat so your own army is at the bottom
function rotate4(sq, times) {
	for (let n = 0; n < times; n++) sq = (13 - (sq % 14)) * 14 + Math.floor(sq / 14);
	return sq;
}

function renderBoard4() {
	const b = st.board4;
	const turns = (FOUR.indexOf(st.color || 'r') + (flipped ? 2 : 0)) % 4;
	const last = st.moves.length ? parseUci(st.moves[st.moves.length - 1].uci) : null;
	const targets = selected !== null ? st.legal.map(parseUci).filter((m) => m && m.from === selected).map((m) => m.to) : [];
	const el = $('board');
	el.innerHTML = '';
	el.classList.remove('sensing');
	el.style.gridTemplateColumns = 'repeat(14, 1fr)';
	el.style.gridTemplateRows = 'repeat(14, 1fr)';
	document.documentElement.style.setProperty('--ratio', 1);
	for (let row = 0; row < 14; row++) {
		for (let col = 0; col < 14; col++) {
			const i = rotate4((13 - row) * 14 + col, turns);
			const f = i % 14;
			const r = Math.floor(i / 14);
			const sq = document.createElement('div');
			sq.dataset.sq = i;
			if (!st.valid[i]) { sq.className = 'sq void'; el.appendChild(sq); continue; }
			sq.className = `sq ${(r + f) % 2 ? 'light' : 'dark'}`;
			if (last && (i === last.from || i === last.to)) sq.classList.add('last');
			if (i === selected) sq.classList.add('sel');
			if (st.check && b[i] === st.turn + 'K') sq.classList.add('check');
			if (targets.includes(i)) sq.classList.add('move', b[i] ? 'cap' : 'none');
			if (b[i]) {
				const p = document.createElement('div');
				p.className = 'piece' + (st.alive.includes(b[i][0]) ? '' : ' dead');
				p.style.backgroundImage = `url(${pieceUrl(b[i])})`;
				sq.appendChild(p);
			}
			el.appendChild(sq);
		}
	}
}

function renderFourPlayers() {
	$('bar-top').classList.add('hidden');
	$('bar-bottom').classList.add('hidden');
	const list = $('four-players');
	list.classList.remove('hidden');
	list.innerHTML = FOUR.map((c) => {
		const p = st.players[c];
		const out = !st.alive.includes(c);
		const place = st.places ? st.places[c] : null;
		const diff = st.rating_diff && st.rating_diff[c] !== undefined ? ` ${st.rating_diff[c] >= 0 ? '+' : ''}${st.rating_diff[c]}` : '';
		const tag = place ? ['', '1st', '2nd', '3rd', '4th'][place] : out ? 'out' : '';
		return `<div class="fp${st.turn === c && !st.result ? ' turn' : ''}${out ? ' out' : ''}${c === st.color ? ' me' : ''}" data-color="${c}">
			<span class="dot ${c}"></span><span class="pname">${esc(p ? p.name : 'Waiting…')}</span>
			<span class="prating">${p && p.rating ? `(${p.rating}${diff})` : ''}</span>
			<span class="tag">${tag}</span><span class="clock"></span></div>`;
	}).join('');
	tickClocks();
}

function renderBoard() {
	if (st.board4) return renderBoard4();
	const board = parseFen(viewedFen());
	const white = orientation() === 'w';
	const live = isLive();
	const ply = viewPly === null ? st.moves.length : viewPly;
	const last = ply > 0 && st.moves[ply - 1].uci ? parseUci(st.moves[ply - 1].uci) : null;
	const turn = viewedFen().split(' ')[1];
	const inCheck = live ? st.check : (ply > 0 && /[+#]$/.test(st.moves[ply - 1].san));
	const king = turn === 'w' ? 'K' : 'k';
	// selected is a square index, or a piece letter picked from the hand
	const targets = live && selected !== null ? st.legal.map(parseUci).filter((m) => m && (typeof selected === 'string' ? m.drop === selected : m.from === selected)).map((m) => m.to) : [];
	const hill = st.hill || [];
	const ghosts = live && st.ghosts ? st.ghosts : {};
	// Players see this turn's sense window; spectators and finished games see the sense made before the shown move
	let sensed = live && st.sensed ? st.sensed : [];
	if (st.mode === 'recon' && (st.result || !st.color) && ply > 0 && st.moves[ply - 1].sense) sensed = senseWindow(sqIndex(st.moves[ply - 1].sense)).map(sqName);
	const hover = senseHover === null ? [] : senseWindow(senseHover);
	const el = $('board');
	el.innerHTML = '';
	el.classList.toggle('sensing', sensing());
	el.style.gridTemplateColumns = `repeat(${W()}, 1fr)`;
	el.style.gridTemplateRows = `repeat(${H()}, 1fr)`;
	document.documentElement.style.setProperty('--ratio', H() / W());
	for (let row = 0; row < H(); row++) {
		for (let col = 0; col < W(); col++) {
			const r = white ? H() - 1 - row : row;
			const f = white ? col : W() - 1 - col;
			const i = r * W() + f;
			const sq = document.createElement('div');
			sq.className = `sq ${(r + f) % 2 ? 'light' : 'dark'}`;
			sq.dataset.sq = i;
			if (board[i] === '*') sq.classList.add('wall');
			if (hill.includes(sqName(i))) sq.classList.add('hill');
			if (live && (st.stars || []).includes(sqName(i))) sq.insertAdjacentHTML('beforeend', '<span class="star">★</span>');
			if (last && (i === last.from || i === last.to)) sq.classList.add('last');
			if (i === selected) sq.classList.add('sel');
			if (inCheck && board[i] === king) sq.classList.add('check');
			if (targets.includes(i)) sq.classList.add('move', board[i] || (board[selected] || '').toLowerCase() === 'p' && i % W() !== selected % W() ? 'cap' : 'none');
			if (row === H() - 1) sq.insertAdjacentHTML('beforeend', `<span class="coord file">${FILES[f]}</span>`);
			if (col === 0) sq.insertAdjacentHTML('beforeend', `<span class="coord rank">${r + 1}</span>`);
			if (sensed.includes(sqName(i))) sq.classList.add('sensed');
			if (hover.includes(i)) sq.classList.add('sense-hover');
			if (board[i] && board[i] !== '*') {
				const p = document.createElement('div');
				p.className = 'piece';
				p.style.backgroundImage = `url(${pieceUrl(board[i])})`;
				sq.appendChild(p);
			} else if (ghosts[sqName(i)]) {
				// Reconnaissance Blind: where an enemy piece was last seen, faded, with how many turns ago
				const g = ghosts[sqName(i)];
				const p = document.createElement('div');
				p.className = g.piece === '?' ? 'piece ghost unknown' : 'piece ghost';
				if (g.piece === '?') p.textContent = '?';
				else p.style.backgroundImage = `url(${pieceUrl(g.piece)})`;
				sq.appendChild(p);
				if (g.age > 0) sq.insertAdjacentHTML('beforeend', `<span class="ghost-age">${g.age}</span>`);
			}
			el.appendChild(sq);
		}
	}
}

function renderBars() {
	if (st.board4) return renderFourPlayers();
	$('four-players').classList.add('hidden');
	$('bar-top').classList.remove('hidden');
	$('bar-bottom').classList.remove('hidden');
	const bottom = orientation();
	const top = bottom === 'w' ? 'b' : 'w';
	const board = parseFen(viewedFen());
	for (const [id, color] of [['bar-top', top], ['bar-bottom', bottom]]) {
		const bar = $(id);
		const p = st.players[color];
		bar.querySelector('.pname').textContent = p ? p.name : 'Waiting…';
		const diff = st.rating_diff && st.rating_diff[color] !== undefined ? ` ${st.rating_diff[color] >= 0 ? '+' : ''}${st.rating_diff[color]}` : '';
		bar.querySelector('.prating').textContent = p && p.rating ? `(${p.rating}${diff})` : '';
		// In Reconnaissance Blind the board only holds your own pieces until the game ends, so captures can't be counted from it
		const cap = bar.querySelector('.captured');
		cap.classList.toggle('hand', !!st.hand);
		cap.innerHTML = st.hand ? handHtml(color) : st.mode === 'recon' && !st.result ? '' : capturedHtml(board, color);
		bar.querySelector('.checks').textContent = st.checks ? '+'.repeat(st.checks.limit - st.checks[color]) : '';
		bar.querySelector('.checks').title = st.checks ? `${st.checks.limit - st.checks[color]} of ${st.checks.limit} checks given` : '';
	}
	tickClocks();
}

function handHtml(color) {
	const hand = st.hand[color] || {};
	return Object.entries(hand).map(([k, n]) => `<span class="slot${selected === k && st.color === color ? ' sel' : ''}" data-drop="${color === st.color ? k : ''}"><img src="${pieceUrl(color === 'w' ? k : k.toLowerCase())}" alt="">${n > 1 ? `<i>${n}</i>` : ''}</span>`).join('');
}

function capturedHtml(board, color) {
	// Pieces of the other color missing compared to the start position, i.e. what this side has captured
	const theirs = color === 'w' ? (c) => c === c.toLowerCase() : (c) => c === c.toUpperCase();
	const value = (c) => c.toUpperCase() === 'P' ? 1 : st.values[c.toUpperCase()] || 0;
	const count = {};
	const start = {};
	let material = 0;
	for (const c of board) {
		if (!c || c === '*' || c.toLowerCase() === 'k') continue;
		material += (c === c.toUpperCase()) === (color === 'w') ? value(c) : -value(c);
		if (theirs(c)) count[c.toLowerCase()] = (count[c.toLowerCase()] || 0) + 1;
	}
	for (const c of parseFen(st.start_fen)) if (c && c !== '*' && c.toLowerCase() !== 'k' && theirs(c)) start[c.toLowerCase()] = (start[c.toLowerCase()] || 0) + 1;
	let html = '';
	for (const k of Object.keys(start).sort((a, b) => value(a) - value(b))) {
		const missing = Math.max(0, start[k] - (count[k] || 0));
		const ch = color === 'w' ? k : k.toUpperCase();
		for (let n = 0; n < missing; n++) html += `<img src="${pieceUrl(ch)}" alt="">`;
	}
	return html + (material > 0 ? `<b>+${material}</b>` : '');
}

function tickClocks() {
	if (!st) return;
	if (st.board4) {
		for (const c of FOUR) {
			const el = document.querySelector(`#four-players [data-color="${c}"] .clock`);
			if (!el) continue;
			if (!st.clock) { el.textContent = ''; continue; }
			let ms = st.clock[c];
			const running = st.clock_running && !st.result && st.turn === c;
			if (running) ms -= performance.now() - fetchedAt;
			el.textContent = fmtClock(ms);
			el.classList.toggle('active', running);
			el.classList.toggle('low', running && ms < 20000);
			if (running && ms <= 0 && performance.now() - flagPolled > 1000) { flagPolled = performance.now(); fetchState(); }
		}
		return;
	}
	const bottom = orientation();
	for (const [id, color] of [['bar-top', bottom === 'w' ? 'b' : 'w'], ['bar-bottom', bottom]]) {
		const el = $(id).querySelector('.clock');
		if (!st.clock) { el.textContent = ''; continue; }
		let ms = st.clock[color];
		const running = st.clock_running && !st.result && st.turn === color;
		if (running) ms -= performance.now() - fetchedAt;
		el.textContent = fmtClock(ms);
		el.classList.toggle('active', running);
		el.classList.toggle('low', running && ms < 20000);
		// Ask the server to end the game once a clock hits zero
		if (running && ms <= 0 && performance.now() - flagPolled > 1000) { flagPolled = performance.now(); fetchState(); }
	}
}

function renderMoves() {
	const el = $('moves');
	const cur = viewPly === null ? st.moves.length : viewPly;
	let html = '';
	el.classList.toggle('four', !!st.board4);
	document.querySelector('.nav').classList.toggle('no-replay', !!st.board4);
	if (st.board4) {
		// One row per round, a column per player, with knock-outs listed after the move that caused them
		st.moves.forEach((m, i) => {
			if (i % 4 === 0) html += `<span class="num">${i / 4 + 1}.</span>`;
			html += `<span class="mv c4-${m.color}">${esc(m.san)}</span>`;
		});
		for (const e of st.events || []) html += `<span class="event">${esc(e.text)}</span>`;
		el.innerHTML = html;
		el.scrollTop = el.scrollHeight;
		return;
	}
	st.moves.forEach((m, i) => {
		if (i % 2 === 0) html += `<span class="num">${i / 2 + 1}.</span>`;
		html += `<span class="mv${i + 1 === cur ? ' cur' : ''}" data-ply="${i + 1}">${esc(m.san)}</span>`;
	});
	const atBottom = el.scrollTop + el.clientHeight >= el.scrollHeight - 30;
	el.innerHTML = html;
	el.querySelectorAll('.mv').forEach((m) => m.onclick = () => setView(+m.dataset.ply));
	if (atBottom || viewPly === null) el.scrollTop = el.scrollHeight;
}

function renderStatus() {
	const s = $('status');
	const mine = st.color;
	const playing = mine && !st.result;
	const opponent = mine ? st.players[mine === 'w' ? 'b' : 'w'] : null;
	s.className = 'status';
	if (st.board4) return renderStatusFour();
	if (st.result) {
		let text = st.result === '1/2-1/2' ? 'Draw' : st.result === '*' ? 'No result' : `${st.result === '1-0' ? 'White' : 'Black'} wins`;
		text += ` · ${REASONS[st.reason] || st.reason}`;
		s.textContent = text;
		if (mine && st.result !== '*' && st.result !== '1/2-1/2') s.classList.add((st.result === '1-0') === (mine === 'w') ? 'win' : 'loss');
	} else if (!st.players.w || !st.players.b) {
		s.textContent = 'Waiting for an opponent · share the link';
	} else if (st.mode === 'recon' && mine) {
		s.textContent = st.phase === 'sense' ? 'Sense: click a square to see the 3x3 around it' : st.phase === 'move' ? 'Move, or pass' : 'Opponent\'s turn';
	} else if (st.mode === 'recon') {
		s.textContent = `Watching ${st.delay} moves behind · ${st.turn === 'w' ? 'White' : 'Black'} to move`;
	} else if (mine) {
		s.textContent = st.turn === mine ? (st.check ? 'Your move · check!' : 'Your move') : st.bot ? 'Computer is thinking…' : 'Opponent to move';
	} else {
		s.textContent = `${st.turn === 'w' ? 'White' : 'Black'} to move`;
	}
	$('draw-offer').classList.toggle('hidden', !(playing && st.draw_offer && st.draw_offer !== mine));
	const canAbort = playing && st.moves.length < 2;
	$('btn-abort').classList.toggle('hidden', !canAbort);
	$('btn-abort').querySelector('.lbl').textContent = opponent ? 'Abort' : 'Cancel';
	$('btn-draw').classList.toggle('hidden', !playing || !opponent || canAbort || !!st.bot);
	$('btn-draw').disabled = st.draw_offer === mine;
	$('btn-draw').querySelector('.lbl').textContent = st.draw_offer === mine ? 'Draw offered' : 'Offer draw';
	$('btn-resign').classList.toggle('hidden', !playing || !opponent || canAbort);
	const canRematch = mine && st.result && opponent;
	$('btn-rematch').classList.toggle('hidden', !canRematch);
	if (canRematch) {
		const asked = st.rematch.includes(mine);
		const theyAsked = st.rematch.length && !asked;
		$('btn-rematch').disabled = asked;
		$('btn-rematch').querySelector('.lbl').textContent = st.bot ? 'Play again' : asked ? 'Rematch sent' : theyAsked ? 'Accept rematch' : 'Rematch';
	}
	$('chat-input').classList.toggle('hidden', !mine || !!st.bot);
	$('btn-pgn').classList.toggle('hidden', !st.pgn);
}

function renderStatusFour() {
	const s = $('status');
	const mine = st.color;
	const seated = FOUR.every((c) => st.players[c]);
	const playing = mine && !st.result && st.alive.includes(mine);
	s.className = 'status';
	if (st.result === '*') s.textContent = 'Game aborted';
	else if (st.result) {
		const winners = st.result.split('').map((c) => FOUR_NAMES[c]).join(' & ');
		s.textContent = `${winners} win${st.result.length > 1 ? '' : 's'} · ${REASONS[st.reason] || st.reason}`;
		if (mine) s.classList.add(st.result.includes(mine) ? 'win' : 'loss');
	} else if (!seated) {
		s.textContent = `Waiting for players · ${FOUR.filter((c) => st.players[c]).length}/4 · share the link`;
	} else if (mine && !st.alive.includes(mine)) {
		s.textContent = `You are out · ${FOUR_NAMES[st.turn]} to move`;
	} else if (mine && st.turn === mine) {
		s.textContent = st.check ? 'Your move · check!' : 'Your move';
	} else {
		s.textContent = `${FOUR_NAMES[st.turn]} to move`;
	}
	$('draw-offer').classList.add('hidden');
	const canAbort = playing && st.moves.length < 4;
	$('btn-abort').classList.toggle('hidden', !canAbort);
	$('btn-abort').querySelector('.lbl').textContent = seated ? 'Abort' : 'Cancel';
	$('btn-draw').classList.add('hidden');
	$('btn-resign').classList.toggle('hidden', !playing || !seated || canAbort);
	const canRematch = mine && st.result && seated;
	$('btn-rematch').classList.toggle('hidden', !canRematch);
	if (canRematch) {
		$('btn-rematch').disabled = st.rematch.includes(mine);
		$('btn-rematch').querySelector('.lbl').textContent = `Rematch ${st.rematch.length}/4`;
	}
	$('chat-input').classList.toggle('hidden', !mine);
	$('btn-pgn').classList.add('hidden');
}

function renderRecon() {
	const on = st.mode === 'recon' && st.color && !st.result;
	$('recon-bar').classList.toggle('hidden', !on || !st.phase);
	$('btn-skip-sense').classList.toggle('hidden', st.phase !== 'sense');
	$('btn-pass').classList.toggle('hidden', st.phase !== 'move');
	$('recon-hint').textContent = st.phase === 'sense' ? 'Your turn' : st.phase === 'move' ? 'Sensed' : '';
	const notes = st.mode === 'recon' && st.color ? st.notices || [] : [];
	$('notices').classList.toggle('hidden', !notes.length);
	// Notices from the last two plies are this turn's news
	$('notices').innerHTML = notes.slice(-8).map((n) => `<div class="${n.ply >= st.moves.length - 2 ? 'new' : ''}">${esc(n.text)}</div>`).join('');
	$('notices').scrollTop = $('notices').scrollHeight;
}

function sensing() {
	return st && st.mode === 'recon' && st.phase === 'sense' && isLive();
}

function senseWindow(i) {
	const f = i % W();
	const r = Math.floor(i / W());
	const out = [];
	for (let dr = -1; dr <= 1; dr++) for (let df = -1; df <= 1; df++) if (f + df >= 0 && f + df < W() && r + dr >= 0 && r + dr < H()) out.push((r + dr) * W() + f + df);
	return out;
}

async function sense(square) {
	senseHover = null;
	const data = await api('/sense', { square });
	if (data.error) return toast(data.error);
	setState(data);
}

function renderChat() {
	const log = $('chat-log');
	log.innerHTML = st.chat.map((c) => `<div><b class="${c.color}">${esc(c.name)}:</b> ${esc(c.text)}</div>`).join('');
	log.scrollTop = log.scrollHeight;
}

function showResult() {
	const mine = st.color;
	if (st.board4) {
		const place = mine && st.places ? st.places[mine] : null;
		const big = st.result === '*' ? 'Aborted' : !mine ? `${st.result.split('').map((c) => FOUR_NAMES[c]).join(' & ')} win` : st.result.includes(mine) ? 'You won!' : st.teams ? 'Your team lost' : `You finished ${['', '1st', '2nd', '3rd', '4th'][place]}`;
		const diff = mine && st.rating_diff && st.rating_diff[mine] !== undefined ? `<p class="result-sub">Rating ${st.rating_diff[mine] >= 0 ? '+' : ''}${st.rating_diff[mine]}</p>` : '';
		const lost = mine && st.result !== '*' && !st.result.includes(mine);
		openModal(`<div class="result-icon${lost ? ' loss' : ''}">${icon(st.result === '*' ? 'x' : lost ? 'flag' : 'crown')}</div><div class="result-big">${big}</div><p class="result-sub">${esc(REASONS[st.reason] || st.reason)}</p>${diff}
			<div class="row">${mine && st.result !== '*' ? `<button class="btn primary" id="res-rematch">${icon('rematch')}Rematch</button>` : ''}<button class="btn" id="res-home">${icon('home')}Home</button></div>`);
		if ($('res-rematch')) $('res-rematch').onclick = () => { closeModal(); action('/rematch'); };
		$('res-home').onclick = () => { closeModal(); showHome(); };
		return;
	}
	let big = st.result === '1/2-1/2' ? 'Draw' : st.result === '*' ? 'Aborted' : `${st.result === '1-0' ? 'White' : 'Black'} wins`;
	if (mine && (st.result === '1-0' || st.result === '0-1')) big = (st.result === '1-0') === (mine === 'w') ? 'You won!' : 'You lost';
	const diff = mine && st.rating_diff && st.rating_diff[mine] !== undefined ? `<p class="result-sub">Rating ${st.rating_diff[mine] >= 0 ? '+' : ''}${st.rating_diff[mine]}</p>` : '';
	openModal(`
		<div class="result-icon${big === 'You lost' ? ' loss' : ''}">${icon(st.result === '*' ? 'x' : big === 'You lost' ? 'flag' : st.result === '1/2-1/2' ? 'scale' : 'crown')}</div>
		<div class="result-big">${big}</div>
		<p class="result-sub">${esc(REASONS[st.reason] || st.reason)}</p>
		${diff}
		<div class="row">
			${mine && st.result !== '*' ? `<button class="btn primary" id="res-rematch">${icon('rematch')}${st.bot ? 'Play again' : 'Rematch'}</button>` : ''}
			<button class="btn" id="res-home">${icon('home')}Home</button>
		</div>`);
	if ($('res-rematch')) $('res-rematch').onclick = () => { closeModal(); action('/rematch'); };
	$('res-home').onclick = () => { closeModal(); showHome(); };
}

function setView(ply) {
	// A Reconnaissance Blind player can't replay a game in progress, the past positions would show the enemy. 4-player has no replay yet
	if (!st || st.board4 || (st.mode === 'recon' && st.color && !st.result)) return;
	ply = Math.max(0, Math.min(st.moves.length, ply));
	viewPly = ply === st.moves.length ? null : ply;
	selected = null;
	renderBoard();
	renderBars();
	renderMoves();
}

async function action(path, body) {
	const data = await api(path, body || {});
	if (data.error) toast(data.error);
	else if (path === '/abort' && st && !st.players[st.color === 'w' ? 'b' : 'w']) showHome();
}


// ---------- moving pieces ----------

function legalFrom(from, to) {
	return st.legal.filter((u) => { const m = parseUci(u); return m && (typeof from === 'string' ? m.drop === from : m.from === from) && m.to === to; });
}

function canMove() {
	return st && st.color && st.turn === st.color && !st.result && isLive() && st.legal.length;
}

function ownPiece(i) {
	if (st.board4) return !!st.board4[i] && st.board4[i][0] === st.color;
	const p = parseFen(st.fen)[i];
	return p && (p === p.toUpperCase()) === (st.color === 'w');
}

async function tryMove(from, to) {
	const moves = legalFrom(from, to);
	if (!moves.length) return false;
	if (moves.length > 1) {
		choosePromotion(from, to, moves.map((u) => parseUci(u).promo));
		return true;
	}
	sendMove(moves[0]);
	return true;
}

function choosePromotion(from, to, options) {
	const box = $('promotion');
	const color = st.color;
	const art = (k) => st.board4 ? pieceUrl(color + k.toUpperCase()) : pieceUrl(color === 'w' ? k.toUpperCase() : k);
	box.innerHTML = options.map((k) => `<button data-p="${k}" style="background-image:url(${art(k)})"></button>`).join('');
	box.classList.remove('hidden');
	box.querySelectorAll('button').forEach((b) => b.onclick = (e) => {
		e.stopPropagation();
		box.classList.add('hidden');
		sendMove(sqName(from) + sqName(to) + b.dataset.p);
	});
	box.onclick = () => { box.classList.add('hidden'); selected = null; renderBoard(); };
}

async function sendMove(uci) {
	// Show the move straight away, the server reply replaces it
	const m = parseUci(uci);
	const from = m ? $('board').querySelector(`[data-sq="${m.from}"] .piece`) : null;
	const to = m ? $('board').querySelector(`[data-sq="${m.to}"]`) : null;
	if (from && to) { to.querySelector('.piece')?.remove(); to.appendChild(from); }
	selected = null;
	st.legal = [];
	const data = await api('/move', { uci });
	if (data.error) { toast(data.error); return fetchState(); }
	setState(data);
}

function squareAt(x, y) {
	const el = document.elementFromPoint(x, y);
	const sq = el && el.closest('.sq');
	return sq ? +sq.dataset.sq : null;
}

function onPointerDown(e) {
	if (!st || e.button > 0) return;
	const sqEl = e.target.closest('.sq');
	if (!sqEl) return;
	const i = +sqEl.dataset.sq;
	if (sensing()) return sense(sqName(i));
	if (!canMove()) return;
	if (typeof selected === 'string') {
		// A piece from the hand is waiting for a square
		const drop = legalFrom(selected, i);
		selected = null;
		if (drop.length) return sendMove(drop[0]);
		renderBoard(); renderBars();
	}
	if (selected !== null && selected !== i && legalFrom(selected, i).length) {
		const from = selected;
		selected = null;
		tryMove(from, i);
		return;
	}
	if (!ownPiece(i)) { selected = null; renderBoard(); return; }
	const reselect = selected === i;
	selected = i;
	renderBoard();
	const piece = $('board').querySelector(`[data-sq="${i}"] .piece`);
	if (!piece) return;
	const rect = piece.getBoundingClientRect();
	drag = { from: i, piece, reselect, startX: e.clientX, startY: e.clientY, w: rect.width, moved: false, over: null };
	piece.classList.add('drag');
	$('board').setPointerCapture(e.pointerId);
	e.preventDefault();
}

function onPointerMove(e) {
	if (sensing()) {
		const over = squareAt(e.clientX, e.clientY);
		if (over !== senseHover) { senseHover = over; renderBoard(); }
		return;
	}
	if (!drag) return;
	const dx = e.clientX - drag.startX;
	const dy = e.clientY - drag.startY;
	if (Math.abs(dx) + Math.abs(dy) > 3) drag.moved = true;
	drag.piece.style.transform = `translate(${dx}px, ${dy}px)`;
	const over = squareAt(e.clientX, e.clientY);
	if (over !== drag.over) {
		$('board').querySelectorAll('.hover').forEach((s) => s.classList.remove('hover'));
		if (over !== null && legalFrom(drag.from, over).length) $('board').querySelector(`[data-sq="${over}"]`).classList.add('hover');
		drag.over = over;
	}
}

function onPointerUp(e) {
	if (!drag) return;
	const d = drag;
	drag = null;
	d.piece.classList.remove('drag');
	d.piece.style.transform = '';
	$('board').querySelectorAll('.hover').forEach((s) => s.classList.remove('hover'));
	const to = squareAt(e.clientX, e.clientY);
	if (d.moved && to !== null && to !== d.from && legalFrom(d.from, to).length) {
		selected = null;
		tryMove(d.from, to);
		return;
	}
	// A plain click on an already selected piece deselects it
	if (!d.moved && d.reselect) { selected = null; renderBoard(); }
}


// ---------- wiring ----------

function init() {
	$('guest-name').value = localStorage.getItem('acidchess_name') || '';
	$('guest-name').oninput = () => localStorage.setItem('acidchess_name', guestName());
	document.querySelectorAll('.tab').forEach((t) => t.onclick = () => openTab(t.dataset.tab));
	$('btn-join').onclick = () => joinRoom($('join-code').value);
	$('join-code').onkeydown = (e) => { if (e.key === 'Enter') joinRoom($('join-code').value); };
	$('btn-create').onclick = createRoom;
	$('btn-quick').onclick = quickPlay;
	$('btn-signin').onclick = () => showAuth('login');
	$('btn-profile').onclick = () => showProfile(me.id);
	$('btn-logout').onclick = async () => { await api('/auth/logout', {}); authToken = ''; localStorage.removeItem('acidchess_auth'); me = null; renderAccount(); };
	$('modal-close').onclick = closeModal;
	$('modal').onclick = (e) => { if (e.target === $('modal')) closeModal(); };
	const closeHelp = () => $('help-modal').classList.add('hidden');
	$('btn-help').onclick = () => openHelp(false);
	$('btn-game-help').onclick = () => openHelp(true);
	$('help-all').onclick = () => openHelp(false);
	$('help-close').onclick = closeHelp;
	$('help-modal').onclick = (e) => { if (e.target === $('help-modal')) closeHelp(); };

	$('board').addEventListener('pointerdown', onPointerDown);
	$('board').addEventListener('pointermove', onPointerMove);
	$('board').addEventListener('pointerup', onPointerUp);
	$('board').addEventListener('pointercancel', onPointerUp);
	$('board').addEventListener('contextmenu', (e) => e.preventDefault());
	$('board').addEventListener('pointerleave', () => { if (senseHover !== null) { senseHover = null; renderBoard(); } });
	$('btn-skip-sense').onclick = () => sense(null);
	// Clicking a piece in your hand picks it for dropping
	for (const id of ['bar-top', 'bar-bottom']) $(id).addEventListener('click', (e) => {
		const slot = e.target.closest('[data-drop]');
		if (!slot || !slot.dataset.drop || !canMove()) return;
		selected = selected === slot.dataset.drop ? null : slot.dataset.drop;
		renderBoard(); renderBars();
	});
	$('btn-pass').onclick = () => sendMove('pass');
	$('leader-mode').onchange = loadLeaders;
	// Twists don't exist for Reconnaissance Blind yet, and twisted games are never rated
	const syncTwists = () => {
		const four = ['four', 'teams'].includes($('create-mode').value);
		$('btn-twists').classList.toggle('hidden', $('create-mode').value === 'recon' || four);
		const count = Object.values(chosenTwists()).flat().length;
		$('twist-count').textContent = count ? count : '';
		const twisted = Object.keys(chosenTwists()).length > 0;
		// Explosions and drops don't combine
		const atomic = document.querySelector('[data-toggle=atomic]');
		const drops = document.querySelector('[data-toggle=drops]');
		drops.disabled = atomic.checked;
		atomic.disabled = drops.checked;
		$('create-rated').disabled = twisted;
		if (twisted) $('create-rated').checked = false;
	};
	$('create-mode').addEventListener('change', syncTwists);
	$('create-twists').addEventListener('change', syncTwists);
	const closeTwists = () => $('twists-modal').classList.add('hidden');
	$('btn-twists').onclick = () => $('twists-modal').classList.remove('hidden');
	$('twists-done').onclick = closeTwists;
	$('twists-close').onclick = closeTwists;
	$('twists-modal').onclick = (e) => { if (e.target === $('twists-modal')) closeTwists(); };

	document.querySelectorAll('[data-nav]').forEach((b) => b.onclick = () => {
		if (!st) return;
		const cur = viewPly === null ? st.moves.length : viewPly;
		setView({ first: 0, prev: cur - 1, next: cur + 1, last: st.moves.length }[b.dataset.nav]);
	});
	document.addEventListener('keydown', (e) => {
		if (!st || e.target.tagName === 'INPUT') return;
		const cur = viewPly === null ? st.moves.length : viewPly;
		if (e.key === 'ArrowLeft') setView(cur - 1);
		if (e.key === 'ArrowRight') setView(cur + 1);
		if (e.key === 'ArrowUp') setView(0);
		if (e.key === 'ArrowDown') setView(st.moves.length);
		if (e.key === 'f') { flipped = !flipped; render(); }
	});
	$('btn-flip').onclick = () => { flipped = !flipped; render(); };
	$('btn-abort').onclick = () => action('/abort');
	$('btn-draw').onclick = () => action('/draw', { action: 'offer' });
	$('btn-draw-accept').onclick = () => action('/draw', { action: 'accept' });
	$('btn-draw-decline').onclick = () => action('/draw', { action: 'decline' });
	$('btn-rematch').onclick = () => action('/rematch');
	$('btn-resign').onclick = () => {
		if ($('btn-resign').dataset.confirm) { delete $('btn-resign').dataset.confirm; $('btn-resign').querySelector('.lbl').textContent = 'Resign'; return action('/resign'); }
		$('btn-resign').dataset.confirm = '1';
		$('btn-resign').querySelector('.lbl').textContent = 'Confirm?';
		setTimeout(() => { delete $('btn-resign').dataset.confirm; $('btn-resign').querySelector('.lbl').textContent = 'Resign'; }, 3000);
	};
	$('btn-pgn').onclick = () => navigator.clipboard.writeText(st.pgn).then(() => toast('PGN copied'), () => toast('copy failed'));
	$('btn-copy-link').onclick = () => navigator.clipboard.writeText(location.href).then(() => toast('Link copied'), () => toast('copy failed'));
	$('chat-input').onkeydown = async (e) => {
		if (e.key !== 'Enter' || !e.target.value.trim()) return;
		const data = await api('/chat', { text: e.target.value });
		if (data.error) return toast(data.error);
		e.target.value = '';
	};

	// Browsers only allow sound after the page has been tapped or clicked
	document.addEventListener('pointerdown', () => { if (!audio) audio = new (window.AudioContext || window.webkitAudioContext)(); }, { once: true });
	document.addEventListener('visibilitychange', () => { if (!document.hidden && unread) { unread = 0; render(); } });
	$('btn-sound').onclick = () => { localStorage.setItem('acidchess_sound', soundOn() ? 'off' : 'on'); renderAlerts(); play('move'); };
	$('btn-notify').onclick = async () => {
		if (!notifyAvailable()) return toast('Desktop notifications need the site on HTTPS');
		if (notifyOn()) localStorage.setItem('acidchess_notify', 'off');
		else if ((await Notification.requestPermission()) === 'granted') localStorage.setItem('acidchess_notify', 'on');
		else toast('Notifications are blocked for this site in your browser');
		renderAlerts();
	};
	renderAlerts();
	setInterval(tickClocks, 100);
	setInterval(() => { if (rid) fetchState(); }, 15000);
	loadMe();
	loadTimeControls();

	const path = location.pathname.replace(/^\/+|\/+$/g, '');
	if (/^[a-z0-9]{4}$/i.test(path)) joinRoom(path, new URLSearchParams(location.search).has('watch'));
	else showHome();
}

init();
