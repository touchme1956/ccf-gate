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
  四関門を通っているのは **17社だけ**で、残り32社は堀不足・E[r]<0・点検要修正で
  落ちており、根拠を全部埋めても投下可には来ない。**危ないのは次点だけ。**

何をするか（二層。第四の関門と同じ作法）:
  ・**投下可（席に入った社）に FAIL があれば落とす**（今日はゼロ＝「今より悪くしない」ラチェット。
    ⚠席の数は門の CCF_SEATS＝v9.9.171 で 10→5。この道具は score_all.json の buy/quali を読むので自動で追随する。
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
TODAY = __import__("datetime").date.today().isoformat()
os.chdir(ROOT)

BAND = "--band" in sys.argv[1:]
JSON = "--json" in sys.argv[1:]   # 2026-08-11: 作業リストを機械可読で出す（enqueue_reaudit が読む）


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
    print(f"  判定圏(Ω72+) {len(band)}社 のうち 四関門を通っているのは {len(buy)+len(nxt)}社"
          f"（🟢投下可 {len(buy)} ／ 🔵次点 {len(nxt)}）")
    print("  残りは堀不足・E[r]<0・点検要修正で落ちており、根拠を埋めても投下可には来ない\n")

    fb = validate([r["t"] for r in buy])
    print(f"── 🟢投下可 {len(buy)}社 ── ここは落とす（今より悪くしないラチェット）")
    for r in buy:
        f = fb.get(r["t"], [])
        print(f"   {'✗' if f else '✓'} {r['t']:<7}Ω{r['s']:>5.1f}  合成{r.get('a', 0):>7.2f}"
              f"{'  ' + ' / '.join(f) if f else ''}")

    fn = validate([r["t"] for r in nxt])
    print(f"\n── 🔵次点 {len(nxt)}社 ── **次に席が空いたら上から入る**")
    for i, r in enumerate(nxt, 1):
        f = fn.get(r["t"], [])
        print(f"   {'⚠' if f else '✓'} {i}位 {r['t']:<7}Ω{r['s']:>5.1f}  合成{r.get('a', 0):>7.2f}")
        for line in f:
            print(f"        {line}")

    # ── v9.9.95 以降、納品検査FAILは第四の関門そのものなので、FAILを持つ社は quali を失う。
    #   すると**作業リストが「落ちている社」の山に埋もれて見えなくなる**ので、
    #   「根拠さえ埋めれば資格を得る社」だけを合成点順に切り出す＝ここが本当の作業リスト。
    # 2026-08-11 是正: **buyGate と同じ条件を並べる（納品検査FAILだけを外す）**。
    #   旧実装は `xPass is True` を要求していたが、**v9.9.98 で門X遮断器は関門から外れている**
    #   ——外した関門の条件がこの道具に残り、**ETN(xPass=None)・6920(xPass=False) を黙って作業リストから
    #   落としていた**（実測: 3社→5社）。加えて buyGate が見る frame85（別枠85）・shrink（事業の収縮）・
    #   pending（未完了の重大事象）を見ていなかった。
    #   ⚠ ここは buyGate を import できない（Python）ので**条件を書き写している**＝v9.9.65 の例外。
    #      score_all.js が同じ判定を row の各欄として出しているので、**その欄だけを見る**形にして
    #      規則の再実装ではなく「結果を読む」に留める。
    def ready_ok(r):
        return (((r.get("s") or 0) >= 75 or r.get("frame85"))   # Ωの線 or 別枠85
                and r.get("moatOK") is True                      # 堀70+
                and (r.get("audE") or 0) == 0 and (r.get("audU") or 0) == 0
                and r.get("staleBS") is None and r.get("pending") is None
                and r.get("shrink") is None
                and (r.get("vFail") or 0) > 0)                   # ← ここだけが残っている穴
    ready = [r for r in rows if ready_ok(r)]
    ready.sort(key=lambda r: -(r.get("a") or 0))
    fr = validate([r["t"] for r in ready])
    print(f"\n── 🔧 根拠さえ埋めれば資格を得る {len(ready)}社 ── "
          f"**ここが作業リスト。上から潰すと繰り上がりの不意打ちが消える**")
    for i, r in enumerate(ready, 1):
        print(f"   {i}. {r['t']:<7}Ω{r['s']:>5.1f}  合成{r.get('a', 0):>7.2f}"
              f"（埋めれば次点 {len(nxt) + i} 位相当）")
        for line in fr.get(r["t"], []):
            print(f"        {line}")

    if BAND:
        rest = [r for r in band if not r.get("quali")]
        fr = validate([r["t"] for r in rest])
        print(f"\n── 判定圏だが四関門に落ちている {len(rest)}社 ── 作業リスト（急がない）")
        for r in sorted(rest, key=lambda r: -(r.get("s") or 0)):
            why = ("堀不足" if not r.get("moatOK") else
                   "点検要修正" if not r.get("audOK") else
                   "門X遮断器" if r.get("xPass") is not True else
                   "Ω75未満" if (r.get("s") or 0) < 75 else "期末後の重大事象")
            f = fr.get(r["t"], [])
            print(f"   {'⚠' if f else '✓'} {r['t']:<7}Ω{r['s']:>5.1f}  {why:<10}"
                  f"{'FAIL ' + str(len(f)) + '件' if f else ''}")

    nb, nn = len(fb), len(fn)
    print(f"\n■ 結果: 投下可 FAIL {nb}社 ／ 次点 FAIL {nn}社 ／ 根拠待ち {len(ready)}社")
    if nb or nn:
        # v9.9.95 で関門にしたので、ここが鳴るのは **out/validate_fail.json が古い** ときだけ。
        # 関門が JSON を読む以上、JSON の鮮度が関門の鮮度そのものになる。
        print("✗ 関門を通っている社に FAIL がある＝ out/validate_fail.json が古い。"
              "`python3 night/validate_packs.py --json` を回してから score_all を回すこと")
        return 1
    if JSON:
        # 2026-08-11: **作業リストを待ち行列へ渡す**ための機械可読出力。
        #   検出は既に自動なのに、渡し先が人の目しか無かった（enqueue_reaudit が読む）。
        json.dump({"generated": TODAY, "n": len(ready),
                   "note": "根拠さえ埋めれば四関門を通る社（納品検査FAILだけが残っている）。"
                           "合成点順＝繰り上がる順。night/enqueue_reaudit.py が最優先で拾う。",
                   "rows": [{"t": r["t"], "s": r.get("s"), "a": r.get("a"),
                             "vFail": r.get("vFail"), "rank": i}
                            for i, r in enumerate(ready, 1)]},
                  open(os.path.join(ROOT, "out", "promotion_ready.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print(f"→ out/promotion_ready.json を更新（{len(ready)}社）")
    if ready:
        print(f"::warning::根拠さえ埋めれば資格を得る: {' '.join(r['t'] for r in ready)} ——"
              f" 席順＝繰り上がる順。上から潰すと不意打ちが消える")
    print("✓ 投下可・次点ともに根拠の穴ゼロ")
    return 0


if __name__ == "__main__":
    sys.exit(main())
