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

# パックの欄 → build_numbers の出力キー
MAP = {"roic": "roic", "roicg": "roicg", "roict": "roict", "gm": "gm", "gmt": "gmt",
       "cagr": "cagr5", "nde": "nde", "fcf": "fcf_abs", "ni": "ni_abs",
       "accr": "accr", "gpa": "gpa", "dilNet": "dilNet", "eps": "eps"}
TODAY = "2026-07-29"


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


def main():
    write = "--write" in sys.argv or "--sync" in sys.argv
    sync = "--sync" in sys.argv
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
    if not write:
        print("  ※--write で一致欄に根拠を刻む。--sync で食い違いも実測値へ直す")
    return 0


if __name__ == "__main__":
    sys.exit(main())
