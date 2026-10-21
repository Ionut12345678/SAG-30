import unittest
from datetime import date,timedelta
from radar_annual_research import analyze_symbol,summarize,parse

def daily(n=220):
    start=date(2025,11,1)
    out=[]
    for i in range(n):
        price=10+i*.003
        out.append({"session":(start+timedelta(days=i)).isoformat(),
                    "open":price,"high":price*1.01,"low":price*.99,
                    "close":price,"volume":1000})
    return out

class AnnualResearchTests(unittest.TestCase):
 def test_forward_high_not_same_day(self):
    bars=daily()
    bars[50]["close"]=bars[49]["close"]*1.07
    bars[50]["high"]=bars[49]["close"]*3
    bars[51]["open"]=10
    bars[51]["high"]=10.5
    x=analyze_symbol("ABC",bars)
    e=[x for x in x["events"] if x["signal_date"]==bars[50]["session"]][0]
    self.assertFalse(e["hits_20_pct_upper_bound"])
    self.assertEqual(e["proxy_entry_date"],bars[51]["session"])
    self.assertFalse(e["valid_entry_fill"])
 def test_future_change_cannot_change_prior_signal(self):
    b=daily()
    b[60]["close"]=b[59]["close"]*1.06
    e=analyze_symbol("A",b)["events"]
    a=next(x for x in e if x["signal_date"]==b[60]["session"])
    b[63]["high"]*=5
    e2=analyze_symbol("A",b)["events"]
    z=next(x for x in e2 if x["signal_date"]==b[60]["session"])
    self.assertEqual(a["group"],z["group"])
    self.assertEqual(a["signal_close"],z["signal_close"])
    self.assertNotEqual(a["five_session_max_high_pct"],z["five_session_max_high_pct"])
 def test_split_excluded(self):
    x=analyze_symbol("SPLIT",daily(),True)
    self.assertFalse(x["eligible"])
    self.assertEqual(x["excluded_reason"],"SPLIT_EVENT_IN_WINDOW")
 def test_insufficient_coverage_excluded(self):
    x=analyze_symbol("NEW",daily(90))
    self.assertFalse(x["eligible"])
 def test_daily_window_not_intraday_trade(self):
    b=daily()
    b[40]["close"]=b[39]["close"]*1.07
    r=summarize([analyze_symbol("A",b)])
    self.assertFalse(r["intraday_validation_complete"])
    self.assertFalse(r["buy_enabled"])
 def test_no_events_does_not_invent_results(self):
    r=summarize([analyze_symbol("A",daily())])
    self.assertEqual(r["status"],"NO_ELIGIBLE_EVENTS")
if __name__=="__main__":unittest.main()
