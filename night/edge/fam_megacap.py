#!/usr/bin/env python3
"""night/edge/fam_megacap.py — 系統 megacap：超大型株（French の規模の最大の十分位・五分位）の買いだけ／勢いで市場（またはその残り）と入れ替え

事前登録 out/edge_prereg.json（第1回）の一系統。読むだけ・門の採点に不使用。
  ・データは harness の french() と us_market() / french_region() だけで読む（選定の段では 2000-12 で切れる）
      米国: 'Portfolios_Formed_on_ME'（NYSE の分位点の十分位・五分位・時価加重）
      他の市場: '{地域}_25_Portfolios_ME_BE-ME'（地域の時価の 3/7/13/25% を分位点にした規模の五分位 × 簿価時価の五分位）
        → 規模の最上段の5つを時価で合わせて「最大の五分位」、下の4段の20個を合わせて「残り」を作る
  ・組の中身は French が作る（毎年6月末の時価で組む）＝月 m の組の中身は m−1 月末より前の情報。
    この module が自分で作る信号は (a) 組を合わせるときの時価の重み（m−1 行の 社数×平均時価）と
    (b) 組どうし・組と市場の過去 J か月の相対リターン（m−1 月まで）だけ。lookahead_test() で確かめる
  ・費用: 回転1あたり 0.10%（大型株 ETF・中小型 ETF・全市場 ETF で実行する前提）。回転は
      入れ替えの月に 1.0（片道100%）＋ 十分位・五分位・残りの組を持つ月は組の中の回転 年10% を月割り（市場 ETF を持つ月は0）
  ・相手: 米国市場（h.us_market）。他の市場: その地域の市場（h.french_region・米ドル建て）
    ⚠ 統括の指示は「再現は無し（French の国際には規模の十分位が無い）」だったが、規模の五分位は 25 Portfolios の規模の段で作れる。
      事前登録の「他の市場に当てられる規則は再現を見る」に従い、互いに重ならない3地域（欧州・日本・日本を除くアジア太平洋）に
      同じ凍結した規則を変えずに当てる（北米＝米国を含む・先進国除く米国＝3地域の和 は独立でないので使わない）
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as h

FAMILY = {
    'key': 'megacap',
    'name': '超大型株と中小型株の勢いの入れ替え（規模の最大の五分位 ⇄ 残り・過去12か月）',
    'implement': ('月末に、米国の超大型株の ETF（楽天証券の米国ETF: MGC＝Vanguard Mega Cap〔時価の上位70%〕・または OEF＝S&P100）と'
                  '中小型の ETF（VXF＝S&P500 以外の米国株、または VO＋VB を時価の比で）の過去12か月のリターンを比べ、勝っていた方を翌月まるごと持つ'
                  '（年に1回前後の入れ替え）。どれも楽天の米国ETF一覧（out/broker_lineup.json）にあり、成長投資枠（NISA）でも買えるが、'
                  'NISA は売った枠が翌年まで戻らず入れ替えのたびに枠を食うので、実際は課税の特定口座（利益が出ている入れ替えのたびに約20%の税・主の判定には入れない）。'
                  '入れ替え無しの買いだけ（A1〜A3）なら NISA の成長投資枠でそのまま持てる。'
                  '⚠ ETF の区切りは French の分位（NYSE の分位点）と同じではない（MGC の上位70%は十分位の上位より少し広く、VXF は S&P500 の下位を含まない）'),
}

FILE = 'Portfolios_Formed_on_ME'
VW = 'Average Value Weight Returns -- Monthly'
COST = 0.001                     # 回転1あたり（ETF の入れ替え）
INNER = 0.10                     # 十分位・五分位・残りの組の中の回転（年）
DECILES = ['Lo 10', '2-Dec', '3-Dec', '4-Dec', '5-Dec', '6-Dec', '7-Dec', '8-Dec', '9-Dec', 'Hi 10']
EVAL_START = 193108              # すべての変種を同じ月から比べる（最長の J=60＋1か月の空けが揃う最初の月・データに依らない定数）
REGIONS = ['Europe', 'Japan', 'Asia_Pacific_ex_Japan']


# ───────────────────────── 読み込み ─────────────────────────
def _monthly(s, scale=100.0):
    return {k: v / scale for k, v in s.items() if 99999 < k < 1000000}


def _tables(d):
    vw = d[next(t for t in d if t.startswith('Average Value Weight') and 'Monthly' in t)]
    nf = d[next(t for t in d if t.startswith('Number of Firms'))]
    sz = d[next(t for t in d if 'Firm Size' in t or 'Market Cap' in t)]
    return vw, nf, sz


def _pack(vw, nf, sz, cols, mkt, rf, combos, direct=()):
    """data: 'r:列'・'n:列'・'s:列'（数値の辞書）＋ 'mkt','rf' ＋ '_combo': {名前: [列]}（'_' で始まるキーは数値でない）"""
    data = {'mkt': mkt, 'rf': rf, '_combo': combos}
    for c in list(cols) + list(direct):
        data['r:' + c] = _monthly(vw[c])
    for c in cols:
        data['n:' + c] = {k: v for k, v in nf[c].items() if 99999 < k < 1000000}
        data['s:' + c] = {k: v for k, v in sz[c].items() if 99999 < k < 1000000}
    return data


def load():
    """米国: 'Hi 10','Hi 20','Hi 30' は French の列そのまま。'rest10'＝最大の十分位を除く9つ、'rest20'＝最大の五分位を除く8つ（時価加重）"""
    vw, nf, sz = _tables(h.french(FILE))
    mkt, rf = h.us_market()
    combos = {'rest10': DECILES[:9], 'rest20': DECILES[:8]}
    return _pack(vw, nf, sz, DECILES, mkt, rf, combos, direct=['Hi 20', 'Hi 30'])


def load_region(region):
    """地域: 25 Portfolios（規模5段×簿価時価5段・列は規模の小さい段から5つずつ）→ 'Hi 20'＝最上段の5つ、'rest20'＝下の4段の20個（時価加重）"""
    vw, nf, sz = _tables(h.french(f'{region}_25_Portfolios_ME_BE-ME'))
    cols = list(vw)
    assert len(cols) == 25 and cols[20] == 'BIG LoBM' and cols[24] == 'BIG HiBM', cols
    mkt, rf = h.french_region(region)
    combos = {'Hi 20': cols[20:], 'rest20': cols[:20]}
    return _pack(vw, nf, sz, cols, mkt, rf, combos)


def combo_series(data, cols):
    """列の時価加重。月 m の重みは m−1 行の 社数×平均時価（m−1 月末より前の情報）。社数0の組は重み0"""
    out = {}
    for m in data['r:' + cols[0]]:
        p = h.add_months(m, -1)
        num = den = 0.0
        ok = True
        for c in cols:
            try:
                w = data['n:' + c][p] * data['s:' + c][p]
            except KeyError:
                ok = False
                break
            if w <= 0:
                continue
            if m not in data['r:' + c]:
                ok = False
                break
            num += w * data['r:' + c][m]
            den += w
        if ok and den > 0:
            out[m] = num / den
    return out


def series(data, name):
    if name == 'mkt':
        return data['mkt']
    if name in data['_combo']:
        return combo_series(data, data['_combo'][name])
    return data['r:' + name]


# ───────────────────────── 規則の組み立て（純関数） ─────────────────────────
def build(spec, data):
    """spec: {'hold': 'Hi 10'|'Hi 20'|'Hi 30', 'alt': None|'mkt'|'rest10'|'rest20', 'lookback': J, 'skip': s, 'mode': 'mom'|'rev',
              'start': EVAL_START}
    alt=None → 買いだけ。alt あり → m−1−s 月までの J か月の累積で hold と alt を比べ、
      mode='mom' なら勝っていた側・'rev' なら負けていた側を月 m に持つ。
    → {'ret','turnover','pos'}（費用の前）"""
    hold, alt = spec['hold'], spec.get('alt')
    start = spec.get('start', EVAL_START)
    A = series(data, hold)
    ret, tov, pos = {}, {}, {}
    if not alt:
        for m in sorted(A):
            if m < start:
                continue
            ret[m] = A[m]
            tov[m] = INNER / 12
            pos[m] = hold
        return {'ret': ret, 'turnover': tov, 'pos': pos}
    B = series(data, alt)
    J, s, mode = spec['lookback'], spec.get('skip', 0), spec.get('mode', 'mom')
    prev = None
    for m in sorted(set(A) & set(B)):
        if m < start:
            continue
        past = [h.add_months(m, -(s + j)) for j in range(1, J + 1)]
        if not all(p in A and p in B for p in past):
            continue
        ga = gb = 1.0
        for p in past:
            ga *= 1 + A[p]
            gb *= 1 + B[p]
        a_wins = ga > gb
        pick = hold if (a_wins if mode == 'mom' else not a_wins) else alt
        r = A[m] if pick == hold else B[m]
        t = 0.0 if prev is None or prev == pick else 1.0
        if pick != 'mkt':
            t += INNER / 12
        ret[m], tov[m], pos[m] = r, t, pick
        prev = pick
    return {'ret': ret, 'turnover': tov, 'pos': pos}


# ───────────────────────── run（統括が選定・検定の両方で呼ぶ） ─────────────────────────
def run(spec):
    data = load()
    b = build(spec, data)
    out = {'ret': b['ret'], 'bench': data['mkt'], 'rf': data['rf'], 'turnover': b['turnover'], 'cost': COST,
           'markets': {}, 'pos': b['pos']}
    # 他の市場: 同じ凍結した規則（hold/alt の中身だけ地域の組に置き換える）。地域は 1990-07 から＝最初の12か月は勢いを測る助走
    alt = spec.get('alt')
    if spec.get('hold') == 'Hi 20' and alt in (None, 'rest20'):
        for reg in REGIONS:
            try:
                d = load_region(reg)
                bb = build(dict(spec, start=0), d)
            except Exception as e:                            # 取れない地域は黙って捨てず名前を残す
                out.setdefault('markets_missing', {})[reg] = str(e)[:160]
                continue
            if bb['ret']:
                out['markets'][reg] = {'ret': bb['ret'], 'bench': d['mkt'], 'rf': d['rf'], 'turnover': bb['turnover'], 'cost': COST}
    return out


# ───────────────────────── 先読みの検査 ─────────────────────────
def lookahead_test(spec, data, cuts=(194512, 196006, 197512, 198806, 199606), seed=11):
    """(1) X 以降の全データ（全組のリターン・社数・平均時価・市場・rf）を乱しても、pos[m≤X]・turnover[m≤X] と ret[m<X] が変わらない
         ＝月 m の持ち方は m−1 月までの情報だけで決まる（月 X の持ち方が X 月のリターンを見ていない）
       (2) データを X−1 月で切って組み立てても、X−1 までの ret・turnover・pos が全データの場合と一致する
       (3) 月 X だけに逆向きの衝撃（大型の組 ±50%・それ以外 ∓30%）を入れても pos[X] が変わらない
    → 失敗した項目の一覧（空なら合格）"""
    import random
    rnd = random.Random(seed)
    num = {k: v for k, v in data.items() if not k.startswith('_')}
    keep = {k: v for k, v in data.items() if k.startswith('_')}
    base = build(spec, data)
    bad = []
    for X in cuts:
        pert = {k: {m: (v * (1 + rnd.uniform(-0.9, 0.9)) + rnd.uniform(-0.05, 0.05) if m >= X else v) for m, v in s.items()}
                for k, s in num.items()}
        pb = build(spec, {**pert, **keep})
        for m in base['pos']:
            if m <= X and (pb['pos'].get(m) != base['pos'][m] or abs(pb['turnover'].get(m, 9) - base['turnover'][m]) > 1e-12):
                bad.append(f'perturb {X}: pos/turnover[{m}] changed')
                break
        for m in base['ret']:
            if m < X and abs(base['ret'][m] - pb['ret'].get(m, 9)) > 1e-12:
                bad.append(f'perturb {X}: ret[{m}] changed')
                break
        tr = {k: {m: v for m, v in s.items() if m < X} for k, s in num.items()}
        tb = build(spec, {**tr, **keep})
        for m in tb['ret']:
            if abs(tb['ret'][m] - base['ret'][m]) > 1e-12 or abs(tb['turnover'][m] - base['turnover'][m]) > 1e-12 or tb['pos'][m] != base['pos'][m]:
                bad.append(f'truncate {X}: month {m} differs')
                break
        before = [m for m in base['ret'] if m < X]
        if before and (not tb['ret'] or max(tb['ret']) != max(before)):
            bad.append(f'truncate {X}: last month missing')
        big = set(keep['_combo'].get('Hi 20', [])) | {'Hi 10', 'Hi 20', 'Hi 30'}
        for sgn in (1, -1):
            def shk(k):
                if not (k.startswith('r:') or k == 'mkt'):
                    return 0.0
                return 0.5 * sgn if k[2:] in big else -0.3 * sgn
            one = {k: {m: (v + shk(k) if m == X else v) for m, v in s.items()} for k, s in num.items()}
            ob = build(spec, {**one, **keep})
            if X in base['pos'] and ob['pos'].get(X) != base['pos'][X]:
                bad.append(f'shock {X}: pos[{X}] reacted to month {X} itself')
    return bad
