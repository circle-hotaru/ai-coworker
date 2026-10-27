"""Per-device capture, reply, and follow-up gates for the voice bridge."""
import time
from core.utils.util import remove_punctuation_and_length


def is_single_turn(conn):
    route = getattr(getattr(conn, 'llm', None), 'route', None) or {}
    return route.get('interaction_mode') == 'single_turn'


def is_continuous(conn):
    route = getattr(getattr(conn, "llm", None), "route", None) or {}
    return route.get("interaction_mode") == "continuous"


def requires_button(conn):
    route = getattr(getattr(conn, 'llm', None), 'route', None) or {}
    return route.get('activation_mode') == 'button_only'


def capture_allowed(conn):
    return not is_busy(conn) and (not requires_button(conn) or getattr(conn, 'voice_capture_started', False))


def is_busy(conn):
    return (is_single_turn(conn) or is_continuous(conn)) and getattr(conn, 'voice_turn_committed', False)


def accept_command(conn, text):
    if not (is_single_turn(conn) or is_continuous(conn)):
        return True
    if not capture_allowed(conn):
        return False
    _, normalized = remove_punctuation_and_length(text)
    wakeups = {remove_punctuation_and_length(w)[1] for w in conn.config.get('wakeup_words', [])}
    if not normalized or normalized in wakeups:
        return False
    # Claim the turn before any await. The existing TTS sender closes the
    # WebSocket after the final response's audio has drained.
    conn.voice_turn_committed = True
    conn.close_after_chat = is_single_turn(conn)
    conn.voice_capture_started = False
    return True


def begin_capture(conn):
    conn.voice_capture_started = True
    if is_continuous(conn):
        conn.voice_idle_since = time.monotonic()


def finish_reply(conn):
    if is_continuous(conn) and not conn.close_after_chat:
        conn.voice_turn_committed = False
        conn.voice_capture_started = False
        conn.voice_idle_since = None


def empty_capture_expired(conn, have_voice):
    """Only empty listening expires; silence after speech submits via VAD."""
    if not is_continuous(conn) or not capture_allowed(conn):
        return False
    if have_voice or conn.client_have_voice:
        conn.voice_idle_since = None
        return False
    started = getattr(conn, "voice_idle_since", None)
    return started is not None and time.monotonic() - started >= 5.0
