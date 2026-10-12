"""Execution diagnostics only; quote availability never proves a fill or no halt."""
import math
from datetime import datetime


def quote_diagnostic(snapshot, retrieval_ts, max_age=300):
    quote = snapshot.get('latestQuote') or {}
    result = {'status': 'UNKNOWN', 'reason': 'MISSING_QUOTE', 'source_ts': quote.get('t'),
              'retrieval_ts': retrieval_ts, 'halt_status': 'UNKNOWN',
              'execution_actionable': 'UNKNOWN', 'spread_pct': None}
    try:
        source = datetime.fromisoformat(quote['t'].replace('Z', '+00:00'))
        retrieval = datetime.fromisoformat(retrieval_ts.replace('Z', '+00:00'))
        if source.tzinfo is None or retrieval.tzinfo is None:
            raise ValueError('timezone missing')
        age = (retrieval-source).total_seconds()
        result['age_seconds'] = age
        if age < 0 or age > max_age:
            result['reason'] = 'FUTURE_QUOTE' if age < 0 else 'STALE_QUOTE'
            return result
        bid, ask = quote.get('bp'), quote.get('ap')
        if any(isinstance(v, bool) or not isinstance(v, (int,float)) or not math.isfinite(v) or v <= 0 for v in (bid,ask)):
            result['reason'] = 'INVALID_BID_ASK'
        elif ask < bid:
            result['reason'] = 'CROSSED_QUOTE'
        else:
            result.update(status='FRESH_QUOTE_ONLY', reason=None, spread_pct=100*(ask-bid)/((ask+bid)/2))
    except (KeyError, ValueError, TypeError, AttributeError):
        if quote:
            result['reason'] = 'INVALID_QUOTE_TIMESTAMP'
    return result
