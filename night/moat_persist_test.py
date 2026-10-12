#!/usr/bin/env python3
"""night/moat_persist_test.py — 堀の5本は『その後も利益率が残ったか』を当てるか（2026-10-11新設・読むだけ）

事前登録 out/moat_persist_prereg.json（f5321cc・結果を1件も見る前にコミット）のとおりに一度だけ裁く。
門の採点・刻み・重み・関門・売却規律には触れない（絶対のルール1）。決断待ち moat_redesign_1011 の①。

何を測るか:
  堀＝高い資本利益率を競争から守り続ける力。株価ではなく事業の持続で答え合わせする——
  入口の水準から予想される以上に、その後も利益率が残ったか（驚き）。
  驚き＝入口の値の順位から前方の値の順位を線形回帰した残差（retro_surprise.split をそのまま使う）。
  O1（主） 前方 +6〜+10年の ROIC の中央値（fwd_roic_med5_a2）／錨 入口の roic_med5
  O2（副） asof+10年の営業利益率（fwd_opm_10y）／錨 入口の opm
  O3（副） 前方 +1〜+5年の ROIC（fwd_roic_med5_a1）／錨 入口の roic_med5
  O4（副） 入口 roic_med5≥0.15 の社が +6〜+10年に 0.08 未満へ落ちた割合（上の段 対 残り）
入力（在庫・追加取得ゼロ）:
  out/retro_moat_pillars_{2013,2015}.json（rep・dur・dom・moatW）／out/retro_moat_2013{,q}・2015{,q,qb}.json（irr・moat5）
  out/irr70_regrade_{map,grades}.json（irr の 70/75 を今日の規約で盲検再採点・副）
  out/retro_cohort_{2013,2015}.json（gate0 式の ROIC＝のれん込み・USD 報告だけ）／out/retro_sic.json（業種）
出力: out/moat_persist.json
"""
import datetime, json, math, os, random, statistics as S, sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
import retro_surprise as RS        # noqa: E402  split（驚き）・prices（自己検問）
import irr_rung_audit as IRA       # noqa: E402  semi_map（半導体連鎖）
import audit_moat_gap as AG        # noqa: E402  moat_idx（今日の ccfMoat と同値・index.html の重みを読む）

OUT = os.path.join(BASE, 'out')
PRE = os.path.join(OUT, 'moat_persist_prereg.json')
NPERM, SEED = 2000, 20261011
VINT = (2013, 2015)
PREV = {2013: ['retro_moat_2013.json', 'retro_moat_2013q.json'],
        2015: ['retro_moat_2015.json', 'retro_moat_2015q.json', 'retro_moat_2015qb.json']}
PILLARS = ['irr', 'rep', 'dur', 'moatW', 'dom']            # 主（この順が置換の種の番号）
TOP = {'irr': 70, 'rep': 80, 'dur': 75, 'dom': 70, 'moatW': 85}   # O4 の上の段
MODE_CAP, MIN_N, MIN_N_VINT = 0.85, 150, 100
OUTCOMES = {'O1': ('roic_med5', 'fwd_roic_med5_a2', '前方 +6〜+10年の ROIC の驚き（錨 入口 roic_med5）'),
            'O2': ('opm', 'fwd_opm_10y', '+10年の営業利益率の驚き（錨 入口 opm）'),
            'O3': ('roic_med5', 'fwd_roic_med5_a1', '前方 +1〜+5年の ROIC の驚き（錨 入口 roic_med5）')}


def rows(name):
    p = os.path.join(OUT, name)
    if not os.path.exists(p):
        raise SystemExit(f'✗ 在庫が無い: {name}')
    d = json.load(open(p))
    return d['rows'] if isinstance(d, dict) and 'rows' in d else d


def num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def ranks(xs):
    o = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs)
    i = 0
    while i < len(o):
        j = i
        while j + 1 < len(o) and xs[o[j + 1]] == xs[o[i]]:
            j += 1
        for k in range(i, j + 1):
            r[o[k]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return r


def spear(a, b, floor=20):
    if len(a) < floor:
        return None
    x, y = ranks(a), ranks(b)
    n = len(x)
    mx, my = sum(x) / n, sum(y) / n
    num_ = sum((x[i] - mx) * (y[i] - my) for i in range(n))
    dx = math.sqrt(sum((v - mx) ** 2 for v in x))
    dy = math.sqrt(sum((v - my) ** 2 for v in y))
    return num_ / (dx * dy) if dx > 0 and dy > 0 else None


def perm(a, b, strata, seed, floor=20):
    """ビンテージ（strata）の中で b を入れ替える置換・両側"""
    obs = spear(a, b, floor)
    if obs is None:
        return None, None
    rnd = random.Random(seed)
    groups = {}
    for i, s in enumerate(strata):
        groups.setdefault(s, []).append(i)
    hit = 0
    y = list(b)
    for _ in range(NPERM):
        for idx in groups.values():
            vals = [y[i] for i in idx]
            rnd.shuffle(vals)
            for i, v in zip(idx, vals):
                y[i] = v
        r = spear(a, y, floor)
        if r is not None and abs(r) >= abs(obs):
            hit += 1
    return obs, hit / NPERM


def partial(a, b, c):
    ab, ac, bc = spear(a, b), spear(a, c), spear(b, c)
    if None in (ab, ac, bc):
        return None
    d = math.sqrt((1 - ac * ac) * (1 - bc * bc))
    return (ab - ac * bc) / d if d > 0 else None


def holm(pvals):
    """{k: p} → {k: 調整後 p}"""
    ks = sorted(pvals, key=lambda k: pvals[k])
    m, out, run = len(ks), {}, 0.0
    for i, k in enumerate(ks):
        run = max(run, min(1.0, (m - i) * pvals[k]))
        out[k] = run
    return out


def load():
    """ビンテージごとの {ticker: dict}。柱・irr・moat5・今日の規約の irr・入口と前方・SIC・規模"""
    sic = {r['ticker']: r for r in rows('retro_sic.json')}
    semi = IRA.semi_map()
    rmap = json.load(open(os.path.join(OUT, 'irr70_regrade_map.json')))['key']
    rgr = {x['id']: x['verdict'] for x in json.load(open(os.path.join(OUT, 'irr70_regrade_grades.json')))['items']}
    regrade = {}
    for k, v in rmap.items():
        regrade.setdefault(int(v['v']), {})[v['t']] = (v['irr'], rgr.get(k))
    D = {}
    for y in VINT:
        pil = {r['ticker']: r for r in rows(f'retro_moat_pillars_{y}.json') if r.get('ticker')}
        prev = {}
        for f in PREV[y]:
            for r in rows(f):
                t = r.get('ticker') or r.get('t')
                if t and t not in prev:
                    prev[t] = r
        co = {r['ticker']: r for r in rows(f'retro_cohort_{y}.json') if r.get('ticker')}
        V = {}
        for t, r in pil.items():
            p = prev.get(t, {})
            irr = num(p.get('irr'))
            it = irr
            if irr in (70, 75):
                g = regrade.get(y, {}).get(t)
                it = None if (g is None or g[1] not in ('keep70', 'demote50')) else (70 if g[1] == 'keep70' else 50)
            c = co.get(t, {})
            d = dict(irr=irr, irr_today=it, moat5=num(p.get('moat5')),
                     rep=num(r.get('rep')), dur=num(r.get('dur')), dom=num(r.get('dom')), moatW=num(r.get('moatW')),
                     sic2=(sic.get(t) or {}).get('sic2'), semi=bool(semi.get(t, (False,))[0]),
                     rev=num(c.get('rev_asof')))
            for k in ('roic_med5', 'opm', 'fwd_roic_med5_a2', 'fwd_roic_med5_a1', 'fwd_opm_10y'):
                d[k] = num(c.get(k))
            mi = AG.moat_idx({k: d[k] for k in ('dom', 'irr', 'rep', 'dur', 'moatW')})
            d['moat_today'] = mi.get('idx') if isinstance(mi, dict) else mi
            V[t] = d
        D[y] = V
    return D


def surprises(D):
    """各ビンテージの読解の社の中で、目的変数ごとに驚きを作り順位の割合（0〜1）にする"""
    S_ = {}
    for y, V in D.items():
        S_[y] = {}
        for o, (e, f, _) in OUTCOMES.items():
            tk = [t for t, d in V.items() if d[e] is not None and d[f] is not None]
            _fit, res, r2 = RS.split([V[t][e] for t in tk], [V[t][f] for t in tk])
            rk = ranks(res)
            S_[y][o] = {'pct': {t: rk[i] / len(tk) for i, t in enumerate(tk)}, 'n': len(tk),
                        'r2_entry': round(r2, 3) if r2 is not None else None}
    return S_


def self_check():
    """retro_surprise と同じ作り方（錨 roic_med5・株価のある社だけ・その標本の中で回帰）で O3 の irr の ρ を再現"""
    want = {2013: (222, 0.187), 2015: (439, 0.077)}
    got = {}
    for y in VINT:
        m = {}
        for f in PREV[y]:
            for r in rows(f):
                t, v = r.get('ticker'), r.get('irr')
                if t and v is not None and t not in m:
                    m[t] = v
        co = {r['ticker']: r for r in rows(f'retro_cohort_{y}.json') if r.get('ticker')}
        px = RS.prices(y)
        tk = [t for t in m if t in co and co[t].get('roic_med5') is not None
              and co[t].get('fwd_roic_med5_a1') is not None and t in px]
        _f, res, _ = RS.split([co[t]['roic_med5'] for t in tk], [co[t]['fwd_roic_med5_a1'] for t in tk])
        r = spear([m[t] for t in tk], res)
        got[y] = (len(tk), round(r, 3))
        if got[y] != want[y]:
            raise SystemExit(f'✗ 自己検問: {y} の irr→驚き（O3 相当）が retro_surprise.json と違う（{got[y]} 対 {want[y]}）')
    return {str(y): {'n': got[y][0], 'rho': got[y][1], '錨（retro_surprise.json）': list(want[y])} for y in VINT}


def pooled(D, S_, o, key, filt=None, sic_adjust=False):
    """社単位: 各社は最新のビンテージ（2015 に読まれた社は 2015）で1回だけ。戻り (値, 驚き, ビンテージ, 社)"""
    read15 = set(D[2015])
    a, b, st, tk = [], [], [], []
    for y in (2015, 2013):
        pct = S_[y][o]['pct']
        if sic_adjust:
            pct = sic_pct(D[y], pct)
        for t, d in D[y].items():
            if y == 2013 and t in read15:
                continue
            v = d.get(key)
            if v is None or t not in pct or (filt and not filt(d)):
                continue
            a.append(v); b.append(pct[t]); st.append(y); tk.append(t)
    return a, b, st, tk


def vint(D, S_, o, key, y, only=None):
    pct = S_[y][o]['pct']
    tk = [t for t, d in D[y].items() if d.get(key) is not None and t in pct and (only is None or t in only)]
    return [D[y][t][key] for t in tk], [pct[t] for t in tk]


def sic_pct(V, pct):
    """業種（SIC2・3社以上）の中の順位の割合に直す"""
    g = {}
    for t in pct:
        s = V[t].get('sic2')
        if s:
            g.setdefault(s, []).append(t)
    out = {}
    for s, ts in g.items():
        if len(ts) < 3:
            continue
        rk = ranks([pct[t] for t in ts])
        for i, t in enumerate(ts):
            out[t] = rk[i] / len(ts)
    return out


def grade_table(a, b):
    g = {}
    for v, x in zip(a, b):
        g.setdefault(v, []).append(x)
    return {str(k): {'n': len(v), '驚きの中央値': round(S.median(v), 3)} for k, v in sorted(g.items())}


def main():
    pre = json.load(open(PRE))
    chk = self_check()
    D = load()
    S_ = surprises(D)
    read13 = set(D[2013])
    res = {'generated': datetime.date.today().isoformat(), 'tool': 'night/moat_persist_test.py',
           '事前登録': 'out/moat_persist_prereg.json（f5321cc）',
           '注記（事前登録の文に無いもの）': 'O4 の moat5（≥4）の行と、参考の3つ（moat5・今日の堀指数・irr の今日の規約での再採点）の O3 の行は'
                                         '事前登録の文に無い（コードには結果を見る前に入れた）＝参考。判定には使っていない',
           '自己検問（retro_surprise の再現）': chk,
           '母集団（驚きを作った社の数）': {str(y): {o: S_[y][o]['n'] for o in OUTCOMES} for y in VINT},
           '入口が前方を予言した割合（順位の R²）': {str(y): {o: S_[y][o]['r2_entry'] for o in OUTCOMES} for y in VINT}}

    # ── 主の判定（O1） ──
    prim, pv = {}, {}
    for i, k in enumerate(PILLARS):
        a, b, st, tk = pooled(D, S_, 'O1', k)
        vals = [x for x in a]
        mode = max((vals.count(v) for v in set(vals)), default=0) / max(1, len(vals))
        rec = {'n_社単位': len(a), '最頻値の占有': round(mode, 3)}
        if mode >= MODE_CAP:
            rec['判定'] = '測れない（最頻値の占有≥0.85）'
        elif len(a) < MIN_N:
            rec['判定'] = '判定不能（n<150）'
        else:
            r, p = perm(a, b, st, SEED + i)
            rec.update(rho=round(r, 3), p=round(p, 4))
            pv[k] = p
        a15, b15 = vint(D, S_, 'O1', k, 2015)
        a13, b13 = vint(D, S_, 'O1', k, 2013)
        oos = set(D[2015]) - read13
        ao, bo = vint(D, S_, 'O1', k, 2015, only=oos)
        rec['2015だけ'] = {'n': len(a15), 'rho': None if spear(a15, b15) is None else round(spear(a15, b15), 3)}
        rec['2013だけ'] = {'n': len(a13), 'rho': None if spear(a13, b13) is None else round(spear(a13, b13), 3)}
        rec['2015の厳密OOS（2013で読んでいない社）'] = {'n': len(ao), 'rho': None if spear(ao, bo) is None else round(spear(ao, bo), 3)}
        rec['刻みごと（社単位）'] = grade_table(a, b)
        prim[k] = rec
    adj = holm(pv)
    for k in pv:
        rec = prim[k]
        rec['p_Holm'] = round(adj[k], 4)
        c1 = rec['rho'] > 0 and adj[k] < 0.05
        if rec['2013だけ']['n'] >= MIN_N_VINT:
            c23 = (rec['2015だけ']['rho'] or 0) > 0 and (rec['2013だけ']['rho'] or 0) > 0
            how = '②2015 ρ>0 ③2013 ρ>0'
        else:
            c23 = (rec['2015の厳密OOS（2013で読んでいない社）']['rho'] or 0) > 0
            how = '②③の代わりに 2015 の厳密OOS ρ>0（2013 の n<100）'
        if c1 and c23:
            rec['判定'] = '合格（事業の持続を当てる）'
        elif rec['rho'] < 0 and rec['p'] < 0.05:
            rec['判定'] = '逆（高い段ほど利益率が残らない）'
        else:
            why = []
            if not (rec['rho'] > 0):
                why.append('社単位の ρ が正でない')
            elif not adj[k] < 0.05:
                why.append(f'Holm 調整の p={adj[k]:.3f} が0.05に届かない')
            if not c23:
                why.append(f'符号の再現（{how}）を満たさない')
            rec['判定'] = '不合格（' + '・'.join(why) + '）'
        rec['再現の条件'] = how
    res['主の判定（O1: 前方 +6〜+10年の ROIC の驚き）'] = prim

    # ── 副: O2・O3 と参考の3つ ──
    sec = {}
    for o in ('O1', 'O2', 'O3'):
        sec[o] = {'説明': OUTCOMES[o][2]}
        for i, k in enumerate(PILLARS + ['moat5', 'moat_today', 'irr_today']):
            a, b, st, tk = pooled(D, S_, o, k)
            if len(a) < 30:
                sec[o][k] = {'n': len(a), 'note': 'n<30'}
                continue
            r, p = perm(a, b, st, SEED + 100 * (1 + list(OUTCOMES).index(o)) + i)
            a15, b15 = vint(D, S_, o, k, 2015)
            a13, b13 = vint(D, S_, o, k, 2013)
            sec[o][k] = {'n': len(a), 'rho': round(r, 3), 'p': round(p, 4),
                         'rho_2015': None if spear(a15, b15) is None else round(spear(a15, b15), 3),
                         'rho_2013': None if spear(a13, b13) is None else round(spear(a13, b13), 3)}
    res['副: 目的変数ごと・参考の3つ（社単位・置換の p は調整なし）'] = sec

    # ── 副: 頑健さ（O1） ──
    rob = {}
    for i, k in enumerate(PILLARS + ['moat5', 'moat_today']):
        a, b, st, tk = pooled(D, S_, 'O1', k)
        if len(a) < 30:
            continue
        rev = []
        okr = True
        for t, y in zip(tk, st):
            v = D[y][t].get('rev')
            if v is None:
                okr = False
                break
            rev.append(v)
        an, bn, sn, _ = pooled(D, S_, 'O1', k, filt=lambda d: not d['semi'])
        ai, bi, si, _ = pooled(D, S_, 'O1', k, sic_adjust=True)
        rn = perm(an, bn, sn, SEED + 300 + i)
        ri = perm(ai, bi, si, SEED + 400 + i)
        rob[k] = {'規模を除いた偏順位相関': None if not okr or partial(a, b, rev) is None else round(partial(a, b, rev), 3),
                  '半導体連鎖を除く': {'n': len(an), 'rho': None if rn[0] is None else round(rn[0], 3), 'p': None if rn[1] is None else round(rn[1], 4)},
                  '業種（SIC2）の中の順位で作り直す': {'n': len(ai), 'rho': None if ri[0] is None else round(ri[0], 3), 'p': None if ri[1] is None else round(ri[1], 4)}}
    res['副: 頑健さ（O1）'] = rob

    # ── 副: 柱どうしの順位相関（社単位・両方そろう社） ──
    cor = {}
    keys = PILLARS + ['moat5']
    for i, k1 in enumerate(keys):
        for k2 in keys[i + 1:]:
            pa, pb = [], []
            for y in (2015, 2013):
                for t, d in D[y].items():
                    if y == 2013 and t in D[2015]:
                        continue
                    if d.get(k1) is not None and d.get(k2) is not None:
                        pa.append(d[k1]); pb.append(d[k2])
            r = spear(pa, pb, 30)
            cor[f'{k1}×{k2}'] = {'n': len(pa), 'rho': None if r is None else round(r, 3)}
    res['副: 柱どうしの順位相関'] = cor

    # ── 副: O4 左の裾 ──
    tail = {}
    for i, k in enumerate(PILLARS + ['moat5']):
        flags, tops, st = [], [], []
        for y in (2015, 2013):
            for t, d in D[y].items():
                if y == 2013 and t in D[2015]:
                    continue
                if d.get(k) is None or d['roic_med5'] is None or d['fwd_roic_med5_a2'] is None or d['roic_med5'] < 0.15:
                    continue
                flags.append(1 if d['fwd_roic_med5_a2'] < 0.08 else 0)
                tops.append(d[k] >= (TOP.get(k, 4)))
                st.append(y)
        if len(flags) < 30:
            continue
        def rate(sel):
            v = [f for f, s in zip(flags, sel) if s]
            return (sum(v) / len(v), len(v)) if v else (None, 0)
        rt, nt = rate(tops)
        rr, nr = rate([not x for x in tops])
        diff = None if rt is None or rr is None else rt - rr
        p = None
        if diff is not None:
            rnd = random.Random(SEED + 500 + i)
            hit = 0
            groups = {}
            for j, s in enumerate(st):
                groups.setdefault(s, []).append(j)
            for _ in range(NPERM):
                f2 = list(flags)
                for idx in groups.values():
                    vals = [f2[j] for j in idx]
                    rnd.shuffle(vals)
                    for j, v in zip(idx, vals):
                        f2[j] = v
                a1 = [f for f, s in zip(f2, tops) if s]
                a2 = [f for f, s in zip(f2, tops) if not s]
                if a1 and a2 and abs(sum(a1) / len(a1) - sum(a2) / len(a2)) >= abs(diff):
                    hit += 1
            p = hit / NPERM
        tail[k] = {'上の段の定義': f'≥{TOP.get(k, 4)}', '上の段': {'n': nt, '破れた割合': None if rt is None else round(rt, 3)},
                   '残り': {'n': nr, '破れた割合': None if rr is None else round(rr, 3)},
                   '差': None if diff is None else round(diff, 3), 'p': None if p is None else round(p, 4)}
    res['副: O4 左の裾（入口 ROIC≥15% の社が +6〜+10年に 8% 未満へ落ちた割合）'] = tail

    res['合格した柱'] = [k for k, r in prim.items() if str(r.get('判定', '')).startswith('合格')]
    with open(os.path.join(OUT, 'moat_persist.json'), 'w', encoding='utf-8') as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print('自己検問', chk)
    print('母集団', res['母集団（驚きを作った社の数）'], 'R²', res['入口が前方を予言した割合（順位の R²）'])
    for k, r in prim.items():
        print(f"{k:6} n={r['n_社単位']:4} 最頻{r['最頻値の占有']:.2f} ρ={r.get('rho')} p={r.get('p')} Holm={r.get('p_Holm')} "
              f"| 2015 {r['2015だけ']} 2013 {r['2013だけ']} OOS {r['2015の厳密OOS（2013で読んでいない社）']} → {r['判定']}")
        print('        刻み', r['刻みごと（社単位）'])
    for o, d in sec.items():
        print(o, {k: (v.get('n'), v.get('rho'), v.get('p'), v.get('rho_2015'), v.get('rho_2013')) for k, v in d.items() if isinstance(v, dict)})
    for k, v in rob.items():
        print('頑健', k, v)
    print('相関', {k: v['rho'] for k, v in cor.items()})
    for k, v in tail.items():
        print('左の裾', k, v)
    print('書いた out/moat_persist.json')


if __name__ == '__main__':
    main()
