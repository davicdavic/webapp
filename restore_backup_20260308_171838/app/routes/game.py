"""
Game Routes
Game center with Emperor's Circle and other games
"""
import time
import uuid
from threading import Lock
from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required, current_user
from app.models import GameScore, User, EmperorMatchStat
from app.extensions import db

game_bp = Blueprint('game', __name__)

ALLOWED_BETS = {1000, 5000, 10000, 30000, 50000, 100000}
ROUND_SECONDS = 240
REMATCH_WINDOW_SECONDS = 60
VALID_CARDS = {'king', 'people', 'slave'}

# In-memory game state.
stake_queues = {bet: [] for bet in ALLOWED_BETS}  # bet -> [user_id]
user_queue_bet = {}  # user_id -> bet
active_rooms = {}  # room_id -> room data
user_room = {}  # user_id -> room_id
# track when each player last polled/acted; helps detect lost connections
INACTIVITY_TIMEOUT = 30  # seconds before we consider a player disconnected
state_lock = Lock()


def _cleanup_room(room_id):
    room = active_rooms.pop(room_id, None)
    if not room:
        return
    for uid in room['players']:
        if user_room.get(uid) == room_id:
            user_room.pop(uid, None)


def _remove_from_queue(user_id):
    bet = user_queue_bet.pop(user_id, None)
    if bet is not None:
        stake_queues[bet] = [uid for uid in stake_queues[bet] if uid != user_id]


def _get_room_for_user(user_id):
    room_id = user_room.get(user_id)
    if not room_id:
        return None, None
    room = active_rooms.get(room_id)
    if not room:
        user_room.pop(user_id, None)
        return None, None
    return room_id, room


def _other_player(room, user_id):
    return room['players'][0] if room['players'][1] == user_id else room['players'][1]


def _compare_cards(card_a, card_b):
    if card_a == card_b:
        return 0
    beats = {'king': 'people', 'people': 'slave', 'slave': 'king'}
    return 1 if beats[card_a] == card_b else -1


def _get_or_create_match_stat(user_id):
    stat = EmperorMatchStat.query.filter_by(user_id=user_id).first()
    if not stat:
        stat = EmperorMatchStat(user_id=user_id, matches_played=0, matches_won=0, total_winnings=0)
        db.session.add(stat)
    return stat


def _record_match_stats(room, result):
    uid_a, uid_b = room['players']
    stat_a = _get_or_create_match_stat(uid_a)
    stat_b = _get_or_create_match_stat(uid_b)
    stat_a.matches_played += 1
    stat_b.matches_played += 1

    winner_id = result.get('winner_id')
    if winner_id == uid_a:
        stat_a.matches_won += 1
        stat_a.total_winnings += room['pot']
    elif winner_id == uid_b:
        stat_b.matches_won += 1
        stat_b.total_winnings += room['pot']


def _check_inactivity(room):
    """Terminate room if one player hasn\'t been seen for too long."""
    now = time.time()
    last = room.get('last_seen', {})
    for uid in room['players']:
        if now - last.get(uid, 0) > INACTIVITY_TIMEOUT:
            # mark other player as winner by abandonment, refund if before round
            other = _other_player(room, uid)
            if room.get('status') == 'active' and not room.get('result'):
                # refund bets
                for pid in room['players']:
                    u = User.query.get(pid)
                    if u:
                        u.coins += room['bet']
                db.session.commit()
            room['status'] = 'terminated'
            room['termination_message'] = 'Opponent disconnected.'
            return True
    return False


def _resolve_room_if_needed(room):
    # Check if rematch is confirmed and delay has passed
    confirmed_at = room.get('rematch_confirmed_at')
    if confirmed_at:
        if time.time() - confirmed_at >= 4:
            # Start the rematch
            uid_a, uid_b = room['players']
            user_a = User.query.get(uid_a)
            user_b = User.query.get(uid_b)
            if not user_a or not user_b:
                room['status'] = 'terminated'
                room['termination_message'] = 'Player data missing. Room closed.'
                return
            if user_a.coins < room['bet'] or user_b.coins < room['bet']:
                room['rematch_requests'] = set()
                room['rematch_started_at'] = None
                room['rematch_confirmed_at'] = None
                return  # Insufficient balance, don't start
            user_a.coins -= room['bet']
            user_b.coins -= room['bet']
            db.session.commit()
            room['round'] += 1
            room['pot'] = room['bet'] * 2
            room['selections'] = {}
            room['deadline'] = time.time() + ROUND_SECONDS
            room['result'] = None
            room['status'] = 'active'
            room['rematch_requests'] = set()
            room['rematch_started_at'] = None
            room['rematch_expired_at'] = None
            room['rematch_confirmed_at'] = None
        return  # Wait for delay or just started

    # check for inactivity first
    if _check_inactivity(room):
        return
    if room.get('result') or room.get('status') != 'active':
        return

    selections = room['selections']
    if len(selections) < 2 and time.time() < room['deadline']:
        return

    uid_a, uid_b = room['players']
    card_a = selections.get(uid_a)
    card_b = selections.get(uid_b)
    user_a = User.query.get(uid_a)
    user_b = User.query.get(uid_b)
    if not user_a or not user_b:
        room['status'] = 'terminated'
        room['termination_message'] = 'Game data invalid. Room closed.'
        return

    if card_a and card_b:
        cmp_result = _compare_cards(card_a, card_b)
        if cmp_result == 0:
            user_a.coins += room['bet']
            user_b.coins += room['bet']
            result = {
                'kind': 'draw',
                'winner_id': None,
                'loser_id': None,
                'payout': room['bet'],  # Each player gets their bet back (1000)
                'cards': {uid_a: card_a, uid_b: card_b},
                'outcomes': {uid_a: 'draw', uid_b: 'draw'}
            }
        else:
            winner_id = uid_a if cmp_result > 0 else uid_b
            loser_id = uid_b if winner_id == uid_a else uid_a
            winner = user_a if winner_id == uid_a else user_b
            winner.coins += room['pot']
            result = {
                'kind': 'win',
                'winner_id': winner_id,
                'loser_id': loser_id,
                'payout': room['pot'],  # Winner gets 2000, loser gets 0
                'cards': {uid_a: card_a, uid_b: card_b},
                'outcomes': {winner_id: 'win', loser_id: 'lose'}
            }
    else:
        # Selection timeout behavior: if both cards were not submitted in time,
        # treat the round as draw and refund each player's own bet.
        user_a.coins += room['bet']
        user_b.coins += room['bet']
        result = {
            'kind': 'draw_timeout',
            'winner_id': None,
            'loser_id': None,
            'payout': room['bet'],
            'cards': {uid_a: None, uid_b: None},
            'outcomes': {uid_a: 'draw', uid_b: 'draw'}
        }

    _record_match_stats(room, result)
    db.session.commit()
    room['result'] = result
    room['status'] = 'finished'
    room['resolved_at'] = int(time.time())
    room['rematch_requests'] = set()
    room['rematch_started_at'] = None
    room['rematch_expired_at'] = None


def _expire_rematch_if_needed(room):
    started = room.get('rematch_started_at')
    if not started or not room.get('rematch_requests'):
        return
    if time.time() - started > REMATCH_WINDOW_SECONDS:
        room['rematch_requests'] = set()
        room['rematch_started_at'] = None
        room['rematch_expired_at'] = int(time.time())


def _room_payload(user_id, room):
    # update last-seen for heartbeat
    room.setdefault('last_seen', {})[user_id] = time.time()
    opp_id = _other_player(room, user_id)
    opp_user = User.query.get(opp_id)
    me = User.query.get(user_id)

    payload = {
        'room_id': room['id'],
        'bet': room['bet'],
        'pot': room['pot'],
        'round': room['round'],
        'opponent_name': opp_user.username if opp_user else 'Unknown',
        'balance': me.coins if me else 0
    }

    if room.get('status') == 'terminated':
        payload.update({
            'status': 'opponent_left',
            'message': room.get('termination_message', 'Opponent left the game.')
        })
        return payload

    if room.get('rematch_confirmed_at'):
        elapsed = time.time() - room['rematch_confirmed_at']
        if elapsed < 4:
            payload.update({
                'status': 'waiting_rematch_start',
                'seconds_left': max(0, 4 - elapsed),
                'message': 'Both players confirmed. Starting match in...'
            })
            return payload

    if room.get('result'):
        requests = room.get('rematch_requests') or set()
        if requests:
            started = room.get('rematch_started_at') or int(time.time())
            payload.update({
                'status': 'waiting_rematch',
                'rematch_seconds_left': max(0, REMATCH_WINDOW_SECONDS - int(time.time() - started)),
                'rematch_requested_by_you': user_id in requests,
                'rematch_ready_count': len(requests),
                'message': 'Waiting for both players to confirm rematch.'
            })
            return payload

        if room.get('rematch_expired_at'):
            payload.update({
                'status': 'rematch_expired',
                'message': 'Rematch expired. Both players must press Rematch within 60 seconds.'
            })
            return payload

        result = room['result']
        payload.update({
            'status': 'result',
            'outcome': result['outcomes'].get(user_id, 'draw'),
            'your_card': result['cards'].get(user_id),
            'opponent_card': result['cards'].get(opp_id),
            'winner_id': result.get('winner_id'),
            'payout': result.get('payout', 0),
            'result_kind': result.get('kind', 'win'),
            'resolved_at': room.get('resolved_at')
        })
        return payload

    payload.update({
        'status': 'matched',
        'time_left': max(0, int(room['deadline'] - time.time())),
        'your_selected': user_id in room['selections'],
        'opponent_selected': opp_id in room['selections']
    })
    return payload


@game_bp.route('/')
@login_required
def index():
    """Game center home"""
    # Get user's game scores
    user_scores = GameScore.query.filter_by(user_id=current_user.id)\
        .order_by(GameScore.score.desc()).all()
    
    # Get leaderboard
    leaderboard = GameScore.query.order_by(GameScore.score.desc()).limit(10).all()
    
    return render_template('game/index.html',
                         user_scores=user_scores,
                         leaderboard=leaderboard)


@game_bp.route('/emperors-circle')
@login_required
def emperors_circle():
    """Emperor's Circle game"""
    # Get user's best score
    best_score = GameScore.query.filter_by(
        user_id=current_user.id,
        game_id='emperors_circle'
    ).first()
    
    # Top players by match wins and total winnings.
    top_players = EmperorMatchStat.query\
        .order_by(EmperorMatchStat.matches_won.desc(), EmperorMatchStat.total_winnings.desc())\
        .limit(10).all()
    
    return render_template('game/emperors_circle.html',
                         best_score=best_score,
                         top_players=top_players)




@game_bp.route('/join-queue', methods=['POST'])
@login_required
def join_queue():
    """Join exact-stake queue. Match pays both bets immediately."""
    amount = request.form.get('bet', type=int)
    if amount not in ALLOWED_BETS:
        return jsonify({'success': False, 'message': 'Invalid bet amount'}), 400

    with state_lock:
        user_id = current_user.id
        user = User.query.get(user_id)
        if not user:
            return jsonify({'success': False, 'message': 'User not found'}), 404

        room_id, room = _get_room_for_user(user_id)
        if room_id and room:
            _resolve_room_if_needed(room)
            payload = _room_payload(user_id, room)
            return jsonify({'success': True, **payload})

        _remove_from_queue(user_id)

        if user.coins < amount:
            return jsonify({'success': False, 'message': 'Not enough balance for this stake'}), 400

        queue = stake_queues[amount]
        while queue:
            opp_id = queue.pop(0)
            user_queue_bet.pop(opp_id, None)
            if opp_id == user_id:
                continue
            if _get_room_for_user(opp_id)[0]:
                continue

            opponent = User.query.get(opp_id)
            if not opponent:
                continue
            if opponent.coins < amount:
                continue

            # Immediate pay-in when match is created.
            user.coins -= amount
            opponent.coins -= amount
            db.session.commit()

            new_room_id = uuid.uuid4().hex[:12]
            now = time.time()
            new_room = {
                'id': new_room_id,
                'players': [user_id, opp_id],
                'bet': amount,
                'pot': amount * 2,
                'round': 1,
                'selections': {},
                'deadline': now + ROUND_SECONDS,
                'result': None,
                'status': 'active',
                'rematch_requests': set(),
                'rematch_started_at': None,
                'rematch_expired_at': None,
                'created_at': int(now),
                'last_seen': {user_id: now, opp_id: now}
            }
            active_rooms[new_room_id] = new_room
            user_room[user_id] = new_room_id
            user_room[opp_id] = new_room_id

            payload = _room_payload(user_id, new_room)
            return jsonify({'success': True, **payload})

        queue.append(user_id)
        user_queue_bet[user_id] = amount
        return jsonify({'success': True, 'status': 'waiting', 'bet': amount})


@game_bp.route('/queue-status')
@login_required
def queue_status():
    """Poll queue and matchmaking state."""
    with state_lock:
        user_id = current_user.id
        room_id, room = _get_room_for_user(user_id)
        if room_id and room:
            _resolve_room_if_needed(room)
            _expire_rematch_if_needed(room)
            payload = _room_payload(user_id, room)
            if payload['status'] == 'opponent_left':
                _cleanup_room(room_id)
            return jsonify({'success': True, **payload})

        if user_id in user_queue_bet:
            return jsonify({'success': True, 'status': 'waiting', 'bet': user_queue_bet[user_id]})

        return jsonify({'success': True, 'status': 'idle'})


@game_bp.route('/round-status')
@login_required
def round_status():
    """Poll in-room game state and resolve timeout when needed."""
    with state_lock:
        user_id = current_user.id
        room_id, room = _get_room_for_user(user_id)
        if not room_id or not room:
            return jsonify({'success': True, 'status': 'idle'})

        _resolve_room_if_needed(room)
        _expire_rematch_if_needed(room)
        payload = _room_payload(user_id, room)
        if payload['status'] == 'opponent_left':
            _cleanup_room(room_id)
        return jsonify({'success': True, **payload})


@game_bp.route('/select-card', methods=['POST'])
@login_required
def select_card():
    """Submit chosen card for the active room."""
    card = (request.form.get('card') or '').strip().lower()
    if card not in VALID_CARDS:
        return jsonify({'success': False, 'message': 'Invalid card'}), 400

    with state_lock:
        user_id = current_user.id
        room_id, room = _get_room_for_user(user_id)
        if not room_id or not room:
            return jsonify({'success': False, 'message': 'No active room'}), 400
        if room.get('status') != 'active':
            payload = _room_payload(user_id, room)
            return jsonify({'success': True, **payload})

        # Prevent changing card if already selected in this round
        if user_id in room['selections']:
            return jsonify({'success': False, 'message': 'You already selected a card. Cannot change it.'}), 400

        room['selections'][user_id] = card
        _resolve_room_if_needed(room)
        payload = _room_payload(user_id, room)
        return jsonify({'success': True, **payload})


@game_bp.route('/rematch', methods=['POST'])
@login_required
def rematch():
    """Request rematch; start next round when both agree and can pay."""
    with state_lock:
        user_id = current_user.id
        room_id, room = _get_room_for_user(user_id)
        if not room_id or not room:
            return jsonify({'success': False, 'message': 'No active room'}), 400
        if room.get('status') == 'terminated':
            return jsonify({'success': False, 'message': 'Room already closed'}), 400

        # If user already requested rematch, return current status instead of erroring
        if user_id in room.get('rematch_requests', set()):
            payload = _room_payload(user_id, room)
            return jsonify({'success': True, **payload})

        if not room.get('result'):
            return jsonify({'success': False, 'message': 'Round not finished yet'}), 400

        # Check balance before allowing rematch request
        user = User.query.get(user_id)
        if not user or user.coins < room['bet']:
            return jsonify({'success': False, 'message': 'Insufficient balance for rematch'}), 400

        _expire_rematch_if_needed(room)
        now = time.time()
        if not room.get('rematch_requests'):
            room['rematch_started_at'] = now
            room['rematch_expired_at'] = None

        room['rematch_requests'].add(user_id)
        seconds_left = max(0, REMATCH_WINDOW_SECONDS - int(time.time() - room['rematch_started_at']))
        if len(room['rematch_requests']) < 2:
            return jsonify({'success': True, 'status': 'waiting_rematch', 'rematch_seconds_left': seconds_left})

        if time.time() - room['rematch_started_at'] > REMATCH_WINDOW_SECONDS:
            room['rematch_requests'] = set()
            room['rematch_started_at'] = None
            room['rematch_expired_at'] = int(time.time())
            return jsonify({
                'success': True,
                'status': 'rematch_expired',
                'message': 'Rematch expired. Both players must press Rematch within 60 seconds.'
            })

        # Both agreed, set confirmed time for 4-second delay before starting
        room['rematch_confirmed_at'] = time.time()
        payload = _room_payload(user_id, room)
        return jsonify({'success': True, **payload})


@game_bp.route('/leave-queue', methods=['POST'])
@login_required
def leave_queue():
    """Leave queue or active room."""
    with state_lock:
        user_id = current_user.id
        _remove_from_queue(user_id)

        room_id, room = _get_room_for_user(user_id)
        if not room_id or not room:
            return jsonify({'success': True})

        opp_id = _other_player(room, user_id)
        if room.get('status') == 'active' and not room.get('result'):
            # If someone leaves mid-round, refund current round stake to both players.
            for uid in room['players']:
                u = User.query.get(uid)
                if u:
                    u.coins += room['bet']
            db.session.commit()

            room['status'] = 'terminated'
            room['termination_message'] = 'Opponent left the game.'
            user_room.pop(user_id, None)
            if opp_id not in user_room:
                _cleanup_room(room_id)
            return jsonify({'success': True})

        # Leaving after result/idle: remove this player mapping and mark room as terminated
        # so opponent sees opponent_left status
        room['status'] = 'terminated'
        room['termination_message'] = 'Opponent left the game.'
        user_room.pop(user_id, None)
        if opp_id not in user_room:
            _cleanup_room(room_id)
        return jsonify({'success': True})



@game_bp.route('/game-state')
@login_required
def game_state():
    """Get current game state for polling."""
    with state_lock:
        user_id = current_user.id
        user = User.query.get(user_id)
        
        # First check if in queue
        if user_id in user_queue_bet:
            return jsonify({
                'success': True,
                'status': 'waiting',
                'bet': user_queue_bet[user_id],
                'balance': user.coins if user else 0
            })
        
        # Check if in a room
        room_id, room = _get_room_for_user(user_id)
        if room_id and room:
            _resolve_room_if_needed(room)
            _expire_rematch_if_needed(room)
            payload = _room_payload(user_id, room)
            payload['balance'] = user.coins if user else 0
            if payload['status'] == 'opponent_left':
                _cleanup_room(room_id)
            return jsonify({'success': True, **payload})
        
        return jsonify({
            'success': True,
            'status': 'idle',
            'balance': user.coins if user else 0
        })


@game_bp.route('/respond-rematch', methods=['POST'])
@login_required
def respond_rematch():
    """Respond to rematch offer."""
    accept = request.form.get('accept', 'false').lower() == 'true'
    
    with state_lock:
        user_id = current_user.id
        room_id, room = _get_room_for_user(user_id)
        
        if not room_id or not room:
            return jsonify({'success': False, 'message': 'No active room'}), 400
        
        if not room.get('result'):
            return jsonify({'success': False, 'message': 'Round not finished'}), 400
        
        user = User.query.get(user_id)
        if not user:
            return jsonify({'success': False, 'message': 'User not found'}), 400
        
        if not accept:
            # User declined rematch - clear requests and end round
            room['rematch_requests'] = set()
            room['rematch_started_at'] = None
            payload = _room_payload(user_id, room)
            return jsonify({'success': True, **payload})
        
        # User accepted - check balance
        if user.coins < room['bet']:
            return jsonify({'success': False, 'message': 'Insufficient balance for rematch'}), 400
        
        _expire_rematch_if_needed(room)
        
        # Add this user to rematch requests
        if not room.get('rematch_requests'):
            room['rematch_started_at'] = time.time()
        
        room['rematch_requests'].add(user_id)
        
        # Check if both agreed
        if len(room['rematch_requests']) >= 2:
            # Both confirmed - set delay before starting
            room['rematch_confirmed_at'] = time.time()
        
        payload = _room_payload(user_id, room)
        return jsonify({'success': True, **payload})


@game_bp.route('/leave-game', methods=['POST'])
@login_required
def leave_game():
    """Leave current game and return to lobby."""
    return leave_queue()


@game_bp.route('/new-match-same-opponent', methods=['POST'])
@login_required
def new_match_same_opponent():
    """Start a NEW match with the SAME opponent (deducts real coins)."""
    with state_lock:
        user_id = current_user.id
        user = User.query.get(user_id)
        
        if not user:
            return jsonify({'success': False, 'message': 'User not found'}), 404
        
        # Get current room
        room_id, room = _get_room_for_user(user_id)
        if not room_id or not room:
            return jsonify({'success': False, 'message': 'No active room'}), 400
        
        # Get opponent
        opp_id = _other_player(room, user_id)
        opponent = User.query.get(opp_id)
        
        if not opponent:
            return jsonify({'success': False, 'message': 'Opponent not found'}), 404
        
        bet_amount = room['bet']
        
        # Check both players have enough coins
        if user.coins < bet_amount:
            return jsonify({'success': False, 'message': 'Insufficient balance'}), 400
        
        if opponent.coins < bet_amount:
            return jsonify({'success': False, 'message': 'Opponent has insufficient balance'}), 400
        
        # Clean up current room
        room['status'] = 'terminated'
        room['termination_message'] = 'Starting new match.'
        user_room.pop(user_id, None)
        
        # Check if opponent also left
        if opp_id not in user_room:
            _cleanup_room(room_id)
        
        # Deduct coins for new match
        user.coins -= bet_amount
        opponent.coins -= bet_amount
        db.session.commit()
        
        # Create new room with same opponent
        new_room_id = uuid.uuid4().hex[:12]
        now = time.time()
        new_room = {
            'id': new_room_id,
            'players': [user_id, opp_id],
            'bet': bet_amount,
            'pot': bet_amount * 2,
            'round': 1,
            'selections': {},
            'deadline': now + ROUND_SECONDS,
            'result': None,
            'status': 'active',
            'rematch_requests': set(),
            'rematch_started_at': None,
            'rematch_expired_at': None,
            'created_at': int(now),
            'last_seen': {user_id: now, opp_id: now}
        }
        active_rooms[new_room_id] = new_room
        user_room[user_id] = new_room_id
        user_room[opp_id] = new_room_id
        
        payload = _room_payload(user_id, new_room)
        return jsonify({'success': True, **payload})


@game_bp.route('/save-score', methods=['POST'])
@login_required
def save_score():
    """Save game score via AJAX"""
    from flask import jsonify
    from app.services import UserService
    
    score = request.form.get('score', 0, type=int)
    game_id = request.form.get('game_id', 'emperors_circle')
    
    if score <= 0:
        return jsonify({'success': False, 'message': 'Invalid score'}), 400
    
    game_score = UserService.save_game_score(current_user.id, score, game_id)
    
    return jsonify({
        'success': True,
        'message': 'Score saved!',
        'score': game_score.score
    })


@game_bp.route('/leaderboard')
@login_required
def leaderboard():
    """Game leaderboard page"""
    game_id = request.args.get('game_id', 'emperors_circle')
    limit = request.args.get('limit', 50, type=int)
    
    scores = GameScore.query.filter_by(game_id=game_id)\
        .order_by(GameScore.score.desc())\
        .limit(limit).all()
    
    # Calculate user's rank
    user_rank = None
    all_scores = GameScore.query.filter_by(game_id=game_id)\
        .order_by(GameScore.score.desc()).all()
    
    for rank, s in enumerate(all_scores, 1):
        if s.user_id == current_user.id:
            user_rank = rank
            break
    
    return render_template('game/leaderboard.html',
                         scores=scores,
                         game_id=game_id,
                         user_rank=user_rank)
