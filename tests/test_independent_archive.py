import unittest
from radar_independent_archive import sample_paths,decode_daily_csv
class IndependentArchiveTests(unittest.TestCase):
 def test_sample_independent_of_input_order(self):
  names=[f"collected_stocks/{i:04d}.csv" for i in range(100)]
  self.assertEqual(sample_paths(names,20),sample_paths(list(reversed(names)),20))
  self.assertEqual(len(sample_paths(names,20)),20)
 def test_no_nested_unexpected_paths(self):
  self.assertEqual(sample_paths(["collected_stocks/sub/A.csv","x/B.csv",
                                 "collected_stocks/A.csv"]),["collected_stocks/A.csv"])
 def test_parse_real_csv_column_layout(self):
  src="Unnamed: 0,DateTime,Open,High,Low,Close,Volume\n1,2025-10-02,10,12,9,11,25000\n"
  x=decode_daily_csv(src)
  self.assertEqual(len(x),1)
  self.assertEqual(x[0]["close"],11)
if __name__=="__main__":unittest.main()
