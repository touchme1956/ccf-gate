#!/usr/bin/env python3
"""night/bestfund_val.py — 世界 D の材料: 今の割高さ（PER・配当利回り・アナリストの長期の伸びの予想）を賭けごとにそろえる（bestfund・読むだけ）

入力 out/bestfund_valuations_raw.json（2026-10-11 に調べ役が集めた値・407行＋長期の平均・中央値154行・各行に出典の URL と原文）。
事前登録 out/bestfund_prereg.json（d5eab7f）future_worlds.D の入力（今の PER〔先の12か月を優先・無ければ実績〕・同じ物差しの PER の長期の中央値・
配当利回り・g_c＝アナリストの長期の伸びの予想）を、賭けの指数そのものの値からだけ取る。1つでも欠ける賭けは D を C と同じにする（推して埋めない）。

決めたこと（行の選び方）:
  - 今の PER: 先の12か月（pe_forward_12m）を優先。複数あれば日付の新しいもの（同じ日なら FactSet → JPM の順）。FY1（当年度）は使わない
  - 長期の PER: 同じ物差し（先の12か月）の長期の値のうち期間の最も長いもの。中央値が無く平均だけなら平均を使い、そう書く
  - 配当利回り: 指数の配当利回り（dividend_yield_pct）。複数あれば新しいもの
  - g_c: 指数の 3〜5年の1株利益の伸びの予想（eps_growth_est_3_5y_pct）。来期だけの伸び（next 12m・CY2026）は長期の予想ではないので使わない。
    Vanguard の earnings growth rate は過去5年の実績なので使わない
  - 賭けと指数の対応: SP500＝S&P 500／TECH_SPDR＝S&P 500 情報技術（XLK の指数＝SSGA の XLK の値と FactSet・JPM の業種の値）／HEALTH・ENERGY・FIN・
    STAPLES・UTIL＝それぞれの Select Sector（S&P 500 の業種）。他の賭けは g_c（と多くは長期の PER）が集まらなかった

  python3 night/bestfund_val.py   → out/bestfund_valuations.json
"""
import datetime, json, os, re

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(BASE, 'out', 'bestfund_valuations_raw.json')
OUT = os.path.join(BASE, 'out', 'bestfund_valuations.json')
# 賭け → (今の PER・長期の PER を探す指数の名前の頭, 配当と g_c を探す指数の名前の頭)
MAP = {
    'SP500': (['S&P 500'], ['S&P 500']),
    'TECH_SPDR': (['S&P 500 Information Technology sector'], ['Technology Select Sector Index']),
    'HEALTH': (['S&P 500 Health Care sector'], ['Health Care Select Sector Index']),
    'ENERGY': (['S&P 500 Energy sector'], ['Energy Select Sector Index']),
    'FIN': (['S&P 500 Financials sector'], ['Financial Select Sector Index']),
    'STAPLES': (['S&P 500 Consumer Staples sector'], ['Consumer Staples Select Sector Index']),
    'UTIL': (['S&P 500 Utilities sector'], ['Utilities Select Sector Index']),
}
SRC_RANK = ('FactSet', 'J.P. Morgan')


def period_years(p):
    p = p or ''
    m = re.search(r'since (\d{4})', p)
    if m:
        return 2026 - int(m.group(1))
    m = re.search(r'(\d+)-year', p)
    if m:
        return int(m.group(1))
    m = re.search(r'(\d{4})\s*-\s*(\d{4})', p)
    if m:
        return int(m.group(2)) - int(m.group(1))
    return 0


def exact(name, heads):
    """指数の名前が頭と同じか、頭のあとに括弧の注記が付くだけのとき（『S&P 500 Real Estate sector』を『S&P 500』と読まない）"""
    return any(name == h or name.startswith(h + ' (') for h in heads)


def pick_rows(rows, heads, metric):
    c = [r for r in rows if r['metric'] == metric and exact(r['index'], heads) and r.get('value') is not None]

    def key(r):
        sr = next((i for i, s in enumerate(SRC_RANK) if s in (r.get('source') or '')), 9)
        return (r.get('as_of') or '', -sr)
    return sorted(c, key=key)[-1] if c else None


def build():
    raw = json.load(open(RAW))
    rows, meds = raw['rows'], raw['medians']
    bets = {}
    for b, (pe_heads, dy_heads) in MAP.items():
        e = {}
        pe = pick_rows(rows, pe_heads, 'pe_forward_12m')
        mc = [m for m in meds if m['metric'] in ('pe_forward_12m_median', 'pe_forward_12m_average') and exact(m['index'], pe_heads)]
        med = sorted(mc, key=lambda m: (period_years(m.get('period')), m['metric'] == 'pe_forward_12m_median'))[-1] if mc else None
        dy = pick_rows(rows, dy_heads, 'dividend_yield_pct')
        gc = pick_rows(rows, dy_heads, 'eps_growth_est_3_5y_pct')
        e['pe_now'] = pe['value'] if pe else None
        e['pe_median'] = med['value'] if med else None
        e['dy'] = dy['value'] / 100 if dy else None
        e['g_c'] = gc['value'] / 100 if gc else None
        e['src'] = {
            'pe_now': pe and f"{pe['index']}・{pe['as_of']}・{pe['source']}",
            'pe_median': med and f"{med['index']}・{med['metric']}・{med.get('period')}・{med['source']}",
            'dy': dy and f"{dy['index']}・{dy['as_of']}・{dy['source']}",
            'g_c': gc and f"{gc['index']}・{gc['as_of']}・{gc['source']}",
            'urls': [x['url'] for x in (pe, med, dy, gc) if x],
        }
        e['median_is_average'] = bool(med and med['metric'].endswith('average'))
        bets[b] = e
    missing = 'それ以外の賭け: g_c（指数の 3〜5年の伸びの予想）が集まらなかった（多くは同じ物差しの長期の PER も無い）＝D は C と同じ'
    doc = {'generated': datetime.date.today().isoformat(), 'tool': 'night/bestfund_val.py', 'input': 'out/bestfund_valuations_raw.json',
           'prereg': 'out/bestfund_prereg.json（d5eab7f）future_worlds.D', 'bets': bets, 'others': missing,
           'rules': __doc__.split('決めたこと')[1].split('python3')[0].strip()}
    json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1)
    return doc


def main():
    doc = build()
    print('→', OUT)
    for b, e in doc['bets'].items():
        print(f"  {b:10} PER {e['pe_now']} 長期 {e['pe_median']}{'(平均)' if e['median_is_average'] else ''} 配当 {e['dy']} g_c {e['g_c']}")
        for k in ('pe_now', 'pe_median', 'dy', 'g_c'):
            print(f"      {k}: {(e['src'][k] or '')[:150]}")


if __name__ == '__main__':
    main()
