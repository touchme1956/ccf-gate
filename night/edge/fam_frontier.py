#!/usr/bin/env python3
"""night/edge/fam_frontier.py — 系統 frontier（第10回）: フロンティア市場を持つ vs 米国市場

事前登録 out/edge_prereg_r10.json の families.frontier。読むだけ・門の採点に不使用。
  データ: JKP（jkpfactors.com）の frontier 地域の市場（vw・ew）と国別の市場（vw）。どれも米ドル建ての**超過**リターン
          → 総リターン = ret ＋ French の RF（fam_profit.py と同じ扱い）。
  フロンティアの国 = JKP の国のうち、先進国22か国（spec_profit.json の replicate＋米国）と新興国24か国（confirm_em.py の EM）の
          どちらにも入らない国。国の市場は その月の銘柄数（n_stocks）が20社以上の月だけ使う。
  変種: frontier 地域の市場 vw／ew、フロンティアの国の等加重（毎月戻す・前月末に20社以上の国だけ）＝3
  費用: 年0.80%（FM の経費率）を毎月引く。国の等加重は戻す売買の回転 × 0.10%（事前登録 costs.指数・国の入れ替え）。
  相手: French の米国市場。

★先読み: 国の等加重で持つ国は m−1 月末の銘柄数で決める（月 m の銘柄数は使わない）。
使い方: python3 night/edge/fam_frontier.py [--save]
"""
import sys, os, io, csv, zipfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as h  # noqa: E402
from concurrent.futures import ThreadPoolExecutor  # noqa: E402

FAMILY = {
    'key': 'frontier',
    'name': 'フロンティア市場（JKP の frontier 地域・国の等加重）を持つ',
    'implement': ('楽天証券の海外ETF: iShares MSCI Frontier and Select EM（FM・経費0.79%・2012〜）。NISA 成長投資枠で可（取扱があれば）。'
                  '国の等加重を個人が作るのは現実的でない（国別ETFがほとんど無い）。'),
}
DEV = 'usa jpn gbr deu fra can aus che swe nld ita esp hkg sgp dnk nor bel fin aut irl prt nzl isr'.split()
EM = 'bra chl chn col cze egy grc hun ind idn kor kwt mys mex per phl pol qat sau zaf twn tha tur are'.split()
AGG = {'all_countries', 'all_regions', 'developed', 'emerging', 'frontier', 'world', 'world_ex_us'}
FEE, COST, MIN_N = 0.008, 0.001, 20


def frontier_countries():
    import json
    d = json.loads(h.cached('jkp_availability.json', 'https://jkpfactors-data.s3.amazonaws.com/public/availability.json'))
    return sorted(c for c in d['factors'] if c not in AGG and c not in DEV and c not in EM)


def country_mkt(c):
    """(ret, n): {YYYYMM: 超過リターン}, {YYYYMM: 銘柄数}。h.guard 済み"""
    try:
        h.jkp(c, 'mkt', 'factor', 'vw')                     # キャッシュを作る
    except Exception:
        return {}, {}
    z = zipfile.ZipFile(os.path.join(h.CACHE, f'jkp_factor_{c}_mkt_vw.zip'))
    r, n = {}, {}
    for x in csv.DictReader(io.StringIO(z.read(z.namelist()[0]).decode())):
        m = int(x['date'][:4]) * 100 + int(x['date'][5:7])
        try:
            r[m] = float(x['ret'])
            n[m] = int(x['n_stocks']) if x.get('n_stocks') not in (None, '', 'na') else 0
        except ValueError:
            continue
    return h.guard(r), h.guard(n)


def run(spec):
    mkt, rf = h.us_market()
    if spec['kind'] == 'region':
        x = h.jkp('frontier', 'mkt', 'factor', spec['w'])
        ret = {m: v + rf[m] - FEE / 12 for m, v in x.items() if m in rf and m in mkt}
        tv = {m: 0.0 for m in ret}
    else:
        cs = frontier_countries()
        with ThreadPoolExecutor(8) as ex:
            data = dict(zip(cs, ex.map(country_mkt, cs)))
        months = sorted(set().union(*[set(r) for r, n in data.values()]))
        ret, tv, prev = {}, {}, {}
        for m in months:
            p = h.add_months(m, -1)
            hold = [c for c, (r, n) in data.items() if n.get(p, 0) >= MIN_N and m in r]
            if not hold or m not in rf or m not in mkt:
                continue
            w = {c: 1 / len(hold) for c in hold}
            ret[m] = sum(data[c][0][m] for c in hold) / len(hold) + rf[m] - FEE / 12
            tv[m] = 0.5 * sum(abs(w.get(c, 0) - prev.get(c, 0)) for c in set(w) | set(prev)) if prev else 0.0
            prev = w
    return {'ret': ret, 'bench': {m: mkt[m] for m in ret}, 'rf': rf, 'turnover': tv, 'cost': COST}


def variants():
    return [{'kind': 'region', 'w': 'vw'}, {'kind': 'region', 'w': 'ew'}, {'kind': 'countries_ew', 'min_n': MIN_N}]


def main():
    assert h.PHASE == 'select'
    rows = []
    for v in variants():
        try:
            r = run(v)
        except Exception as e:
            print(v, '取れない', e); continue
        st = h.stats(r['ret'], r['bench'], r['rf'], b=h.SEL_END, turnover=r['turnover'], cost=r['cost'])
        rows.append((v, st))
        s = st or {}
        print(v, f"{s.get('from')}〜{s.get('to')} 年率 {s.get('cagr')} vs {s.get('bench_cagr')} 超過 {s.get('excess')} t{s.get('t')} ぶれ {s.get('vol')}/{s.get('bench_vol')} 最大下落 {s.get('maxdd')}/{s.get('bench_maxdd')}")
    if '--save' in sys.argv:
        ok = [(v, s) for v, s in rows if s]
        good = [(v, s) for v, s in ok if s['excess'] >= 1.0]
        v, s = max(good or ok, key=lambda z: z[1]['t'] if z[1]['t'] is not None else -99)
        note = '' if good else '⚠ 選定期間で +1%/年 に届いた変種は0 → 事前登録どおり t 最大の変種を凍結した（条件3で落ちる見込み）。'
        doc = h.save_spec('frontier', v,
                          f"【規則】{v}。【なぜ】小さく未発達で世界の資本とつながりの薄い市場は、分散の効果とリスクの対価で高いリターンを持つという説"
                          f"（Speidell & Krohne 2007・Harvey 1995 の新興市場の議論）。{note} フロンティアの国: {', '.join(frontier_countries())}",
                          len(rows), s, {'variants_table': [{'spec': a, 'stats': b} for a, b in rows]})
        print('凍結:', doc['spec'])


if __name__ == '__main__':
    main()
