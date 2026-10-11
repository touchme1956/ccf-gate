#!/usr/bin/env python3
"""night/bestfund_cma.py — 世界 C の材料: 機関の長期の期待リターンを賭けごとにそろえる（bestfund・読むだけ）

入力 out/bestfund_cma_raw.json（2026-10-11 に調べ役が集めた 2025〜2026年の版・24機関・729行・各行に出典の URL と原文）。
事前登録 out/bestfund_prereg.json（d5eab7f）future_worlds.C の決まりどおりに、機関ごとに1つの数字（名目・幾何・米国と世界はドル・日本は円）へ直し、
賭けの種類に当てて取れた機関の単純平均を出す。決めたこと（数字を見て選んだのではなく、規約を行に当てる手順）:
  - 1機関1つ: 版は最新だけ（最新の日から90日以内の資料は同じ版の別の表とみなす＝JPM の米ドル表と円表）。期間は10年に最も近いもの。シナリオは平均（GMO の金利2通り・GPIF の4通り）。BlackRock は基本の『Starting point』だけ
    （AI の生産性ブーム・リスク上昇のシナリオは使わない）。Research Affiliates は既定の評価依存モデルだけ。Schroders は2チームあるので10年の
    Multi-Asset を使い、30年の Economics Group は使わない。Horizon Actuarial は43社の調査の平均＝他の機関と重なるので使わない
  - 通貨: 米国・世界の賭けはドル（無ければ現地通貨の数字をドルと同じとみなす＝ドル円の期待の変化0と同じ約束）。円の数字は米国・世界の賭けには使わない。
    日本の賭けは円の予想があればそれ（事前登録）、無ければドルの数字
  - 実質は名目へ: その機関の同じ通貨のインフレの置き値を足す（無ければ 2.5%）。算術は幾何へ: σ²/2 を引く（σ はその機関の数字、無ければこの調査の
    つなぎの A1 窓の歴史）。『明記なし』は幾何とみなす（年率の予想の慣例）
  - 型の賭けはその機関の型（バリュー・小型・クオリティ等）が無ければ米国大型。セクター・テーマの賭け（半導体・テック・FANG・NASDAQ100・ソフト・
    インターネット・メガグロース）は米国大型グロース、無ければ米国大型（事前登録）。他のセクター（ヘルスケア等）は米国大型

  python3 night/bestfund_cma.py   → out/bestfund_cma.json
"""
import datetime, json, math, os, re, statistics as S, sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
RAW = os.path.join(BASE, 'out', 'bestfund_cma_raw.json')
OUT = os.path.join(BASE, 'out', 'bestfund_cma.json')
EXCLUDE_INST = ('Horizon Actuarial', 'Schroders (Schroders Economics Group)')
DEFAULT_INFL = 2.5
TECH = ['US_LARGE_GROWTH', 'US_LARGE', 'US_TOTAL']
BET_CLASS = {
    'ACWI': ['ACWI'], 'SP500': ['US_LARGE', 'US_TOTAL'], 'USTOT': ['US_TOTAL', 'US_LARGE'],
    'NDX': TECH, 'SEMI_MV': TECH, 'SEMI_SOX': TECH, 'TECH_SPDR': TECH, 'TECH_VGT': TECH, 'FANG': TECH, 'SOFT': TECH, 'INET': TECH,
    'MEGAG': TECH, 'GROWTH': ['US_LARGE_GROWTH', 'US_LARGE', 'US_TOTAL'],
    'VALUE': ['US_LARGE_VALUE', 'US_LARGE', 'US_TOTAL'], 'SMALL': ['US_SMALL', 'US_LARGE', 'US_TOTAL'],
    'SMALLV': ['US_SMALL_VALUE', 'US_SMALL', 'US_LARGE', 'US_TOTAL'], 'QUALITY': ['US_QUALITY', 'US_LARGE', 'US_TOTAL'],
    'MOM': ['US_MOMENTUM', 'US_LARGE', 'US_TOTAL'], 'LOWVOL': ['US_MINVOL', 'US_LARGE', 'US_TOTAL'],
    'DIVG': ['US_QUALITY', 'US_LARGE', 'US_TOTAL'], 'HIDIV': ['US_DIVIDEND', 'US_LARGE_VALUE', 'US_LARGE', 'US_TOTAL'],
    'EQW': ['US_MID', 'US_LARGE', 'US_TOTAL'],
    'HEALTH': ['US_LARGE', 'US_TOTAL'], 'DEFENSE': ['US_LARGE', 'US_TOTAL'], 'ENERGY': ['US_LARGE', 'US_TOTAL'], 'FIN': ['US_LARGE', 'US_TOTAL'],
    'STAPLES': ['US_LARGE', 'US_TOTAL'], 'UTIL': ['US_LARGE', 'US_TOTAL'], 'REIT': ['US_REIT', 'US_LARGE', 'US_TOTAL'],
    'KOKUSAI': ['DEV_WORLD'], 'DEVXUS': ['DEV_EX_US'], 'EM': ['EM'], 'TOPIX': ['JAPAN'], 'N225': ['JAPAN'], 'INDIA': ['INDIA', 'EM'],
    'DXUS_VAL': ['INTL_VALUE', 'DEV_EX_US'], 'EM_VAL': ['EM_VALUE', 'EM'], 'GOLD': ['GOLD'], 'BOND': ['US_AGG'],
}
CLASS_SIGMA_BET = {'US_LARGE': 'SP500', 'US_TOTAL': 'USTOT', 'US_SMALL': 'SMALL', 'US_MID': 'EQW', 'ACWI': 'ACWI', 'DEV_WORLD': 'KOKUSAI',
                   'DEV_EX_US': 'DEVXUS', 'GLOBAL_EX_US': 'ACWI', 'EM': 'EM', 'US_AGG': 'BOND', 'JAPAN': 'TOPIX', 'US_REIT': 'REIT',
                   'US_LARGE_GROWTH': 'GROWTH', 'US_LARGE_VALUE': 'VALUE', 'GOLD': 'GOLD', 'INDIA': 'INDIA'}


def classify(r):
    s = (r.get('asset_class') or '').strip()
    t = s.lower()
    inst = r['institution']
    if 'GPIF' in inst:
        return 'JAPAN' if '国内株式' in s else None      # 4つのシナリオは後で平均
    if any(x in t for x in ('scenario', 'yield & growth', 'inflation', 'cash', 'tips', 'treas', 'terminal', 'appreciation', 'fx ',
                             'over-/under', '60/40', '60-40', 'debt', 'commodit', 'short ', 'linked')):
        return None
    if r.get('currency') and r['currency'].startswith('JPY') and not r['currency'].startswith('JPY (local'):
        # 円建ての表: 日本株だけ使う（米国・世界の資産の円の数字はドル円の予想を含むので使わない）
        if re.search(r'日本大型株式|^japan(?! cash| aggregate)|japan large cap equities|japan equity|equity — jp', t) and '小型' not in s \
                and not re.search(r'ex[- ]japan|除く日本', t):
            return 'JAPAN'
        return None
    if re.search(r'\bgold\b|precious', t):
        return 'GOLD'
    if re.search(r'global aggregate|japan aggregate|japanese|jgb|japan bond|government bonds', t):
        return None
    if re.search(r'aggregate|\bagg\b|core us fixed|investment grade|^u\.s\. bonds', t):
        return 'US_AGG'
    if 'reit' in t or 'real estate' in t:
        if re.search(r'global|listed|developed|ex us|除く米国', t):
            return None
        return 'US_REIT'
    if 'india' in t:
        return 'INDIA'
    if re.search(r'japan|equity — jp$', t):
        if re.search(r'ex[- ]japan|small value|小型', t):
            return None
        return 'JAPAN'
    if re.search(r'emerging.*value', t):
        return 'EM_VALUE'
    if re.search(r'emerging|\bem\b|e m equities|msci em\b|all em', t):
        if re.search(r'ex china|asia', t):
            return None
        return 'EM'
    if 'intl deep value' in t:
        return 'INTL_VALUE'
    if 'small' in t and re.search(r"int'l|intl|dev|world|global|non-u", t):
        return None
    if re.search(r'global.*ex[- ]?u\.?s|acwi ex|ac world ex|all.*ex[- ]?us|global ex-us|global ex-u\.s', t):
        return 'GLOBAL_EX_US'
    if re.search(r"eafe|world ex usa|dev(eloped)?[^,]*ex[- ]?u\.?s|non-u\.?s\.? developed|non-us developed|int'l dev large|intl large|glob\. dev\. ex us|developed international ex", t):
        return 'DEV_EX_US'
    if re.search(r'small-cap equity$', t) and 'all-country' in t:
        return None
    if re.search(r'ac world|all country|all-country world equity|msci acwi|global equities unhedged|^global equity|global stocks|equity — global|equity markets: global|global all|acwi\)', t):
        return 'ACWI'
    if re.search(r'msci world|developed market equity$|developed markets equity|developed markets large|developed market equities|global developed \(world\)|equity markets: developed markets|world equity|global dev\.|global large cap equities|equities — developed markets', t):
        if re.search(r'value|growth|quality|momentum|minimum', t):
            return None
        return 'DEV_WORLD'
    if re.search(r'small value', t):
        return 'US_SMALL_VALUE'
    if re.search(r'small growth', t):
        return None
    if re.search(r'large growth|u\.s\. growth$|us growth|1000 growth', t):
        return 'US_LARGE_GROWTH'
    if re.search(r'large value|u\.s\. value$|us value|1000 value|equity value factor|deep value', t):
        return 'US_LARGE_VALUE'
    if 'quality factor' in t:
        return 'US_QUALITY'
    if 'momentum factor' in t:
        return 'US_MOMENTUM'
    if 'minimum volatility factor' in t:
        return 'US_MINVOL'
    if 'dividend yield factor' in t:
        return 'US_DIVIDEND'
    if re.search(r'mid ?cap|midcap|mid-cap|s&p 400', t) and 'small/mid' not in t:
        return 'US_MID'
    if re.search(r'u\.?s\.? small|us small|russell 2000|s&p 600|small cap \(s&p|small/mid cap us|u\.s\. small-cap|small-cap equity', t):
        return 'US_SMALL'
    if re.search(r'russell 3000|s&p 1500|total stock market|^u\.s\. equities$|broad us equity', t):
        return 'US_TOTAL'
    if re.search(r"u\.?s\.? large|us large|s&p 500|large cap us|russell 1000 index|^us stocks$|^u\.s\. equity$|msci usa|nddlus|equity markets: us$|equity — us$|regional outlook returns: us$|u\.s\. equity \(u\.s\. large\)", t):
        return 'US_LARGE'
    return None


def horizon_num(h):
    if h is None:
        return 25.0
    if isinstance(h, (int, float)):
        return float(h)
    m = re.findall(r'\d+', str(h))
    if not m:
        return 25.0
    v = [float(x) for x in m]
    return sum(v[:2]) / len(v[:2])


def is_real(r):
    return (r.get('nominal_or_real') or '').lower().startswith('real')


def is_arith(r):
    return (r.get('geometric_or_arithmetic') or '').lower().startswith('arith')


def vol_from_quote(r):
    m = re.search(r'Volatility \(%\)\s*([\d.]+)', r.get('quote') or '')
    return float(m.group(1)) / 100 if m else None


def hist_sigma():
    import bestfund_data as D
    ch = D.chains()
    ks = [k for k in ch['SP500']['usd'] if D.A1[0] <= k <= D.A1[1]]
    out = {}
    for c, b in CLASS_SIGMA_BET.items():
        cur = 'jpy' if b in D.JPY_NATIVE else 'usd'
        x = [math.log1p(ch[b][cur][k]) for k in ks if k in ch[b][cur]]
        out[c] = S.stdev(x) * math.sqrt(12)
    return out


def inflation_of(rows, cur):
    for r in rows:
        t = (r.get('asset_class') or '').lower()
        is_infl = (re.search(r'^(u\.s\. |us |united states )?inflation|^inflation', t) or 'インフレ率' in (r.get('asset_class') or '')) \
            and not re.search(r'linked|bond|tips', t)
        if is_infl and r.get('value_pct') is not None:
            if cur == 'JPY' and (r.get('currency') or '').startswith('JPY'):
                return float(r['value_pct'])
            if cur != 'JPY' and (r.get('currency') or '').startswith('USD'):
                return float(r['value_pct'])
    return None


def build():
    raw = json.load(open(RAW))
    rows = [r for r in raw['rows'] if not any(r['institution'].startswith(x) for x in EXCLUDE_INST)]
    sig = hist_sigma()
    by = {}
    for r in rows:
        by.setdefault(r['institution'], []).append(r)
    chosen = {}
    for inst, rs in by.items():
        latest = max(r['date'] for r in rs)
        d_latest = datetime.date.fromisoformat(latest)
        # 同じ版の別の資料（JPM の米ドル表 2025-10-20 と円表 2025-12-10 など）を残すため、最新の日から90日以内を同じ版とみなす
        rs_l = [r for r in rs if (d_latest - datetime.date.fromisoformat(r['date'])).days <= 90]
        cand = {}
        for r in rs_l:
            if r.get('value_pct') is None:
                continue
            c = classify(r)
            if not c:
                continue
            cur = (r.get('currency') or '').upper()
            jpy = cur.startswith('JPY')
            if c != 'JAPAN' and jpy:
                continue
            cand.setdefault(c, []).append(r)
        out = {}
        for c, lst in cand.items():
            # 通貨 → 期間（10年に近い）→ 名目 → 幾何 の順に選ぶ
            def cur_rank(r):
                cur = (r.get('currency') or '').upper()
                if c == 'JAPAN':
                    return 0 if cur.startswith('JPY') else (1 if cur.startswith('USD') else 2)
                return 0 if cur.startswith('USD') else 1
            best_cur = min(cur_rank(r) for r in lst)
            lst2 = [r for r in lst if cur_rank(r) == best_cur]
            hbest = min(abs(horizon_num(r['horizon_years']) - 10) for r in lst2)
            lst2 = [r for r in lst2 if abs(horizon_num(r['horizon_years']) - 10) == hbest]
            if any(not is_real(r) for r in lst2):
                lst2 = [r for r in lst2 if not is_real(r)]
            if any(not is_arith(r) for r in lst2):
                lst2 = [r for r in lst2 if not is_arith(r)]
            # 同じ物差しの行が複数＝シナリオ（GMO の金利2通り・GPIF の4通り）や同じ種類の別名 → 平均
            vals, notes = [], []
            for r in lst2:
                v = float(r['value_pct'])
                note = []
                ccy = 'JPY' if (r.get('currency') or '').upper().startswith('JPY') else 'USD'
                if is_real(r):
                    infl = inflation_of(rs_l, ccy)
                    infl = DEFAULT_INFL if infl is None else infl
                    v += infl
                    note.append(f'実質＋インフレ{infl}')
                if is_arith(r):
                    s_ = vol_from_quote(r) or sig.get(c)
                    v -= 100 * s_ * s_ / 2
                    note.append(f'算術−σ²/2（σ={100 * s_:.1f}%）')
                vals.append(v)
                notes.append({'label': r['asset_class'], 'value_pct_raw': r['value_pct'], 'currency': r.get('currency'),
                              'horizon': r.get('horizon_years'), 'nominal_or_real': r.get('nominal_or_real'),
                              'geometric_or_arithmetic': r.get('geometric_or_arithmetic'), 'conv': note, 'url': r.get('url')})
            out[c] = {'value_pct': round(S.mean(vals), 3), 'n_rows_averaged': len(vals), 'rows': notes}
        chosen[inst] = {'edition_date': latest, 'classes': out}
    bets = {}
    for b, pref in BET_CLASS.items():
        vals = []
        for inst, e in chosen.items():
            for c in pref:
                if c in e['classes']:
                    vals.append({'institution': inst, 'class': c, 'value_pct': e['classes'][c]['value_pct']})
                    break
        bets[b] = {'n': len(vals), 'avg_pct': round(S.mean(v['value_pct'] for v in vals), 3) if vals else None,
                   'median_pct': round(S.median(v['value_pct'] for v in vals), 3) if vals else None, 'values': vals}
    doc = {'generated': datetime.date.today().isoformat(), 'tool': 'night/bestfund_cma.py', 'input': 'out/bestfund_cma_raw.json',
           'prereg': 'out/bestfund_prereg.json（d5eab7f）future_worlds.C', 'institutions_used': sorted(chosen),
           'n_institutions': len(chosen), 'excluded': list(EXCLUDE_INST), 'bet_to_class': BET_CLASS,
           'rules': __doc__.split('決めたこと')[1].split('python3')[0].strip(), 'chosen': chosen, 'bets': bets}
    json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1)
    return doc


def main():
    doc = build()
    print('→', OUT, '機関', doc['n_institutions'])
    for inst, e in doc['chosen'].items():
        print(f"  {inst[:40]:40} {e['edition_date']} " + ' '.join(f"{c}={v['value_pct']}" for c, v in sorted(e['classes'].items())))
    print('賭けごと:')
    for b, e in doc['bets'].items():
        print(f"  {b:10} n={e['n']:2d} 平均{e['avg_pct']} 中央{e['median_pct']}")


if __name__ == '__main__':
    main()
