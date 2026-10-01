#!/usr/bin/env python3
"""night/edge/fam_intl_value.py — 系統 intl_value（第2回）: 国の中の割安・高配当

  各国で『高い側の30%』（割安 BE/ME・E/P・CE/P、または高配当 Yld）を買いだけで持つ。
  主の系列は 21か国の等加重（各国の高い側の等分）vs 21か国の市場（French 国別 Mkt・時価加重・米ドル）の等加重。

  データ: Ken French『F-F_International_Countries.zip』の各国ファイル（Value-Weight Dollar Returns の月次表）。
    列（実物で確かめた順）: Mkt | BE/ME High Low | E/P High Low | CE/P High Low | Yld High Low Zero
    High/Low は各国の上位/下位 30%。ポートフォリオは French が毎年12月末に組み替える（年1回・時価加重）。
  ⚠ この module は h.cached で zip を取り、読んだ系列は必ず h.guard を通す（選定の段では 2000-12 で切れる）。

  先読みの扱い:
    月 m の持ち物（どの国・どの特徴の High を持つか）は m−1 月末までに分かっていること（その国・その列の m−1 の値が在る）だけで決める。
    月 m に値が欠けていたら: 特徴の列が欠けた分はその国の市場で代える（超過0）。市場が欠けた国は戦略と相手の両方から外す（対称）。
    French の High/Low 自体の組み替えは前年末の会計値で行われる（French の作業・規則は固定なので、この規則の信号は時間で変わらない）。
"""
import sys, os, io, zipfile, re, itertools, math

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as h

FAMILY = {
    'key': 'intl_value',
    'name': '国の中の割安・高配当（21か国の等加重）',
    'implement': ('楽天証券で買える形なら: 米国上場の先進国割安ETF（iShares MSCI EAFE Value＝EFV・Alpha Architect IVAL・'
                  'Schwab Fundamental Intl＝FNDF 等。⚠ 2026-09 の楽天の取扱一覧〔out/broker_lineup.json〕には EFV/IVAL/FNDF が無く、'
                  '在るのは First Trust Global Select Dividend＝FGD〔高配当・経費0.55%〕程度）。日本の部分は東証の高配当ETF'
                  '（1489 日経高配当株50・1478 iShares MSCI Japan 高配当利回り 等・NISA 成長投資枠で可）。'
                  '国ごとの等加重を個人が再現するには国別の割安ETFが要り現実的でない＝実行は時価加重の先進国割安ETFで近似する'
                  '（等加重の国の配分とは別物）。NISA: 成長投資枠で非レバレッジのETFは可（取扱があれば）'),
}

ZIP_NAME = 'fr_F-F_International_Countries.zip'
ZIP_URL = 'https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_International_Countries.zip'
COLS = ['Mkt', 'BM_H', 'BM_L', 'EP_H', 'EP_L', 'CEP_H', 'CEP_L', 'YLD_H', 'YLD_L', 'YLD_0']
CHARS = ['BM', 'EP', 'CEP', 'YLD']
CHAR_JA = {'BM': '簿価時価比 BE/ME', 'EP': '益回り E/P', 'CEP': 'キャッシュフロー利回り CE/P', 'YLD': '配当利回り Yld'}
COST = 0.0025          # 事前登録: 個別株の組（French の分位）は回転1あたり 0.25%
TURN_YEAR = 0.5        # 事前登録: 会計の信号は 50%/年（French は12月末に年1回組み替える → 1月に 0.5 を計上）


# ───────────────────────── 読み込み ─────────────────────────
def country_tables(ccy='Dollar', items='Not Reqd'):
    """{国(ファイル名): {列: {YYYYMM: 小数}}}。French 国別ファイルの 'Value-Weight {ccy} Returns … {items}' の**月次**表。
    items: 'Not Reqd'（4項目が揃わない会社も含む・h.french_countries と同じ母集団）/ 'Required'。**h.guard 済み**"""
    z = zipfile.ZipFile(io.BytesIO(h.cached(ZIP_NAME, ZIP_URL)))
    head = re.compile(r'Value-Weight\s+' + ccy + r'\s+Returns\s+All 4 Data Items ' + items)
    out = {}
    for fn in z.namelist():
        if not fn.lower().endswith('.dat'):
            continue
        L = z.read(fn).decode('latin-1').split('\n')
        i = next((k for k, l in enumerate(L) if head.search(l)), None)   # 最初の一致＝月次の表（年次の表は後ろ）
        if i is None:
            continue
        toks = L[i + 2].split()
        assert toks == ['Mkt', 'High', 'Low', 'High', 'Low', 'High', 'Low', 'High', 'Low', 'Zero'], (fn, toks)
        assert 'BE/ME' in L[i + 1] and 'E/P' in L[i + 1] and 'CE/P' in L[i + 1] and 'Yld' in L[i + 1], (fn, L[i + 1])
        tab = {c: {} for c in COLS}
        started = False
        for l in L[i + 3:]:
            p = l.split()
            if not p or not (p[0].isdigit() and len(p[0]) == 6):
                if started:
                    break
                continue
            started = True
            assert len(p) == 11, (fn, p)
            m = int(p[0])
            for c, v in zip(COLS, p[1:]):
                f = float(v)
                if f > -99:
                    tab[c][m] = f / 100
        out[fn[:-4]] = {c: h.guard(s) for c, s in tab.items()}
    return out


# ───────────────────────── 規則 ─────────────────────────
def positions(tabs, mkt, chars, m):
    """月 m の持ち物（m−1 月末までに分かること**だけ**で決める）。
    → {国: [使う特徴の High 列]}（国は m−1 の市場の値が在るもの。列は m−1 の値が在るもの。空リスト＝その国は市場を持つ）"""
    p = h.add_months(m, -1)
    pos = {}
    for c in sorted(mkt):
        if p not in mkt[c]:
            continue
        pos[c] = [k + '_H' for k in chars if p in tabs.get(c, {}).get(k + '_H', {})]
    return pos


def realize(tabs, mkt, pos, m):
    """持ち物 pos の月 m の実現: → (国ごとの戦略リターン, 国ごとの市場リターン, 回転)。
    特徴の列が月 m に欠けたらその分を国の市場で代える（超過0）。市場が欠けた国は両方から外す（対称）"""
    rs, rb = {}, {}
    nh = 0
    for c, cols in pos.items():
        if m not in mkt[c]:
            continue
        b = mkt[c][m]
        if cols:
            rs[c] = sum(tabs[c][k].get(m, b) for k in cols) / len(cols)
            nh += 1
        else:
            rs[c] = b
        rb[c] = b
    n = len(rb)
    turn = (TURN_YEAR * nh / n) if (n and m % 100 == 1) else 0.0
    return rs, rb, turn


def build(tabs, mkt, chars):
    """→ ret, bench, turnover（21か国の等加重）と 国ごとの {国: (ret, bench, turnover)}"""
    allm = sorted(set().union(*[set(s) for s in mkt.values()])) if mkt else []
    ret, bench, turn = {}, {}, {}
    per = {c: ({}, {}, {}) for c in mkt}
    for m in allm:
        pos = positions(tabs, mkt, chars, m)
        if not pos:
            continue
        rs, rb, tu = realize(tabs, mkt, pos, m)
        if not rb:
            continue
        ret[m] = sum(rs.values()) / len(rs)
        bench[m] = sum(rb.values()) / len(rb)
        turn[m] = tu
        for c in rb:
            r_, b_, t_ = per[c]
            r_[m] = rs[c]
            b_[m] = rb[c]
            t_[m] = (TURN_YEAR if (pos[c] and m % 100 == 1) else 0.0)
    return ret, bench, turn, per


def load(spec):
    ccy = spec.get('ccy', 'Dollar')
    tabs = country_tables(ccy, spec.get('items', 'Not Reqd'))
    mkt = h.french_countries(ccy)                  # 相手＝事前登録どおり French 国別 Mkt（Not Reqd・時価加重・米ドル）
    return tabs, mkt


def run(spec):
    tabs, mkt = load(spec)
    chars = spec['chars']
    ret, bench, turn, per = build(tabs, mkt, chars)
    _, rf = h.us_market()
    markets = {}
    for c, (r_, b_, t_) in per.items():
        if len(r_) >= 24:
            markets[c] = {'ret': r_, 'bench': b_, 'rf': rf, 'turnover': t_, 'cost': COST}
    return {'ret': ret, 'bench': bench, 'rf': rf, 'turnover': turn, 'cost': COST, 'markets': markets}


# ───────────────────────── 先読みの検査 ─────────────────────────
def _truncate(tabs, mkt, K):
    return ({c: {k: {m: v for m, v in s.items() if m <= K} for k, s in t.items()} for c, t in tabs.items()},
            {c: {m: v for m, v in s.items() if m <= K} for c, s in mkt.items()})


def _scramble(tabs, mkt, K, seed=7):
    """K より後の値を乱数に差し替え・一部を欠測にする（未来を変える）"""
    import random
    R = random.Random(seed)
    f = lambda s: {m: (R.gauss(0, .08) if m > K else v) for m, v in s.items() if not (m > K and R.random() < .1)}
    return ({c: {k: f(s) for k, s in t.items()} for c, t in tabs.items()}, {c: f(s) for c, s in mkt.items()})


def lookahead_test(chars=('BM', 'EP', 'CEP', 'YLD'), items='Not Reqd'):
    """(1) 月 m の持ち物は m−1 までで切ったデータで作っても全データで作っても同じ
       (2) K で切った/K より後を乱数にしたデータで回しても、K 以前の ret・bench・回転は1ビットも変わらない
       (3) 1か月ずらし: 全ての系列を1か月後ろへずらすと、持ち物の日付も正確に1か月ずれる"""
    tabs, mkt = load({'items': items})
    chars = list(chars)
    ret, bench, turn, _ = build(tabs, mkt, chars)
    ms = sorted(ret)
    n1 = 0
    for m in ms[::7]:
        t2, m2 = _truncate(tabs, mkt, h.add_months(m, -1))
        assert positions(t2, m2, chars, m) == positions(tabs, mkt, chars, m), m
        n1 += 1
    n2 = 0
    for K in ms[24::37]:
        for t2, m2 in (_truncate(tabs, mkt, K), _scramble(tabs, mkt, K)):
            r2, b2, u2, _ = build(t2, m2, chars)
            for m in ms:
                if m > K:
                    break
                assert r2[m] == ret[m] and b2[m] == bench[m] and u2[m] == turn[m], (K, m)
        n2 += 1
    sh = lambda s: {h.add_months(m, 1): v for m, v in s.items()}
    t3 = {c: {k: sh(s) for k, s in t.items()} for c, t in tabs.items()}
    m3 = {c: sh(s) for c, s in mkt.items()}
    n3 = 0
    for m in ms[::11]:
        assert positions(t3, m3, chars, h.add_months(m, 1)) == positions(tabs, mkt, chars, m), m
        n3 += 1
    return {'positions_prefix_checked': n1, 'truncate_scramble_cuts': n2, 'shift1_checked': n3}


# ───────────────────────── 選定（1975〜2000） ─────────────────────────
def variants():
    """試す変種（数えて spec に書く）。主: Not Reqd の 4特徴の全ての組（15）。頑健性: Required の 単独4＋4つ全部（5）"""
    V = []
    for r in range(1, 5):
        for cmb in itertools.combinations(CHARS, r):
            V.append({'chars': list(cmb), 'items': 'Not Reqd', 'ccy': 'Dollar'})
    for cmb in [['BM'], ['EP'], ['CEP'], ['YLD'], ['BM', 'EP', 'CEP', 'YLD']]:
        V.append({'chars': cmb, 'items': 'Required', 'ccy': 'Dollar'})
    return V


def vname(s):
    return '+'.join(s['chars']) + ('' if s['items'] == 'Not Reqd' else '[Req]')


def select(verbose=True):
    assert h.PHASE == 'select'
    rows = []
    for s in variants():
        o = run(s)
        st = h.stats(o['ret'], o['bench'], o['rf'], turnover=o['turnover'], cost=o['cost'])
        assert st['to'] <= h.SEL_END
        # 国ごとの再現（選定期間）
        pos = tot = 0
        exs = []
        for c, mk in o['markets'].items():
            s2 = h.stats(mk['ret'], mk['bench'], mk['rf'], turnover=mk['turnover'], cost=mk['cost'])
            if s2:
                tot += 1
                pos += s2['excess'] > 0
                exs.append(s2['excess'])
        rows.append({'name': vname(s), 'spec': s, 'excess': st['excess'], 't': st['t'], 't_nw': st['t_nw'],
                     'cagr': st['cagr'], 'bench_cagr': st['bench_cagr'], 'vol': st['vol'], 'bench_vol': st['bench_vol'],
                     'maxdd': st['maxdd'], 'bench_maxdd': st['bench_maxdd'], 'from': st['from'], 'to': st['to'],
                     'countries_pos': f'{pos}/{tot}', 'stats': st})
        if verbose:
            print(f"{vname(s):22s} ex {st['excess']:+6.2f} t {st['t']:5.2f} tNW {st['t_nw']:5.2f} "
                  f"cagr {st['cagr']:6.2f} vs {st['bench_cagr']:6.2f} vol {st['vol']:5.1f}/{st['bench_vol']:5.1f} "
                  f"dd {st['maxdd']:6.1f}/{st['bench_maxdd']:6.1f} 国 {pos}/{tot} {st['from']}-{st['to']}")
    return rows


if __name__ == '__main__':
    print(lookahead_test())
    select()
