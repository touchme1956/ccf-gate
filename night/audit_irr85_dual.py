# night/audit_irr85_dual.py — irr=85 の「二重読み」の有無を数える（2026-08-12新設）
#
# ★この器が存在する理由（実測された穴）:
#   2026-08-12 の測定で、**同じ111社でも読解の班が違うと irr=85 の付与率が
#   5.4% → 17.1%（3.2倍・符号検定 p=0.017）** と動くことが判った。
#   門は irr=85 に **別枠(v9.9.119) と 席の優先(v9.9.100)** を与えているので、
#   **同じ会社が「いつ・誰に読まれたか」で買付に入ったり入らなかったりしうる**。
#
#   門には既に3つの防御がある——
#     (1) `audit_irr85.py` が根拠の型を仕分ける
#     (2) `irr85_mech_diff.py` が機構文を原本と**毎月一字照合**する
#     (3) 2026-08-05/06 に同じ厳格な試験を当て直して **53社→11社** へ削った再アンカーの実績
#   **足りないのは「新しく85を付けたとき、別の読み手が検証する」という一手**だけだった。
#   実例: KRMN は 2026-08-10 に新規上場の掃除が irr 70→**85** へ上げたが、
#   **誰も独立に検証していない**まま買付の土俵の資格に効いている。
#
# ⚠ **これは関門ではない。** 未検証は「欠陥」ではなく「工程の途中」で、
#   ここで買付を止めると **v9.9.66 が未解決warnについて出した結論
#   （原本で確定済みなのに鳴り続けるものを『データ経路の欠落』を理由に落とすことになる）**
#   と同じ誤りを犯す。この器が出すのは**作業リスト**であって合否ではない。
#   採点式・刻み・重み・関門・売却規律には一切触れない。
#
# 【二重読みが満たすべき検問（審査プロトコルと同じ6点。ここと文が食い違ってはいけない）】
#   1. 引用が原本に一字一句あるか（`irr85_mech_diff.py` が機械で照合する）
#   2. 引用が「**顧客の側が**再認定・再試験の費用と時間を負う」を述べているか
#   3. **向きが逆でないか**——自社が受ける認証／自社が仕入先を認定する話は当たらない
#      （RMD=自社特許・IRMD=自社510(k)・MSI=『reduce barriers to entry』を根拠にしていた前例）
#   4. **願望形でないか**（『we work closely with』『strive to』。CDNS を70へ下げた理由）
#   5. 同じ原本に**反証が同居していないか**（『low barriers to entry』『price erosion』等）
#   6. **機構の射程**——全社の記述か、一セグメントのリスク要因の中か
#      （CW の決定的な機構文は Item 1A の航空の節にあり射程12.29% だった）
#
# 記録の置き場: `_meta.irr85_verify`（配列）。
#   ⚠ `_meta.evidence.irr` の中に書かない——`irr85_mech_diff.py` が evidence の英文引用を
#     原本と逐語照合するので、日本語の注記を混ぜると照合の断片が汚れる（v9.9.128 で確立した作法）。
#   欄: {date, kind, verdict, by, note}
#     kind    = "二重読み"（rung そのものの独立な再検算）/ "初回審査"（一人しか読んでいない）
#     verdict = "据置" / "据置(留保)" / "変更" / "撤回"
#
# 実行: python3 night/audit_irr85_dual.py [--json] [--all]
# 出力: out/irr85_dual.json
# 終了コード: **常に0**（作業リストであって関門ではない）

import datetime
import glob
import json
import os
import sys

# ─────────────────────────────────────────────────────────────────────────
# ★2026-08-19: **irr=70 の買付圏にも二重読みを広げた**
#
#   なぜ（費用の非対称）: 実測(night/shadow_irr_step.js)で
#     判定圏の **70→50 は投下可を10社→5社**にする（6社が堀の関門70を割り、RBCは席を失う）。
#     一方 **50→70 も 85→70 も 0社しか動かさない**＝**コストは 70→50 の一方向**。
#   そして刻み別のラベル一致率は 100:1.00(n=3) / 85:1.00(n=5) / **70:0.706(n=34)** / 50:0.971(n=104)
#     ＝**70だけが不安定**なのに、85にある三層（根拠の型・逐語照合・二重読み）のうち
#     70が持っていたのはキーワードのtriageだけだった。
#
#   ⚠ **全213社は対象にしない**。全数を積むと作業リストが埋まって
#     「鳴りすぎる警報は鳴らないのと同じ」になり、しかも費用が生じるのは買付圏だけ。
#
#   検問は 85 とは**別**（問いが違う）——85は「顧客が費用を負うか」、70は「50ではないと言えるか」。
#   v9.9.144（2026-08-12 ユーザー明示指示）が定めた
#   「70を置くなら**摩擦の機構を名指しし、原本の引用を付ける**／付けられないなら50」を検問に落としただけで、
#   **新しい定数も新しい刻みも導入していない**。
# ─────────────────────────────────────────────────────────────────────────
CHECKS = {
    '85': [
        "引用が原本に一字一句あるか（irr85_mech_diff が機械で照合）",
        "引用が『**顧客の側が**再認定・再試験の費用と時間を負う』を述べているか",
        "向きが逆でないか（自社が受ける認証／自社が仕入先を認定する話は当たらない）",
        "願望形でないか（we work closely with / strive to）",
        "同じ原本に反証が同居していないか（low barriers to entry / price erosion）",
        "機構の射程——全社の記述か、一セグメントのリスク要因の中か",
    ],
    '70': [
        "引用が原本に一字一句あるか（irr85_mech_diff --rung 70 --buy が機械で照合）",
        "**摩擦の機構を名指ししているか**——複数年の購買義務／消耗品の専用性／"
        "データ移行・再教育の費用／設置基盤／工程への組込／解約率・更新率の実数。"
        "『highly competitive』『many competitors』は根拠にならない（競争の激しさは移行障壁を語らない）",
        "向きが逆でないか——**当社が外側にいる証明ではないか**（ONTO型『高い切替コストゆえ"
        "**我々が**競合から顧客を奪いにくい』）／当社が自社の仕入先を替える話ではないか",
        "同じ原本に反証が同居していないか（low barriers to entry ／ 顧客の内製 ／ 随時解約可 ／ 短い製品寿命）",
        "摩擦の射程——全社の記述か、一セグメントだけか",
    ],
}

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "out")
STALE_DAYS = 400          # 回転盤の「年次」(430日)より少し手前で鳴らす
# ⚠ ここを固定値にしてはいけない（2026-08-17に実際に踏んで是正した）。
#   旧: TODAY = datetime.date(2026, 8, 12) ＝ 5日間そのまま残り、二つのものを同時に壊していた——
#   (1) `generated` が動かないので**回転盤が永久に「停止疑い」**を出す（実際に出ていた）。
#       この盤の唯一の仕事は「止まった作業を見つけること」なのに、鳴りっぱなしは鳴らないのと同じ。
#   (2) もっと重い: **STALE_DAYS の一斉再読の周期が凍る**。age_days が伸びなくなるので
#       「400日を超えた検証は自動で作業リストへ戻る＝周期を人が覚えている必要が無い」という
#       機構そのものが黙って止まる。**止まったことを検出する機構も同時に壊れる**のが質の悪いところ。
#   backfill_machine_evidence.py の TODAY 固定（2週間放置）と同型。
#   再発は night/check_frozen_dates.py が機械で止める（CI）。
TODAY = datetime.date.today()


def packs():
    for p in sorted(glob.glob(os.path.join(OUT, "*_gate_pack.json"))):
        try:
            d = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        yield os.path.basename(p).split("_gate_pack")[0], d


def score_map():
    """Ω・投下可・判定圏を score_all から読む（判定を再実装しない）"""
    p = os.path.join(OUT, "score_all.json")
    if not os.path.exists(p):
        return {}
    d = json.load(open(p, encoding="utf-8"))
    rs = d["rows"] if isinstance(d, dict) and "rows" in d else d
    m = {}
    for r in rs:
        t = (r.get("t") or r.get("ticker") or r.get("nm") or "").split()[0]
        if t:
            # ⚠ quali(四関門を通ったか) を落とすと、買付圏の「次点」が黙って消える。
            #   2026-08-19 に実際に踏んだ——irr=70 の band が 13社→**6社**に痩せ、
            #   しかも痩せたことが画面に出ないので「次点は検証済み」と読めてしまう。
            m[t] = {"s": r.get("s"), "buy": bool(r.get("buy")),
                    "quali": bool(r.get("quali")), "moat": r.get("moat")}
    return m


def scope_of(m):
    """機構の射程を人が読める文字列に。**点と帯を書き分ける**——`_meta.mech` は
    点推定が原本から導けない社を scope_pct=None・scope_low/high で持つので、
    素の数字で並べると『測れていない』が『測れた』に見える（v9.9.119 で踏んだ型）。"""
    def num(v):
        try:
            return None if v in (None, "", "None") else float(v)
        except Exception:
            return None
    p, lo, hi = num(m.get("scope_pct")), num(m.get("scope_low")), num(m.get("scope_high"))
    if p is not None:
        return f"{p:.1f}%"
    if lo is not None and hi is not None:
        return f"{lo:.0f}-{hi:.0f}%"
    if hi is not None:
        return f"<={hi:.1f}%"
    if lo is not None:
        return f">={lo:.1f}%"
    return None


def days_since(iso):
    try:
        y, mo, dd = (int(x) for x in str(iso)[:10].split("-"))
        return (TODAY - datetime.date(y, mo, dd)).days
    except Exception:
        return None


def buy_band(S):
    """買付圏＝🟢投下可 ＋ 🔵次点（四関門を通っているが席に入っていない社）。
    **判定を再実装しない**——score_all の buy/quali をそのまま読む（v9.9.65）。"""
    return {t for t, v in S.items() if v.get("buy") or v.get("quali")}


def main():
    as_json = "--json" in sys.argv
    show_all = "--all" in sys.argv
    rung = "85"
    for i, a in enumerate(sys.argv):
        if a == "--rung" and i + 1 < len(sys.argv):
            rung = sys.argv[i + 1]
    S = score_map()
    BAND = buy_band(S) if rung == "70" else None
    if rung == "70" and not BAND:
        print("⚠ out/score_all.json が読めないので買付圏を絞れない。"
              "**全社を対象にしたと誤解させないよう中止する**（0件を『異常なし』と読ませない）")
        return

    rows = []
    for t, d in packs():
        dd = d.get("data") or d
        if str(dd.get("irr")) != rung:
            continue
        if BAND is not None and t not in BAND:
            continue
        m = d.get("_meta") or {}
        ver = m.get("irr85_verify") or []
        if isinstance(ver, dict):
            ver = [ver]
        duals = [v for v in ver if isinstance(v, dict) and v.get("kind") == "二重読み"]
        latest = max((v.get("date") or "" for v in duals), default=None) or None
        age = days_since(latest) if latest else None
        held = [v for v in duals if str(v.get("verdict") or "").startswith("据置(留保")]
        st = S.get(t, {})
        state = ("未検証" if not duals
                 else ("検証が古い" if (age is not None and age > STALE_DAYS) else "✓検証済"))
        rows.append({
            "ticker": t, "state": state, "last_dual": latest, "age_days": age,
            "n_dual": len(duals), "reserved": bool(held),
            "omega": st.get("s"), "moat": st.get("moat"), "buy": st.get("buy"),
            "in_band": (st.get("s") or 0) >= 72,
            "evidence_len": len((m.get("evidence") or {}).get("irr") or ""),
            "has_mech": bool(m.get("mech")),
            # ★機構の射程（2026-08-13追加・**表示だけ。順位にも合否にも使わない**）
            #   検問⑥「機構の射程——全社の記述か一セグメントのリスク要因の中か」を数字で見せる。
            #   ⚠ **線は引かない**——射程と本人の実現複利の順位相関は ρ=−0.143(n=6) で、
            #   最も狭い CW(12.3%) が2番目に良い。狭いことは欠陥の証拠ではなく、**読むときに確かめる点**。
            "scope": scope_of(m.get("mech") or {}),
            "verify": ver,
        })

    # 作業の優先順: 投下可 > 判定圏 > その他、同点は Ω降順
    rank = lambda r: (0 if r["buy"] else (1 if r["in_band"] else 2), -(r["omega"] or 0))
    todo = sorted([r for r in rows if r["state"] != "✓検証済"], key=rank)
    out = {
        "generated": TODAY.isoformat(),
        "rung": rung, "band": ("買付圏(投下可+次点)のみ" if BAND is not None else "全社"),
        "note": f"irr={rung} の二重読みの有無。**関門ではなく作業リスト**（未検証は欠陥ではなく工程の途中）",
        "why": "同じ111社で班により irr=85 の付与率が 5.4%→17.1%（3.2倍・p=0.017）と動くと実測された",
        "stale_days": STALE_DAYS,
        "n_irr85": len(rows), "n_todo": len(todo),
        "n_reserved": sum(1 for r in rows if r["reserved"]),
        "todo": todo,
        "rows": sorted(rows, key=rank),
    }
    json.dump(out, open(os.path.join(OUT, "irr85_dual.json" if rung == "85" else f"irr{rung}_dual.json"), "w"),
              ensure_ascii=False, indent=1)

    if as_json:
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return
    print(f"=== irr={rung} の二重読み（{out['generated']}）"
          + ("・買付圏(投下可+次点)のみ" if BAND is not None else "") + " ===")
    print(f"  対象 {out['n_irr85']}社 ／ **未検証・要再検証 {out['n_todo']}社** ／ 留保つき {out['n_reserved']}社")
    print(f"  ⚠ これは作業リストであって関門ではない（未検証は欠陥ではなく工程の途中）\n")
    print(f"  {'銘柄':<7}{'状態':<7}{'Ω':>6} {'堀':>5}  {'最終の二重読み':<12}{'根拠':>5}  {'射程':<12}印")
    for r in (out["rows"] if show_all else todo + [x for x in out["rows"] if x["state"] == "✓検証済"]):
        mark = ("🟢投下可" if r["buy"] else ("・判定圏" if r["in_band"] else ""))
        if r["reserved"]:
            mark += " ⚠留保つき"
        last = r["last_dual"] or "—"
        print(f"  {r['ticker']:<7}{r['state']:<7}{(r['omega'] or 0):>6.1f} {(r['moat'] or 0):>5.1f}  "
              f"{last:<12}{r['evidence_len']:>5}字  {(r['scope'] or '未取得'):<12}{mark}")
    if todo:
        ck = CHECKS.get(rung, CHECKS["85"])
        print(f"\n  【二重読みの検問（審査プロトコルと同じ{len(ck)}点）】")
        for i, q in enumerate(ck, 1):
            print(f"   {i}. {q}")
        print("  記録は `_meta.irr85_verify` へ（evidence の中に書かない＝逐語照合が汚れる）")


if __name__ == "__main__":
    main()
