#!/usr/bin/env python3
"""night/edge/fam_equalweight.py — 系統 equalweight: 等加重（大きい会社の群を『等分に近い形』で持つ）

事前登録 out/edge_prereg.json（第2回で足した系統）の一系統。読むだけ・門の採点に不使用。

  考え方: 時価加重の市場は、いちばん大きい会社に最も多く賭ける。等加重は (1) 小さめの会社へ寄る（規模の効果・Banz 1981）
        (2) 毎回『上がったものを売り、下がったものを買う』戻しをする（逆張りの戻し・Plyakha, Uppal & Vilkov 2012 は
        S&P500 等加重の上乗せの一部をこれに帰した）(3) 割安側へ寄る、の三つで市場に勝ちうる（DeMiguel, Garlappi & Uppal 2009 の 1/N）。

  変種の三つの型（VARIANTS に全部を並べ、試した数を数える）:
    size_vw  French 'Portfolios_Formed_on_ME' の十分位の**時価加重**の表から、大きい側の十分位を等分に混ぜる。
             戻しは 毎月(M) / 四半期(Q＝3・6・9・12月末) / 年1回(A＝12月末)。戻さない月は前月のリターンで重みを流す。
    size_ew  同じファイルの**等加重**の表（十分位の中が等加重・French が毎月等分に戻す）。上位10/20/30% は French の列を
             そのまま使い、上位40/50% は十分位の等加重を **m−1 月の社数**で重み付けて合わせる（m 月の社数は読まない）。
    ind      French '{N}_Industry_Portfolios' の業種の時価加重リターン（業種の中は時価加重）を、業種の間は等分に持つ。
             m−1 月にリターンのある業種だけを入れる（m 月に業種が消える／現れることを前もって知らない）。

  先読みの防止: 月 m の重みは m−1 月末までのリターン・社数だけで決まる（重みは前の月のループで作り終えてから m 月の
        リターンを掛ける）。十分位・業種の組入れは French が各年6月末の時価で決めたもので、m 月より前に決まっている。
        lookahead_test() が (1) データを途中の月で切って走らせても、その月までの成績が1ビットも変わらないこと
        (2) m 月のリターンを乱数に替えても m 月の重み・回転が変わらないこと、を確かめる。

  相手: 米国市場（h.us_market＝French の CRSP 全上場の時価加重・配当込み）。
  費用: 事前登録どおり 片道の回転1あたり 0.10%（RSP 型ETF）。回転は
        ・size_vw / ind: 等分へ戻す回転（流れた重みと等分の差の絶対値の和の半分）を毎月実測。最初の月は 1。
          size_vw は French の6月末の組み替え（十分位の間の移動）を実測できないので、毎年7月に 0.20（20%/年）を足す（置き値）。
        ・size_ew: 株の単位の戻し（毎月・等分へ）は表から測れないので、毎月 0.05（60%/年）と置く（大型株の月次の
          散らばり〔標準偏差8%前後〕から見た片道の戻し 3〜4%/月＋組み替えを丸めた置き値・上側に置いた）。
  経費: 実行するETFの経費率を ret の中で毎月引く（事前登録の最低限より厳しい側）。
        規模の型は RSP（Invesco S&P 500 Equal Weight・経費率 0.20%/年）、業種の型は Select Sector SPDR（0.08〜0.09%）＝0.10%/年と置く。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as h                                                  # noqa: E402
import json, math, random

FAMILY = {
    'key': 'equalweight',
    'name': '等加重（大きい会社の群を等分に近い形で持つ）',
    'implement': ('楽天証券の米国株口座で RSP（Invesco S&P 500 Equal Weight ETF・経費率0.20%・楽天の海外ETF取扱一覧に在る）を買って持つ'
                  '（ETF の中で四半期ごとに等分へ戻すので、持つ人は何もしない）。レバレッジ型ではないので NISA の成長投資枠で買える見込み'
                  '（枠の対象かは楽天の画面で要確認）。業種の型なら Select Sector SPDR 11本（XLK・XLV・XLF など）を等分に持ち、'
                  '決めた頻度で等分へ戻す（戻しの売りは課税口座で行う）。上位10%型なら EQWL（Invesco S&P 100 Equal Weight）。'),
}

COST = 0.001            # 事前登録: 指数・ETF の入れ替え＝片道の回転100%につき 0.10%（RSP 型ETF）
DEC = {1: 'Lo 10', 2: '2-Dec', 3: '3-Dec', 4: '4-Dec', 5: '5-Dec', 6: '6-Dec', 7: '7-Dec', 8: '8-Dec', 9: '9-Dec', 10: 'Hi 10'}
EW_DIRECT = {(10,): 'Hi 10', (9, 10): 'Hi 20', (8, 9, 10): 'Hi 30'}
FEE_SIZE, FEE_IND = 0.002, 0.001
EW_TURN = 0.05          # size_ew の株の単位の回転（置き値・毎月）
RECON_TURN = 0.20       # size_vw の6月末の組み替え（置き値・7月に）

_cache = {}


def _me():
    if 'me' not in _cache:
        d = h.french('Portfolios_Formed_on_ME')
        mon = lambda s: {m: v for m, v in s.items() if m > 99999}
        vw = {i: {m: v / 100 for m, v in mon(d['Average Value Weight Returns -- Monthly'][c]).items()} for i, c in DEC.items()}
        ew_t = d['Average Equal Weighted Returns -- Monthly']
        ew = {c: {m: v / 100 for m, v in mon(s).items()} for c, s in ew_t.items()}
        nf = {c: mon(s) for c, s in d['Number of Firms in Portfolios'].items()}
        _cache['me'] = (vw, ew, nf)
    return _cache['me']


def _ind(n):
    k = f'ind{n}'
    if k not in _cache:
        d = h.french(f'{n}_Industry_Portfolios')
        _cache[k] = {i: {m: v / 100 for m, v in s.items() if m > 99999}
                     for i, s in d['Average Value Weighted Returns -- Monthly'].items()}
    return _cache[k]


def _due(m, rebal):
    mo = m % 100
    return rebal == 'M' or (rebal == 'Q' and mo in (1, 4, 7, 10)) or (rebal == 'A' and mo == 1)


def _idx(m):
    return (m // 100) * 12 + m % 100 - 1


def mix(R, rebal, fee, extra=None, record=None, due=None):
    """R: {群: {YYYYMM: 小数}} を等分に持つ。rebal: M/Q/A（due を渡せばそちらで決める）。戻さない月は重みを流す。
    → (ret, turnover)。record を渡すと {月: 重み} を書き込む（先読みの検査用）"""
    due = due or (lambda m: _due(m, rebal))
    months = sorted(set().union(*[set(s) for s in R.values()]))
    ret, tv = {}, {}
    w = None                       # 月初の重み
    for m in months:
        prev = h.add_months(m, -1)
        avail = sorted(b for b, s in R.items() if prev in s)          # m−1 月にリターンのある群（m 月は見ない）
        if not avail:
            continue
        if w is None:
            w = {b: 1 / len(avail) for b in avail}
            turn = 1.0
        else:
            turn = 0.0
            gone = [b for b in w if b not in avail]
            if gone:                                                  # 消えた群は売って残りへ按分
                g = sum(w[b] for b in gone)
                turn += g
                keep = {b: x for b, x in w.items() if b not in gone}
                s = sum(keep.values())
                w = {b: x / s for b, x in keep.items()} if s > 0 else {b: 1 / len(avail) for b in avail}
            if due(m):
                tgt = {b: 1 / len(avail) for b in avail}
                turn += 0.5 * sum(abs(tgt.get(b, 0.0) - w.get(b, 0.0)) for b in set(tgt) | set(w))
                w = tgt
        if record is not None:
            record[m] = dict(w)
        rp = sum(x * R[b].get(m, 0.0) for b, x in w.items())         # m 月に欠測の群は 0 と置く
        ret[m] = rp - fee / 12
        tv[m] = turn + (extra(m) if extra else 0.0)
        w = {b: x * (1 + R[b].get(m, 0.0)) / (1 + rp) for b, x in w.items()} if 1 + rp > 0 else w
    return ret, tv


def mix_staggered(R, period, fee, extra=None, record=None):
    """時期をずらした分割（period 個の小口）。小口 k は月の通し番号 ≡ k (mod period) の月初にだけ等分へ戻し、それ以外は流す。
    小口どうしは戻さない（それぞれ別の口座のように持つ）＝『毎月、全体のおよそ 1/period だけを等分へ戻す』。
    特定の月（1月など）を選ばないので、戻しの月の偶然に頼らない"""
    parts = []
    for k in range(period):
        rec = {} if record is not None else None
        r, t = mix(R, None, 0.0, record=rec, due=lambda m, k=k: _idx(m) % period == k)
        parts.append((r, t, rec))
    months = sorted(set().union(*[set(p[0]) for p in parts]))
    V = [1.0 / period] * period
    ret, tv = {}, {}
    for m in months:
        tot = sum(V)
        rs = [p[0].get(m, 0.0) for p in parts]
        ret[m] = sum(v * x for v, x in zip(V, rs)) / tot - fee / 12
        tv[m] = sum(v * p[1].get(m, 0.0) for v, p in zip(V, parts)) / tot + (extra(m) if extra else 0.0)
        if record is not None:
            agg = {}
            for v, p in zip(V, parts):
                for b, x in (p[2].get(m) or {}).items():
                    agg[b] = agg.get(b, 0.0) + v / tot * x
            record[m] = agg
        V = [v * (1 + x) for v, x in zip(V, rs)]
    return ret, tv


def size_ew(decs, fee, record=None):
    vw, ew, nf = _me()
    decs = tuple(sorted(decs))
    if decs in EW_DIRECT:
        s = ew[EW_DIRECT[decs]]
        ret = {m: v - fee / 12 for m, v in s.items()}
        if record is not None:
            for m in s:
                record[m] = {EW_DIRECT[decs]: 1.0}
    else:
        ret = {}
        months = sorted(set.intersection(*[set(ew[DEC[d]]) for d in decs]))
        for m in months:
            prev = h.add_months(m, -1)
            cnt = {d: nf[DEC[d]].get(prev, 0) for d in decs}               # m−1 月の社数（m 月の社数は読まない）
            tot = sum(cnt.values())
            if tot <= 0:
                continue
            wt = {d: c / tot for d, c in cnt.items()}
            if record is not None:
                record[m] = wt
            ret[m] = sum(wt[d] * ew[DEC[d]][m] for d in decs) - fee / 12
    ms = sorted(ret)
    tv = {m: (1.0 if i == 0 else EW_TURN) for i, m in enumerate(ms)}
    return ret, tv


def run(spec, record=None):
    mkt, rf = h.us_market()
    t = spec['type']
    if t == 'size_vw':
        vw, _, _ = _me()
        R = {d: vw[d] for d in spec['deciles']}
        ret, tv = mix(R, spec['rebal'], spec.get('fee', FEE_SIZE), extra=lambda m: RECON_TURN if m % 100 == 7 else 0.0, record=record)
    elif t == 'size_ew':
        ret, tv = size_ew(spec['deciles'], spec.get('fee', FEE_SIZE), record=record)
    elif t == 'ind':
        if spec['rebal'] == 'stag':
            ret, tv = mix_staggered(_ind(spec['n']), spec['period'], spec.get('fee', FEE_IND), record=record)
        else:
            ret, tv = mix(_ind(spec['n']), spec['rebal'], spec.get('fee', FEE_IND), record=record)
    else:
        raise ValueError(t)
    return {'ret': ret, 'bench': mkt, 'rf': rf, 'turnover': tv, 'cost': COST, 'markets': {}}


# ───────────────────────── 変種（試した数を正直に数える） ─────────────────────────
def _nm(s):
    if s['type'] == 'size_vw':
        return f"十分位{min(s['deciles'])}-10の時価加重を等分・戻し{s['rebal']}"
    if s['type'] == 'size_ew':
        return f"上位{len(s['deciles'])*10}%を株で等加重（毎月）"
    if s['rebal'] == 'stag':
        return f"{s['n']}業種を等分・{s['period']}か月ごと（時期をずらした小口）"
    return f"{s['n']}業種を等分・戻し{s['rebal']}"


VARIANTS = (
    [{'type': 'size_vw', 'deciles': list(range(a, 11)), 'rebal': 'M'} for a in (9, 8, 7, 6, 5)]
    + [{'type': 'size_vw', 'deciles': list(range(a, 11)), 'rebal': r} for r in ('Q', 'A') for a in (9, 8, 6)]
    + [{'type': 'size_ew', 'deciles': list(range(a, 11))} for a in (10, 9, 8, 7, 6)]
    + [{'type': 'ind', 'n': n, 'rebal': 'M'} for n in (5, 10, 12, 17, 30, 49)]
    + [{'type': 'ind', 'n': n, 'rebal': r} for r in ('Q', 'A') for n in (10, 49)]
    # 第二段（最初の26本を見た後に足した・試した数に数える）: 業種は戻しを減らすほど良かった（業種の勢い〔1〜12か月〕に
    # 逆らわず、長い期間の戻り〔DeBondt & Thaler 1985・3〜5年〕を取る、という筋）→ 年1回の格子を埋め、
    # 1月という特定の月に頼っていないか（年末の節税売りの戻り）を時期をずらした小口で確かめ、戻しの間隔を3年・5年へ延ばす
    + [{'type': 'ind', 'n': n, 'rebal': 'A'} for n in (5, 12, 17, 30)]
    + [{'type': 'ind', 'n': n, 'rebal': 'stag', 'period': 12} for n in (10, 49)]
    + [{'type': 'ind', 'n': 10, 'rebal': 'stag', 'period': p} for p in (36, 60)]
    + [{'type': 'size_vw', 'deciles': list(range(5, 11)), 'rebal': 'A'}]
    # 第三段: 1月に戻す年1回は『特定の月』に頼る分がある（10業種: 1月 0.96 → ずらした小口 0.87）ので、月に頼らない
    # ずらした小口（12か月）を残りの業種の粒度にも当てる（選ぶ土俵を月に中立な変種にそろえるため）
    + [{'type': 'ind', 'n': n, 'rebal': 'stag', 'period': 12} for n in (5, 12, 17, 30)]
)


def evaluate_all():
    rows = []
    for s in VARIANTS:
        r = run(s)
        st = h.stats(r['ret'], r['bench'], r['rf'], turnover=r['turnover'], cost=r['cost'])
        rows.append({'name': _nm(s), 'spec': s, 'stats': st})
    return rows


# ───────────────────────── 先読みの検査 ─────────────────────────
def lookahead_test(spec, cuts=(195012, 197012, 199012), n_perturb=40, seed=7):
    """(1) 全データを cut で切って走らせた成績が、全期間（〜2000-12）で走らせた成績の cut までと完全に一致するか
    (2) m 月の全群のリターンを乱数に替えても、m 月の重み・回転が変わらないか（同じ月の先読みの検査）"""
    out = {'truncate': {}, 'perturb': None}
    full_rec = {}
    full = run(spec, record=full_rec)

    orig_guard_end = h.SEL_END
    for cut in cuts:
        _cache.clear()
        h.SEL_END = cut
        try:
            part = run(spec)
        finally:
            h.SEL_END = orig_guard_end
            _cache.clear()
        bad = [m for m in part['ret'] if m <= cut and (m not in full['ret'] or abs(part['ret'][m] - full['ret'][m]) > 1e-12
                                                       or abs(part['turnover'][m] - full['turnover'][m]) > 1e-12)]
        n = sum(1 for m in part['ret'] if m <= cut)
        out['truncate'][cut] = {'months': n, 'diffs': len(bad), 'last_month_in_part': max(part['ret']) if part['ret'] else None}

    # (2) 乱す
    rnd = random.Random(seed)
    months = sorted(full_rec)
    picks = rnd.sample(months[24:], min(n_perturb, len(months) - 24))
    bad = 0
    for m in picks:
        _cache.clear()
        _load_all(spec)
        _perturb(spec, m, rnd)
        rec = {}
        pr = run(spec, record=rec)
        if any(abs(rec[m].get(k, 0) - full_rec[m].get(k, 0)) > 1e-12 for k in set(rec[m]) | set(full_rec[m])):
            bad += 1
        elif abs(pr['turnover'][m] - full['turnover'][m]) > 1e-12:
            bad += 1
        elif any(abs(pr['ret'][x] - full['ret'][x]) > 1e-12 for x in pr['ret'] if x < m):
            bad += 1
    _cache.clear()
    out['perturb'] = {'months_tested': len(picks), 'weight_or_past_changed': bad}
    out['ok'] = all(v['diffs'] == 0 for v in out['truncate'].values()) and bad == 0
    return out


def _load_all(spec):
    _me()
    if spec['type'] == 'ind':
        _ind(spec['n'])


def _perturb(spec, m, rnd):
    """キャッシュの中の m 月のリターン（全群）を乱数に替える"""
    if spec['type'] == 'ind':
        R = _cache[f"ind{spec['n']}"]
        for s in R.values():
            if m in s:
                s[m] = rnd.uniform(-0.3, 0.3)
    else:
        vw, ew, nf = _cache['me']
        for s in list(vw.values()) + list(ew.values()):
            if m in s:
                s[m] = rnd.uniform(-0.3, 0.3)
        for s in nf.values():                              # m 月の社数も乱す（読まないはず）
            if m in s:
                s[m] = rnd.randint(1, 999)


if __name__ == '__main__':
    rows = evaluate_all()
    for x in rows:
        st = x['stats']
        print(f"{x['name']:34} {st['from']}-{st['to']} 年率{st['cagr']:6.2f} 市場{st['bench_cagr']:6.2f} 超過{st['excess']:6.2f} "
              f"算術{st['ex_arith']:6.2f} t{st['t']:5.2f} NW{st['t_nw']:5.2f} ぶれ{st['vol']}/{st['bench_vol']} "
              f"下落{st['maxdd']}/{st['bench_maxdd']} 10年{st['roll10_win']}")
