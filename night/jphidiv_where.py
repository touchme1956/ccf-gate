#!/usr/bin/env python3
"""night/jphidiv_where.py — 日本の高配当 5% をどこから入れるか（2026-10-27・参考・判定なし）

ユーザーの問い「日本の高配当を5%はどこに入れる？」。配分は変えない。形と選び方は結果を見る前にこのファイルで固定し、回す前にコミットする。
今: QQQM 40 / SMH 30 / ITA 15 / SHLD 5 / XLV 5 / FBT 5。案: 出す元 X（QQQM・SMH・ITA・SHLD・XLV・FBT）から5を日本の高配当へ。
日本の高配当の器: NEXT FUNDS 日経平均高配当株50（1489.T・2017-03〜・円）。確かめ: iシェアーズ MSCI ジャパン高配当（1478.T・2015-11〜）。
A 本物の記録（円・月次・配当込み）: 他の本は unx_assets.build の系列（ドル）を FRED DEXJPUS で円に（jpy_chains）。窓は日本の高配当の器がそろう月から 2026-09。
  毎月リバランスの年率・ぶれ・最大下落・2022年・毎月同額の積立の最終額（今を1）。Yahoo の東証の値段は1日の誤り・分割の誤りがあるので、月次で −30% 以下か +40% 以上の月があれば止める。
B 長い物差し（unx_assets.measure・USD・崩れあり）: 日本の高配当の長い系列が無いので **TOPIX の行で代える**（高配当は直近10年 TOPIX に勝っている＝控えめな代わり）。
選び方（回す前に固定）: A で 年率の差 ≥ −0.3pt ∧ 最大下落が今より浅い ∧ B で 平均の差 ≥ −0.10pt の出す元のうち、A の最大下落の改善が最大。無ければ「入れない（今のまま）」。
⚠ A の窓は日本の割安株が見直された時期を含む・東証の月末は米国の前日の終値まで・B の代わりは TOPIX＝高配当そのものではない。
使い方: python3 night/jphidiv_where.py → out/jphidiv_where.json
"""
import datetime, json, math, os, sys, time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
OUT = os.path.join(BASE, 'out', 'jphidiv_where.json')
NOW = '今'
BASEF = {'QQQM': 40, 'SMH': 30, 'ITA': 15, 'SHLD': 5, 'XLV': 5, 'FBT': 5}
SRCS = ['QQQM', 'SMH', 'ITA', 'SHLD', 'XLV', 'FBT']


def forms(jp):
    F = {NOW: dict(BASEF)}
    for x in SRCS:
        f = dict(BASEF); f[x] -= 5
        if f[x] == 0:
            del f[x]
        f[jp] = 5; F[f'{x}→日本高配当'] = f
    return F


def realized(F, ser, ms):
    out = {}
    for nm, f in F.items():
        tw = sum(f.values())
        r = [sum(w / tw * ser[a][m] for a, w in f.items()) for m in ms]
        g = math.exp(sum(math.log1p(x) for x in r) * 12 / len(r)) - 1
        mu = sum(r) / len(r); sd = math.sqrt(sum((x - mu) ** 2 for x in r) / len(r)) * math.sqrt(12)
        v = pk = 1.0; mdd = 0.0; dca = 0.0
        for x in r:
            v *= 1 + x; pk = max(pk, v); mdd = min(mdd, v / pk - 1)
            dca = (dca + 1) * (1 + x)
        y22 = [x for m, x in zip(ms, r) if 202201 <= m <= 202212]
        out[nm] = dict(年率=round(100 * g, 2), ぶれ=round(100 * sd, 1), 最大下落=round(100 * mdd, 1), 積立の最終額=dca,
                       **{'2022年': round(100 * (math.prod(1 + x for x in y22) - 1), 1) if len(y22) == 12 else None})
    base = out[NOW]['積立の最終額']
    for nm in out:
        out[nm]['積立_今との比'] = round(out[nm].pop('積立の最終額') / base, 3)
    return out


def main():
    import unx_assets as U
    import upside_check as UC
    import mw_common as M
    t0 = time.time()
    res = U.build()
    rows, chains = res['rows'], res['chains']
    jc, fx_url = U.jpy_chains(chains)
    doc = dict(generated=datetime.date.today().isoformat(), tool='night/jphidiv_where.py', kind='参考（配分は変えない・選び方は道具の頭に固定）',
               question='日本の高配当を5%はどこに入れる？', fx=fx_url)
    A = {}
    for jp in ('1489.T', '1478.T'):
        s = M.yahoo(jp)
        bad = {m: v for m, v in s.items() if v <= -0.30 or v >= 0.40}
        if bad:
            raise SystemExit(f'{jp} の月次に誤りの疑い: {bad}')
        ser = {a: jc[a] for a in BASEF}; ser['JPHD'] = s
        ms = sorted(m for m in set.intersection(*[set(v) for v in ser.values()]) if m <= 202609)
        A[jp] = dict(窓=(ms[0], ms[-1], len(ms)), 結果=realized(forms('JPHD'), ser, ms))
    F = forms('TOPIX')
    tab = U.measure(F, rows, chains, mega=U.mega_map(rows, sorted({a for f in F.values() for a in f} | {'VOO'})))[UC.W_CRASH]
    B = {nm: {k: tab[nm][k] for k in ('π加重の平均の年率', 'P15π', 'P5π（5%未満）', '最悪の世界', '最大下落', '過去の転がる20年で15%以上')} for nm in F}
    a = A['1489.T']['結果']; why, best = {}, None
    for nm in a:
        if nm == NOW:
            continue
        c1 = a[nm]['年率'] - a[NOW]['年率'] >= -0.3
        c2 = a[nm]['最大下落'] > a[NOW]['最大下落']
        c3 = B[nm]['π加重の平均の年率'] - B[NOW]['π加重の平均の年率'] >= -0.10
        why[nm] = dict(年率=c1, 最大下落=c2, 長い物差し=c3, 最大下落の改善=round(a[nm]['最大下落'] - a[NOW]['最大下落'], 1))
        if c1 and c2 and c3 and (best is None or why[nm]['最大下落の改善'] > why[best]['最大下落の改善']):
            best = nm
    doc.update(A_本物の記録_円=A, B_長い物差し_TOPIXで代える=B, choice=dict(per_source=why, pick=best or '入れない（今のまま）'), secs=round(time.time() - t0))
    json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1, default=str)
    for jp, d in A.items():
        print('==', jp, d['窓'])
        for nm, v in d['結果'].items():
            print(f'  {nm:<14} {v}')
    print('== 長い物差し（TOPIX で代える）')
    for nm, v in B.items():
        print(f'  {nm:<14} {v}')
    print('選び', json.dumps(why, ensure_ascii=False), '→', best)


if __name__ == '__main__':
    main()
