#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/audit_promotion_ready.py — **繰り上がる前に、繰り上がる社を検査する**（2026-08-07新設）

なぜ要るか（2026-08-06に6回連続で踏んだ）:
  validate_packs の FAIL を **投下可10社だけ**で運用していたため、10番目の席が動くたびに
  「投下可の厳しさで監査されたことのないパック」が露出した。実際の連鎖:
      ECL → ISRG → IDXX → APH → CDNS → MCO
  そのうち2社は**誤値そのもの**が出た（ISRG roic 19.6→12.8 で投下可から脱落 /
  CDNS f1=80 が roiic 空欄で根拠ゼロ→55 で脱落）。つまりこれは事務作業の遅れではなく、
  **未監査の社が買付の席に着いてから初めて検査される**という順序の問題だった。

  一方「判定圏(Ω72+)49社を全部同じ厳しさで」は単位が大きすぎる。実測すると——
  四段関門を通っているのは **17社だけ**で、残り32社は堀不足・E[r]<0・点検要修正で
  落ちており、根拠を全部埋めても投下可には来ない。**危ないのは次点だけ。**

何をするか（二層。第四の関門と同じ作法）:
  ・**投下可10社に FAIL があれば落とす**（今日はゼロ＝「今より悪くしない」ラチェット。
    AMBIQ の要修正ラチェットと同型）
  ・**次点に FAIL があれば名指しで警告**（落とさない。今日は5社あるので、
    ここを hard fail にすると CI が常時赤＝鳴りすぎる警報は鳴らないのと同じ）
  警告は**合成点の順**＝実際に繰り上がる順に並べる。次に席が空いたとき最初に入る社が先頭に来る。

思想:
  この道具は**読むだけ**。採点にもパックにも書き込まない（絶対のルール1）。
  合成点は score_all.json の `a`（門の単一実装 ccfAllocScore が出した値）をそのまま読む
  ——式を書き写すと v9.9.65 の「同じ台帳を見る二つの検査器が違うことを言う」になる。

使い方:
  python3 night/audit_promotion_ready.py          投下可＋次点を検査（CIはこれ）
  python3 night/audit_promotion_ready.py --band   判定圏(Ω72+)全社の作業リストも出す
終了コード: 投下可に FAIL があれば 1。次点の FAIL では落とさない。
"""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)

BAND = "--band" in sys.argv[1:]


def validate(tickers):
    """validate_packs をそのまま呼ぶ（判定の正本は向こう＝二重実装を作らない）。
    返り値: {ticker: [FAILの行, ...]}"""
    if not tickers:
        return {}
    p = subprocess.run([sys.executable, "night/validate_packs.py", *tickers],
                       capture_output=True, text=True)
    out, cur = {}, None
    for line in p.stdout.splitlines():
        s = line.strip()
        if line[:1] in "✓✗△":
            cur = s.split()[1] if len(s.split()) > 1 else None
        elif s.startswith("FAIL") and cur:
            out.setdefault(cur, []).append(s)
    return out


def main():
    rows = json.load(open(os.path.join(ROOT, "out", "score_all.json"), encoding="utf-8"))
    if not rows or "a" not in rows[0]:
        print("✗ out/score_all.json に合成点(a)が無い。先に `node night/score_all.js` を回すこと")
        return 1

    buy = sorted([r for r in rows if r.get("buy")], key=lambda r: -(r.get("a") or 0))
    nxt = sorted([r for r in rows if r.get("quali") and not r.get("buy")],
                 key=lambda r: -(r.get("a") or 0))
    band = [r for r in rows if (r.get("s") or 0) >= 72]

    print("■ 繰り上がる前の検査（validate_packs の FAIL を、繰り上がる順に）")
    print(f"  判定圏(Ω72+) {len(band)}社 のうち 四段関門を通っているのは {len(buy)+len(nxt)}社"
          f"（🟢投下可 {len(buy)} ／ 🔵次点 {len(nxt)}）")
    print("  残りは堀不足・E[r]<0・点検要修正で落ちており、根拠を埋めても投下可には来ない\n")

    fb = validate([r["t"] for r in buy])
    print(f"── 🟢投下可 {len(buy)}社 ── ここは落とす（今より悪くしないラチェット）")
    for r in buy:
        f = fb.get(r["t"], [])
        print(f"   {'✗' if f else '✓'} {r['t']:<7}Ω{r['s']:>5.1f}  合成{r.get('a', 0):>7.2f}"
              f"{'  ' + ' / '.join(f) if f else ''}")

    fn = validate([r["t"] for r in nxt])
    print(f"\n── 🔵次点 {len(nxt)}社 ── 落とさない。**次に席が空いたら上から入る**")
    for i, r in enumerate(nxt, 1):
        f = fn.get(r["t"], [])
        head = f"   {'⚠' if f else '✓'} {i}位 {r['t']:<7}Ω{r['s']:>5.1f}  合成{r.get('a', 0):>7.2f}"
        print(head)
        for line in f:
            print(f"        {line}")

    if BAND:
        rest = [r for r in band if not r.get("quali")]
        fr = validate([r["t"] for r in rest])
        print(f"\n── 判定圏だが四段関門に落ちている {len(rest)}社 ── 作業リスト（急がない）")
        for r in sorted(rest, key=lambda r: -(r.get("s") or 0)):
            why = ("堀不足" if not r.get("moatOK") else
                   "点検要修正" if not r.get("audOK") else
                   "門X遮断器" if r.get("xPass") is not True else
                   "Ω75未満" if (r.get("s") or 0) < 75 else "期末後の重大事象")
            f = fr.get(r["t"], [])
            print(f"   {'⚠' if f else '✓'} {r['t']:<7}Ω{r['s']:>5.1f}  {why:<10}"
                  f"{'FAIL ' + str(len(f)) + '件' if f else ''}")

    nb, nn = len(fb), len(fn)
    print(f"\n■ 結果: 投下可 FAIL {nb}社 ／ 次点 FAIL {nn}社")
    if nb:
        print("✗ **投下可に根拠なき値がある**。買付の直前に必ず潰すこと"
              "（門はパックの _meta を読めないので、この関門は端末にしか無い）")
        return 1
    if nn:
        names = " ".join(t for t in (r["t"] for r in nxt) if t in fn)
        print(f"::warning::次点に FAIL: {names} ——"
              f" 席が空くとこの順で入るので、上から先に潰すと7回目の不意打ちが無くなる")
    print("✓ 投下可は根拠の穴ゼロ")
    return 0


if __name__ == "__main__":
    sys.exit(main())
