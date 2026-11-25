"""セクター SPDR（XLV・XLP・XLU）の出たばかりの時期の壊れた月次を直す（2026-11-25 新設・ユーザー明示指示「XLV・XLP・XLUのデータ直して」）

使い方:
  import sector_spdr_fix as SF
  r = SF.repair('XLV', r)        # {yyyymm: 小数} の月次リターン → 壊れた月だけ直した新しい dict（対象外の本はそのまま返す）
  python3 night/sector_spdr_fix.py   # 証拠の表を測り直して出す（決まりの選び方がまだ同じかも確かめる）

【何が壊れていたか】Yahoo（と Alpha Vantage・それを写した各サイト）の3本の 1999-01〜2002-06 の終値が、同じ業種の器と合わない。
  出たばかりで売買の少なかった時期の終値の誤りとみられる（XLV の2001年7月の月の出来高は約26万株）。
  2026-11-25 の実測（配当込み月次・参照は French 49業種の同じ業種の時価総額加重＝CRSP の全上場株から作った値で ETF の取引の乱れが入らない）:
    半年ごとの月次の相関（本 と French の参照）      1999H1  1999H2  2000H1  2000H2  2001H1  2001H2  2002H1  2002H2
      XLV（Drugs＋MedEq＋Hlth）                       0.27    0.07   −0.01    0.22    0.40    0.55    0.91    1.00
      XLP（Food＋Soda＋Beer＋Smoke＋Hshld）           −0.33    0.95    0.83    0.86    0.87    0.22    0.95    0.99
      XLU（Util）                                      0.58    0.07    0.83    0.21    0.94    0.10    0.73    0.99
    暦年（本／参照／iShares）: XLV 2000 −11.8／+35.4／—・2002 −0.7／−22.7／IYH −21.3
                             XLP 2002 −20.1／−0.9／IYK −5.5（2002年前半は毎月 −2〜−6pt ずれる）
                             XLU 2000 +22.5／+50.4／—・2001 −13.0／−9.8／IDU −25.9
    2002-07 以降は3本とも参照と 0.987 以上（2003〜2010 は 0.955〜0.983）。XLK・XLE・XLF・XLI・XLB は 2000〜2002 も
    同じ業種の iShares と 0.95〜0.99 で合う（直さない）。XLY は 2000年後半と2002年前半に少しずれる（0.64・0.83）が、
    この決まりの対象にしていない（指示の外・必要なら同じ形で足せる）。

【直し方（2026-11-25 に固定・測る前にコミット）】
  1. 直す月: 3本とも 1999-01〜2002-06（データの最初の月から）。元の系列にある月だけを替え、月を足しも減らしもしない。
  2. 置き換える先: その本のデータがきれいな 2003-01〜2010-12 に、その本自身と月次の相関が高いほう——
       iShares の同じ業種の器（IYH・IYK・IDU・2000-06 設定・最初のリターンは 2000-07）か、French の同じ業種の時価総額加重。
       実測（2026-11-25）: XLV  IYH 0.991 ＞ French 0.973 → IYH
                           XLP  French 0.955 ＞ IYK 0.938 → French
                           XLU  IDU 0.986 ＞ French 0.983 → IDU（French の Util は Enron など2001年に崩れた商社型の電力を含まない分類で、
                                2001年 French −9.8% 対 IDU −25.9% とずれる＝iShares のほうが S&P の公益の中身に近い）
       iShares を選んだ本でも、iShares が無い 1999-01〜2000-06 は French。
  3. 費用: iShares は当時の経費率の差 (0.60−0.28)%/年を足し、French（費用なし）は 0.28%/年を引く（目安・月 0.03pt 以下）。
  4. 自己検問: 替える月が参照に無ければ止まる。2002-07 以降の月には触らない。
  ⚠ 凍結した前向きの検定（mw_forward・nx_forward と mw_common・nx_common の閉包）はこの道具を使わない＝触らない。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

BROKEN = {'XLV': (199901, 200206), 'XLP': (199901, 200206), 'XLU': (199901, 200206)}
TWIN = {'XLV': 'IYH', 'XLP': 'IYK', 'XLU': 'IDU'}
FRENCH = {'XLV': ['Drugs', 'MedEq', 'Hlth'], 'XLP': ['Food', 'Soda', 'Beer', 'Smoke', 'Hshld'], 'XLU': ['Util']}
USE_TWIN = {'XLV': True, 'XLP': False, 'XLU': True}     # 2003-01〜2010-12 の相関で決めた（上の 2.）
TWIN_FROM = 200007                                      # iShares の最初の月次リターン
ER_SPDR, ER_TWIN = 0.0028, 0.0060                       # 当時の経費率（目安）
CHOICE_WINDOW = (200301, 201012)

_CACHE = {}


def _french():
    if 'fr' not in _CACHE:
        import future30 as F
        cols, ret, capm, *_ = F.load()
        strip = {c.strip(): c for c in cols}
        _CACHE['fr'] = (F, ret, capm, strip)
    return _CACHE['fr']


def french_ref(t):
    """French 49業種の同じ業種の時価総額加重（費用なし）→ {yyyymm: 小数}"""
    key = ('ref', t)
    if key not in _CACHE:
        F, ret, capm, strip = _french()
        inds = [strip.get(n, n) for n in FRENCH[t]]
        ms = sorted(set().union(*[set(ret[c]) for c in inds]))
        _CACHE[key] = F.capw(ret, capm, inds, ms)
    return _CACHE[key]


def twin(t):
    key = ('twin', t)
    if key not in _CACHE:
        import mw_common as M
        _CACHE[key] = M.yahoo(TWIN[t])
    return _CACHE[key]


def source_for(t, m):
    """月 m に使う値と出所の名前"""
    if USE_TWIN[t] and m >= TWIN_FROM:
        v = twin(t).get(m)
        return (None if v is None else v + (ER_TWIN - ER_SPDR) / 12), TWIN[t]
    v = french_ref(t).get(m)
    return (None if v is None else v - ER_SPDR / 12), 'French ' + '+'.join(FRENCH[t])


def repair(t, series):
    # 比べるためだけに直しを外す口（子のプロセスにも効く）: CCF_SPDR_FIX=off
    if t not in BROKEN or os.environ.get('CCF_SPDR_FIX') == 'off':
        return series
    m0, m1 = BROKEN[t]
    out = dict(series)
    for m in sorted(series):
        if m0 <= m <= m1:
            v, src = source_for(t, m)
            if v is None:
                raise SystemExit(f'sector_spdr_fix: {t} の {m} を直す値が {src} に無い')
            out[m] = v
    return out


def info(t):
    """直した区間の説明（画面や出力に添える）"""
    if t not in BROKEN:
        return None
    m0, m1 = BROKEN[t]
    fr = 'French ' + '+'.join(FRENCH[t])
    segs = ([dict(src=fr, frm=m0, to=200006), dict(src=TWIN[t], frm=TWIN_FROM, to=m1)]
            if USE_TWIN[t] else [dict(src=fr, frm=m0, to=m1)])
    return dict(frm=m0, to=m1, segments=segs, tool='night/sector_spdr_fix.py',
                note='出たばかりの時期の終値が壊れていた月を同じ業種の器の値で直した（2026-11-25）')


def _corr(a, b, m0, m1):
    import numpy as np
    ks = [m for m in sorted(set(a) & set(b)) if m0 <= m <= m1]
    if len(ks) < 6:
        return None
    return round(float(np.corrcoef([a[k] for k in ks], [b[k] for k in ks])[0, 1]), 3)


def evidence():
    """証拠の表を測り直す（決まりの選び方がまだ同じかも）"""
    import mw_common as M
    out = {}
    halves = [(y * 100 + 1, y * 100 + 6) for y in range(1999, 2004)] + [(y * 100 + 7, y * 100 + 12) for y in range(1999, 2004)]
    halves.sort()
    for t in BROKEN:
        raw, ref, tw = M.yahoo(t), french_ref(t), twin(t)
        fixed = repair(t, raw)
        c_tw, c_fr = _corr(raw, tw, *CHOICE_WINDOW), _corr(raw, ref, *CHOICE_WINDOW)
        out[t] = dict(
            choice=dict(window=CHOICE_WINDOW, twin=c_tw, french=c_fr, rule_picks=('twin' if c_tw > c_fr else 'french'),
                        fixed_choice=('twin' if USE_TWIN[t] else 'french'), same=(c_tw > c_fr) == USE_TWIN[t]),
            halves={f'{a}-{b}': dict(raw_vs_french=_corr(raw, ref, a, b), raw_vs_twin=_corr(raw, tw, a, b),
                                     twin_vs_french=_corr(tw, ref, a, b), fixed_vs_french=_corr(fixed, ref, a, b)) for a, b in halves},
            months_changed=sum(1 for m in raw if BROKEN[t][0] <= m <= BROKEN[t][1]))
    return out


if __name__ == '__main__':
    import json
    ev = evidence()
    print(json.dumps(ev, ensure_ascii=False, indent=1))
    bad = [t for t, v in ev.items() if not v['choice']['same']]
    if bad:
        print('⚠ 2003〜2010 の相関で選ぶと、固定した置き換え先と違う本:', bad)
        sys.exit(1)
    print('✓ 置き換え先の選び方は固定した値と同じ')
