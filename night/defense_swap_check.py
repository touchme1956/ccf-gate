#!/usr/bin/env python3
"""night/defense_swap_check.py — 守りの本どうしで替えてもいいものはあるか（2026-11-04・参考・配分は変えない）

ユーザー「守り同士で替えてもいいのがないかもっと検証して」。門・採点・配分（portfolio.json）・注文書には触れない。
★形・候補・物差し・同等の幅・分け方・勧めの決まりはこの頭のとおりで、結果を見る前にこのファイルをコミットする。

今（portfolio.json と照合）: NASDAQ100 40 / SMH 20 / ITA 15 / XLV 10 / VBR 15。伸びの側（NASDAQ100 40・SMH 20）は動かさない。
守りの候補 28本＝best15 の物差しの本33本（best15_check.pool_list）から伸びの本（QQQM・SMH・XLK・XLY・VUG）を除いた全部
  （ITA・XLV・FBT・GDX・SLV・GLDM・XLU・XLP・XLE・XLF・XLI・VTV・VBR・IJR・VOO・MOAT・VT・VEA・VWO・PXF・DEM・EPI_LONG・EWY・
   EDV・TLT・TIP・TOPIX・UST_HEDGED_2621）。楽天の一覧（out/broker_lineup.json）で米国上場の本はすべて買える・TOPIX と 2621 は東証。
入れ替え:
 ①1本の入れ替え: 今の守りの本 H（ITA 15・XLV 10・VBR 15）から a（5・10・H の全部）を候補 Y へ。Y が今の守りの本でもよい（守りの中の比の付け替え）。
 ②守りの40%の組み直し（--blocks）: 候補28本から最大4本・5%刻みで40%を組む全部（788,095通り）。
物差し（今との差・すべて既存の関数）:
 期待値の側: 元の平均（π加重の年率）・元の15%以上・業種の基礎率の平均（感度6本・best15r.FastBR）・100年の代用の30年の積立の中央（best15.Cent）・
   実績（2000-09〜の転がる20年の毎月の積立）の年15%以上の割合と年率の中央（five_mix_ndx.realized）
 守りの側: 元の5%未満・元の最悪の世界・最大下落（USD・2000-09〜）・円の最大下落・基礎率の5%未満（主）・100年の代用の30年の最悪・
   暴落の4局面での全体の騰落（ドットコム後半 2000-09〜2002-09・金融危機 2007-11〜2009-02・コロナ 2020-01〜2020-03・2022年 2022-01〜2022-09・
   月次・毎月組み直し・費用前）
同等の幅（これより小さい差は「同じ」と読む）: 平均 0.05pt・15%以上 0.5pt・5%未満 0.5pt・最悪の世界 0.05pt・最大下落 1pt・円の最大下落 1pt・
   基礎率の平均 0.05pt（感度6本のどれか1本でも幅を超えて下がれば「悪い」・6本すべてで幅を超えて上がれば「良い」）・100年 0.02・
   実績の15%以上の割合 3pt・実績の年率の中央 0.2pt・暴落の局面 1pt
分け方:
  替えないほうがいい＝どれか1つでも幅を超えて悪い／良い＝悪いものが無く、期待値の側と守りの側の両方で幅を超えて良いものがある／
  守りが厚くなる＝悪いものが無く守りの側だけ良い／期待値が上がる＝悪いものが無く期待値の側だけ良い／同等＝悪いものも良いものも無い。
  100年の写しが無い本（金・銀・国債・米国外・ワイドモート・全世界ほか）を含む形は100年の2つを測れない＝その旨を添え、「良い」にはしない（最高で「同等以上（100年は測れない）」）。
勧めの決まり: ①の中に「良い」があれば、良い物差しの数が最も多い形（同じなら動かす量が小さい形→基礎率の平均〔主〕が高い形）。
  無ければ「今のまま」とし、「守りが厚くなる」「期待値が上がる」「同等」の入れ替えを『替えてもいい（好みの差）』として並べる。
⚠ 限界: 未来の世界は予想・分散の上乗せは仮定・実績と暴落の局面は一つの歴史（2000年以降）・100年の写しは業種の代わり・
  788,095通りから上を選べば偶然で良く見える形も混じる・税・NISA の枠・為替ヘッジの費用は見ない
使い方: python3 night/defense_swap_check.py（①）→ out/defense_swap_check.json ／ --blocks（②）→ out/defense_swap_blocks.json
"""
import contextlib, io, itertools, json, os, sys, time
import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
BLOCKS = '--blocks' in sys.argv
OUT = os.path.join(BASE, 'out', 'defense_swap_blocks.json' if BLOCKS else 'defense_swap_check.json')

import best15_check as B   # noqa: E402
import best15r_check as BR  # noqa: E402
from five_mix_ndx_check import realized  # noqa: E402

NOW = {'QQQM': 40, 'SMH': 20, 'ITA': 15, 'XLV': 10, 'VBR': 15}
FIXED = {'QQQM': 40, 'SMH': 20}
CUR_DEF = {'ITA': 15, 'XLV': 10, 'VBR': 15}
GROWTH = {'QQQM', 'SMH', 'XLK', 'XLY', 'VUG'}
CRASH = {'ドットコム後半 2000-09〜2002-09': (200009, 200209), '金融危機 2007-11〜2009-02': (200711, 200902),
         'コロナ 2020-01〜2020-03': (202001, 202003), '2022年 2022-01〜2022-09': (202201, 202209)}
# (鍵, 日本語, 側, 向き〔+1 は大きいほど良い〕, 同等の幅)
MEAS = [('mean', '元の平均', 'ret', 1, 0.05), ('p15', '元の15%以上', 'ret', 1, 0.5), ('br', '基礎率の平均（感度6本）', 'ret', 1, 0.05),
        ('cmed', '100年の30年の中央', 'ret', 1, 0.02), ('rshare', '実績の20年積立で年15%以上', 'ret', 1, 3.0), ('rmed', '実績の20年積立の年率の中央', 'ret', 1, 0.2),
        ('p5', '元の5%未満', 'def', -1, 0.5), ('worst', '元の最悪の世界', 'def', 1, 0.05), ('mdd', '最大下落（USD）', 'def', 1, 1.0),
        ('mddj', '円の最大下落', 'def', 1, 1.0), ('brp5', '基礎率の5%未満', 'def', -1, 0.5), ('cmin', '100年の30年の最悪', 'def', 1, 0.02)] + \
       [(f'crash{i}', k, 'def', 1, 1.0) for i, k in enumerate(CRASH)]
JA = dict(ITA='ITA（防衛）', XLV='XLV（ヘルスケア）', VBR='VBR（米国小型バリュー）', FBT='FBT（バイオ）', GDX='GDX（金鉱株）', SLV='SLV（銀）',
          GLDM='GLDM（金）', XLU='XLU（公益）', XLP='XLP（生活必需品）', XLE='XLE（エネルギー）', XLF='XLF（金融）', XLI='XLI（産業）',
          VTV='VTV（米国大型バリュー）', IJR='IJR（米国小型）', VOO='VOO（S&P500）', MOAT='MOAT（ワイドモート）', VT='VT（全世界）',
          VEA='VEA（先進国）', VWO='VWO（新興国）', PXF='PXF（先進国バリュー）', DEM='DEM（新興国高配当）', EPI_LONG='EPI（インド）',
          EWY='EWY（韓国）', EDV='EDV（米国超長期国債）', TLT='TLT（米国長期国債）', TIP='TIP（物価連動国債）', TOPIX='TOPIX（日本株）',
          UST_HEDGED_2621='2621（円ヘッジ米国債）')


def log(*a):
    print('[defense_swap]', *a, file=sys.stderr, flush=True)


class Meas:
    def __init__(self):
        import unx_assets as U
        import upside_check as UC
        import bestpf_check as BC
        t = json.load(open(os.path.join(BASE, 'portfolio.json')))['target']
        w = {('QQQM' if k == 'IFREE-NDX' else k): v for k, v in t['ami_weights'].items() if v}
        if w != NOW or float(t.get('shiro_castle_pct') or 0) != 0:
            raise SystemExit(f'今の形が正本と違う: {w}')
        self.U = U
        with contextlib.redirect_stdout(io.StringIO()):
            res = U.build()
        self.rows, self.chains = res['rows'], res['chains']
        self.P = B.pool_list()
        self.D = [c for c in self.P if c not in GROWTH]
        assert len(self.D) == 28, self.D
        B.century_extend(U)
        self.fast, self.cent = B.Fast(U, self.rows, self.chains, self.P), B.Cent(U, self.P)
        self.fbr = BR.FastBR(self.fast)
        BR.POOL = list(self.P)                     # 中身の業種をこの33本で（MOAT ほか）。値は R・X・unx と同じ保有から
        vec, self.vchk = BR.industry_vectors(U, self.rows)
        st = BR.industry_state()
        self.adj = {nm: BR.adj_vector(vec, st, rt, self.P)[0] for nm, rt in BR.RATES.items()}
        ch_jpy, _ = U.jpy_chains(self.chains)
        a, b = BC.WINDOWS[UC.W_CRASH]
        self.months = U.R.months(a, b)
        self.Gj = np.array([[ch_jpy[x][m] for m in self.months] for x in self.P])
        self.cidx = {k: [i for i, m in enumerate(self.months) if lo <= m <= hi] for k, (lo, hi) in CRASH.items()}

    def W_of(self, forms):
        return np.array([[f.get(c, 0) for c in self.P] for f in forms], dtype=np.float64)

    def eval(self, W):
        import etf_forward_combo as CB
        fb, a0, adj = self.fbr, self.adj['主（20年の値）'], self.adj
        e, c, rz = self.fast.eval(W), self.cent.eval(W), realized(W, self.fast)
        Wn = W / W.sum(axis=1, keepdims=True)
        brv = {'主': fb.eval(W, a0), '10年の値': fb.eval(W, adj['10年の値']),
               '1位の業種を強く': fb.eval(W, adj['1位の業種を強く（10年の値・Chips −4.0）']), '主の半分': fb.eval(W, adj['主の半分']),
               '分散の上乗せなし': fb.eval(W, a0, nobonus=True), '共分散をA2の窓から': fb.eval(W, a0, cov2=True)}
        _, _, mddj = CB.path_stats(Wn @ self.Gj, self.Gj.shape[1])
        R1 = Wn @ self.fast.G1
        out = dict(mean=e['mean_pi'] * 100, p15=e['P15'] * 100, p5=e['P5'] * 100, worst=e['worst'] * 100, mdd=e['mdd'] * 100,
                   mddj=mddj * 100, brp5=brv['主']['P5'] * 100, cmed=c['c30med'], cmin=c['c30min'],
                   rshare=rz['share'] * 100, rmed=rz['med'] * 100, ok=e['ok'] & brv['主']['ok'],
                   br={v: brv[v]['mean_pi'] * 100 for v in brv}, brmain=brv['主']['mean_pi'] * 100)
        for i, k in enumerate(CRASH):
            ix = self.cidx[k]
            out[f'crash{i}'] = (np.prod(1 + R1[:, ix], axis=1) - 1) * 100
        return out


def classify(m, j, m0):
    """j 行の形を今（m0 の0行）と比べる → (分け方, 悪い, 良い, 差, 100年を測れたか)"""
    worse, better, diff = [], [], {}
    cent_ok = not (np.isnan(m['cmed'][j]) or np.isnan(m['cmin'][j]))
    for k, ja, side, sgn, tol in MEAS:
        if k == 'br':
            ds = {v: float(m['br'][v][j] - m0['br'][v][0]) for v in m['br']}
            diff[ja] = {v: round(x, 3) for v, x in ds.items()}
            if min(ds.values()) < -tol:
                worse.append(ja)
            elif min(ds.values()) > tol:
                better.append((ja, side))
            continue
        x, x0 = float(m[k][j]), float(m0[k][0])
        if np.isnan(x) or np.isnan(x0):
            diff[ja] = None
            continue
        d = x - x0
        diff[ja] = round(d, 3)
        if sgn * d < -tol:
            worse.append(ja)
        elif sgn * d > tol:
            better.append((ja, side))
    rs, ds_ = any(s == 'ret' for _, s in better), any(s == 'def' for _, s in better)
    if worse:
        cls = '替えないほうがいい'
    elif rs and ds_:
        cls = '良い' if cent_ok else '同等以上（100年は測れない）'
    elif ds_:
        cls = '守りが厚くなる' if cent_ok else '守りが厚くなる（100年は測れない）'
    elif rs:
        cls = '期待値が上がる' if cent_ok else '期待値が上がる（100年は測れない）'
    else:
        cls = '同等' if cent_ok else '同等（100年は測れない）'
    return cls, worse, [b for b, _ in better], diff, cent_ok


def nm(f):
    return ' / '.join(f'{("NASDAQ100" if k == "QQQM" else k)} {v:g}' for k, v in f.items() if v)


def self_check(M):
    forms = [dict(NOW), {'QQQM': 40, 'SMH': 20, 'ITA': 15, 'XLV': 10, 'GLDM': 15}, {'QQQM': 40, 'SMH': 20, 'TLT': 20, 'VEA': 20}]
    U, UC = M.U, __import__('upside_check')
    with contextlib.redirect_stdout(io.StringIO()):
        tab = U.measure({str(i): f for i, f in enumerate(forms)}, M.rows, M.chains)
    m = M.eval(M.W_of(forms))
    rep, ok = {}, True
    for i in range(len(forms)):
        t = tab[UC.W_CRASH][str(i)]
        pair = dict(P15=(float(m['p15'][i]), t['P15π']), 平均=(float(m['mean'][i]), t['π加重の平均の年率']), 最大下落=(float(m['mdd'][i]), t['最大下落']))
        rep[nm(forms[i])] = {k: (round(a, 3), b) for k, (a, b) in pair.items()}
        ok = ok and all(abs(a - b) < 0.051 for a, b in pair.values())
    ref = json.load(open(os.path.join(BASE, 'out', 'aggr_lean_check.json')))['形ごとの物差し']['今']
    rep['100年の中央（今）'] = (round(float(m['cmed'][0]), 3), ref['百年']['三十年の中央'])
    ok = ok and abs(float(m['cmed'][0]) - ref['百年']['三十年の中央']) < 0.0011
    return ok, rep


def direct(M):
    forms, meta = [dict(NOW)], [None]
    for h, hw in CUR_DEF.items():
        for a in sorted({5, 10, hw}):
            if a > hw:
                continue
            for y in M.D:
                if y == h:
                    continue
                f = dict(NOW)
                f[h] -= a
                f[y] = f.get(y, 0) + a
                forms.append({k: v for k, v in f.items() if v})
                meta.append(dict(元=h, 量=a, 先=y))
    m = M.eval(M.W_of(forms))
    rows = []
    for j in range(1, len(forms)):
        cls, worse, better, diff, cok = classify(m, j, m)
        rows.append(dict(meta[j], 名前=nm(forms[j]), 分け方=cls, 悪い=worse, 良い=better, 差=diff,
                         物差しが範囲内=bool(m['ok'][j]), 基礎率の平均_主=round(float(m['brmain'][j]), 3)))
    now = {ja: (None if (k == 'br') else (None if np.isnan(float(m[k][0])) else round(float(m[k][0]), 3))) for k, ja, *_ in MEAS}
    now['基礎率の平均（感度6本）'] = {v: round(float(m['br'][v][0]), 3) for v in m['br']}
    good = [r for r in rows if r['分け方'] == '良い']
    if good:
        pick = sorted(good, key=lambda r: (-len(r['良い']), r['量'], -r['基礎率の平均_主']))[0]
        ans = dict(勧め=pick['名前'], 理由='決まりの①（良いの中で良い物差しが最も多い）')
    else:
        ok_ = [r for r in rows if r['分け方'] != '替えないほうがいい']
        ans = dict(勧め='今のまま', 替えてもいい_好みの差=[dict(名前=r['名前'], 分け方=r['分け方'], 良い=r['良い']) for r in ok_])
    return dict(今の値=now, 入れ替え=rows, 答え=ans)


def blocks(M):
    D = M.D
    idx = {c: i for i, c in enumerate(M.P)}
    m0 = M.eval(M.W_of([dict(NOW)]))
    cnt, keep, n = {}, [], 0
    nworse = {}                                    # 報告だけ（2026-11-04 追記・分け方は不変）: 幅を超えて悪い物差しの数ごとの通り数
    buf = []

    def flush():
        nonlocal buf, n
        if not buf:
            return
        W = np.zeros((len(buf), len(M.P)))
        W[:, idx['QQQM']], W[:, idx['SMH']] = 40, 20
        for r, comb in enumerate(buf):
            for c, u in comb:
                W[r, idx[c]] += 5 * u
        m = M.eval(W)
        for j, comb in enumerate(buf):
            cls, worse, better, diff, cok = classify(m, j, m0)
            cnt[cls] = cnt.get(cls, 0) + 1
            nworse[len(worse)] = nworse.get(len(worse), 0) + 1
            if cls not in ('替えないほうがいい',):
                f = dict(FIXED)
                for c, u in comb:
                    f[c] = f.get(c, 0) + 5 * u
                dist = sum(abs(f.get(c, 0) - NOW.get(c, 0)) for c in set(f) | set(NOW)) / 2
                keep.append(dict(名前=nm(f), 分け方=cls, 良い=better, 良い数=len(better), 動かす量=dist,
                                 基礎率の平均_主の差=round(float(m['brmain'][j] - m0['brmain'][0]), 3),
                                 元の平均の差=round(float(m['mean'][j] - m0['mean'][0]), 3), 最大下落の差=round(float(m['mdd'][j] - m0['mdd'][0]), 2),
                                 差=diff))
        n += len(buf)
        buf = []
        log(f'{n} 通り', {k: v for k, v in cnt.items()})
    for k in range(1, 5):
        for sub in itertools.combinations(D, k):
            for cut in itertools.combinations(range(1, 8), k - 1):
                parts = np.diff((0,) + cut + (8,))
                buf.append(list(zip(sub, parts)))
                if len(buf) >= 8000:
                    flush()
    flush()
    good = sorted([r for r in keep if r['分け方'] == '良い'], key=lambda r: (-r['良い数'], r['動かす量'], -r['基礎率の平均_主の差']))
    return dict(通り=n, 分け方の数=cnt, 悪い物差しの数ごとの通り数=dict(sorted(nworse.items())),
                替えないほうがいい以外の全部=sorted(keep, key=lambda r: (r['分け方'], r['動かす量'])), 良い_上位30=good[:30], 良い_動かす量が小さい順_上位15=sorted(good, key=lambda r: (r['動かす量'], -r['良い数']))[:15],
                同等以上_100年は測れない_上位15=sorted([r for r in keep if r['分け方'] == '同等以上（100年は測れない）'],
                                               key=lambda r: (-r['良い数'], r['動かす量']))[:15])


def main():
    t0 = time.time()
    M = Meas()
    ok, rep = self_check(M)
    log('自己検問', ok, json.dumps(rep, ensure_ascii=False))
    if not ok:
        raise SystemExit('自己検問が通らない')
    out = dict(generated=time.strftime('%Y-%m-%d'), tool='night/defense_swap_check.py', kind='参考（配分は変えない・決まりは道具の頭に固定）',
               question='守り同士で替えてもいいのがないかもっと検証して', 今=NOW, 守りの候補=M.D, selfcheck=rep,
               中身の業種の一致={c: bool(v) for c, v in M.vchk.items()})
    if BLOCKS:
        out['組み直し'] = blocks(M)
    else:
        out.update(direct(M))
    out['secs'] = round(time.time() - t0)
    json.dump(out, open(OUT, 'w'), ensure_ascii=False, indent=1, default=str)
    log('→', OUT, f'{time.time() - t0:.0f}秒')


if __name__ == '__main__':
    main()
