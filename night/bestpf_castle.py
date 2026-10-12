#!/usr/bin/env python3
"""night/bestpf_castle.py — 個別株の枠（今の投下可8社）を bestpf の物差しに載せる系列（2026-10-12・ユーザー「NDX20/SMH50/ITA20/XLE10 これに個別枠10％を入れるなら？」）

読むだけ。門・採点・配分には触れない。事前登録の外。
個別株の枠をどう置くかで答えが変わるので、bestpf_check では3通りを並べる:
  MOAT  … 質の高い大型株の代用（French BIG HiOP〔大型×高収益〕を 2012-04 まで・その後 VanEck MOAT）＝後知恵なし（主）
  VOO   … 市場並み（個別株の上乗せ0＝これまでの検証の『城が指数に勝つ証拠は無い』の側）
  CASTLE… 今の投下可8社の実際の値動き（このファイルが作る）＝**今日の顔ぶれを過去へ当てた後知恵の上限**
CASTLE の作り:
  - 顔ぶれと重みは今日の門（out/score_all.json の buy=True・Ω順）と席の順位の重み 5:3（portfolio.json の castle_rank_weights）
  - 月のリターン = Yahoo の調整後終値（配当込み）を毎月その重みへ組み直したもの。上場前の社（GOOGL 2004-08 まで）は残りで按分
  - 世界 B・C・D は bestpf_tech12.compute_worlds と同じ式（保有の49業種・記録の二業種の比重・JPM の米国大型株・D は QQQM の総額）。
    費用0（個別株）・配当の外国税は配当利回りの置き値 0.6%×10%
出力: out/bestpf_castle.json
"""
import datetime, json, math, os, sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
import mw_common as MW      # noqa: E402

OUT = os.path.join(BASE, 'out', 'bestpf_castle.json')
FEE = 0.0
DY = 0.006
TAX_K = 0.10


def seats():
    sa = json.load(open(os.path.join(BASE, 'out', 'score_all.json')))
    buy = sorted([r for r in sa if r.get('buy')], key=lambda r: -float(r['s']))
    pj = json.load(open(os.path.join(BASE, 'portfolio.json')))
    rw = (pj.get('target') or {}).get('castle_rank_weights') or [5, 5, 5, 5, 5, 3, 3, 3, 3, 3]
    rw = rw[:len(buy)]
    tot = sum(rw)
    return [(r['t'], w / tot, float(r['s'])) for r, w in zip(buy, rw)]


def compute_worlds(hold):
    import etf_forward_rank as R
    import bestpf_ext as X
    bi = X.b_inputs()
    ind_of, _ = X.mapper([t for t, _ in hold])
    X_ind = bi['X_ind']
    mapped = [(t, ind_of(t), w) for t, w in hold]
    mw = sum(w for _, k, w in mapped if k)
    e = sum(w for _, k, w in mapped if k in ('Softw', 'Chips')) / mw
    xi = sum(w * X_ind[k]['x'] for _, k, w in mapped if k in X_ind) / mw
    b_gross = R.R_EQ + R.SHRINK * xi + (R.REC_A - R.REC_B * e)
    c_gross = (R.H_JPM * R.JPM['USL'] / 100 + (R.H - R.H_JPM) * b_gross) / R.H
    tax = DY * TAX_K
    cma = json.load(open(os.path.join(BASE, 'out', 'bestpf_cma_2026.json')))['D_net_by_asset']
    q = X.rank_result()['rows']['QQQM']
    d_gross = cma['QQQM'] + q['er_vehicle'] + q['tax_drag']
    return dict(holdings=[[t, round(100 * w, 2)] for t, w in hold], industries={t: k for t, k, _ in mapped}, coverage=round(mw, 3),
                record_share_e=e, X_ind=xi, B_gross=b_gross, C_gross=c_gross, D_gross=d_gross, fee=FEE, dy=DY, tax_drag=tax,
                B=b_gross - FEE - tax, C=c_gross - FEE - tax, D=d_gross - FEE - tax,
                note='bestpf_tech12.compute_worlds と同じ式（業種は SEC の SIC→French 49・未分類は重みから外して按分）')


def main():
    st = seats()
    print('今の投下可（Ω順・重み）', [(t, round(100 * w, 2), s) for t, w, s in st])
    rets = {t: MW.yahoo(t) for t, _, _ in st}
    months = sorted({m for r in rets.values() for m in r if m >= 199901})
    out = {}
    for m in months:
        num = den = 0.0
        for t, w, _ in st:
            r = rets[t].get(m)
            if r is not None:
                num += w * r; den += w
        if den >= 0.5:          # 重みの半分以上の社の値があれば（GOOGL 上場前は残り7社）
            out[m] = num / den
    hold = [(t, w) for t, w, _ in st]
    worlds = compute_worlds(hold)

    def cagr(a, b):
        ms = [m for m in sorted(out) if a <= m <= b]
        g = 1.0
        for m in ms:
            g *= 1 + out[m]
        return 100 * (g ** (12 / len(ms)) - 1)
    for a, b in [(200009, 202609), (201110, 202609), (200211, 202609)]:
        print(f'  年率（ドル・費用前）{a}〜{b}: 今の8社 {cagr(a, b):5.1f}%')
    print('  世界', {k: round(100 * worlds[k], 2) for k in ('B', 'C', 'D')}, 'e', round(worlds['record_share_e'], 2), worlds['industries'])
    doc = dict(generated=datetime.date.today().isoformat(), tool='night/bestpf_castle.py', posthoc=True, hindsight=True,
               question='NDX20/SMH50/ITA20/XLE10 これに個別枠10％を入れるなら？（ユーザーの問い）',
               seats=[dict(t=t, w=round(w, 4), omega=s) for t, w, s in st],
               monthly_usd={str(m): v for m, v in sorted(out.items())}, worlds=worlds,
               warn=['今日の投下可の顔ぶれを過去へ当てた＝後知恵（今日の門は過去の勝ちを見て高い点を付けうる）。上限として読む',
                     '毎月その重みへ組み直した（本物の買い方は不足から1株ずつ・売らない）',
                     'GOOGL の上場前（2004-08 まで）は残り7社で按分'])
    json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1)
    print('→', OUT)


if __name__ == '__main__':
    main()
