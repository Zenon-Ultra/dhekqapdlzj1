"""Runtime data must never be committed to the source repository."""
def is_auto_sync_enabled(): return False
def set_auto_sync_enabled(enabled):
    if enabled: raise ValueError('GitHub data sync is disabled; use B2 or ZIP export')
def start_auto_sync(): pass
