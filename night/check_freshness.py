#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
「日付は動いたが、中身/入力は死んでいる」を機械で測る（2026-08-17新設）。

## なぜ要るか——回転盤は**日付しか見ていない**

`night/ops_status.py` は各作業の錨ファイルの日付を見て鮮度を採点する。
だが日付と中身は独立に壊れるので、壊れ方は**三つ**ある:

| 型 | 例（すべて実測） | 盤の見え方 |
|---|---|---|
| A **日付が凍る**（中身は動く） | audit_irr85_dual の `TODAY` 固定 | ⚠ 永久に停止疑い＝**偽陽性** |
| B **日付は動くが中身が凍る** | （この検査器が探す） | 🟢＝**偽陰性** |
| C **中身も動くが入力が死ぬ** | sp500_pe_monthly(2026-03停止) → hist_val_now(generated 08-09) | 🟢＝**偽陰性** |

A は `night/check_frozen_dates.py` で塞いだ（CIで落とす）。**この器は B と C を測る。**
B と C は**偽陰性**なのが質が悪い——盤が緑なので、誰も探しに行かない。

## 何を測るか（新しい定数をひとつも作らない）

① **本体の前進**: 錨の「日付欄を除いた本体」のハッシュが、git 履歴上いつ最後に動いたか。
   期限（盤と**同じ** due_days）を超えて本体が動いていなければ作業リストへ。
   ⚠ 日付欄を除くのが肝——除かないと「generated だけ変わって中身は同じ」を永久に検出できない。
② **データの末端**: 中に日付キーの時系列（{"1871-01": …} 型）があれば、その最大値と今日の差。
   **ファイルは新しいのに、中のデータがカバーする期間が伸びていない**を捕まえる。
③ **入力の鮮度**: 錨の生成器を静的に特定し、その生成器が読む out/*.json を入力として、
   ①②を伝播する。**入力の宣言を人が書かなくてよい**（コードから導出する）。
   ⚠ 入力が古い理由は**二つ**——(a)取りに行っていない＝我々の停止 (b)取りに行ったが
   配信元にそれ以上が無い＝**配信元の限界**。取得日と末端を比べれば機械で分けられる。
   混ぜると (b) で永久に鳴り続け、今朝直した鳴りっぱなしを自分で作ることになる。
   **だが (b) を消しはしない**——取得器が壊れて古い値を返す形も同じ見え方をするので、
   別の段に意味を書いて出す。

## この器が守っている作法

- **判定を持たない**——採点にも門にも一切触れない。出すのは作業リストだけ（終了コードは常に0）。
- **錨を推測しない**——`ops_status.py` の中で錨はタプルに埋まっていて外から取れないので、
  ソースから正規表現で拾ったうえで、**自分が読んだ日付が盤の報告と一致するか**で検算する。
  一致しなければ「錨を特定できなかった」と出す（推測で測ると、測った顔をした嘘になる）。
- **「測れない」と「測って問題なし」を分ける**——git に無い/JSONが壊れている/錨が特定できないは
  すべて `unmeasurable` に積み、健全の側に混ぜない（ルール7）。
- **二重実装を作らない**——期限も錨も `ops_status` のものを使う（import して build() を呼ぶ）。

実行: python3 night/check_freshness.py [--json] [--all]
      --all  … 作業リストに載らないものも全部出す
"""
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "night"))
import ops_status  # noqa: E402  ← 期限も錨も盤のものを使う（二重実装しない）

TODAY = datetime.date.today()

# **本体が動かないのが正常な器**（本体検査の対象外）。**理由を必ず書く**——
#   ここへ足すことは「この器の本体が凍っても鳴らさない」と宣言することなので、
#   「本体が動く＝異常が起きた」と言い切れる器だけを入れる。日付の側は盤が別に見ている。
BODY_STABLE = {
    # 値は {"why": 理由, "gen": 生成器}。gen は generator_of() が引けない錨だけ書く
    #   ——除外したせいで「誰が作った錨か」の情報まで消える（実測で freshness が空になった）。
    "freshness": {"why": "自分の出力なので本体検査は行わない（所見が安定＝本体が動かないのが正常）",
                  "gen": ["night/check_freshness.py"]},
    # 2026-08-19追加: 実測で「本体が5日動いていない（期限4日）」と鳴っていたが、**これは誤検出**。
    #   この器は irr=85 の機構文を**毎回 SEC から取り直して**照合する（irr85_extract.get() が
    #   urlopen する＝キャッシュを読んでいるのではない）。原本(10-K/20-F)は年1回しか変わらないので
    #   **中身が動かない＝原本も取得も安定**で二重に健全。逆に本体が動く＝機構文が消えた／取得に失敗した
    #   ＝赤信号のほうで、それは gone/no_quote に出る（実測 gone:[]・15社とも一字同文）。
    "irr85mech": {"why": "原本を毎回SECから取り直して照合する器。原本は年1回しか変わらないので本体が動かないのが正常"
                         "（動く＝機構文が消えた/取得失敗＝赤信号のほう）。止まったことは盤の日付が見る"},
}

# 「これは日付欄であって中身ではない」——本体のハッシュから外す鍵。
#   ここを外さないと、generated だけ動いて中身が凍っている状態を永久に検出できない。
DATE_KEYS = {"generated", "generated_at", "asof", "as_of", "date", "updated", "updated_at",
             "fetched", "fetched_at", "timestamp", "ts", "run_at", "created"}
# 時系列の鍵の形（"1871-01" / "2026-03-31"）
DATE_KEY_RE = re.compile(r"^\d{4}-\d{2}(-\d{2})?$")
# 履歴を遡る上限。これを超えても本体が動いていなければ「≥N版」と正直に書く
WALK = 25


def glob_yaml():
    import glob as _g
    return _g.glob(os.path.join(BASE, ".github", "workflows", "*.yml"))


def sh(*args):
    try:
        return subprocess.run(args, cwd=BASE, capture_output=True, text=True, timeout=120).stdout
    except Exception:
        return ""


def strip_dates(o):
    """日付欄を落とした写しを返す（再帰）。中身が動いたかだけを見るため。"""
    if isinstance(o, dict):
        return {k: strip_dates(v) for k, v in o.items() if k not in DATE_KEYS}
    if isinstance(o, list):
        return [strip_dates(v) for v in o]
    return o


def body_hash(text):
    """日付欄を除いた本体のハッシュ。JSONとして読めなければ None（0を返さない＝ルール7）。"""
    try:
        d = json.loads(text)
    except Exception:
        return None
    return hashlib.md5(
        json.dumps(strip_dates(d), sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]


def data_end(path):
    """中の時系列の末端。日付キーの辞書が無ければ None（『時系列なし』であって異常ではない）。"""
    try:
        d = json.load(open(os.path.join(BASE, path), encoding="utf-8"))
    except Exception:
        return None
    best = None

    def walk(o, depth=0):
        nonlocal best
        if depth > 4:
            return
        if isinstance(o, dict):
            ks = [k for k in o if isinstance(k, str) and DATE_KEY_RE.match(k)]
            # 「日付キーの辞書」と言えるのは大半が日付キーのとき（数個の混入では判定しない）
            if ks and len(ks) >= max(3, len(o) * 0.8):
                m = max(ks)
                if best is None or m > best:
                    best = m
            for v in o.values():
                walk(v, depth + 1)
        elif isinstance(o, list):
            for v in o[:200]:
                walk(v, depth + 1)
    walk(d)
    return best


def body_last_change(path):
    """本体（日付欄を除く）が最後に動いたコミット日。戻り: (日付 or None, 遡った版数, 理由)

    ⚠ 初版はここで**この repo がいちばん警戒する取り違え**をやった——履歴を遡り切っても
      変化が見つからないとき `None` を返し、呼び出し側が「フラグなし＝健全」と読んでいた。
      ＝**『測っていない』が『測って問題なし』に化けていた**（それを防ぐために作った器の中で）。
      正しくは「遡り切って変化が無い＝**最古の版から今の本体のまま**」なので、
      その最古の版の日付が答え（測れている）。日付が本当に出せないのは
      『gitに履歴が無い』『その版のJSONが読めない』の二つだけで、そこは None を返して
      呼び出し側が unmeasurable に積む。
    ⚠ WALK版で打ち切ったときの日付は**下限**（それ以前は見ていない）。凍結の長さを
      過小に言う側なので、判定は保守側へ倒れる。"""
    revs = [r for r in sh("git", "log", f"-n{WALK}", "--format=%H %ad", "--date=short",
                          "--", path).splitlines() if r.strip()]
    if not revs:
        return None, 0, "gitに履歴が無い"
    cur = None
    newest = None
    for i, line in enumerate(revs):
        sha, d = line.split(None, 1)
        h = body_hash(sh("git", "show", f"{sha}:{path}"))
        if h is None:
            return None, i, "その版のJSONが読めない"
        if cur is None:
            cur, newest = h, d.strip()
            continue
        if h != cur:
            # ひとつ前（＝今の本体が最初に現れた版）の日付が「最後に動いた日」
            return newest, i, ""
        newest = d.strip()
    if len(revs) >= WALK:
        return newest, len(revs), f"≥{WALK}版 遡ったが変化なし（それ以前は見ていない＝日数は下限）"
    return newest, len(revs), f"作成({newest})から本体は一度も動いていない（全{len(revs)}版）"


def generator_of(anchor):
    """錨を書いているツール。静的抽出＝完全ではないが『測っていない』より遥かに良い。

    ⚠ **ソースだけを見ると取り逃す。配線はワークフロー側にあることがある**——実測で
      `hist_valuation.py` は出力パスを引数で受けるので、ソースに `hist_val_now.json` の
      文字列が一度も出てこない。`.github/workflows/ops.yml:96` の
      `--out out/hist_val_now.json` が唯一の配線。ここを見ないと入力の追跡が黙って切れる。
    ⚠ 自分自身は必ず除く（docstring に錨の名前を書くので、素朴に探すと自分を生成器と誤認する）。
    """
    base = os.path.basename(anchor)
    hits = []
    # ① ワークフローの run: 行——同じ行/ステップで錨を名指ししているツールが生成器
    for wf in sorted(glob_yaml()):
        try:
            t = open(wf, encoding="utf-8", errors="ignore").read()
        except Exception:
            continue
        for line in t.splitlines():
            # ⚠ 「同じ行に錨の名前がある」だけでは生成器ではない——実測で ops.yml:96 は
            #   `--tickers kanshi_list.json --out out/hist_val_now.json` と**入力と出力を同じ行に**
            #   書くので、素朴に見ると hist_valuation.py が kanshi_list.json の生成器に化けた
            #   （そして sp500 の遅れが監視リスト生成の欠陥として誤って報告された）。
            #   **`--out` / `-o` / リダイレクトの直後**にあるときだけ出力と読む。
            if not re.search(r'(?:--out|--output|-o|>)\s+["\']?[\w./-]*' + re.escape(base), line):
                continue
            for m in re.findall(r'(?:python3?|node) +((?:night/)?[\w./-]+\.(?:py|js))', line):
                if m not in hits:
                    hits.append(m)
    # ② ツールのソース
    for d in ("night", "."):
        p0 = os.path.join(BASE, d)
        if not os.path.isdir(p0):
            continue
        for fn in sorted(os.listdir(p0)):
            if not fn.endswith((".py", ".js")):
                continue
            if os.path.abspath(os.path.join(p0, fn)) == os.path.abspath(__file__):
                continue
            p = os.path.join(p0, fn)
            try:
                t = open(p, encoding="utf-8", errors="ignore").read()
            except Exception:
                continue
            if base not in t:
                continue
            # ⚠ 窓を80字にしていたら **hist_valuation.py を取り逃した**——
            #   `os.path.join(OUT, "hist_val_now.json")` で組んで別行で open(p,"w") する形が普通で、
            #   basename と "w" は隣り合わない。400字（＝数行ぶん）へ広げた。
            #   広げると読み手を拾う偽陽性が出うるが、**取り逃すより偽陽性のほうが安全**
            #   （候補は全部出すので人が読める。取り逃すと入力の追跡が黙って切れる）。
            if re.search(r'writeFileSync\([^)]{0,400}?' + re.escape(base), t, re.S) or \
               re.search(re.escape(base) + r'.{0,400}?["\']w["\']', t, re.S) or \
               re.search(r'["\']w["\'].{0,400}?' + re.escape(base), t, re.S):
                hits.append(os.path.join(d, fn).replace("./", ""))
    return hits


def inputs_of(tool, anchor):
    """その生成器が読む out/*.json（自分の出力は除く）。"""
    try:
        t = open(os.path.join(BASE, tool), encoding="utf-8", errors="ignore").read()
    except Exception:
        return []
    outs = set(re.findall(r'["\'](out/[\w./-]+\.json)["\']', t))
    # ⚠ `out/` 付きだけを探すと**この repo で最も普通の書き方を取り逃す**——実測で
    #   hist_valuation.py:757 は `os.path.join(BASE, "out", "sp500_pe_monthly.json")` と組むので、
    #   文字列は裸の basename。これを拾わないと**入力の追跡が一番大事なところで切れる**
    #   （まさに sp500_pe_monthly＝5ヶ月止まっている分母がそれだった）。
    for b in re.findall(r'["\']([\w.-]+\.json)["\']', t):
        if "/" in b:
            continue
        if os.path.exists(os.path.join(BASE, "out", b)):
            outs.add("out/" + b)
    outs.discard(anchor)
    # パック（*_gate_pack）は glob で読む群なので個別の鮮度の話にしない
    return sorted(o for o in outs if not o.endswith("_gate_pack.json") and ".partial." not in o)


def anchors_from_source():
    """ops_status.py のソースから (job_id, 錨のパス) を拾う。**推測なので後で検算する**。"""
    src = open(os.path.join(BASE, "night", "ops_status.py"), encoding="utf-8").read()
    body = src[src.find("def build():"):]
    out = {}
    for m in re.finditer(r'\(\s*"([a-z0-9_]+)",\s*"[^"]+",\s*"[^"]+",\s*(\d+),\s*\n?\s*'
                         r'\(?\s*(?:json_field|git_date|file_date)\(\s*"([^"]+)"', body):
        out.setdefault(m.group(1), m.group(3))
    return out


def unmapped_reason(job_id):
    """錨が拾えなかった理由を、推測でなくソースの形から言う。
       ⚠『特定できなかった』で終わらせると、次に読む人が器のバグだと思って同じ所を掘る。"""
    src = open(os.path.join(BASE, "night", "ops_status.py"), encoding="utf-8").read()
    m = re.search(r'\(\s*"' + re.escape(job_id) + r'",[^\n]*\n\s*([^\n]+)', src)
    expr = (m.group(1).strip().rstrip(",") if m else "")
    if re.match(r'\w+\(\)', expr):
        return f"錨が単一ファイルでなくヘルパ経由（{expr}）＝この器では追えない"
    if "glob" in expr or "max(" in expr:
        return f"錨が複数ファイルの集約（{expr[:50]}…）＝この器では追えない"
    return f"錨をソースから特定できなかった（式: {expr[:60]}）"


def main():
    show_all = "--all" in sys.argv
    board = ops_status.build()
    amap = anchors_from_source()

    rows, unmeasurable = [], []
    for job in board["items"]:
        jid, name, due = job["id"], job["name"], job["due_days"]
        anchor = amap.get(jid)
        if not anchor:
            unmeasurable.append({"id": jid, "name": name, "why": unmapped_reason(jid)})
            continue
        if not os.path.exists(os.path.join(BASE, anchor)):
            unmeasurable.append({"id": jid, "name": name, "anchor": anchor, "why": "ファイルが無い"})
            continue
        # ★検算: 自分が錨から読んだ日付と、盤が報告した日付が一致するか。
        #   一致しなければ錨の特定が誤り＝測った顔をした嘘になるので測らない。
        mine = ops_status.json_field(anchor, "generated", "asof", "date", "updated") \
            or ops_status.git_date(anchor)
        if job["last"] and mine and job["last"] != mine:
            unmeasurable.append({"id": jid, "name": name, "anchor": anchor,
                                 "why": f"錨の検算が合わない（盤 {job['last']} / この器 {mine}）"})
            continue

        # ⚠ **本体が動かないのが正常な器**は本体検査から外す。素朴に測ると
        #   健全なものを凍結と誤認して**永久に鳴る**（鳴りすぎる警報は鳴らないのと同じ）。
        #   ⚠ 外してよいのは「**本体が動く＝異常が起きた**」と言い切れる器だけ。
        #     日付の側は盤が毎営業日見ているので、止まったことは別に検出できる。
        if jid in BODY_STABLE:
            rows.append({"id": jid, "name": name, "anchor": anchor, "due_days": due,
                         "board_last": job["last"], "board_state": job["state"],
                         "body_last": None, "body_days": None,
                         "body_note": BODY_STABLE[jid]["why"],
                         "data_end": None, "data_days": None,
                         "generator": BODY_STABLE[jid].get("gen") or generator_of(anchor),
                         "inputs": [], "flags": [], "src_lag": []})
            continue

        blast, walked, why = body_last_change(anchor)
        bdays = (TODAY - datetime.date.fromisoformat(blast)).days if blast else None
        dend = data_end(anchor)
        if dend:
            de = dend if len(dend) == 10 else dend + "-01"
            ddays = (TODAY - datetime.date.fromisoformat(de)).days
        else:
            ddays = None

        gens = generator_of(anchor)
        ins = []
        for g in gens[:2]:
            for i in inputs_of(g, anchor):
                if i in [x["path"] for x in ins]:
                    continue
                iend = data_end(i)
                ib, _, _ = body_last_change(i)
                ins.append({"path": i, "data_end": iend,
                            "data_days": (TODAY - datetime.date.fromisoformat(
                                iend if len(iend) == 10 else iend + "-01")).days if iend else None,
                            "body_last": ib})

        # 判定は**盤と同じ期限**だけを使う（新しい定数をひとつも作らない）
        flags = []
        if bdays is not None and bdays > due:
            flags.append(f"本体が{bdays}日動いていない（期限{due}日）")
        if blast is None and walked >= WALK:
            flags.append(f"本体が直近{walked}版で一度も動いていない")
        if ddays is not None and ddays > due:
            flags.append(f"中のデータが{dend}止まり（{ddays}日前・期限{due}日）")
        # ⚠ 入力のデータが古い理由は**二つある**ので分ける（2026-08-17 に実際に走らせて確定した）。
        #   (a)取りに行っていない＝我々の停止  (b)取りに行ったが配信元にそれ以上が無い＝**配信元の限界**
        #   実測: sp500_pe_monthly は今日 fetch に成功して generated が今日になったのに
        #   series の末端は 2026-03 のまま＝(b)。これを「止まっている」と鳴らし続けると
        #   **今朝直した鳴りっぱなし（audit_irr85_dual）を自分で作る**ことになる。
        #   ⚠ ただし**隠さない**——別の段に、意味を書いて出す（取得器が壊れて古い値を返す形も
        #   同じ見え方をしうるので、消してしまうと本物を見逃す）。
        src_lag = []
        for i in ins:
            if i["data_days"] is None or i["data_days"] <= due:
                continue
            fetched = ops_status.json_field(i["path"], "generated", "asof", "date", "updated")
            fdays = (TODAY - datetime.date.fromisoformat(fetched)).days if fetched else None
            if fdays is not None and fdays <= due:
                src_lag.append(f"入力 {os.path.basename(i['path'])}: 取得は{fetched}に成功したが"
                               f"データは{i['data_end']}止まり（{i['data_days']}日前）"
                               f"＝**配信元の限界**であって我々の停止ではない")
            else:
                flags.append(f"入力 {os.path.basename(i['path'])} のデータが"
                             f"{i['data_end']}止まり（{i['data_days']}日前"
                             + (f"・最後に取得したのは{fetched}" if fetched else "・取得日が不明") + "）")

        rows.append({"id": jid, "name": name, "anchor": anchor, "due_days": due,
                     "board_last": job["last"], "board_state": job["state"],
                     "body_last": blast, "body_days": bdays, "body_note": why,
                     "data_end": dend, "data_days": ddays,
                     "generator": gens, "inputs": ins, "flags": flags, "src_lag": src_lag})

    hits = [r for r in rows if r["flags"]]
    lags = [r for r in rows if r.get("src_lag")]
    out = {"generated": TODAY.isoformat(),
           "note": "回転盤は日付しか見ない。この器は『日付は動いたが中身/入力が死んでいる』を測る。"
                   "判定は持たない＝採点にも門にも触れない作業リスト",
           "n_checked": len(rows), "n_flagged": len(hits), "n_src_lag": len(lags),
           "n_unmeasurable": len(unmeasurable),
           "rows": rows, "unmeasurable": unmeasurable}
    if "--json" in sys.argv:
        with open(os.path.join(BASE, "out", "freshness.json"), "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)

    print("=" * 74)
    print("中身と入力の鮮度（回転盤は日付しか見ていない）")
    print("=" * 74)
    print(f"錨 {len(rows)}件を検査 ／ 作業リスト {len(hits)}件 ／ "
          f"配信元の限界 {len(lags)}件 ／ **測れない {len(unmeasurable)}件**")
    if unmeasurable:
        print("\n■ 測れない（健全と読まないこと）")
        for u in unmeasurable:
            print(f"   {u['name'][:24]:<26}{u.get('anchor','')[:30]:<32}{u['why']}")
    if hits:
        print("\n■ 作業リスト")
        for r in sorted(hits, key=lambda x: -(x["body_days"] or x["data_days"] or 0)):
            print(f"\n   {r['name']}（盤: {r['board_state']} 最終 {r['board_last']}）")
            for f in r["flags"]:
                print(f"      ★ {f}")
    if lags:
        print("\n■ 配信元の限界（我々の停止ではない・だが隠さない）")
        for r in lags:
            for f in r["src_lag"]:
                print(f"   {r['name']}")
                print(f"      · {f}")
    if show_all:
        print("\n■ 全件")
        for r in rows:
            b = f"本体{r['body_days']}日前" if r["body_days"] is not None else f"本体{r['body_note']}"
            d = f" / データ末端 {r['data_end']}" if r["data_end"] else ""
            print(f"   {r['name'][:24]:<26}{b}{d}")
    if not hits and not unmeasurable:
        print("\n✓ 中身も入力も期限内に前進している")
    return 0


if __name__ == "__main__":
    sys.exit(main())
