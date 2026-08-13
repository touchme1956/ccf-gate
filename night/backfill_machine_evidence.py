#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/backfill_machine_evidence.py — 既存パックの機械項目に、式と実額の根拠を原本から刻む（2026-07-29新設）

なぜ要るか:
  実測（night/audit_evidence.py・全316パック）で、機械項目の根拠被覆率は **9.8%**
  （ni 0.3% / cagr 1.0% / gm 4.8% / roic 16.2%）だった。「機械の出力だから正しい」という
  前提が置かれていたためで、絶対のルール7で潰したバグ（欠測をゼロと読む）はまさに
  その前提が外れる場所にあった。根拠が無い値は、**誤っていても目で見えない**。

  この道具は hachimon_fetch.build_numbers をそのまま呼んで再計算し、
    ・保存値と一致  → _meta.evidence に式と実額を刻む（＝検算済みの印）
    ・保存値と食い違う → **書き換えない。人の作業リストへ出す**
  に振り分ける。値を勝手に直さないのは、審査官が原本で検算して置いた値のほうが
  機械より強いから（実測19社のROIC検算で、機械では出せない判断が何度も要った）。

採取器側でこの間に直した誤り（いずれも「確かめていない前提を機械が置く」＝ルール7と同型）:
  (1) **候補タグの先頭を無条件採用**していた。米国企業はASC606適用(2018年前後)で売上タグを
      Revenues → RevenueFromContractWithCustomerExcludingAssessedTax へ改称しており、旧タグが
      先頭にあるため**2017年で止まった系列**で成長率・利益率を測っていた（実測 BR: 2012→2017）。
      → 最新年まで届いている系列を主系列に選ぶ。重なる年で値が一致するタグだけを接ぐ。
  (2) **年数を系列の要素数で数えていた**。年が飛べば span > 要素数 なので cagr が過大になる。
      → 年ラベルの差で数える。
  (3) **dilNet が株式分割をまたいでいた**（実測 NVDA: 2,466百万株→24,304百万株を +114.4%/年の
      希薄化として計上。分割調整後の実態は −0.7%/年＝符号が逆）。→ 不連続の手前を捨てる。
  (4) **nde が有利子負債タグ不在を 0 と読んでいた**（借入のある会社が純現金に見える。roicは
      発散という派手な形で出たが、ndeは"健全に見える"静かな形で出るぶん質が悪い）。→ 空欄化。
  実測 NVDA cagr: 旧85.9% →(2)だけ直すと47.4% → (1)(2)両方で **66.9%**（2021→2026年）。
  cagr は門XのE[r]の g に直結するので、これは買付判断を直接動かす。

使い方:
  python3 night/backfill_machine_evidence.py            検算のみ（差と欠落を表示）
  python3 night/backfill_machine_evidence.py --write    一致した欄に根拠を刻む（値は変えない）
  python3 night/backfill_machine_evidence.py --sync     一致に加え、**食い違いも実測値へ直す**
                                                        （審査官の手入力がある欄は除く）
  python3 night/backfill_machine_evidence.py NVDA BR    指定銘柄のみ
日本株(コード始まり)はEDINET経路で作られているので対象外。
"""
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.chdir(BASE)

import hachimon_fetch as H       # noqa: E402  採取器をそのまま呼ぶ＝二重正本を作らない

# 採取器の版（内容ハッシュ）。**この器では計算しない**——採取器が自分で名乗るものをそのまま使う
# （版の求め方を二箇所に置くと、いつか二つの版が別々に育つ・v9.9.65）
FETCHER_REV = getattr(H, "FETCHER_REV", None)

# パックの欄 → build_numbers の出力キー
MAP = {"roic": "roic", "roicg": "roicg", "roict": "roict", "gm": "gm", "gmt": "gmt",
       "cagr": "cagr5", "nde": "nde", "fcf": "fcf_abs", "ni": "ni_abs",
       "accr": "accr", "gpa": "gpa", "dilNet": "dilNet", "eps": "eps"}
# ★2026-08-13 是正: **新設時の日付がハードコードされたまま2週間放置されていた**。
#   kenshi の是正記録も `--json` の generated も machine_check の日付も、全部 2026-07-29 と
#   名乗っていた＝**いつ検算したかが判らない**。刻印の日付が固定では取り残しの検出が成立しない。
#   （この台帳が繰り返す「数字を書き写した箇所は必ず陳腐化する」型の、日付版）
TODAY = __import__("time").strftime("%Y-%m-%d")


def same(a, b):
    """保存値と再計算値が実質同じか。列挙値は文字列一致、数値は2%か0.15の緩い方。"""
    if isinstance(a, str) or isinstance(b, str):
        return str(a) == str(b)
    try:
        x, y = float(a), float(b)
    except Exception:
        return False
    return abs(x - y) <= max(0.15, abs(y) * 0.02)


def note_kenshi(meta, line):
    k = meta.get("kenshi")
    if isinstance(k, list):
        k.append(line)
    elif isinstance(k, str) and k:
        meta["kenshi"] = k + "\n" + line
    else:
        meta["kenshi"] = [line]


def classify(old, new):
    """★2026-08-13 追加: 食い違いを**原因で分ける**。
       実測で、根拠なしの食い違い382件は**均質な作業リストではなかった**——
       ・PKE の fcf 11.0 → 0.0095 は **単位のずれ**（パックは百万$・採取器は十億$）＝同期すると桁が壊れる
       ・AVGO の ni 23.1 → 5.895 は **年ずれ**（採取器がFY2024・パックがFY2025）＝比べてはいけない二つ
       ・nde の12社は **本物の取り残し**（採取器の是正がパックに届いていない）
       一括 --sync はこの三つを区別しないので、**桁の誤りと年の誤りを注入する**。
       ⚠ これは原因の**当たり**であって断定ではない（3倍差は年ずれとIC縮退の両方でありうる）"""
    try:
        a, b = float(old), float(new)
    except (TypeError, ValueError):
        return "enum"
    if a == 0 or b == 0:
        return "zero"
    r = a / b
    if 300 < abs(r) < 3000 or 1 / 3000 < abs(r) < 1 / 300:
        return "unit"          # ★同期禁止
    if r < 0:
        return "sign"
    if 0.8 <= r <= 1.25:
        return "small"
    if 0.33 <= r <= 3:
        return "mid"
    return "large"             # ★年ずれ・IC縮退の疑い＝個別に検算


def stamps_report():
    """★取得を一切せずに『どのパックが今の採取器で検算されていないか』を答える（2026-08-13）。
       これが (b)『パックに採取器の版を刻む』の効き目そのもの——
       今までは全社再計算(約40分)しないと判らなかった。"""
    import collections as _c
    cur = FETCHER_REV
    sc = {}
    sp = os.path.join(BASE, "out", "score_all.json")
    if os.path.exists(sp):
        _d = json.load(open(sp, encoding="utf-8"))
        sc = {r["t"]: r for r in (_d if isinstance(_d, list) else _d.get("rows", []))}
    never, old, cur_n, jp = [], [], [], []
    for f in sorted(os.listdir(os.path.join(BASE, "out"))):
        if not f.endswith("_gate_pack.json"):
            continue
        t = f.split("_gate_pack")[0]
        d = json.load(open(os.path.join(BASE, "out", f), encoding="utf-8"))
        mc = (d.get("_meta") or {}).get("machine_check")
        # ★食い違いは**根拠の有無で分ける**。根拠がある欄は審査官が原本で置いた可能性があり
        #   機械より強い（backfill が値を書き換えない理由そのもの）＝作業リストから外す。
        _ev = ((d.get("_meta") or {}).get("evidence") or {})
        _df = (mc or {}).get("diff") or []
        row = {"t": t, "omega": (sc.get(t) or {}).get("s"), "buy": bool((sc.get(t) or {}).get("buy")),
               "date": (mc or {}).get("date"), "rev": (mc or {}).get("rev"),
               "diff": [f for f in _df if not _ev.get(f)],          # 取り残しの疑い＝作業リスト
               "diff_with_evidence": [f for f in _df if _ev.get(f)]}
        if re.match(r"^\d", t):
            jp.append(row)                     # 日本株は EDINET 経路＝この器の対象外
        elif not mc:
            never.append(row)
        elif mc.get("rev") != cur:
            old.append(row)
        else:
            cur_n.append(row)
    print(f"■ 採取器の版とパックの検算状態  現在の採取器 rev = {cur}")
    print(f"  ✓ 今の版で検算済み : {len(cur_n)}社")
    print(f"  ⚠ 古い版で検算     : {len(old)}社")
    print(f"  ⏳ 一度も検算していない: {len(never)}社")
    print(f"  — 日本株(EDINET経路・対象外): {len(jp)}社")
    stale = old + never
    q = [r for r in stale if (r["omega"] or 0) >= 72]
    b = [r for r in stale if r["buy"]]
    print(f"\n  取り残しのうち 判定圏(Ω72+) {len(q)}社 / 🟢投下可 {len(b)}社"
          + (": " + " ".join(r["t"] for r in b) if b else ""))
    if q:
        print("  " + " ".join(r["t"] for r in sorted(q, key=lambda r: -(r["omega"] or 0))[:20]))
    withdiff = [r for r in cur_n if r["diff"]]
    nev = sum(len(r["diff_with_evidence"]) for r in cur_n)
    print(f"\n  今の版で検算済みだが**根拠なしの食い違いが残っている**社: {len(withdiff)}"
          f"（欄の合計 {sum(len(r['diff']) for r in withdiff)}）"
          f"  ※別に『根拠あり＝審査官の可能性』が {nev}欄（作業リスト外）")
    for r in sorted(withdiff, key=lambda r: -(r["omega"] or 0))[:10]:
        m = "🟢" if r["buy"] else "  "
        print(f"     {m}{r['t']:<7} Ω{(r['omega'] or 0):>5.1f}  {' '.join(r['diff'])}")
    if "--json" in sys.argv:
        json.dump({"tool": "backfill_machine_evidence.py --stamps", "generated": TODAY,
                   "fetcher_rev": cur,
                   "counts": {"current": len(cur_n), "old_rev": len(old),
                              "never": len(never), "jp_out_of_scope": len(jp)},
                   "stale_q72": [r["t"] for r in q], "stale_buy": [r["t"] for r in b],
                   "current_with_diff": withdiff},
                  open(os.path.join(BASE, "out", "backfill_stamps.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print("\n→ out/backfill_stamps.json")
    return 0


def main():
    if "--stamps" in sys.argv:
        return stamps_report()
    write = "--write" in sys.argv or "--sync" in sys.argv
    sync = "--sync" in sys.argv
    as_json = "--json" in sys.argv
    rows_json = []
    only = {a.upper() for a in sys.argv[1:] if not a.startswith("--")}

    packs = []
    for f in sorted(os.listdir("out")):
        if not f.endswith("_gate_pack.json"):
            continue
        t = f.split("_gate_pack")[0]
        if re.match(r"^\d", t):
            continue
        if only and t.upper() not in only:
            continue
        packs.append(t)

    n_stamp = n_diff = n_gone = n_hand = 0
    err = []
    for t in packs:
        p = f"out/{t}_gate_pack.json"
        d = json.load(open(p, encoding="utf-8"))
        meta = d.setdefault("_meta", {})
        ev_m = meta.setdefault("evidence", {})
        pv = meta.setdefault("provenance", {})
        nulls = meta.get("nulls") or {}
        try:
            calc = H.build_numbers(H.facts_of(H.cik_of(t)))
        except (Exception, SystemExit) as e:
            err.append((t, str(e)[:70]))
            continue
        evid = calc.get("_evid") or {}

        # fcf / ni は門が**比でしか使わない**（conv=fcf/ni、reinvest=1−conv）。
        # パック側が百万$、機械が十億$のように単位規約が違っても比が同じなら実害は無い。
        # 絶対値で突き合わせると単位差だけで全社が作業リストに乗り、**鳴りすぎる警報は
        # 鳴らないのと同じ**になる。よって fcf/ni は比で判定する。
        ratio_ok = None
        if all(isinstance(d.get(k), (int, float)) for k in ("fcf", "ni")) and d.get("ni"):
            nf, nn_ = calc.get("fcf_abs"), calc.get("ni_abs")
            if isinstance(nf, (int, float)) and isinstance(nn_, (int, float)) and nn_:
                ratio_ok = same(d["fcf"] / d["ni"] * 100, nf / nn_ * 100)

        stamped, diffs, gone = [], [], []
        for fld, src in MAP.items():
            stored = d.get(fld)
            if stored is None:
                continue                      # 空欄は健全。機械で埋め直さない（審査官がnull化した欄もある）
            if fld in nulls:
                continue                      # 明示的に算出不能と宣言された欄は触らない
            new = calc.get(src)
            # 審査官が原本で検算して置いた欄は機械より強い。根拠があり provenance が machine でない＝手入力
            hand = bool(ev_m.get(fld)) and pv.get(fld) != "machine"
            if new is None:
                gone.append(fld)
                continue
            if fld in ("fcf", "ni") and ratio_ok is not None:
                if ratio_ok:
                    if evid.get(fld) and not hand:
                        ev_m[fld] = (evid[fld] + "（門はfcf/niを比でしか使わないため、"
                                                 "パック側の単位規約はそのまま。比は一致）")
                        pv[fld] = "machine"
                        stamped.append(fld)
                    continue
                diffs.append((fld, stored, new, hand))
                continue
            if same(stored, new):
                if evid.get(fld) and not hand:
                    ev_m[fld] = evid[fld]
                    pv[fld] = "machine"
                    stamped.append(fld)
                continue
            diffs.append((fld, stored, new, hand))

        if stamped:
            n_stamp += len(stamped)
        for fld, old, new, hand in diffs:
            if hand:
                n_hand += 1
            else:
                n_diff += 1
        n_gone += len(gone)

        for fld, old, new, hand in diffs:
            rows_json.append({"t": t, "field": fld, "old": old, "new": new,
                              "hand": bool(hand),
                              # ★根拠があれば「審査官が原本で置いた値」の可能性＝機械より強い
                              "has_evidence": bool((meta.get("evidence") or {}).get(fld)),
                              "class": classify(old, new)})

        if diffs or gone:
            head = f"{t:6s}"
            for fld, old, new, hand in diffs:
                print(f"{head} {fld:7s} {str(old):>9s} → {str(new):>9s}"
                      + ("   ※審査官の手入力あり＝直さない" if hand else ""))
                head = " " * 6
            if gone:
                print(f"{head} 機械で再現できない欄: {' '.join(gone)}（タグ不在・単位不明など）")

        if write:
            changed = bool(stamped)
            # ★2026-08-13: **いつ・どの版の採取器で検算したか**をパックに刻む。
            #   これが無かったので「採取器を直したがパックが追いつかない」取り残しを
            #   全社再計算(約40分)しないと知れなかった。刻めば `--stamps` が一瞬で答える。
            #   ⚠ `ok` は**値が採取器と一致した欄**、`diff` は**食い違ったまま残っている欄**＝
            #     この二つを分けて持つので、「検算した」と「問題なし」を取り違えない（ルール7の同族）。
            meta["machine_check"] = {
                "date": TODAY, "rev": FETCHER_REV,
                "ok": sorted(stamped),
                "diff": sorted(f for f, _o, _n, h in diffs if not h),
                "hand": sorted(f for f, _o, _n, h in diffs if h),
                "gone": sorted(gone),
                "note": ("night/backfill_machine_evidence.py が採取器で再計算して突き合わせた記録。"
                         "rev は hachimon_fetch.py の内容ハッシュ＝**採取器が変わればここも変わる**。"
                         "ok の欄だけが『この版で検算済み』。diff は人が原因（年ずれ・単位・IC縮退・"
                         "審査官の判断）を確かめる作業リスト"),
            }
            changed = True
            if sync:
                for fld, old, new, hand in diffs:
                    if hand:
                        continue
                    d[fld] = new
                    if evid.get(fld):
                        ev_m[fld] = evid[fld]
                    pv[fld] = "machine"
                    note_kenshi(meta, f"{TODAY} {fld}再計算: {old}→{new}"
                                      f"（採取器のタグ選択・年数・分割・負債欠測の是正を反映）")
                    changed = True
            if changed:
                json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print(f"\n対象 {len(packs)}社 / 根拠を刻んだ欄 {n_stamp}"
          f" / 食い違い {n_diff}（{'反映済み' if sync else '未反映——人の判断へ'}）"
          f" / 手入力ゆえ触らず {n_hand} / 機械で再現不能 {n_gone}")
    if err:
        print(f"  取得失敗 {len(err)}社: " + " ".join(t for t, _ in err))

    if as_json:
        import collections as _c
        sc = {}
        sp = os.path.join(BASE, "out", "score_all.json")
        if os.path.exists(sp):
            _d = json.load(open(sp, encoding="utf-8"))
            sc = {r["t"]: r for r in (_d if isinstance(_d, list) else _d.get("rows", []))}
        for r in rows_json:
            s_ = sc.get(r["t"]) or {}
            r["omega"], r["buy"] = s_.get("s"), bool(s_.get("buy"))
        todo = [r for r in rows_json if not r["hand"] and not r["has_evidence"]]
        out = {"tool": "night/backfill_machine_evidence.py --json",
               "generated": TODAY, "n_packs": len(packs), "n_diff": len(rows_json),
               "note": ("食い違いを『根拠の有無』と『原因』で仕分ける。**根拠がある欄は審査官が原本で"
                        "置いた可能性があり機械より強い**ので作業リストから外す。原因の class は "
                        "unit(単位ずれ＝同期禁止) / large(3倍超＝年ずれ・IC縮退の疑い) / sign / mid / "
                        "small / enum / zero。⚠**一括 --sync はこれを区別しない**"),
               "by_evidence": {"has_evidence": len(rows_json) - len(todo),
                               "no_evidence_TODO": len(todo)},
               "todo_by_class": dict(_c.Counter(r["class"] for r in todo)),
               "todo_q72": [r for r in todo if (r.get("omega") or 0) >= 72],
               "todo_buy": [r for r in todo if r["buy"]],
               "rows": rows_json}
        # ★部分実行で正本を潰さない（今日 v11_facts.py で同じ事故を実際に踏んだ。
        #   score_all.js の --jp/--us が正本を約40行で潰したのと同じ型）。構造で塞ぐ。
        out["partial"] = sorted(only) if only else None
        dest = os.path.join(BASE, "out",
                            "backfill_diff.partial.json" if only else "backfill_diff.json")
        json.dump(out, open(dest, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"\n→ {os.path.relpath(dest, BASE)}（根拠なし={len(todo)} / "
              f"判定圏={len(out['todo_q72'])} / 投下可={len(out['todo_buy'])}）"
              + ("  ⚠部分実行なので正本は書き換えていない" if only else ""))
    if not write:
        print("  ※--write で一致欄に根拠を刻む。--sync で食い違いも実測値へ直す")
    return 0


if __name__ == "__main__":
    sys.exit(main())
