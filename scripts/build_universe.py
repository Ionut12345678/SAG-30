"""Build dated common-equity coverage; never changes SAG-30 model rules."""
import argparse
import csv
import gzip
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.request import Request, urlopen

SOURCES = {
    'screener': 'https://api.nasdaq.com/api/screener/stocks?tableonly=true&limit=25000&download=true',
    'nasdaqlisted': 'https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt',
    'otherlisted': 'https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt',
}
CAP_CEILING = Decimal('2000000000')
# Positive type identification; unfamiliar instruments are excluded, not guessed.
COMMON = re.compile(r'common (stock|shares?\b|subordinate voting shares|new\b)|ordinary (shares?\b|stock)|american deposit[ao]ry (shares?\b|receipts?)|\bADRs?\b|\bADSs?\b|subordinate voting shares|class [AB] shares|common units|capital stock|business development company|real estate investment trust', re.I)
NON_COMMON = re.compile(r'\b(warrants?|rights?|preferred|preference|notes?|bonds?|debentures?|ETNs?|ADW)\b|\btangible equity units\b', re.I)
FUND = re.compile(r'\bfunds?\b|\bmunicipal\b|\bincome trust\b|\bdividend trust\b|\bcredit.*trust\b|\bhealth sciences trust\b', re.I)


def now():
    return datetime.now(timezone.utc).isoformat()


def listings(raw, kind):
    lines = raw.decode('utf-8-sig').splitlines()
    if not lines or not lines[-1].startswith('File Creation Time:'):
        raise ValueError('Missing official symbol-directory footer')
    return list(csv.DictReader(lines[:-1], delimiter='|')), lines[-1].split('|')[0]


def select(screener, nasdaq, other):
    index = {}
    for row in nasdaq:
        if row['Test Issue'] == 'N' and row['ETF'] == 'N' and row['NextShares'] == 'N':
            index[row['Symbol']] = ('NASDAQ', row['Security Name'], row.get('Financial Status'))
    for row in other:
        if row['Test Issue'] == 'N' and row['ETF'] == 'N' and row['Exchange'] in ('N', 'A'):
            symbol = row['ACT Symbol']
            if symbol in index:
                raise ValueError('Conflicting exchange listings for ' + symbol)
            index[symbol] = ({'N': 'NYSE', 'A': 'NYSE AMERICAN'}[row['Exchange']], row['Security Name'], None)
    accepted, exclusions = {}, []
    for row in screener:
        symbol = row['symbol'].strip().upper()
        reason = None
        try:
            cap = Decimal(row.get('marketCap', '').replace(',', ''))
            if not cap.is_finite() or not 0 < cap < CAP_CEILING:
                reason = 'outside_positive_below_2b_market_cap'
        except (InvalidOperation, AttributeError):
            cap, reason = None, 'missing_or_invalid_market_cap'
        if reason is None and symbol not in index:
            reason = 'not_eligible_current_target_exchange_listing'
        if reason is None and not re.fullmatch(r'[A-Z][A-Z0-9]*(?:[.-][A-Z0-9]+)?', symbol):
            reason = 'unsupported_or_special_symbol'
        if reason is None:
            exchange, listing_name, financial_status = index[symbol]
            name = listing_name + ' ' + row['name']
            is_reit = 'real estate' in row.get('industry', '').lower() or 'real estate' in name.lower()
            if NON_COMMON.search(name):
                reason = 'non_common_instrument'
            elif FUND.search(name) and not is_reit:
                reason = 'fund_or_income_trust'
            elif 'beneficial interest' in name.lower() and not is_reit:
                reason = 'ambiguous_or_pooled_beneficial_interest'
            elif not COMMON.search(name) and not (is_reit and 'shares of beneficial interest' in name.lower()):
                reason = 'unclassified_security_type'
        if reason:
            exclusions.append({'symbol': symbol, 'name': row['name'], 'reason': reason})
            continue
        result = {'symbol': symbol, 'market_cap_usd': format(cap, 'f'), 'exchange': exchange,
                  'security_name': listing_name, 'country': row.get('country', ''),
                  'listing_financial_status': financial_status}
        if symbol in accepted and result != accepted[symbol]:
            raise ValueError('Conflicting market-cap records for ' + symbol)
        accepted[symbol] = result
    return [accepted[key] for key in sorted(accepted)], exclusions


def build(output, refresh):
    sources_dir = output / 'universe_sources'
    sources_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output / 'universe_metadata.json'
    prior = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    metadata, raw = {}, {}
    for name, url in SOURCES.items():
        path = sources_dir / (name + '.gz')
        if refresh:
            started = now()
            with urlopen(Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json,text/plain,*/*'}), timeout=60) as response:
                raw[name] = response.read()
                retrieved = now()
                response_date = response.headers.get('Date')
            path.write_bytes(gzip.compress(raw[name], mtime=0))
            metadata[name] = {'url': url, 'request_started_ts': started, 'retrieval_ts': retrieved,
                              'http_date': response_date, 'source_ts': None}
        else:
            raw[name] = gzip.decompress(path.read_bytes())
            metadata[name] = prior['sources'][name].copy()
        digest = hashlib.sha256(raw[name]).hexdigest()
        if not refresh and digest != metadata[name]['sha256_uncompressed']:
            raise ValueError('Source archive checksum mismatch')
        metadata[name]['sha256_uncompressed'] = digest
        metadata[name]['archive'] = str(path.relative_to(output.parent))
    response = json.loads(raw['screener'])
    if response['status']['rCode'] != 200 or not response.get('data', {}).get('rows'):
        raise ValueError('Invalid or empty Nasdaq screener response')
    metadata['screener']['source_ts'] = response['data'].get('asOf')
    nasdaq, footer = listings(raw['nasdaqlisted'], 'nasdaqlisted')
    metadata['nasdaqlisted']['source_timestamp_raw'] = footer
    other, footer = listings(raw['otherlisted'], 'otherlisted')
    metadata['otherlisted']['source_timestamp_raw'] = footer
    selected, excluded = select(response['data']['rows'], nasdaq, other)
    if not selected:
        raise ValueError('No eligible equities; refusing empty production universe')
    as_of = metadata['screener']['retrieval_ts'][:10]
    with (output / 'universe.csv').open('w', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=['symbol', 'market_cap_usd', 'as_of'], lineterminator='\n')
        writer.writeheader()
        writer.writerows({'symbol': row['symbol'], 'market_cap_usd': row['market_cap_usd'], 'as_of': as_of} for row in selected)
    with (output / 'universe_details.csv').open('w', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=list(selected[0]), lineterminator='\n')
        writer.writeheader()
        writer.writerows(selected)
    with (output / 'universe_exclusions.csv').open('w', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=['symbol', 'name', 'reason'], lineterminator='\n')
        writer.writeheader()
        writer.writerows(excluded)
    manifest = {'schema_version': 1, 'as_of': as_of, 'as_of_semantics': 'UTC retrieval date; Nasdaq screener supplies no valuation SOURCE_TS',
                'policy': {'market_cap_usd_min_exclusive': 0, 'market_cap_usd_max_exclusive': 2000000000,
                           'exchanges': ['NASDAQ', 'NYSE', 'NYSE AMERICAN'], 'domicile_filter': None,
                           'types': 'positively identified common equities/ADRs including REITs/BDCs/common partnership units; ambiguous types excluded',
                           'model_rules_changed': False},
                'symbol_count': len(selected), 'exchange_counts': dict(sorted(Counter(row['exchange'] for row in selected).items())),
                'cap_band_counts': {label: sum(lower <= Decimal(row['market_cap_usd']) < upper for row in selected)
                                    for label, lower, upper in [('nano_below_50m',Decimal(0),Decimal(50000000)),('micro_50m_to_300m',Decimal(50000000),Decimal(300000000)),('small_300m_to_2b',Decimal(300000000),CAP_CEILING)]},
                'screener_record_count': len(response['data']['rows']), 'listing_record_counts': {'NASDAQ':len(nasdaq),'other':len(other)},
                'exclusion_counts': dict(sorted(Counter(row['reason'] for row in excluded).items())),
                'universe_csv_sha256': hashlib.sha256((output / 'universe.csv').read_bytes()).hexdigest(),
                'alpaca_tradability_verified': False, 'sources': metadata}
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
    print(json.dumps({key: manifest[key] for key in ['as_of','symbol_count','exchange_counts','cap_band_counts','exclusion_counts']}, indent=2))

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--refresh', action='store_true', help='Fetch fresh sources; default reproduces the committed snapshot offline')
    parser.add_argument('--output', type=Path, default=Path('config'))
    args = parser.parse_args()
    build(args.output, args.refresh)
