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

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "out")
STALE_DAYS = 400          # 回転盤の「年次」(430日)より少し手前で鳴らす
TODAY = datetime.date(2026, 8, 12)


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
            m[t] = {"s": r.get("s"), "buy": bool(r.get("buy")), "moat": r.get("moat")}
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


def main():
    as_json = "--json" in sys.argv
    show_all = "--all" in sys.argv
    S = score_map()

    rows = []
    for t, d in packs():
        dd = d.get("data") or d
        if dd.get("irr") != 85:
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
        "note": "irr=85 の二重読みの有無。**関門ではなく作業リスト**（未検証は欠陥ではなく工程の途中）",
        "why": "同じ111社で班により irr=85 の付与率が 5.4%→17.1%（3.2倍・p=0.017）と動くと実測された",
        "stale_days": STALE_DAYS,
        "n_irr85": len(rows), "n_todo": len(todo),
        "n_reserved": sum(1 for r in rows if r["reserved"]),
        "todo": todo,
        "rows": sorted(rows, key=rank),
    }
    json.dump(out, open(os.path.join(OUT, "irr85_dual.json"), "w"), ensure_ascii=False, indent=1)

    if as_json:
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return
    print(f"=== irr=85 の二重読み（{out['generated']}）===")
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
        print(f"\n  【二重読みの検問（審査プロトコルと同じ6点）】")
        for i, s in enumerate([
                "引用が原本に一字一句あるか（irr85_mech_diff が機械で照合）",
                "引用が『**顧客の側が**再認定・再試験の費用と時間を負う』を述べているか",
                "向きが逆でないか（自社が受ける認証／自社が仕入先を認定する話は当たらない）",
                "願望形でないか（we work closely with / strive to）",
                "同じ原本に反証が同居していないか（low barriers to entry / price erosion）",
                "機構の射程——全社の記述か、一セグメントのリスク要因の中か"], 1):
            print(f"   {i}. {s}")
        print("  記録は `_meta.irr85_verify` へ（evidence の中に書かない＝逐語照合が汚れる）")


if __name__ == "__main__":
    main()
