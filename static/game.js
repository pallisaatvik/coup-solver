'use strict';

let stateToken   = null;
let displayState = null;
let legalMoves   = [];
let lastLogLength = 0;

const CARD_COLORS = {
  Duke:       '#7b5ea7',
  Assassin:   '#c0392b',
  Captain:    '#2471a3',
  Ambassador: '#1e8449',
  Contessa:   '#d4ac0d',
};

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

async function startGame() {
  const res  = await fetch('/api/new', {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify({ seed: null }),
  });
  const data = await res.json();
  applyResponse(data);
  document.getElementById('start-screen').style.display = 'none';
  document.getElementById('game-screen').style.display  = 'flex';
  lastLogLength = 0;
  render();
}

async function submitMove(move) {
  setButtonsDisabled(true);
  const res  = await fetch('/api/move', {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify({ state_token: stateToken, move }),
  });
  const data = await res.json();
  applyResponse(data);
  render();
}

function applyResponse(data) {
  stateToken   = data.state_token;
  displayState = data.display;
  legalMoves   = data.legal_moves;
}

// ---------------------------------------------------------------------------
// Render
// ---------------------------------------------------------------------------

function render() {
  const s = displayState;
  renderPlayerArea(s.players[1], document.getElementById('bot-area'),   false);
  renderPlayerArea(s.players[0], document.getElementById('human-area'), true);
  renderLog(s.history);
  renderPrompt(s);
  renderButtons(s);
}

function renderPlayerArea(player, el, isHuman) {
  el.querySelector('.player-coins').textContent = `${player.coins} coins`;

  const influenceEl = el.querySelector('.player-influence');
  influenceEl.innerHTML = '';
  player.influence.forEach(card => {
    const div = document.createElement('div');
    div.className = 'card-badge';
    if (card === 'hidden') {
      div.textContent = '?';
      div.style.background = '#444';
    } else {
      div.textContent = card;
      div.style.background = CARD_COLORS[card] || '#555';
    }
    influenceEl.appendChild(div);
  });

  const revealedEl = el.querySelector('.player-revealed');
  revealedEl.innerHTML = '';
  player.revealed.forEach(card => {
    const div = document.createElement('div');
    div.className = 'card-badge revealed';
    div.textContent = card;
    div.style.background = '#555';
    revealedEl.appendChild(div);
  });
}

function renderLog(history) {
  const logEl = document.getElementById('game-log');
  for (let i = lastLogLength; i < history.length; i++) {
    const entry = history[i];
    const div   = document.createElement('div');
    div.className = `log-entry player-${entry.player}`;
    div.textContent = entry.desc;
    logEl.appendChild(div);
  }
  lastLogLength = history.length;
  logEl.scrollTop = logEl.scrollHeight;
}

function renderPrompt(s) {
  const el = document.getElementById('phase-prompt');
  if (s.phase === 'game_over') {
    const humanAlive = s.players[0].influence.length > 0;
    el.textContent = humanAlive ? 'You win!' : 'Bot wins!';
    el.className = humanAlive ? 'prompt win' : 'prompt lose';
    return;
  }
  el.className = 'prompt';
  if (s.current_decision_player === 1) {
    el.textContent = 'Bot is thinking...';
    return;
  }
  const prompts = {
    action_selection:    'Your turn — choose an action',
    await_challenge:     "Challenge the bot's claim?",
    await_block:         'Block the action?',
    await_block_challenge: "Challenge the bot's block?",
    lose_influence:      'Choose a card to lose',
    exchange_selection:  'Choose which cards to keep',
  };
  el.textContent = prompts[s.phase] || s.phase;
}

// ---------------------------------------------------------------------------
// Buttons
// ---------------------------------------------------------------------------

function renderButtons(s) {
  const container = document.getElementById('action-buttons');
  container.innerHTML = '';

  if (s.phase === 'game_over') {
    const btn = document.createElement('button');
    btn.textContent = 'Play Again';
    btn.className   = 'action-btn';
    btn.addEventListener('click', startGame);
    container.appendChild(btn);
    return;
  }

  if (s.current_decision_player !== 0 || !legalMoves.length) return;

  if (s.phase === 'lose_influence') {
    renderInfluencePicker(s, container);
    return;
  }

  if (s.phase === 'exchange_selection') {
    renderExchangePicker(s, container);
    return;
  }

  legalMoves.forEach(move => {
    const btn = document.createElement('button');
    btn.textContent = moveLabel(move, s);
    btn.className   = 'action-btn';
    btn.addEventListener('click', () => submitMove(move));
    container.appendChild(btn);
  });
}

function renderInfluencePicker(s, container) {
  const cards = s.players[0].influence;
  legalMoves.forEach(move => {
    const btn = document.createElement('button');
    const card = cards[move.card_index];
    btn.textContent = `Lose ${card}`;
    btn.className   = 'action-btn reveal-btn';
    btn.style.borderColor = CARD_COLORS[card] || '#888';
    btn.addEventListener('click', () => submitMove(move));
    container.appendChild(btn);
  });
}

function renderExchangePicker(s, container) {
  const hand    = s.players[0].influence;
  const drawn   = s.pending?.drawn_cards ?? [];
  const combined = [...hand, ...drawn];
  const nKeep   = hand.length;

  const heading = document.createElement('p');
  heading.textContent = `Pick ${nKeep} card${nKeep > 1 ? 's' : ''} to keep:`;
  heading.style.margin = '0 0 8px';
  container.appendChild(heading);

  const checkboxes = [];
  combined.forEach((card, idx) => {
    const label = document.createElement('label');
    label.className = 'card-checkbox';
    const cb = document.createElement('input');
    cb.type  = 'checkbox';
    cb.value = idx;
    const badge = document.createElement('span');
    badge.className = 'card-badge';
    badge.textContent = card;
    badge.style.background = CARD_COLORS[card] || '#555';
    label.appendChild(cb);
    label.appendChild(badge);
    container.appendChild(label);
    checkboxes.push(cb);
  });

  const confirmBtn = document.createElement('button');
  confirmBtn.textContent = 'Confirm';
  confirmBtn.className   = 'action-btn';
  confirmBtn.disabled    = true;
  confirmBtn.style.marginTop = '8px';

  checkboxes.forEach(cb => {
    cb.addEventListener('change', () => {
      const count = checkboxes.filter(c => c.checked).length;
      confirmBtn.disabled = count !== nKeep;
    });
  });

  confirmBtn.addEventListener('click', () => {
    const kept = checkboxes.filter(c => c.checked).map(c => parseInt(c.value)).sort((a, b) => a - b);
    const move = legalMoves.find(m =>
      m.keep_indices.length === kept.length &&
      m.keep_indices.every((v, i) => v === kept[i])
    );
    if (move) submitMove(move);
  });

  container.appendChild(confirmBtn);
}

function moveLabel(move, s) {
  const botName = s.players[1]?.name ?? 'Bot';
  const labels = {
    income:      'Income (+1 coin)',
    foreign_aid: 'Foreign Aid (+2 coins)',
    coup:        `Coup ${botName} (7 coins)`,
    tax:         'Tax — claim Duke (+3 coins)',
    assassinate: `Assassinate ${botName} — claim Assassin (3 coins)`,
    steal:       `Steal from ${botName} — claim Captain`,
    exchange:    'Exchange — claim Ambassador',
    challenge:   'Challenge',
    pass:        'Pass',
    block:       `Block with ${move.block_card}`,
  };
  return labels[move.move_type] ?? move.move_type;
}

// ---------------------------------------------------------------------------
// Utility
// ---------------------------------------------------------------------------

function setButtonsDisabled(disabled) {
  document.getElementById('action-buttons')
    .querySelectorAll('button, input')
    .forEach(el => { el.disabled = disabled; });
}

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------

document.getElementById('btn-new-game').addEventListener('click', startGame);
