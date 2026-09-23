#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/audit_intcov.py — 利払カバーの**被覆と基準**を数える（2026-08-13新設）

■ なぜ要るか
  歴史側の実測は「`利払カバー<3` は `nde>4` より左尾をよく分ける」と出した
  （母集団=層0・濃縮 **11.0倍 vs 2.82倍**・両方向とも正しい）。
  だが今日の台帳へ**そのまま当てると門が緩くなる**——実測:

    ・被覆   nde 365/369(99%) に対し 利払カバー 215/369(58%)、**日本株 0/68**
    ・交換すると15社でキルが外れ、うち**8社は利払カバーが未取得**
      （その中に **TDG**＝nde 5.88・債務超過＝台帳で最もレバレッジの重い社）
      ＝「測れない」を「問題なし」にする。絶対のルール7の同族

  さらに**数字そのものにも穴があった**——新たに死ぬ21社のうち **8社が `FinanceCosts`**
  （IFRSの財務費用＝為替差損・リース利息・引当の割引を含む上位概念）で、
  しかも**nde が純現金なのに利払カバーが3未満**という内部矛盾を起こしていた。

■ この器がやること（判定は作らない）
  1. 基準(`int_basis`)別・穴の理由別に数える
  2. **内部矛盾**を出す——純現金(nde≤0)なのに利払カバーが低い社は、
     利息以外（為替差損等）を利息と読んでいる疑い。ccfAudit の「内部矛盾」と同じ発想で、
     単独の帯検問では捕まらない**もっともらしい範囲内の誤り**を捕まえる
  3. 穴を**名前で出す**（日本株を「対象外」と黙って落とさない）

■ ★2026-08-13 v9.9.142 で、利払カバーは**キルの入力になった**
  財務キルは `nde>4` **または** `intcov_strict<3` の OR（ユーザー明示指示「入れて」）。
  **交換ではなく追加**なので被覆が薄くても絶対に緩くならないが、**空欄ではキルが眠る＝未測定が有利**。
  だからこの器の仕事は「材料を出す」から**「穴を名前で出し続ける」**へ変わった。
  ⚠ それでもこの器**自身**は買付を止めない（判定は compute() の側）。

■ ⚠ 4. パックが v11_facts に追随しているか（`fill_intcov` が止まった検出）
  キルの入力はパックの `intcov` 欄で、`night/fill_intcov.py` が v11_facts から写す。
  **これが止まると新しいパックの `intcov` が永久に空欄＝キルが眠る＝甘い側へ静かに壊れる**。
  「書けるのに書かれていない社」を数えて出す（0 が正常）。

■ ★2026-09-23: 原本で検算済みのパックを内部矛盾から分ける
  パックの `_meta.provenance.intcov` が machine 以外（審査官が原本で検算）の社は、
  v11_facts（FinanceCosts 等の別基準）ではなく**パックの値**で内部矛盾を裁き、
  消えたものは「✓検算済み」として別に出す（TIMB が鳴り続けて本物の矛盾を埋めていた）。
  逆向きの取り残し（v11_facts は空欄なのにパックに機械の値が残る）も名前で出す。

使い方: python3 night/audit_intcov.py [--json] [--list]
出力: out/audit_intcov.json（--json）
"""
import collections
import glob
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
OUT = os.path.join(BASE, "out")

LINE = 3.0          # 歴史側で測った線（新しい定数を発明していない・V12_SPEC 条件3と同じ）
NDE_KILL = 4.0      # 今日の門の財務キル


def jp(t):
    """日本株か（score_all.js:269 と同じ式——新しい規約を作らない）"""
    return bool(t) and t[:4].isdigit()


def main():
    facts = {}
    p = os.path.join(OUT, "v11_facts.json")
    if os.path.exists(p):
        d = json.load(open(p, encoding="utf-8"))
        facts = d.get("items") or {}
    sc = {}
    p = os.path.join(OUT, "score_all.json")
    if os.path.exists(p):
        d = json.load(open(p, encoding="utf-8"))
        sc = {r["t"]: r for r in (d if isinstance(d, list) else d.get("rows", []))}

    rows = []
    for pk in sorted(glob.glob(os.path.join(OUT, "*_gate_pack.json"))):
        t = os.path.basename(pk).replace("_gate_pack.json", "")
        d = json.load(open(pk, encoding="utf-8"))
        f = facts.get(t) or {}
        s = sc.get(t) or {}
        prov = (((d.get("_meta") or {}).get("provenance") or {}).get("intcov"))
        rows.append({
            "t": t, "omega": s.get("s"), "buy": bool(s.get("buy")),
            "nde": d.get("nde"),
            "pack_intcov": d.get("intcov"),   # ★キルが実際に読む値（v11_facts ではなくパックの欄）
            # 2026-09-23: 日本株は有報から intcov をパックへ直接入れた（v11_facts は SEC だけ）→ 空欄の理由も見る
            "pack_intcov_null": bool(((d.get("_meta") or {}).get("nulls") or {}).get("intcov")),
            # ★2026-09-23: パックの intcov を審査官が原本で検算した社（provenance が machine 以外）。
            #   fill_intcov はこの欄を上書きしない＝キルが読むのは v11_facts ではなくこの検算値
            "pack_prov": prov,
            "pack_verified": bool(prov and prov != "machine"),
            "intcov": f.get("intcov"), "intcov_strict": f.get("intcov_strict"),
            "intcov_cash": f.get("intcov_cash"),
            "basis": f.get("int_basis"), "period": f.get("int_strict_period") or "annual",
            "na": (None if f.get("intcov") is not None
                   else (f.get("intcov_na_reason") or ("absent" if not f else "unknown"))),
            "cands": f.get("int_tag_candidates"),
            "jp": jp(t),
        })
    n = len(rows)
    q72 = [r for r in rows if (r["omega"] or 0) >= 72]
    buy = [r for r in rows if r["buy"]]

    def cov(g, k):
        return sum(1 for r in g if r[k] is not None)

    print(f"■ 利払カバーの被覆（全{n}社 ／ 判定圏 {len(q72)} ／ 🟢投下可 {len(buy)}）")
    print(f"  {'':22}{'全社':>10}{'判定圏':>10}{'投下可':>10}")
    for label, k in (("nde（今日のキル）", "nde"), ("利払カバー intcov", "intcov"),
                     ("└ 真正の利息 strict", "intcov_strict"), ("└ 現金基準 cash", "intcov_cash")):
        print(f"  {label:<22}{cov(rows,k):>10}{cov(q72,k):>10}{cov(buy,k):>10}")

    print("\n■ 利息の基準（intcov が取れた社の内訳）")
    for b, c in collections.Counter(r["basis"] for r in rows if r["basis"]).most_common():
        mark = "  ✓真正" if b == "interest" else "  ⚠別基準"
        print(f"  {b:<16}{c:>5}社{mark}")
    qs = [r for r in rows if r["period"] == "quarters_sum"]
    if qs:
        print(f"  （うち四半期4本を合算して作った社 {len(qs)}: {' '.join(r['t'] for r in qs[:12])}）")

    print("\n■ 穴の理由（intcov が取れない社）")
    holes = collections.Counter(r["na"] for r in rows if r["na"])
    NAMES = {"no_debt": "無借金（＝穴ではない。キルは元から発火しない）",
             "stale": "利息の年次がアンカーから2年以上古い",
             "unmeasured": "負債の痕跡はあるのに利息が採れない",
             "absent": "SEC 経路にそもそも居ない",
             "unit_mismatch": "営業利益と利息の通貨（XBRL units）がそろわない＝割らない",
             "unknown": "不明"}
    for k, c in holes.most_common():
        j = sum(1 for r in rows if r["na"] == k and r["jp"])
        print(f"  {k:<12}{c:>5}社  {NAMES.get(k,'')}" + (f"  ⚠うち日本株 {j}社" if j else ""))
    jpn = [r for r in rows if r["jp"]]
    jp_pack = sum(1 for r in jpn if r["pack_intcov"] is not None)
    jp_null = sum(1 for r in jpn if r["pack_intcov"] is None and r["pack_intcov_null"])
    jp_hole = len(jpn) - jp_pack - jp_null
    print(f"  日本株 {len(jpn)}社は SEC 経路の外（v11_facts の intcov は {cov(jpn,'intcov')}社）——"
          f"**有報からパックへ直接: 実測 {jp_pack}社 ／ 理由つき空欄 {jp_null}社 ／ 理由の無い空欄 {jp_hole}社**"
          "（2026-09-23〜・更新は有報が出たら。上の穴の理由の集計は v11_facts 基準なので日本株を穴と数える）")

    # ── 内部矛盾: 純現金なのに利払カバーが低い ────────────────────────
    #   独立に入った二つの値が定義上ぶつかる＝もっともらしい範囲内の誤りを捕まえる唯一の検査
    #   ★2026-09-23: パックの intcov が**原本で検算済み**（provenance が machine 以外）の社は、
    #   v11_facts の値（FinanceCosts 等の別基準）ではなく**キルが実際に読むパックの値**で裁く。
    #   v11_facts だけを見ると、原本で直した TIMB が永久に鳴り続けて本物の矛盾が埋もれる。
    def _cov(r):
        return r["pack_intcov"] if r["pack_verified"] else r["intcov"]
    cand_bad = [r for r in rows if r["nde"] is not None and r["nde"] <= 0
                and r["intcov"] is not None and r["intcov"] < LINE]
    bad = [r for r in cand_bad if _cov(r) is not None and _cov(r) < LINE]
    cleared = [r for r in cand_bad if r not in bad]
    print(f"\n■ ★内部矛盾: **純現金(nde≤0)なのに利払カバー<{LINE:g}** — {len(bad)}社"
          + (f"（ほか ✓原本で検算済み {len(cleared)}社）" if cleared else ""))
    if cleared:
        print("   ✓検算済み（v11_facts は低いが、パックの intcov は審査官が原本で検算した値＝キルはこちらを読む）:")
        for r in cleared:
            print(f"     {r['t']:<7} nde={str(r['nde']):<7} v11 intcov={str(r['intcov']):<7}"
                  f"（基準={r['basis']}） → パック {r['pack_intcov']}（provenance={r['pack_prov']}）")
    if bad:
        print("   （利息以外〔為替差損・リース利息・引当の割引〕を利息と読んでいる疑い）")
        for r in sorted(bad, key=lambda x: -(x["omega"] or 0)):
            st = f"strict={r['intcov_strict']}" if r["intcov_strict"] is not None else "strict=算出不能"
            st += " ✓パックは検算済みでも<3" if r["pack_verified"] else ""
            print(f"     {'🟢' if r['buy'] else '  '}{r['t']:<7} Ω{(r['omega'] or 0):>5.1f} "
                  f"nde={str(r['nde']):<7} intcov={str(r['intcov']):<7} "
                  f"基準={str(r['basis']):<14} {st}")

    # ── 第二段: 未検証の「純現金」主張 ──────────────────────────────
    #   ★2026-08-13: 第一段(上)が **nde 側の誤り**を掘り当てた。原本で確認済み——
    #     ENB  有利子負債 104,410百万CAD（現金2,012）なのに nde=−0.07
    #     ACI  8,416百万$（現金293）なのに nde=−0.08。負債タグが2019年で終わり
    #          `LongTermDebtAndCapitalLeaseObligations` へ移っている＝**ECL/CDNS と同じ型**
    #     PH   6,769百万$（現金476）なのに nde=−0.10 ← **判定圏(Ω72.1)**
    #     BSX  10,915百万$（現金539）なのに nde=−0.39
    #   ⚠ 純現金かつ利息を払う会社は**実在する**（ADSK: nde−0.06・利払カバー19.7）ので
    #     これは容疑者一覧であって有罪判決ではない。**根拠が無いものだけ**を出す。
    tier2 = [r for r in rows
             if r["nde"] is not None and r["nde"] <= 0 and r["t"] not in {x["t"] for x in bad}
             and (facts.get(r["t"]) or {}).get("no_debt_evidence") is False
             and r["intcov"] is not None]
    noev = []
    for r in tier2:
        pk = os.path.join(OUT, f'{r["t"]}_gate_pack.json')
        ev = (json.load(open(pk, encoding="utf-8")).get("_meta", {}).get("evidence", {}) or {}).get("nde")
        if not ev:
            noev.append(r)
    print(f"\n■ 第二段: **未検証の『純現金』主張**（nde≤0 ∧ 負債の痕跡あり ∧ nde に根拠なし）— {len(noev)}社")
    print("   （純現金で利息も払う会社は実在する＝容疑者一覧であって有罪判決ではない）")
    print("   **利払カバーが低い順**＝利息が重い＝負債が大きいはず＝『純現金』と最も食い違う順")
    for r in sorted(noev, key=lambda x: x["intcov"])[:12]:
        print(f"     {'🟢' if r['buy'] else '  '}{r['t']:<7} Ω{(r['omega'] or 0):>5.1f} "
              f"nde={str(r['nde']):<7} 利払カバー={str(r['intcov'])}")

    # ── 交換 vs 追加（材料。判定はしない）──────────────────────────
    nk = {r["t"] for r in rows if r["nde"] is not None and r["nde"] > NDE_KILL}
    ik = {r["t"] for r in rows if r["intcov"] is not None and r["intcov"] < LINE}
    sk = {r["t"] for r in rows if r["intcov_strict"] is not None and r["intcov_strict"] < LINE}
    lost = [r for r in rows if r["t"] in nk - ik]
    blind = [r for r in lost if r["intcov"] is None]
    print(f"\n■ 物差しを替えたらどうなるか（材料・判定ではない）")
    print(f"  nde>4 が殺す {len(nk)}社 ／ 利払カバー<{LINE:g} が殺す {len(ik)}社"
          f"（真正の利息だけなら {len(sk)}社） ／ 重なり {len(nk & ik)}社")
    print(f"  **交換**すると {len(lost)}社でキルが外れ、うち **{len(blind)}社は利払カバーが未取得**"
          + (f": {' '.join(r['t'] for r in blind)}" if blind else ""))
    add = [r for r in rows if r["t"] in ik - nk]
    print(f"  **追加**（nde>4 または 利払カバー<{LINE:g}）なら新たに {len(add)}社が死ぬ"
          f"——🟢投下可 {sum(1 for r in add if r['buy'])}社 ／ 判定圏 {sum(1 for r in add if (r['omega'] or 0)>=72)}社"
          f" ／ 最高Ω {max([r['omega'] or 0 for r in add], default=0):.1f}")
    print("  ⇒ **追加は被覆が薄くても絶対に緩くならない。交換は測れない社のキルが外れる。**")

    # ★パックが v11_facts に追随しているか＝`fill_intcov` が止まった検出（0 が正常）。
    #   止まると新しいパックの intcov が空欄のまま＝キルが眠る＝**甘い側へ静かに壊れる**。
    #   検算済みのパック（provenance が machine 以外）は fill_intcov が意図して書かないので遅れに数えない
    behind = [r for r in rows if r["intcov_strict"] is not None and not r["pack_verified"]
              and (r["pack_intcov"] is None or abs(r["pack_intcov"] - r["intcov_strict"]) > 1e-9)]
    # ★逆向きの取り残し: v11_facts が空欄（通貨不一致・CIK是正等）なのにパックに機械の値が残っている。
    #   fill_intcov は空欄を書かない（消さない）ので、ここで名前を出さないと古い誤値がキルに残り続ける
    orphan = [r for r in rows if r["intcov_strict"] is None and r["pack_intcov"] is not None
              and not r["pack_verified"] and not r["jp"]]
    print(f"\n■ パックの追随（fill_intcov が止まった検出）: 遅れ {len(behind)}社"
          + ("（0＝正常）" if not behind else
             f"　⚠ python3 night/fill_intcov.py --write が要る: {' '.join(r['t'] for r in behind[:12])}"))
    vfd = [r for r in rows if r["pack_verified"]]
    print(f"  ✓原本で検算済み（fill_intcov が上書きしない）{len(vfd)}社: {' '.join(r['t'] for r in vfd)}")
    if orphan:
        print(f"  ⚠v11_facts は空欄なのにパックに機械の intcov が残る {len(orphan)}社"
              "（fill_intcov は空欄を書かない＝古い値がキルに残る。原因を確かめて人が消すこと）: "
              + " ".join(f"{r['t']}={r['pack_intcov']}({(facts.get(r['t']) or {}).get('intcov_na_reason') or '—'})"
                         for r in orphan))

    cands = [r for r in rows if r["cands"]]
    if cands:
        print(f"\n■ ⏳候補列に無い利息らしいタグが実在する社 {len(cands)}社（作業リスト・値は採っていない）")
        for r in cands[:15]:
            print(f"     {r['t']:<7} {' '.join(r['cands'][:3])}")

    if "--list" in sys.argv:
        print("\n■ 全社（Ω降順）")
        for r in sorted(rows, key=lambda x: -(x["omega"] or 0)):
            print(f"  {'🟢' if r['buy'] else '  '}{r['t']:<7} Ω{(r['omega'] or 0):>5.1f} "
                  f"nde={str(r['nde']):<8} intcov={str(r['intcov']):<8} "
                  f"strict={str(r['intcov_strict']):<8} 基準={str(r['basis']):<14} {r['na'] or ''}")

    if "--json" in sys.argv:
        out = {"tool": "night/audit_intcov.py", "line": LINE, "nde_kill": NDE_KILL,
               "n": n, "n_q72": len(q72), "n_buy": len(buy),
               "coverage": {k: {"all": cov(rows, k), "q72": cov(q72, k), "buy": cov(buy, k)}
                            for k in ("nde", "intcov", "intcov_strict", "intcov_cash")},
               "basis": dict(collections.Counter(r["basis"] for r in rows if r["basis"])),
               "holes": dict(holes),
               "jp_hole": [r["t"] for r in jpn if r["intcov"] is None],
               "contradiction_netcash_lowcov": [r["t"] for r in bad],
               "unverified_netcash": [r["t"] for r in noev],
               "swap_loses_kill": [r["t"] for r in lost],
               "swap_loses_kill_unmeasured": [r["t"] for r in blind],
               "add_newly_killed": [r["t"] for r in add],
               "packs_behind_fill_intcov": [r["t"] for r in behind],
               "contradiction_cleared_by_kenshi": [r["t"] for r in cleared],
               "packs_verified_intcov": [r["t"] for r in rows if r["pack_verified"]],
               "packs_orphan_machine_intcov": [r["t"] for r in orphan],
               "tag_candidates": {r["t"]: r["cands"] for r in cands},
               "rows": rows}
        json.dump(out, open(os.path.join(OUT, "audit_intcov.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print("\n→ out/audit_intcov.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
