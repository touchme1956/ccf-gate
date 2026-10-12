#!/usr/bin/env python3
"""night/moat_deep_posthoc.py — moat_deep の事後の診断（2026-10-12・結果を見た後に足した・判定は動かさない・読むだけ）

E1 社単位の選び方: moat_deep の点検で、社単位を『最新のビンテージを先に』選ぶと、後のビンテージで母集団から外れた社
   （＝その後に落ちた・報告をやめた社）だけが前のビンテージに集まり、前方の窓と重なる年の数字で社を選ぶことになると分かった
   （moat_deep は『最初に条件を満たしたビンテージ』へ直してから事前登録した）。moat_track（②・:18875）の B の社単位
   （pooled_B・2015→2012）も同じ形なので、同じ表・同じ驚き・同じ置換の種で『最初のビンテージを先に』と比べる。
   moat_repl（:18924）の B′ は1ビンテージ（2019）なので影響しない。
出力: out/moat_deep_posthoc.json
"""
import datetime, json, os, sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
import moat_track_test as T     # noqa: E402

OUT = os.path.join(BASE, 'out', 'moat_deep_posthoc.json')


def pooled(V, P, k, o, order):
    """moat_track_test.pooled_B と同じ規則（その年に部品が無ければ数えない）で、ビンテージの順だけを変える"""
    a, b, st, seen = [], [], [], set()
    for y in order:
        for c in P[y][o]:
            if c in seen:
                continue
            seen.add(c)
            v = V[y][c].get(k)
            if v is None:
                continue
            a.append(v)
            b.append(P[y][o][c])
            st.append(y)
    return a, b, st


def e1():
    _pan, V, sic = T.build(fetch_sic=False)
    U = T.universes(V, sic)
    P = {y: {o: T.pct_of(V[y], U[y][o], e, f)[0] for o, (e, f, _) in T.OUTC.items()} for y in T.VINT}
    out = {}
    for o in ('O1t', 'O3t', 'O2m'):
        out[o] = {}
        for ci, k in enumerate(T.COMPS):
            row = {}
            for name, order in (('最新を先に（moat_track の主の選び方）', (2015, 2014, 2013, 2012)), ('最初を先に', (2012, 2013, 2014, 2015))):
                a, b, st = pooled(V, P, k, o, order)
                r, p = T.rho_p(a, b, T.SEED_B + 90000 + ci, strata=st)
                row[name] = {'n': len(a), 'rho': T.r3(r), 'p_両側': round(p, 4), 'ビンテージ別の数': {str(y): st.count(y) for y in T.VINT}}
            out[o][k] = row
    return out


def main():
    res = {'generated': datetime.date.today().isoformat(), 'tool': 'night/moat_deep_posthoc.py',
           '位置づけ': '事後の診断（結果を見た後に足した）。moat_deep・moat_track の判定は動かさない',
           'E1 moat_track の社単位の選び方（最新を先に／最初を先に・同じ驚き・同じ種・置換の p は両側）': e1()}
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    for o, d in res['E1 moat_track の社単位の選び方（最新を先に／最初を先に・同じ驚き・同じ種・置換の p は両側）'].items():
        for k, r in d.items():
            print(o, k, {nm: (v['n'], v['rho'], v['p_両側']) for nm, v in r.items()})
    print('書いた', OUT)


if __name__ == '__main__':
    main()
