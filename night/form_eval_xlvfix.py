"""form_eval を XLV の壊れた初期の値だけ直して回す（参考・2026-11-25 新設・読むだけ）

使い方: python3 night/form_eval_xlvfix.py out/form_eval_<key>_spec.json → out/form_eval_<key>.json

【なぜ】Yahoo（と Alpha Vantage・それを写した各サイト）の XLV の 2000〜2002年の値は、同じ業種の器と合わない。
  2026-11-25 の実測（mw_common.yahoo の配当込み月次）:
    XLV と IYH（iShares US Healthcare・2000-06 設定）の月次の相関  2000-07〜2002-12: 0.386 ／ 2003〜2010: 0.991
    暦年 2001: XLV −0.8%・IYH −13.3%・FSPHX −15.0%／2002: XLV −0.7%・IYH −21.3%・FSPHX −18.1%・VGHCX −11.4%
    IYH と FSPHX（Fidelity Select Health Care）の相関は 2000-07〜2002-12 も 0.95〜0.97＝IYH は当時のヘルスケアを写している
    XLV と IYH の月の差は 2002-07 から ±0.5pt 以内（2000-07〜2002-06 は 1〜16pt の月が続く）
  出たばかりで売買の少なかった時期の終値が壊れている（XLP・XLU・XLY の初期にも同じ形のずれ。XLK・XLE・XLF・XLI・XLB は合う）。

【直し方（回す前に固定）】chains['XLV'] の 2000-07〜2002-06 の月次を、IYH の月次＋費用の差 (0.60−0.28)%/12 に替える。
  rows['XLV'] は A1_gross を直した系列の A1 の窓の年率に替え、A1 は A1_gross＋（元の A1−A1_gross＝費用と税の差）。
  直すのは計算の中だけ（共有の系列・キャッシュ・ほかの道具は変えない）。B・C・D の世界と100年の代用は XLV の系列を使わないので変わらない。
  自己検問: 元の A1_gross が元の系列の A1 の窓の年率と一致しなければ止まる・IYH に替える月が欠けていれば止まる。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np  # noqa: E402

import mw_common as M  # noqa: E402
import unx_assets as U  # noqa: E402
import form_eval as FE  # noqa: E402

FIX_FROM, FIX_TO = 200007, 200206
ER_DIFF = 0.0060 - 0.0028          # IYH の当時の経費率 0.60% − XLV の当時の経費率 0.28%
A1_0, END = 200009, 202609         # form_eval の A1 の窓（Fast と同じ）

_orig_build = U.build


def _geo(ch, ks):
    return float(np.expm1(np.log1p(np.array([ch[m] for m in ks])).sum() * 12 / len(ks)))


def build_fixed(*a, **k):
    res = _orig_build(*a, **k)
    rows, chains = res['rows'], res['chains']
    ks = U.R.months(A1_0, END)
    ch = chains['XLV']
    g0 = _geo(ch, ks)
    if abs(g0 - rows['XLV']['A1_gross']) > 1e-6:
        raise SystemExit(f'XLV の A1_gross が A1 の窓の年率と違う（{rows["XLV"]["A1_gross"]} 対 {g0}）＝直し方を見直す')
    iyh = M.yahoo('IYH')
    fixed = []
    for m in U.R.months(FIX_FROM, FIX_TO):
        if m not in iyh or m not in ch:
            raise SystemExit(f'直す月が欠けている: {m}')
        fixed.append((m, round(ch[m], 4), round(iyh[m] + ER_DIFF / 12, 4)))
        ch[m] = iyh[m] + ER_DIFF / 12
    g1 = _geo(ch, ks)
    cost = rows['XLV']['A1'] - rows['XLV']['A1_gross']
    rows['XLV']['A1_gross'], rows['XLV']['A1'] = g1, g1 + cost
    print(f'[xlvfix] XLV の {FIX_FROM}〜{FIX_TO}（{len(fixed)}か月）を IYH＋{ER_DIFF * 100:.2f}%/年 に替えた・'
          f'A1 の窓の年率 {100 * g0:.2f}% → {100 * g1:.2f}%', file=sys.stderr)
    res.setdefault('info', {})['xlvfix'] = dict(months=fixed, A1_gross_before=g0, A1_gross_after=g1)
    return res


U.build = build_fixed

if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('使い方: python3 night/form_eval_xlvfix.py out/form_eval_<key>_spec.json')
    FE.main(sys.argv[1])
