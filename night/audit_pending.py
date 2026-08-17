#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/audit_pending.py — **合意済み・未完了の重大事象**で買付を止める（v9.9.128・2026-08-10新設）

なぜ要るか（実際に踏んだ穴・ユーザーの問い「こういったことが起きた場合に自動で買付候補から外れる仕組みがいるのでは？」）:

  2026-08-07、デラウェア州衡平法裁判所が **VRSK に AccuLynx 買収（23.5億ドル）の完了へ進むよう命じた**
  （Verisk 自身が2025年12月に解除していたのを「willful conduct が条件不成立を招いた」として無効と判断）。
  VRSK は当日 🟢投下可 のままだった。門はこの事実を**どこからも見ていない**。

  門にはこの型の検査が既に2つあるのに、**どちらも事象より後ろにしか目が無い**:

    合意/判決 ─────► クローズ ─────► 次の10-Q ─────► 次の10-K
        │               │              │              │
        └ 誰も見ていない ┴ 誰も見ていない ┘   stale_bs が   acq5/roic が
                                            初めて見る      見る
        ←──────── ここが穴（数ヶ月〜1年超）────────→

    ・watch_events.py は8-Kを毎日見るが、警報は Item 1.03/2.06/3.01/4.02/5.02 の5つだけ。
      M&Aの 1.01/1.02 と「その他」の 8.01 は `others` に落ちて**記録だけ**（判定に不使用と明記）。
    ・audit_stale_bs.py は**実際に貸借対照表に載ったのれん**を10-Qで見る。
      **未完了の買収はのれんがゼロなので構造的に見えない。**

  つまり VRSK を逃したのは運ではなく設計。**これは stale_bs の時間的な穴を塞ぐだけ**で、
  新しい思想も新しい定数も導入しない。

これは1社の話ではない（数えた）:
  台帳の _meta には既に**6社**ぶんの未完了・期末後の重大事象が書かれている——
    VRSK Ω81.8 🟢投下可  AccuLynx $2.35B・判決で強制（未完了）
    CTAS Ω83.1 判定圏    UniFirst 約$5.5B・株主承認済（未完了）★台帳で2番目に高いΩ
    ALSN Ω31.7 圏外      2026-01 大型買収完了（_meta が「**前方フラグとして記録**」と明記）
    APH  Ω75.7 判定圏    CommScope $10.5B 完了済（stale_bs が捕まえた唯一の例）
    LOAR Ω25.1 圏外      期末後 有利子負債+33%（stale_bs はのれんの新しさ6.7%で捕まえられなかった）
    MKSI Ω38.6 圏外      期末後 nde 4.34→3.72（改善側）
  **「前方フラグ」という語が _meta に literally 書いてある。審査官は既に観測して書いている。
  それを読むものが一つも無かった＝足りないのは観測ではなく配線。**

  いちばん危ないのは VRSK ではなく **CTAS**。Ω83.1 を止めているのは堀66.6 だけで、
  CLAUDE.md 自身が「moatW の2本目が15%線まで2.6pt不足・+0.65pt/年＝**FY2030頃に再判定の扉**」と
  書いている——**堀が上がった瞬間、$5.5B を抱えたまま買付に入る。**

何を測るか（新しい定数をひとつも作らない）:
  **完了したら、のれんの何割が新しくなるか ＝ 対価 ÷（現のれん ＋ 対価）**
  ——これは acq5 と stale_bs がすでに使っている問いで、刻みもそのまま（≥30%／<10%／中間は判定不能）。
  実測: VRSK 2,350÷(1,878+2,350)=**55.6%** ／ CTAS 5,500÷(3,400+5,500)=**61.8%** → どちらも発火。

  **のれんを持たない社は総資産で裁く**——「のれんが無い＝影響なし」ではない（ルール7: 欠測をゼロと読むな）。
  買収は必ず何らかの資産を増やすので、のれん系列が無い社は 対価÷総資産 を同じ刻みに当てる。

  **売却(divestiture)だけは分母が違う＝対価÷総資産（2026-08-16是正・刻みは買収と同一）**。
  買収では現のれんと対価が互いに素なので足して割るのが正しいが、**売却で出ていく事業は既に分母の中にある**。
  同じ式を当てると (a)分母で二重に数え (b)『新しくなる』が0なのに正の%が出る＝答えが問いに対応しない。
  しかも判定が「のれんの大きさ」という無関係な量で決まる——実測 RMD の MatrixCare($490M)は
  のれん基準 14.4%(判定不能=買付を止める) / 総資産基準 **5.5%(ok)** で、のれんが仮に$10Bなら同じ取引が4.7%(ok)。
  **閾値の選び方ではなく分母の category error**（「基準の違う二つを割る」型）。総資産基準は
  売上3.9%・営業利益1.5%・時価総額1.5%という独立な三つの物差しとも向きが揃う。
  ⚠**売却でも大きければ止まる**（注入検査済み: 同じRMDで対価3,000百万$＝総資産の33.5%にすると要審査）。
  ⚠買収側は一切変えていない（実測 CTAS 61.1% / VRSK 55.8% で要審査のまま）。

思想:
  この道具は**読むだけ**で、採点にもパックにも書き込まない。
  検出は「この銘柄は買付の土俵に載せない」＝第四の関門の領分であり、
  Ω・採点式・堀の関門・売却規律S1/S2/S3 はいずれも動かさない（絶対のルール1）。
  **買わない理由であって売る理由ではない。** 落ちた社は⛔で名指し表示（v9.9.52）。

  **完全な自動化ではない**——判決も合意も数字ではないので、`_meta.pending` を書くのは審査官。
  門ができるのは「**書かれていたら必ず効かせる**」ところまで。見落としの網として
  watch_events.py が 8-K の 1.01/1.02/8.01 を判定圏に絞って作業リストに出す（警報には格上げしない
  ——8.01は雑多で「鳴りすぎる警報は鳴らないのと同じ」を自分で作ることになる）。

パックに書く形（_meta.pending・配列）:
  "pending": [{
    "kind":   "acquisition",          // acquisition / divestiture / litigation / debt
    "target": "AccuLynx",
    "size_usd_m": 2350,               // 対価（百万$）。**必須**——これが無いと規模を裁けない
    "status": "court-ordered",        // agreed / shareholder-approved / court-ordered / closed / terminated
    "src":    "https://... (8-K/DEFM14A/判決)",
    "note":   "…"
  }]
  status が **terminated（解消済み）** の項目は発火しない。**closed** も発火しない
  （閉じた後は stale_bs が実額で見るので、ここで二重に数えない）。

使い方:
  python3 night/audit_pending.py             判定圏(Ω72+)だけ
  python3 night/audit_pending.py --all       全パック
  python3 night/audit_pending.py --t VRSK    1銘柄
  python3 night/audit_pending.py --write     out/pending.json を更新（score_all.js と門が読む）
出力:
  out/pending.json … {"items": {ticker: {size, base, newPct, verdict, status, target, ...}}}
"""
import json
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "out")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# **SEC取得は audit_stale_bs のものをそのまま使う**（二重実装を作らない・v9.9.65の掟）。
#   同モジュールは import 時に sys.argv を読むので、`--t` は必ず値を伴わせること（下のARGV検問）。
import audit_stale_bs as SB

# acq5 / stale_bs と同じ刻みを使う（新しい定数を作らない）
NEW_YES, NEW_NO = SB.NEW_YES, SB.NEW_NO

# 発火させない status。**closed は stale_bs が実額で見るのでここでは数えない**（二重計上の回避）
DEAD = {"terminated", "closed", "withdrawn", "abandoned"}

ARGV = sys.argv[1:]
ALL = "--all" in ARGV
WRITE = "--write" in ARGV
ONE = None
if "--t" in ARGV:
    i = ARGV.index("--t")
    if i + 1 >= len(ARGV):
        print("--t にはティッカーが要る（例: --t VRSK）")
        sys.exit(2)
    ONE = ARGV[i + 1].upper()


def pendings(meta):
    """_meta.pending を正規化して返す。単体dictでも配列でも受ける（型崩れ耐性）"""
    p = (meta or {}).get("pending")
    if p is None:
        return []
    if isinstance(p, dict):
        p = [p]
    if not isinstance(p, list):
        return []
    return [x for x in p if isinstance(x, dict)]


def base_of(t, meta, kind=None):
    """規模を測る分母。(値, 何を使ったか) を返す。

    **kind で分母が変わる。閾値(NEW_YES/NEW_NO)は一つも変えない**（2026-08-16是正）:

      買収  … のれん優先、無ければ総資産。問いは「対価÷(現のれん+対価)＝完了後のれんの何割が新規か」。
              現のれんと対価は**互いに素**（新しいのれんが上に乗る）ので足して割るのが正しい。

      売却  … **総資産のみ**。問いは「対価÷総資産＝会社の何割が出ていくか」。
              売る事業は**既に現のれん・総資産の中にある**ので、買収と同じ式にすると
              (a)分母で二重に数える (b)『新しくなる』が0なのに正の%が出る＝**答えが問いに対応しない**。
              しかも判定が「のれんの大きさ」という無関係な量で決まる——実測 RMD の MatrixCare 売却($490M)は
              のれん基準だと 14.4%(判定不能=買付を止める) だが、のれんが仮に$10Bなら同じ取引が 4.7%(ok)。
              **これは閾値の選び方ではなく分母の category error**（この台帳が11回踏んだ「基準の違う二つを割る」型）。
              総資産で測れば 490/8,966=5.5%＝ok で、売上3.9%・営業利益1.5%・時価総額1.5%の実測とも向きが揃う。
              ⚠**売却でも大きければ止まる**——総資産の30%を売れば要審査になる（刻みは買収と同一）。
    """
    if re.fullmatch(r"\d{4}", t):
        return None, "日本株(SEC対象外)"
    cik = SB.cik_of(t)
    if not cik:
        return None, "CIK不明(ADR等)"
    tags = (("Assets", "総資産"),) if kind == "divestiture" else (("Goodwill", "のれん"), ("Assets", "総資産"))
    for tag, lbl in tags:
        s = SB.concept(cik, tag)
        if s:
            k = max(s)
            v = s[k]
            if v and v > 0:
                return (v / 1e6, f"{lbl}({k})")
    return None, ("総資産が取得不能" if kind == "divestiture" else "のれん・総資産とも取得不能")


def main():
    rows = json.load(open(os.path.join(OUT, "score_all.json"), encoding="utf-8"))
    if ONE:
        pick = [r for r in rows if r["t"] == ONE]
    elif ALL:
        pick = rows
    else:
        pick = [r for r in rows if (r.get("s") or 0) >= 72]

    print(f"■ 合意済み・未完了の重大事象（_meta.pending）　対象 {len(pick)}社"
          f"{'（判定圏 Ω72+）' if not (ALL or ONE) else ''}")
    print(f"  判定: 買収=「対価÷(現のれん+対価)＝完了後のれんの何割が新規か」／"
          f"売却=「対価÷総資産＝会社の何割が出ていくか」が {NEW_YES:.0f}% 以上なら要審査")
    print(f"        （acq5・stale_bs と同じ刻み＝新しい定数を作らない。売却で分母が違うのは"
          f"『売る事業は既に分母の中にある』ため）\n")

    res, skipped, seen = {}, [], 0
    for r in pick:
        t = r["t"]
        p = os.path.join(OUT, f"{t}_gate_pack.json")
        if not os.path.exists(p):
            continue
        d = json.load(open(p, encoding="utf-8"))
        items = pendings(d.get("_meta"))
        if not items:
            continue
        seen += 1
        live = [x for x in items if str(x.get("status", "")).lower() not in DEAD]
        if not live:
            print(f"  {t:<7}記録あり（すべて解消済/完了済＝発火しない）")
            continue
        # 規模は**合算しない**——一件ごとに裁く。合算すると小口の積み上げが大型買収に化ける
        sized = [x for x in live if isinstance(x.get("size_usd_m"), (int, float)) and x["size_usd_m"] > 0]
        if not sized:
            # 規模が書かれていない＝**測れない**。ゼロと読まず「判定不能」で明示する（ルール7）
            res[t] = dict(verdict="判定不能", why="size_usd_m が無い（規模を裁けない）",
                          omega=r.get("s"), buy=bool(r.get("buy")),
                          items=[{k: x.get(k) for k in ("kind", "target", "status", "src")} for x in live])
            print(f"  {t:<7}⚠ 判定不能——size_usd_m が書かれていない")
            continue
        big0 = max(sized, key=lambda x: x["size_usd_m"])
        kind0 = str(big0.get("kind") or "").lower()
        base, src = base_of(t, d.get("_meta"), kind0)
        if base is None:
            res[t] = dict(verdict="判定不能", why=f"分母が取れない（{src}）",
                          omega=r.get("s"), buy=bool(r.get("buy")),
                          items=[{k: x.get(k) for k in ("kind", "target", "status", "size_usd_m")} for x in sized])
            print(f"  {t:<7}⚠ 判定不能——{src}")
            continue
        big = big0
        size = float(big["size_usd_m"])
        # 売却は「売る事業が既に分母の中にある」ので +size しない（base_of の頭注）。閾値は買収と同一
        new_pct = (size / base if kind0 == "divestiture" else size / (base + size)) * 100.0
        verdict = ("要審査" if new_pct >= NEW_YES
                   else "判定不能" if new_pct > NEW_NO else "ok")
        rec = dict(verdict=verdict, newPct=round(new_pct, 1), size=size, base=round(base, 1),
                   baseSrc=src, kind=big.get("kind"), target=big.get("target"),
                   metric=("対価÷総資産＝会社の何割が出ていくか" if kind0 == "divestiture"
                           else "対価÷(現のれん+対価)＝完了後のれんの何割が新規か"),
                   # 表示はここが正本。**売却で「のれんが新規」と書くと事実に反する**ので kind で言い分ける
                   pctLabel=(f"総資産の{new_pct:.1f}%が出ていく" if kind0 == "divestiture"
                             else f"完了後のれんの{new_pct:.1f}%が新規"),
                   status=big.get("status"), src=big.get("src"), note=big.get("note"),
                   omega=r.get("s"), buy=bool(r.get("buy")), n=len(live))
        if verdict != "ok":
            res[t] = rec
        mark = "⚠ " + verdict if verdict != "ok" else "✓"
        lbl2 = "規模" if kind0 == "divestiture" else "新しさ"
        print(f"  {t:<7}{str(big.get('target') or big.get('kind') or '')[:18]:<19}"
              f"{size:>9,.0f} 百万$  ÷ {src:<22}  {lbl2:<3}{new_pct:>5.1f}%  {mark}")

    print()
    bad = {k: v for k, v in res.items() if v["verdict"] == "要審査"}
    mid = {k: v for k, v in res.items() if v["verdict"] == "判定不能"}
    if bad:
        print("■ 要審査（完了すれば会社の姿が大きく変わる＝買付の土俵から降ろす）")
        for t, v in sorted(bad.items(), key=lambda x: -(x[1].get("newPct") or 0)):
            # ⚠ v["buy"] は**この関門が効いた後**の score_all を読んでいるので、
            #   発火中の社は常に false になる（自己参照）。だから「投下可か」ではなく
            #   **Ωが判定圏か**で目立たせる——止めた事実そのものは上の verdict が言っている。
            mark = " ← **判定圏(Ω75+)**" if (v.get("omega") or 0) >= 75 else ""
            print(f"   {t:<7}Ω{v['omega']:.1f}  {v.get('target') or ''} {v['size']:,.0f}百万$"
                  f"（{v.get('status')}）＝{v.get('pctLabel') or ('完了後のれんの%.1f%%が新規' % v['newPct'])}{mark}")
    if mid:
        print("■ 判定不能（中間帯・規模不明・分母不明——acq5と同じく空欄に倒すが関門は掛ける）")
        for t, v in mid.items():
            print(f"   {t:<7}{v.get('why') or ('新しさ %.1f%%' % v.get('newPct', 0))}")
    if not res:
        print(f"✓ 発火する未完了の重大事象は無し（_meta.pending を持つ社 {seen}）")
    print(f"\n  _meta.pending を持つ社: {seen} / 対象 {len(pick)}")
    print("  ※ この欄は審査官が書く。門ができるのは「書かれていたら必ず効かせる」ところまで＝")
    print("     見落としの網は night/watch_events.py の 8-K作業リスト（1.01/1.02/8.01）が受け持つ")

    if WRITE:
        # 空書き込みの検問（audit_stale_bs:243 と同じ言葉。v9.9.140）
        #   ⚠錨は pick ではなく **rows（母数）**——`--t T` では pick が1社なのが正常なので、
        #     pick で裁くと単社実行のたびに落ちる。**score_all が空＝第四の関門の入力が作れない**。
        #   検査の不在を「異常なし」と偽らないため、**書かずに落ちる**。
        #   （実測: pending.json が空/キー違いになると VRSK が投下可に入り HWM が落ちる）
        if not rows:
            print("\n⚠ out/score_all.json が空（または読めない）。**pending.json を書き換えない**"
                  "——空で上書きすると第四の関門が全社について通過になる")
            return 1
        path = os.path.join(OUT, "pending.json")
        json.dump({"asof": time.strftime("%Y-%m-%d"),
                   "rule": f"対価÷(現のれん+対価) ≥{NEW_YES:.0f}% で要審査（acq5・stale_bsと同じ刻み）",
                   "note": ("判定には verdict!='ok' を使う。買わない理由であって売る理由ではない。"
                            "⚠ items[].buy は score_all.json から読んだ**この関門が効いた後**の状態なので、"
                            "発火中の社は false になる（関門が仕事をしている証拠であって、"
                            "『元から買付候補ではなかった』という意味ではない）"),
                   "items": res}, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"\n→ {path} を更新（score_all.js と門が第四の関門で読む）")
    else:
        print("\n（--write で out/pending.json を更新する）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
