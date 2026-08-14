#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/gate_history.py — 門が自分の過去の判定を持つ（2026-08-14新設・ユーザー指示「1.2.3すべてやりたい」の②）

■ なぜ要るのか
  `out/score_all.json` は毎日**上書き**される。git に版は残るが**読む道具が一つも無かった**。
  20年の複利を測る門が、自分の履歴を持っていないのは端的におかしい。

  歴史検証で最も硬かった発見は数字ではなく**ラベルの安定性**だった——CW は 2013・2015・2018 の
  3ビンテージすべて、**別の読み手・別の年の原本**で irr=85 と読まれた。
  **安定していること自体が信号**なのに、今日の門はそれを毎日捨てている。

■ ★判定には一切使わない（今日の時点では）
  これは**記録を貯めるだけ**の道具。効くかどうかは半年〜1年後に事前登録して一度だけ測る。
  「先に測る道具を作り、記録を貯め、答えが出てから規則にする」——この台帳の作法そのもの。

■ 形（20年もたせるための設計）
  全社×毎日を丸ごと書くと 369社×20年で100MB級になる。だから**変化した時だけ**書く:
    ・`day` 行 … その日 走ったこと自体の記録（**変化ゼロの日と、走らなかった日を区別する**）
    ・`chg` 行 … ある銘柄のある欄が変わった、という事象だけ
  ⚠ この区別は絶対に要る——「測っていない」と「測って変化なし」を取り違えないため（ルール7の同族）。

■ ★門そのものが変わった日を見分けられるようにする
  各日の行に `gate` = **index.html の内容ハッシュ**を入れる。
  v9.9.141 の TOPCAP のように門の側が変わると全社が一斉に動くので、
  これが無いと「会社が変わった」と「門が変わった」を取り違える。
  （手で上げる版番号ではなく内容ハッシュにするのは hachimon_fetch.FETCHER_REV と同じ作法）

使い方:
  python3 night/gate_history.py --append          今日の判定を記録（CI・毎営業日）
  python3 night/gate_history.py --backfill        git に眠っている過去を取り込む（一度だけ）
  python3 night/gate_history.py --report [--t T]  溜まった記録を読む
出力: out/gate_history.jsonl（追記のみ）／ out/gate_state.json（直近の状態）
"""
import hashlib
import json
import os
import subprocess
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
OUT = os.path.join(BASE, "out")
LOG = os.path.join(OUT, "gate_history.jsonl")
STATE = os.path.join(OUT, "gate_state.json")

# 追う欄。**判定に直結するものだけ**——全部追うと変化の海に埋もれて信号が読めない
FIELDS = ["s", "moat", "buy", "kills", "pfail", "irr", "tier", "exit", "moatOK", "audOK"]
ROUND = {"s": 1, "moat": 1}          # 浮動小数の揺れを事象にしない


def gate_rev(blob=None):
    """門の内容ハッシュ。手で上げる版番号は必ず陳腐化するので中身から採る。"""
    b = blob if blob is not None else open(os.path.join(BASE, "index.html"), "rb").read()
    return "g" + hashlib.sha256(b).hexdigest()[:10]


def norm(r):
    o = {}
    for f in FIELDS:
        v = r.get(f)
        if f in ROUND and isinstance(v, (int, float)):
            v = round(float(v), ROUND[f])
        o[f] = v
    return o


def rows_of(blob):
    d = json.loads(blob)
    if isinstance(d, dict):
        d = d.get("rows") or d.get("items") or []
    return {(x.get("t") or x.get("nm")): norm(x) for x in d if (x.get("t") or x.get("nm"))}


def load_state():
    if not os.path.exists(STATE):
        return {"day": None, "items": {}}
    return json.load(open(STATE, encoding="utf-8"))


def append(day, cur, rev, note=""):
    """状態と突き合わせて、変わった分だけ書く。戻り: 書いた事象の数"""
    st = load_state()
    prev = st.get("items") or {}
    ev = []
    for t, v in cur.items():
        p = prev.get(t)
        if p is None:
            ev.append({"k": "new", "d": day, "t": t, "v": v})
            continue
        ch = {f: [p.get(f), v.get(f)] for f in FIELDS if p.get(f) != v.get(f)}
        if ch:
            ev.append({"k": "chg", "d": day, "t": t, "c": ch})
    for t in prev:
        if t not in cur:
            ev.append({"k": "gone", "d": day, "t": t})
    head = {"k": "day", "d": day, "gate": rev, "n": len(cur),
            "buy": sorted([t for t, v in cur.items() if v.get("buy")]), "ev": len(ev)}
    if note:
        head["note"] = note
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(head, ensure_ascii=False) + "\n")
        for e in ev:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    json.dump({"day": day, "gate": rev, "items": cur}, open(STATE, "w"),
              ensure_ascii=False, indent=0)
    return len(ev)


def git_days():
    """★日次CIのコミットだけを採る（`market prices YYYY-MM-DD`）。

    ⚠ ここを「その日の最後のコミット」にしてはいけない——**実際に踏んだ罠**。
      out/score_all.json の履歴には (a)main で毎日走る CI と (b)開発ブランチの作業 が
      マージで**交互に**入る。両者は**門の版が違う**（実測: 2026-08-13 の最終コミットは
      CI のもので、同じ日にブランチへ入れた v9.9.141 の TOPCAP を含んでいなかった）。
      素朴に「最後の1件」を採ると**別々の門の判定を一本の時系列として並べる**ことになる
      ＝この台帳が10回踏んできた「基準の違う二つを割る」型そのもの。
    ⇒ **同じジョブ・同じ系列(main)の日次コミットだけ**に揃える。開発中の途中経過は履歴に入れない。
    """
    o = subprocess.run(["git", "log", "--format=%H|%ad|%s", "--date=short",
                        "--", "out/score_all.json"], capture_output=True, text=True).stdout
    best = {}
    for ln in o.strip().splitlines():
        sha, day, subj = ln.split("|", 2)
        if not subj.startswith("market prices"):
            continue                            # ★日次CI以外は採らない
        best.setdefault(day, sha)               # 同日に複数あれば新しい方（git log は新しい順）
    return sorted(best.items())


def cat(sha, path):
    r = subprocess.run(["git", "show", f"{sha}:{path}"], capture_output=True)
    return r.stdout if r.returncode == 0 else None


def do_backfill():
    if os.path.exists(LOG):
        sys.exit(f"{LOG} が既にある。backfill は一度だけ（消してからやり直すこと）")
    n = 0
    for day, sha in git_days():
        blob = cat(sha, "out/score_all.json")
        if not blob:
            continue
        try:
            cur = rows_of(blob)
        except Exception as e:
            print(f"  {day}: 読めない（{type(e).__name__}）＝飛ばす")
            continue
        idx = cat(sha, "index.html")
        rev = gate_rev(idx) if idx else "g?"
        k = append(day, cur, rev, note="backfill（gitのその日の最後のコミット）")
        print(f"  {day} {sha[:8]}  {len(cur)}社 / 事象 {k}件  門 {rev}")
        n += 1
    print(f"\n✓ {n}日ぶんを取り込んだ → {os.path.relpath(LOG, BASE)}")
    print("⚠ この期間は**門そのものが変わっている**（v9.9.141 TOPCAP・v9.9.142 財務キル）。")
    print("  各行の `gate` が変われば『会社が変わった』ではなく『門が変わった』と読むこと。")


def do_append():
    p = os.path.join(OUT, "score_all.json")
    if not os.path.exists(p):
        sys.exit("out/score_all.json が無い（先に node night/score_all.js）")
    cur = rows_of(open(p, "rb").read())
    if not cur:
        sys.exit("★score_all.json が空。記録しない（空で上書きすると『変化なし』に化ける）")
    day = __import__("time").strftime("%Y-%m-%d")
    st = load_state()
    if st.get("day") == day:
        print(f"  {day} は記録済み（同じ日に二度書かない）")
        return
    k = append(day, cur, gate_rev())
    print(f"✓ {day}: {len(cur)}社 / 事象 {k}件 → {os.path.relpath(LOG, BASE)}")


def do_report(only=None):
    if not os.path.exists(LOG):
        sys.exit("記録がまだ無い（--backfill か --append）")
    days, ev = [], []
    for ln in open(LOG, encoding="utf-8"):
        o = json.loads(ln)
        (days if o["k"] == "day" else ev).append(o)
    if not days:
        sys.exit("day 行が無い")
    dl = [d["d"] for d in days]
    # 再構成: 各日の各社の状態
    state, hist = {}, {t: [] for t in {e["t"] for e in ev if "t" in e}}
    for d in days:
        for e in [x for x in ev if x["d"] == d["d"]]:
            if e["k"] == "new":
                state[e["t"]] = dict(e["v"])
            elif e["k"] == "chg":
                state.setdefault(e["t"], {}).update({f: v[1] for f, v in e["c"].items()})
            elif e["k"] == "gone":
                state.pop(e["t"], None)
        for t, v in state.items():
            hist.setdefault(t, []).append((d["d"], v.get("buy"), v.get("moat"), v.get("irr"), v.get("s")))

    print(f"■ 記録: {len(dl)}日（{dl[0]} 〜 {dl[-1]}）／ 事象 {len(ev)}件")
    revs = sorted({d["gate"] for d in days})
    print(f"  門そのものの版: {len(revs)}種類 {revs}")
    if len(revs) > 1:
        print("  ⚠ 期間中に門が変わっている＝全社一斉の変化は『会社』ではなく『門』が原因")
    for d in days:
        print(f"    {d['d']}  {d['n']}社  投下可{len(d['buy']):2d}  事象{d['ev']:4d}  門 {d['gate']}")

    if only:
        h = hist.get(only)
        if not h:
            sys.exit(f"{only} の記録が無い")
        print(f"\n■ {only}")
        for day, buy, moat, irr, s in h:
            print(f"    {day}  Ω {s}  堀 {moat}  irr {irr}  {'🟢投下可' if buy else '—'}")
        return

    # 連続で通っている社 / 刻みが下がった社
    print(f"\n■ 投下可を何日連続で保っているか（記録が {len(dl)}日しか無いので**まだ結論は出せない**）")
    streak = []
    for t, h in hist.items():
        run = 0
        for _, buy, *_ in reversed(h):
            if buy:
                run += 1
            else:
                break
        if run:
            streak.append((run, t, len(h)))
    for run, t, n in sorted(streak, reverse=True)[:15]:
        print(f"    {t:8s} 直近 {run}/{n}日 連続")

    print("\n■ ★刻みが下がった社（堀・irr が一度でも下向きに動いた）")
    #   ⚠ 下がった欄**だけ**を出す。同じ事象に上がった欄が混ざることがあり
    #     （実測 KRMN: moat 68.1→66.8 と irr 70→85 が同じ日）、両方出すと
    #     「下がった」という見出しの下に上がった値が並んで読み手を誤らせる。
    def dn(e):
        return {f: e["c"][f] for f in ("moat", "irr")
                if f in e["c"] and isinstance(e["c"][f][0], (int, float))
                and isinstance(e["c"][f][1], (int, float)) and e["c"][f][1] < e["c"][f][0]}
    down = [(e, dn(e)) for e in ev if e["k"] == "chg"]
    down = [(e, d) for e, d in down if d]
    if not down:
        print("    なし")
    for e, d in down[:20]:
        ch = "／".join(f"{f} {v[0]}→{v[1]}" for f, v in d.items())
        up = [f for f in ("moat", "irr") if f in e["c"] and f not in d]
        print(f"    {e['d']}  {e['t']:8s} {ch}" + (f"（同日に {'/'.join(up)} は上昇）" if up else ""))

    print("\n■ ★投下可から落ちた/入った日")
    for i in range(1, len(days)):
        a, b = set(days[i - 1]["buy"]), set(days[i]["buy"])
        if a != b:
            print(f"    {days[i]['d']}  入 {' '.join(sorted(b - a)) or '—'}"
                  f"  ／ 出 {' '.join(sorted(a - b)) or '—'}")
    print("\n⚠ **判定には一切使っていない**。効くかどうかは記録が溜まってから事前登録して一度だけ測る。")


def main():
    if "--backfill" in sys.argv:
        do_backfill()
    elif "--report" in sys.argv:
        i = sys.argv.index("--t") + 1 if "--t" in sys.argv else None
        do_report(sys.argv[i].upper() if i else None)
    else:
        do_append()
    return 0


if __name__ == "__main__":
    sys.exit(main())
