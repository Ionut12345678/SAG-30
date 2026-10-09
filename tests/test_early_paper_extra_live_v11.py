import json,sqlite3,unittest
from radar.early_paper_extra_live_v11 import select,observe
class TestExtraQuote(unittest.TestCase):
 def test_selection_excludes_production_and_caps(self):
  f={s:{"change_pct":5,"turnover":v,"retrieval_ts":"2026-10-09T13:00:00+00:00"} for s,v in [("A",3),("B",2),("C",1),("D",4)]}
  self.assertEqual(select(f,["D"],3),["A","B","C"])
 def test_actual_quote_and_entry_change(self):
  db=sqlite3.connect(":memory:")
  t="2026-10-09T13:00:00+00:00"
  f={"A":{"change_pct":5,"turnover":2,"retrieval_ts":t}}
  quote={"latestTrade":{"p":10,"t":t},"latestQuote":{"bp":9.99,"ap":10.01,"bs":100,"as":100,"t":t},"prevDailyBar":{"c":9.8}}
  r=observe(db,1,"2026-10-09",f,[],{}, "iex",lambda url,headers:({"A":quote},t))
  self.assertEqual(r["paper_review"],1)
  self.assertEqual(db.execute("SELECT screen_stage FROM early_paper_extra_observations").fetchone()[0],"EARLY_PAPER_ENTRY_REVIEW")
 def test_later_price_above_ten_blocks(self):
  db=sqlite3.connect(":memory:");t="2026-10-09T13:00:00+00:00"
  f={"A":{"change_pct":5,"turnover":2,"retrieval_ts":t}}
  quote={"latestTrade":{"p":12,"t":t},"latestQuote":{"bp":11.99,"ap":12.01,"bs":100,"as":100,"t":t},"prevDailyBar":{"c":10}}
  r=observe(db,1,"2026-10-09",f,[],{}, "iex",lambda url,headers:({"A":quote},t))
  self.assertEqual(r["paper_review"],0)
if __name__=="__main__":unittest.main()
