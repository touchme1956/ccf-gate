#!/usr/bin/env python3
"""ami_series.py — ETFの門（ami.html）の『配合を歴史で試す』が読む月次リターンを作る（2026-11-03新設・読むだけ）

ユーザー指示「1でやって〔ami.html を作り直す〕それとこれまで私が見てきた歴史検証をグラフで分かりやすくみれるように
など新機能をたくさん盛り込んで」の材料。**判定・配分には使わない**（参考の表示だけ）。

  出力 out/ami_series.json
    assets[T] = {nm, start(yyyymm), r:[月次リターン（ドル建て・配当込み）…], proxy:{t, nm, until} | None}
    fx        = {start, r:[…]}  ＝ドル円の月次変化（ドルを円で持ったときに掛ける）
  出所: Yahoo の調整後終値（配当込み）を night/mw_common.yahoo で（今月の途中の足は落とす・抜けた月をまたがない）。
  ★2000年より前・設定より前を、同じ賭けの長い投資信託で延ばした本がある（proxy）——
    実物の最初の月より前だけを代理で埋め、つなぎ目は画面に出す。代理は能動の投信で費用が高く、実物の費用は引いていない
    （ETF は価格そのものが費用の後）。ITバブル崩壊（2000〜2002）を窓に入れるための近似であって、実物の成績ではない。
  欠けた月は0で埋めない（ルール7）——続いている塊の最初の月を start にする。
"""
import json, os, sys, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mw_common as M

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'out', 'ami_series.json')

# (表示の鍵, Yahoo, 名前, 代理〔Yahoo, 名前〕 or None)
ASSETS = [
    ('QQQ', 'QQQ', 'NASDAQ100（QQQ・iFreeNEXT と同じ指数）', None),
    ('SMH', 'SMH', '半導体 SMH', ('FSELX', 'Fidelity Select Semiconductors（投信）')),
    ('ITA', 'ITA', '米国の航空宇宙・防衛 ITA', ('FSDAX', 'Fidelity Select Defense & Aerospace（投信）')),
    ('XLV', 'XLV', '米国ヘルスケア XLV', None),
    ('VBR', 'VBR', '米国小型バリュー VBR', ('VISVX', 'Vanguard Small-Cap Value Index（投信）')),
    ('SPY', 'SPY', 'S&P500（SPY）', None),
    ('XLK', 'XLK', '米国テクノロジー XLK', None),
    ('XLE', 'XLE', '米国エネルギー XLE', None),
    ('XLU', 'XLU', '米国公益 XLU', None),
    ('GDX', 'GDX', '金鉱株 GDX', None),
    ('GLD', 'GLD', '金 GLD', None),
    ('TLT', 'TLT', '米国長期国債 TLT', None),
    ('VEA', 'VEA', '先進国株（除く米国）VEA', None),
    ('VT', 'VT', '全世界株 VT', None),
    ('FBT', 'FBT', 'バイオ FBT', None),
]


def mdiff(a, b):
    return (a // 100 * 12 + a % 100) - (b // 100 * 12 + b % 100)


def madd(m, k):
    t = m // 100 * 12 + m % 100 - 1 + k
    return (t // 12) * 100 + t % 12 + 1


def block(r):
    """最後の月から遡って月が続いている塊だけ → (start, [値…])"""
    ks = sorted(r)
    if not ks:
        return None, []
    i = len(ks) - 1
    while i > 0 and mdiff(ks[i], ks[i - 1]) == 1:
        i -= 1
    ks = ks[i:]
    return ks[0], [r[k] for k in ks]


def main():
    out = dict(generated=datetime.date.today().isoformat(), tool='night/ami_series.py',
               note='参考・判定に不使用。Yahoo の調整後終値（配当込み）の月次・ドル建て。proxy は実物より前を埋めた代理（能動の投信）',
               assets={}, fx=None, failed=[])
    last = None
    for key, yt, nm, px in ASSETS:
        try:
            r = M.yahoo(yt)
        except Exception as e:
            out['failed'].append(f'{key}: {e}'[:160])
            continue
        s, v = block(r)
        if not v:
            out['failed'].append(f'{key}: 取れなかった')
            continue
        proxy = None
        if px:
            try:
                p = M.yahoo(px[0])
                ps = {k: x for k, x in p.items() if k < s}
                ps0, pv = block(ps)
                # 代理の塊が実物の最初の月の直前で終わっているときだけつなぐ（隙間をまたがない）
                if pv and mdiff(s, madd(ps0, len(pv) - 1)) == 1:
                    proxy = dict(t=px[0], nm=px[1], until=madd(ps0, len(pv) - 1))
                    s, v = ps0, pv + v
            except Exception as e:
                out['failed'].append(f'{key} の代理 {px[0]}: {e}'[:160])
        e = madd(s, len(v) - 1)
        last = e if last is None else min(last, e)
        out['assets'][key] = dict(nm=nm, start=s, end=e, r=[round(x, 5) for x in v], proxy=proxy)
    fx = M.yahoo('JPY=X')
    fs, fv = block(fx)
    out['fx'] = dict(nm='ドル円（JPY=X の月末）', start=fs, end=madd(fs, len(fv) - 1), r=[round(x, 5) for x in fv])
    out['last'] = last
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, separators=(',', ':'))
    print(f'✓ {OUT}  {len(out["assets"])}本・終わり {last}  失敗 {out["failed"] or "なし"}')
    for k, a in out['assets'].items():
        print(f'  {k:4s} {a["start"]}〜{a["end"]}  {"代理 "+a["proxy"]["t"]+"〜"+str(a["proxy"]["until"]) if a["proxy"] else ""}')
    return 0 if out['assets'] else 1


if __name__ == '__main__':
    sys.exit(main())
