import csv
import gzip
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from decimal import Decimal
from scripts.build_universe import select, build
from radar.runner import load_universe

class UniverseTests(unittest.TestCase):
    def test_production_rows_are_loadable_unique_and_bounded(self):
        metadata = json.loads(Path('config/universe_metadata.json').read_text())
        symbols = load_universe('config/universe.csv')
        with Path('config/universe.csv').open() as file:
            rows = list(csv.DictReader(file))
        self.assertEqual(len(symbols), metadata['symbol_count'])
        self.assertEqual(len(symbols), len(rows))
        self.assertEqual([row['symbol'] for row in rows], symbols)
        self.assertTrue(all(0 < Decimal(row['market_cap_usd']) < Decimal(2000000000) for row in rows))
        self.assertTrue(all(row['as_of'] == metadata['as_of'] for row in rows))
        self.assertEqual(hashlib.sha256(Path('config/universe.csv').read_bytes()).hexdigest(), metadata['universe_csv_sha256'])

    def test_official_source_hashes_and_missing_source_time(self):
        metadata = json.loads(Path('config/universe_metadata.json').read_text())
        self.assertIsNone(metadata['sources']['screener']['source_ts'])
        self.assertFalse(metadata['alpaca_tradability_verified'])
        for source in metadata['sources'].values():
            raw = gzip.decompress(Path(source['archive']).read_bytes())
            self.assertEqual(hashlib.sha256(raw).hexdigest(), source['sha256_uncompressed'])
            self.assertTrue(source['retrieval_ts'])

    def test_funds_derivatives_and_2b_boundary_excluded(self):
        def listing(symbol, name, **extra):
            return {'Symbol':symbol,'Security Name':name,'Test Issue':'N','ETF':'N','NextShares':'N',**extra}
        directory = [listing('OK','Example Common Stock'),listing('WAR','Example Warrants'),listing('ETF','Example ETF',ETF='Y'),listing('FUND','Example Income Fund Common Shares'),listing('BOUND','Example Common Stock')]
        screener = [{'symbol':symbol,'name':name,'marketCap':cap,'industry':''} for symbol,name,cap in [('OK','Example Common Stock','100000000'),('WAR','Example Warrants','100000000'),('ETF','Example ETF','100000000'),('FUND','Example Income Fund Common Shares','100000000'),('BOUND','Example Common Stock','2000000000')]]
        accepted, excluded = select(screener,directory,[])
        self.assertEqual([row['symbol'] for row in accepted],['OK'])
        self.assertEqual(len(excluded),4)

    def test_exchange_details_match_membership(self):
        from collections import Counter
        metadata = json.loads(Path('config/universe_metadata.json').read_text())
        with Path('config/universe_details.csv').open() as file:
            rows = list(csv.DictReader(file))
        self.assertEqual(dict(Counter(row['exchange'] for row in rows)),metadata['exchange_counts'])
        self.assertEqual(sorted(row['symbol'] for row in rows),load_universe('config/universe.csv'))

    def test_offline_rebuild_is_byte_identical(self):
        import shutil
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/'config'
            output.mkdir()
            shutil.copytree('config/universe_sources',output/'universe_sources')
            shutil.copy('config/universe_metadata.json',output/'universe_metadata.json')
            build(output,False)
            for name in ('universe.csv','universe_details.csv','universe_exclusions.csv','universe_metadata.json'):
                self.assertEqual((output/name).read_bytes(),Path('config',name).read_bytes())
