#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/retro_cash_roic.py — 現金を投下資本から引いたROICと、今の引かないROIC、どちらが
「その後も複利が続いた会社」をよく見分けたかを歴史で検定する（2026-10-05新設・ユーザー指示「4」）

**読むだけ。採点・規約・合否には一切触れない。**
事前登録は out/cashroic_prereg.json（**結果を見る前に**コミット 5325885 で固定）。
結果の器（中央値・P(年15%+)・恒久毀損）は night/retro_cliffs_test.stat をそのまま使う。

ROIC は門の今の採取器 hachimon_fetch.build_numbers が作る（再実装しない）。採取器のソースは書き換えず、
年ごとの NOPAT・IC・ICg・現金・短期投資・売上を記録する1行だけを足した写しをメモリ上で作って読み込む。
SEC companyfacts は **filed ≤ asof（各年07-01）** の提出だけを残してから渡す＝当時読めた数字だけ。
採取器の検問（有利子負債の痕跡・無形の上限の不等式・IC/ICg≥20%・税タグの欠測）はすべてそのまま効く。

使い方:
  python3 night/retro_cash_roic.py collect   # SEC から集める（在庫 out/_cashroic_cache/・gitignore）
  python3 night/retro_cash_roic.py test      # 判定 → out/retro_cash_roic.json
  python3 night/retro_cash_roic.py           # 両方
"""
import concurrent.futures as cf
import datetime
import json
import os
import statistics as st
import sys
import time
import types
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from retro_cliffs_test import rows, stat, RET          # 同じ器（stat）と同じリターンの在庫

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, 'out', '_cashroic_cache')
OUT = os.path.join(ROOT, 'out', 'retro_cash_roic.json')
PREREG = 'out/cashroic_prereg.json'
PRIMARY = [2013, 2015, 2018]
FETCHER_REV_PREREG = 'hd770bc0634'
OPCASH = 0.02          # 営業に要る現金＝売上×2%（事前登録）
GUARD = 0.20           # IC−X < ICg×20% の年は引かない（採取器の縮退の物差しと同じ）
LT_TAGS = ['MarketableSecuritiesNoncurrent', 'AvailableForSaleSecuritiesDebtSecuritiesNoncurrent',
           'HeldToMaturitySecuritiesNoncurrent']
TECH = [(3570, 3579), (3600, 3699), (3820, 3829), (7370, 7379)]


# ── 採取器の写し（記録の1行だけを足す）──────────────────────────────────────
def load_machine():
    p = os.path.join(ROOT, 'hachimon_fetch.py')
    src = open(p, encoding='utf-8').read()
    old = '            roics.append((nopat/ic*100, nopat/icg*100, y))\n'
    if src.count(old) != 1:
        raise SystemExit('採取器の構造が変わった——記録の1行を差し込む場所が見つからない（測らずに止める）')
    new = old + ('            _CAPTURE.append(dict(y=y, nopat=nopat, ic=ic, icg=icg, cash=S["cash"].get(y),'
                 ' sti=S["sti"].get(y), rev=S["rev"].get(y), latest=LATEST))\n')
    src = src.replace(old, new).replace('def build_numbers(facts):', '_CAPTURE = []\ndef build_numbers(facts):', 1)
    mod = types.ModuleType('hachimon_capture')
    mod.__file__ = p                                  # FETCHER_REV は元のファイルの内容ハッシュ
    exec(compile(src, p, 'exec'), mod.__dict__)
    return mod


def asof_facts(facts, cut):
    """filed ≤ cut の提出だけを残した companyfacts（当時読めた数字）"""
    out = {'cik': facts.get('cik'), 'entityName': facts.get('entityName'), 'facts': {}}
    for ns, tags in (facts.get('facts') or {}).items():
        o = {}
        for tag, v in tags.items():
            units = {}
            for u, arr in (v.get('units') or {}).items():
                a = [x for x in arr if (x.get('filed') or '9999') <= cut]
                if a:
                    units[u] = a
            if units:
                vv = dict(v)
                vv['units'] = units
                o[tag] = vv
        out['facts'][ns] = o
    return out


def universe():
    """{年: [(ticker, cagr)]}。retro_features2 ∩ retro_returns（stale でなく tr_cagr あり）"""
    U = {}
    for y in PRIMARY:
        F = [r['ticker'] for r in rows('retro_features2_%d.json' % y)]
        R = {r['ticker']: r['tr_cagr'] for r in rows(RET[y]) if not r.get('stale') and r.get('tr_cagr') is not None}
        U[y] = [(t, R[t]) for t in F if t in R]
    return U


def cik_map(mod):
    m = {}
    for y in (2015, 2013, 2012):                       # 新しいコホートを先に（retro_features2 と同じ優先）
        p = os.path.join(ROOT, 'out', 'retro_cohort_%d.json' % y)
        if os.path.exists(p):
            for r in rows('retro_cohort_%d.json' % y):
                if r.get('ticker') and r.get('cik') is not None:
                    m.setdefault(r['ticker'], int(r['cik']))
    try:
        j = json.loads(mod.get('https://www.sec.gov/files/company_tickers.json'))
        for v in j.values():
            m.setdefault(v['ticker'].upper(), int(v['cik_str']))
    except Exception as e:
        print('company_tickers.json を取れなかった（コホートの CIK だけで続ける）:', e)
    return m


def fetch(mod, cik):
    u = 'https://data.sec.gov/api/xbrl/companyfacts/CIK%010d.json' % cik
    for i in range(5):
        try:
            req = urllib.request.Request(u, headers=mod.HDRS)
            b = urllib.request.urlopen(req, timeout=120).read()
            time.sleep(0.12)                          # 1件の取得に数秒かかるので8本並べても 10req/s を超えない
            return json.loads(b)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return {}
            time.sleep(2 ** i)
        except Exception:
            time.sleep(2 ** i)
    return None                                       # 取れなかった＝在庫に書かない（次回また取りに行く）


def collect():
    mod = load_machine()
    if mod.FETCHER_REV != FETCHER_REV_PREREG:
        print(f'⚠ 採取器の版が事前登録と違う: {mod.FETCHER_REV} ≠ {FETCHER_REV_PREREG}（結果に版を記録して続ける）')
    os.makedirs(CACHE, exist_ok=True)
    U = universe()
    M = cik_map(mod)
    need = {}                                         # cik → [(ticker, 年)]
    unmapped = {}
    for y, lst in U.items():
        for t, _ in lst:
            c = M.get(t) or M.get(t.upper()) or M.get(t.replace('.', '-').upper())
            if c is None:
                unmapped.setdefault(y, []).append(t)
                continue
            need.setdefault(c, []).append((t, y))
    json.dump({'unmapped': unmapped, 'fetcher_rev': mod.FETCHER_REV},
              open(os.path.join(CACHE, '_meta.json'), 'w'), ensure_ascii=False)
    todo = [c for c in need if not os.path.exists(os.path.join(CACHE, '%010d.json' % c))]
    print(f'社 {len(need)}（未取得 {len(todo)}）／CIK不明 { {y: len(v) for y, v in unmapped.items()} }', flush=True)
    done = 0
    with cf.ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ex.submit(fetch, mod, c): c for c in todo}
        for fu in cf.as_completed(futs):
            c = futs[fu]
            facts = fu.result()
            if facts is None:
                print('取得失敗（次回また取りに行く）:', c, flush=True)
                continue
            rec = {'cik': c, 'items': {}}
            f = None
            for t, y in need[c]:
                key = '%s|%d' % (t, y)
                if not facts:
                    rec['items'][key] = {'err': 'companyfacts が無い（404）'}
                    continue
                f = asof_facts(facts, '%d-07-01' % y)
                mod._CAPTURE.clear()
                try:
                    ev = mod.build_numbers(f)
                    ev = ev[0] if isinstance(ev, tuple) else ev
                except Exception as e:
                    rec['items'][key] = {'err': 'build_numbers: %s' % str(e)[:120]}
                    continue
                lt = {}
                for tag in LT_TAGS:                   # 構成要素（別の資産）なので年ごとに足す
                    try:
                        d, _u = mod.series(f, [tag])
                    except Exception:
                        d = {}
                    for yy, v in (d or {}).items():
                        lt[str(yy)] = lt.get(str(yy), 0) + (v or 0)
                rec['items'][key] = {'rows': [dict(r) for r in mod._CAPTURE], 'ltms': lt,
                                     'machine_roic': (ev or {}).get('roic') if isinstance(ev, dict) else None}
            json.dump(rec, open(os.path.join(CACHE, '%010d.json' % c), 'w'))
            # 取り終えた companyfacts を手放す（Future が結果を握ったままだと全社分がメモリに残り、
            # 2026-10-05 の初回は約750社目で黙って落ちた＝強制終了でトレースバックも出なかった）
            futs.pop(fu, None)
            fu._result = None
            del facts, f
            done += 1
            if done % 50 == 0:
                print(f'  {done}/{len(todo)}', flush=True)
    print('collect 完了', flush=True)


# ── 判定 ─────────────────────────────────────────────────────────────────────
def med_pair(item, with_lt=False):
    """(roic_incl, roic_ex) の中央値。採取器が算出できた年が3年未満なら None"""
    inc, exx = [], []
    lt = item.get('ltms') or {}
    rs = item.get('rows') or []
    # 採取器と同じ年検問: 系列の最新年が全系列の最新年 LATEST から2年以上遅れていたら使わない（stale）
    if not rs or rs[0].get('latest') is None or max(r['y'] for r in rs) < rs[0]['latest'] - 1:
        return None
    for r in rs:
        if not r.get('ic') or r['ic'] <= 0:
            continue
        ri = r['nopat'] / r['ic'] * 100
        rx = ri
        if r.get('cash') is not None and r.get('rev'):  # 現金・売上が無い年は引かない（今の値のまま）
            X = r['cash'] + (r.get('sti') or 0) + ((lt.get(str(r['y'])) or 0) if with_lt else 0)
            X = max(0.0, X - OPCASH * r['rev'])
            icx = r['ic'] - X
            if r.get('icg') and r['icg'] > 0 and icx >= GUARD * r['icg']:
                rx = r['nopat'] / icx * 100
        inc.append(ri)
        exx.append(rx)
    if len(inc) < 3:
        return None
    return st.median(inc), st.median(exx)


def spearman(xs, ys):
    def rank(v):
        o = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(o):
            j = i
            while j + 1 < len(o) and v[o[j + 1]] == v[o[i]]:
                j += 1
            for k in range(i, j + 1):
                r[o[k]] = (i + j) / 2 + 1
            i = j + 1
        return r
    if len(xs) < 3:
        return None
    rx, ry = rank(xs), rank(ys)
    mx, my = st.mean(rx), st.mean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** 0.5
    return round(num / den, 3) if den else None


def is_tech(sic):
    try:
        s = int(sic)
    except Exception:
        return None
    return any(a <= s <= b for a, b in TECH)


def groups(data, T):
    A = [d for d in data if d['inc'] >= T]
    B = [d for d in data if d['inc'] < T <= d['ex']]
    C = [d for d in data if d['ex'] < T]
    return A, B, C


def judge_year(data, T, key='med'):
    A, B, C = groups(data, T)
    sa, sb, sc = stat(A), stat(B), stat(C)
    res = {'A': sa, 'B': sb, 'C': sc}
    if not (sa and sb and sc) or min(sa['n'], sb['n'], sc['n']) < 20:
        res['valid'] = False
        res['why'] = '群が20社未満'
        return res
    if key == 'dmg':
        den = sc['dmg'] - sa['dmg']
        if den <= 0:
            res['valid'] = False
            res['why'] = 'Aの毀損がCより濃いか同じ（線が効いていない）'
            return res
        res['p'] = round((sc['dmg'] - sb['dmg']) / den, 3)
    else:
        den = sa[key] - sc[key]
        if den <= 0:
            res['valid'] = False
            res['why'] = 'Aの%sがC以下（その年は ROIC の線そのものが効いていない）' % key
            return res
        res['p'] = round((sb[key] - sc[key]) / den, 3)
    res['valid'] = True
    return res


def verdict(yrs):
    ps = [v['p'] for v in yrs.values() if v.get('valid')]
    if len(ps) < 2:
        return 'UNDECIDED'
    if all(p >= 0.5 for p in ps):
        return 'EX_SUPPORTED'
    if all(p < 0.5 for p in ps):
        return 'INCL_SUPPORTED'
    return 'UNDECIDED'


def test():
    mod_meta = json.load(open(os.path.join(CACHE, '_meta.json'), encoding='utf-8'))
    U = universe()
    items = {}
    for fn in os.listdir(CACHE):
        if fn.endswith('.json') and not fn.startswith('_'):
            rec = json.load(open(os.path.join(CACHE, fn)))
            for k, v in rec['items'].items():
                items[k] = dict(v, cik=rec['cik'])
    SIC = json.load(open(os.path.join(ROOT, 'out', 'sic_by_cik.json')))
    out = {'generated': datetime.date.today().isoformat(), 'prereg': PREREG, 'prereg_commit': '5325885',
           'fetcher_rev': mod_meta.get('fetcher_rev'), 'opcash': OPCASH, 'guard': GUARD,
           'years': {}, 'secondary': {}}
    D = {}
    for y in PRIMARY:
        lst = U[y]
        cnt = {'universe': len(lst), 'cik_unknown': len((mod_meta.get('unmapped') or {}).get(str(y), [])),
               'no_facts_or_error': 0, 'roic_lt3y': 0, 'used': 0}
        data, data_lt = [], []
        for t, cagr in lst:
            it = items.get('%s|%d' % (t, y))
            if it is None:
                continue
            if it.get('err'):
                cnt['no_facts_or_error'] += 1
                continue
            mp = med_pair(it)
            if mp is None:
                cnt['roic_lt3y'] += 1
                continue
            sic = SIC.get(str(it['cik']))
            d = {'t': t, 'inc': round(mp[0], 2), 'ex': round(mp[1], 2), 'cagr': cagr, 'sic': sic}
            data.append(d)
            mp2 = med_pair(it, with_lt=True)
            data_lt.append(dict(d, ex=round(mp2[1], 2)))
        cnt['used'] = len(data)
        D[y] = (data, data_lt)
        prim = judge_year(data, 15)
        A, B, C = groups(data, 15)
        out['years'][y] = {'counts': cnt, 'primary_T15': prim,
                           'B_members': sorted([{'t': d['t'], 'inc': d['inc'], 'ex': d['ex'],
                                                 'cagr': round(d['cagr'] * 100, 1)} for d in B],
                                               key=lambda x: -x['cagr'])}
    out['verdict'] = verdict({y: out['years'][y]['primary_T15'] for y in PRIMARY})

    sec = out['secondary']
    sec['s1_p15'] = {y: judge_year(D[y][0], 15, 'p15') for y in PRIMARY}
    sec['s1_dmg'] = {y: judge_year(D[y][0], 15, 'dmg') for y in PRIMARY}
    for T in (12, 18):
        yrs = {y: judge_year(D[y][0], T) for y in PRIMARY}
        sec['s2_T%d' % T] = {'years': yrs, 'verdict': verdict(yrs)}
    sec['s3_spearman'] = {}
    for y in PRIMARY:
        pos = [d for d in D[y][0] if d['inc'] > 0]
        sec['s3_spearman'][y] = {'n': len(pos),
                                 'incl': spearman([d['inc'] for d in pos], [d['cagr'] for d in pos]),
                                 'ex': spearman([d['ex'] for d in pos], [d['cagr'] for d in pos])}
    yrs = {}
    for y in PRIMARY:
        nt = [d for d in D[y][0] if is_tech(d['sic']) is False]
        yrs[y] = judge_year(nt, 15)
        yrs[y]['n_nontech'] = len(nt)
    sec['s4_ex_tech'] = {'years': yrs, 'verdict': verdict(yrs)}
    yrs = {y: judge_year(D[y][1], 15) for y in PRIMARY}
    sec['s5_lt'] = {'years': yrs, 'verdict': verdict(yrs)}

    json.dump(out, open(OUT, 'w'), ensure_ascii=False, indent=1)
    # ── 表示 ──
    print('判定:', out['verdict'])
    for y in PRIMARY:
        v = out['years'][y]
        pr = v['primary_T15']
        f = lambda s: (f"n{s['n']:>4} 中央値{s['med']:>6}% P15 {s['p15']:.3f} 毀損 {s['dmg']:.3f}" if s else '—')
        print(f"\n{y}: {v['counts']}")
        for g in 'ABC':
            print(f"  {g}: {f(pr[g])}")
        print(f"  位置 p = {pr.get('p')}  valid={pr.get('valid')} {pr.get('why', '')}")
    for k in ('s1_p15', 's1_dmg'):
        print(k, {y: (sec[k][y].get('p'), sec[k][y].get('valid')) for y in PRIMARY})
    for k in ('s2_T12', 's2_T18', 's4_ex_tech', 's5_lt'):
        print(k, sec[k]['verdict'], {y: (sec[k]['years'][y].get('p'), sec[k]['years'][y].get('valid'),
                                         (sec[k]['years'][y].get('B') or {}).get('n')) for y in PRIMARY})
    print('s3_spearman', sec['s3_spearman'])


if __name__ == '__main__':
    a = sys.argv[1:] or ['collect', 'test']
    if 'collect' in a:
        collect()
    if 'test' in a:
        test()
