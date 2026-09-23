#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
日付を固定したまま忘れられているツールを見つける（2026-08-17新設）。

## なぜ要るか——**同じ事故を二度踏んだから**

1回目 `night/backfill_machine_evidence.py`: `TODAY = "2026-07-29"` が**2週間**そのまま残り、
       kenshi の是正記録も machine_check の日付も全部その日を名乗った
       ＝「いつ検算したか」が判らなくなり、取り残しの検出がそもそも成立しなくなっていた。
2回目 `night/audit_irr85_dual.py`: `TODAY = datetime.date(2026, 8, 12)` が5日間残り、
       **二つのものを同時に壊していた**——
       (1) `generated` が動かないので**回転盤が永久に「停止疑い」**を出す。
           盤の唯一の仕事は「止まった作業を見つけること」なのに、鳴りっぱなしは鳴らないのと同じ。
       (2) もっと重い: **STALE_DAYS(400日) の一斉再読の周期が凍る**。age_days が伸びないので
           「400日を超えた検証は自動で作業リストへ戻る＝周期を人が覚えている必要が無い」という
           機構そのものが黙って止まる。

**この壊れ方は例外を出さない**（ファイルは毎回きちんと書かれ、中身も正しい顔をしている）。
コードを読んでも気づかない——**日付が動いていないことを機械で数えるしかない**。
CLAUDE.md の掟「記録するだけでは再演は防げない。検査が要る」の実装。

## 何を見るか / 何を見ないか

**見る**: `TODAY / NOW / ASOF / TODAY_STR` 等、**実行時の今日**を意味する名前に固定日を代入している行。
**見ない**（設計どおり固定されるもの）:
  - `retro_* / hist_* / *_prereg*` ＝**歴史検証**。asof は「当時読めた数字だけを使う」ための錨で、
    動いたら look-ahead が入る。**固定されていることが正しさ**なので、ここを鳴らすと逆走になる。
  - `CUTOFF / EPOCH / SINCE / _ANCHOR` 等、名前が「基準時点」だと明示しているもの。
  - コメント・文字列の中の日付（経緯の記述は資産）。

判定は持たない検査器＝**採点にも門にも一切触れない**。終了コードだけで CI に伝える。

実行: python3 night/check_frozen_dates.py [--json]
"""
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 実行時の「今日」を意味する名前。ここに固定日が入ったら事故
LIVE_NAMES = re.compile(r"^\s*(TODAY|_TODAY|NOW|_NOW|ASOF|_ASOF|TODAY_STR|GENERATED|RUN_DATE)\s*=\s*(.+?)\s*(?:#.*)?$")
# 固定日の書き方（datetime.date(2026,8,12) / date(2026,8,12) / "2026-08-12"）
FROZEN = re.compile(r"""(datetime\.)?date\(\s*20\d\d\s*,|["']20\d\d-\d\d-\d\d["']""")

# 設計どおり固定される群（歴史検証の錨）。**ファイル名で除外するのは、
# その群では「固定されていること」が正しさそのものだから**
#   ⚠ 先頭の `_` を許すこと（実測で `_histval_crosscheck.py` を誤検出した。あれは歴史検証の
#     asof のフォールバックで、動いたら look-ahead が入る＝固定が正しい側）
EXEMPT_FILE = re.compile(r"(^|/)_?(retro_?|hist|v10_|v11_|v12_|omega_retro)|_prereg")

# 2026-09-23 追加（todo frozen_date_dict_literal）: **辞書リテラルの固定日**も見る。
#   上の LIVE_NAMES は左辺の変数名しか見ないので、`json.dump({"generated": "2026-08-09", …})` は一度も鳴らなかった。
#   実測40件——大半は shadow_*/opmtrend_*/irr85_* の**一度きりの研究の記録**で、固定が正しい（その日に測ったという記録）。
#   ⚠ だから一律には落とさない（鳴りすぎる警報は鳴らないのと同じ）。**線は「その道具が繰り返し回されるか」**に引く:
#     (a) .github/workflows/*.yml が呼ぶ道具（ops.yml が毎月回す shadow_alloc_buckets 等＝回すたびに嘘になる）
#     (b) 人が周期で回す道具（LIVE_MANUAL。CLAUDE.md のコマンド節や todo が「毎回出す」と書くもの）
#   それ以外は「記録として凍結」として名前だけ出す（失敗にしない）。
DICT_FROZEN = re.compile(r"""["'](asof|generated)["']\s*:\s*["']20\d\d-\d\d-\d\d["']""")
LIVE_MANUAL = {
    "night/rerank_gate0_jp.py",        # 年1回の日本株門0の並べ直し
    "night/shadow_x_gcap_breaker.py",  # perF/gcap の被覆率と binding を「毎回出す」（todo perf_fill_band）
    "night/audit_gate0_fye.py",        # 門0の決算日の錨の全社スキャン（年次発掘のたび）
}


def live_files():
    """ワークフローが呼ぶ道具の相対パス（night/xxx.py と ルート直下の xxx.py）。"""
    out = set(LIVE_MANUAL)
    wf = os.path.join(BASE, ".github", "workflows")
    if os.path.isdir(wf):
        for fn in os.listdir(wf):
            if fn.endswith((".yml", ".yaml")):
                txt = open(os.path.join(wf, fn), encoding="utf-8").read()
                out |= {m.group(0) for m in re.finditer(r"night/[\w.-]+\.py", txt)}
                out |= {m.group(1) for m in re.finditer(r"python3?\s+([\w.-]+\.py)", txt)}
    return out


def scan():
    bad, exempt, frozen_records = [], [], []
    LIVE = live_files()
    roots = [os.path.join(BASE, "night"), BASE]
    seen = set()
    for root in roots:
        if not os.path.isdir(root):
            continue
        for fn in sorted(os.listdir(root)):
            if not fn.endswith(".py"):
                continue
            p = os.path.join(root, fn)
            if p in seen or os.path.abspath(p) == os.path.abspath(__file__):
                continue
            seen.add(p)
            rel = os.path.relpath(p, BASE)
            try:
                lines = open(p, encoding="utf-8").read().splitlines()
            except Exception:
                continue
            for i, ln in enumerate(lines, 1):
                d = DICT_FROZEN.search(ln)
                if d and not ln.lstrip().startswith("#"):
                    rec = {"file": rel, "line": i, "name": d.group(1) + "(辞書)", "code": ln.strip()[:160]}
                    if EXEMPT_FILE.search(rel):
                        exempt.append(rec)
                    elif rel in LIVE:
                        bad.append(rec)
                    else:
                        frozen_records.append(rec)
                m = LIVE_NAMES.match(ln)
                if not m:
                    continue
                name, rhs = m.group(1), m.group(2)
                if not FROZEN.search(rhs):
                    continue
                rec = {"file": rel, "line": i, "name": name, "code": ln.strip()}
                (exempt if EXEMPT_FILE.search(rel) else bad).append(rec)
    return bad, exempt, frozen_records


def main():
    bad, exempt, frozen_records = scan()
    out = {
        "generated": __import__("datetime").date.today().isoformat(),
        "note": "実行時の今日を意味する名前に固定日が入っているツール。歴史検証(retro_/hist_/*_prereg)は設計どおり固定＝除外",
        "frozen": bad,
        "exempt": exempt,
        "frozen_records": frozen_records,
    }
    if "--json" in sys.argv:
        with open(os.path.join(BASE, "out", "frozen_dates.json"), "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)

    print("=" * 68)
    print("日付が凍っているツールの検査")
    print("=" * 68)
    if bad:
        print(f"⛔ {len(bad)}件——実行時の今日を意味する名前に固定日が入っている")
        for r in bad:
            print(f"   {r['file']}:{r['line']}  {r['code']}")
        print()
        print("   直し方: datetime.date.today() へ。固定したい理由があるなら名前を")
        print("   CUTOFF/ANCHOR 等『基準時点』と判る語にし、なぜ固定かをコメントに書くこと。")
    else:
        print("✓ 固定日は無い（実行時の今日を意味する名前について）")
    if frozen_records:
        print(f"\n（記録として凍結＝繰り返し回されない研究の出力 {len(frozen_records)}件・失敗にしない。"
              "繰り返し回すようにしたら LIVE_MANUAL へ足すか ワークフローから呼ぶこと）")
    if exempt:
        print(f"\n（設計どおり固定＝除外 {len(exempt)}件: " +
              ", ".join(sorted({r['file'] for r in exempt})) + "）")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
