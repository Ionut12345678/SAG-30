"""Completed US equity sessions for prospective daily research only."""
from datetime import datetime, timedelta, timezone


def latest_completed_session(now=None, calendar=None):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError('Timezone-aware clock required')
    if calendar is None:
        import exchange_calendars
        calendar = exchange_calendars.get_calendar('XNYS')
    # A small publication delay prevents accepting a bar at the closing instant.
    cutoff = now.astimezone(timezone.utc) - timedelta(minutes=5)
    sessions = calendar.sessions_in_range((cutoff - timedelta(days=14)).date(), cutoff.date())
    completed = [s for s in sessions if calendar.session_close(s).to_pydatetime() <= cutoff]
    if not completed:
        raise ValueError('No completed exchange session in calendar window')
    return completed[-1].date().isoformat()
