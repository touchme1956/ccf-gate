#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/validate_packs.py — 審査パックの納品検査（2026-07-29新設・米国株/共通）

なぜ要るか:
  2026-07-29 の是正ラッシュ（NJR roic16.5→6.6・p2 90→40 / 9790 p2 95→40 / UI roic136.6→80.7 /
  dom 8社 / 市場値11社）は、原因が別々に見えて共通点は一つだった——
  **入力時に根拠を要求していなかった**こと。台帳の上では、原本から測った値と
  それらしく置いた値が**まったく同じ見た目**になる。だから誤りは静かに溜まり、
  人が根拠を1件ずつ読むまで見つからない。
  実測（night/audit_evidence.py・全316パック）: 根拠被覆率は全体33.0%、機械項目に至っては9.8%。

  日本株には validate_jp_packs.py（JP検問の実装側）が既にあった。これはその共通版で、
  **「値があるのに根拠が無い」を落とす**のが主目的。以後、根拠なき値は台帳に入らない。

思想（既存の道具と揃える）:
  ・null は健全。「測っていない」と正しく宣言された欄は再正規化で採点から外れる（v9.9.39）。
    落とすのは**値があるのに根拠が無い**場合だけ。ただし空欄の理由が _meta.nulls に無いものは警告。
  ・**根拠が無い＝誤り、ではない**（正しく測って書き忘れた場合もある）。だからこれは
    「納品を通すか」の検査であって、既存台帳への有罪判決ではない。既存分は作業リスト
    （audit_evidence.py）で扱う。
  ・dom の刻みの検査は night/audit_moat.py の grade_dom をそのまま呼ぶ＝二重正本を作らない。
  ・受理キーの正は index.html の applyFields＝validate_jp_packs.gate_keys をそのまま呼ぶ。

使い方:
  python3 night/validate_packs.py             out/ の全パック（日本株はJP規約も併せて検査）
  python3 night/validate_packs.py NVDA MSFT   指定銘柄のみ（納品時はこちら）
  python3 night/validate_packs.py --new       _meta.auditDate が今日のパックだけ（夜間納品の検問）
  python3 night/validate_packs.py --summary   社ごとの明細を出さず件数だけ
終了コード: 致命(FAIL)が1件でもあれば 1。
"""
import json
import os
import re
import sys
from datetime import date

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
sys.path.insert(0, os.path.join(BASE, "night"))

import audit_moat as AM            # noqa: E402  dom の刻みの検査（v9.9.41）はここが正本
import validate_jp_packs as VJ     # noqa: E402  受理キー・列挙値・JP規約はここが正本

# 判断項目＝審査官が原本を読んで置く。憶測禁止（絶対のルール2）なので根拠は必須。
JUDGE = ["dom", "moatW", "irr", "rep", "dur", "p1", "p2", "p3", "p4",
         "f1", "f2", "f3", "f4", "f5", "erosion", "disrupt", "moatdecay",
         "expiry", "geopol", "nrr"]
# 機械項目＝採取器が算出する。「機械の出力だから正しい」が誤りだったのでこちらも出典が要る。
MACHINE = ["roic", "roicg", "roicEx", "roict", "gm", "gmt", "cagr", "nde", "fcf", "ni",
           "accr", "gpa", "dilNet", "eps"]
# 市場項目＝外部APIで日々動く。根拠は「いつ・どこから」で足りるので警告どまり。
MARKET = ["per", "perF", "px", "shy", "evebit", "beta", "analysts", "instOwn"]

ALIAS = {"per": ["px_per", "per"], "px": ["px_per", "px"], "perF": ["px_per", "perF"],
         "roicg": ["roicg", "roic"], "roicEx": ["roicEx", "roic"], "roict": ["roict", "roic"],
         "gmt": ["gmt", "gm"], "nde": ["nde", "roic"]}


def has_val(v):
    if v is None:
        return False
    if isinstance(v, str):
        return v.strip().lower() not in ("", "na", "n/a", "-", "—", "null")
    return True


def ev_of(meta, k):
    ev = (meta or {}).get("evidence") or {}
    for key in ALIAS.get(k, [k]):
        t = ev.get(key)
        if isinstance(t, str) and t.strip():
            return t
        if isinstance(t, (dict, list)) and t:
            return json.dumps(t, ensure_ascii=False)
    return None


def check(path):
    fails, warns = [], []
    code = os.path.basename(path).split("_gate_pack")[0]
    try:
        d = json.load(open(path, encoding="utf-8"))
    except Exception as e:
        return [f"JSONが壊れている: {e}"], []
    meta = d.get("_meta") or {}
    prov = meta.get("provenance") or {}
    nulls = meta.get("nulls") or {}

    # --- 受理キー（正は門の applyFields） ---
    try:
        extra = (set(d.keys()) - {"_meta"}) - VJ.gate_keys()
        if extra:
            fails.append(f"門が受け取らないキー: {sorted(extra)}")
    except Exception as e:
        warns.append(f"キー照合を省略({e})")

    # --- 列挙値・点数域（正は validate_jp_packs のENUMS） ---
    for k, allowed in VJ.ENUMS.items():
        v = d.get(k)
        if v is not None and str(v) not in allowed:
            fails.append(f"{k}='{v}' は許容外 {sorted(allowed)}")
    g = d.get("geopol")
    if g is not None and (not isinstance(g, int) or not 0 <= g <= 3):
        fails.append(f"geopol={g} は0-3の整数")
    for k in VJ.SCORE100:
        v = d.get(k)
        if v is not None and (not isinstance(v, (int, float)) or not 0 <= v <= 100):
            fails.append(f"{k}={v} は0-100の数値")

    # --- ここが本丸: 値があるのに根拠が無い ---------------------------------
    nj = [k for k in JUDGE if has_val(d.get(k)) and not ev_of(meta, k)]
    if nj:
        fails.append(f"判断項目に根拠が無い: {' '.join(f'{k}={d[k]}' for k in nj)}"
                     f"（原本根拠が必須。憶測なら空欄にせよ＝絶対のルール2）")
    nm = [k for k in MACHINE
          if has_val(d.get(k)) and not ev_of(meta, k) and prov.get(k) != "machine"]
    if nm:
        fails.append(f"機械項目に根拠も出所も無い: {' '.join(f'{k}={d[k]}' for k in nm)}"
                     f"（式と実額を _meta.evidence に。"
                     f"night/backfill_machine_evidence.py で原本から刻める）")
    for k in MARKET:
        if has_val(d.get(k)) and not ev_of(meta, k) and not (meta.get("market") or {}).get("date"):
            warns.append(f"{k}={d[k]} の取得日・出所が無い（_meta.market か evidence.{k}）")

    # --- 空欄の理由 ---
    blank = [k for k in JUDGE if k in d and not has_val(d.get(k)) and not nulls.get(k)]
    if blank:
        warns.append(f"空欄だが _meta.nulls に理由が無い: {' '.join(blank)}"
                     f"（空欄自体は健全。理由が失われているのが問題）")

    # --- dom の刻み（正は audit_moat.grade_dom・v9.9.41） ---
    dom = d.get("dom")
    if has_val(dom):
        mark, why, _ = AM.grade_dom(dom, ev_of(meta, "dom") or "")
        if mark == "✗":
            fails.append(f"dom={dom} の根拠が刻みを支えていない: {why}")
        elif mark == "△":
            warns.append(f"dom={dom}: {why}")

    # --- _meta 必須 ---
    if not isinstance(d.get("_meta"), dict):
        fails.append("_meta が無い")
    else:
        for k in VJ.META_REQ:
            if k not in meta or meta[k] in (None, "", [], {}):
                (fails if k in ("auditDate", "model") else warns).append(f"_meta.{k} が空")

    # --- 日本株はJP規約（ROIC三点・TTM PER・gm粗利混入）も併せて ---
    if re.match(r"^\d{4,5}$", code):
        jf, jw = VJ.check(path)
        fails += [f"[JP] {x}" for x in jf]
        warns += [f"[JP] {x}" for x in jw]
    return fails, warns


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    summary = "--summary" in sys.argv
    new_only = "--new" in sys.argv

    paths = []
    for f in sorted(os.listdir("out")):
        if not f.endswith("_gate_pack.json"):
            continue
        t = f.split("_gate_pack")[0]
        if args and t.upper() not in {a.upper() for a in args}:
            continue
        p = os.path.join("out", f)
        if new_only:
            try:
                ad = str((json.load(open(p, encoding="utf-8")).get("_meta") or {}).get("auditDate") or "")
            except Exception:
                ad = ""
            if not ad.startswith(str(date.today())):
                continue
        paths.append(p)
    if not paths:
        print("対象パックが無い")
        return 0

    nf = nw = bad = 0
    for p in paths:
        fails, warns = check(p)
        code = os.path.basename(p).split("_gate_pack")[0]
        nf += len(fails)
        nw += len(warns)
        if fails:
            bad += 1
        if summary:
            continue
        if fails:
            print(f"✗ {code}")
            for x in fails:
                print(f"    FAIL {x}")
        elif warns:
            print(f"△ {code}")
        else:
            print(f"✓ {code}")
        for x in warns:
            print(f"    warn {x}")

    print(f"\n検査 {len(paths)}件 / 致命を持つパック {bad}件（FAIL {nf}件 / warn {nw}件）")
    if bad:
        print("致命ありは納品不可＝審査官へ差し戻す。"
              "既存台帳の一括是正は night/audit_evidence.py の作業リストで進めること")
    return 1 if nf else 0


if __name__ == "__main__":
    sys.exit(main())
