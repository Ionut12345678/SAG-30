import unittest
from event_attribution import associate
class EventAttributionTests(unittest.TestCase):
    def test_rejects_future_news_and_accepts_prior_news(self):
        signals=[{"id":"one","symbol":"AAPL","signal_date":"2026-10-23"}]
        events=[
          {"symbol":"AAPL","published_at_utc":"2026-10-23T19:00:00Z","event_type":"earnings","source_url":"https://example.org/1"},
          {"symbol":"AAPL","published_at_utc":"2026-10-23T22:00:00Z","event_type":"later","source_url":"https://example.org/2"}]
        r=associate(signals,events)
        self.assertEqual(r[0]["known_event_count"],1)
        self.assertEqual(r[0]["known_events"][0]["event_type"],"earnings")
    def test_requires_timezone(self):
        with self.assertRaises(ValueError):
            associate([{"id":"a","symbol":"AAPL","signal_date":"2026-10-23"}],
                [{"symbol":"AAPL","published_at_utc":"2026-10-23T18:00:00","event_type":"news","source_url":"https://example.org"}])
if __name__=="__main__":unittest.main()
