#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/audit_er_realized.py — 門X の E[r]（期待リターン）の**予実台帳**（2026-08-03新設）

■ なぜ要るか（このリポジトリで一番重い穴だった）
  門X は E[r] で買付を裁いているのに、**その E[r] が当たったかを一度も検証していなかった**
  （`out/calibration.json` の `reviews` が空）。20年で年率15〜18%を狙うなら、
  どんな基準の調整より先に「自分の推定が何%ずれるか」を知る必要がある。
  特に E[r] は**倍率の重力を10年で引く式**なので、20年の時間軸に当てるとどちらへずれるかは
  実測しないと判らない。

■ この道具がやること
  (1) `--snap`  今日の観測を封じる——各銘柄の E[r]・その内訳(g/shy/gcap)・px・per・Ω・堀・関門の合否。
      **これが t=0 の記録**。これが無いと来年の突合せが永久にできない。
  (2) 引数なし  過去の観測と**現在値**を突き合わせ、E[r] が何%と言った銘柄が実際どうだったかを出す。

■ 正直に言っておく制約（もっともらしい誤値より空欄、という門の作法）
  ・**このリポジトリは2026-07に並走開始で、価格の履歴が約11日しかない。**
    だから初回は「記録を始める」ことだけが成果で、予実の答えはまだ出ない。
  ・**180日未満の観測は年率換算しない。** 数日の値動きを年率にすると桁が暴れて、
    数字がある分だけ空欄より有害になる（kessan_check_jp.py と同じ判断）。
  ・**価格リターンには配当が入らない。** E[r] の shy(純還元)は配当＋自社株買いで、
    自社株買いは価格に出るが配当は出ない。だから 実現価格リターン は E[r] より
    **配当利回りの分だけ構造的に低く出る**。観測に shy を残してあるので、
    突合せの時に「価格リターン ＋ 配当分」で読むこと。ここを揃えずに
    「E[r]は過大だった」と結論すると、自分で作った偏りを発見と誤認する。

使い方:
  python3 night/audit_er_realized.py --snap        今日の観測を out/er_ledger.json へ追記
                                                   （**月次idempotent**——同じ月に観測済みならスキップ。
                                                     やり直すときだけ --force＝同日分を置き換える）
  python3 night/audit_er_realized.py --snap --all  Ω75+ だけでなく全パックを封じる
  python3 night/audit_er_realized.py               過去の観測 × 現在値で予実を出す
"""
import json
import os
import subprocess
import sys
from datetime import date, datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER = os.path.join(BASE, "out", "er_ledger.json")
MIN_DAYS = 180          # これ未満は年率換算しない


def load_ledger():
    if os.path.exists(LEDGER):
        return json.load(open(LEDGER, encoding="utf-8"))
    return {
        "note": ("門X の E[r] の予実台帳。`--snap` で観測を封じ、後日 `引数なし` で現在値と突き合わせる。"
                 "**180日未満は年率換算しない**（数日の値動きを年率にすると桁が暴れる）。"
                 "**価格リターンには配当が入らない**ので、E[r] と比べるときは shy の配当分を足して読むこと。"),
        "observations": [],
    }


def current_px():
    """毎営業日 GitHub Actions が更新する out/dashboard.json を現在値の源にする"""
    p = os.path.join(BASE, "out", "dashboard.json")
    if not os.path.exists(p):
        return {}, None
    d = json.load(open(p, encoding="utf-8"))
    q = {k.upper(): v for k, v in (d.get("quotes") or {}).items()}
    return q, d.get("asof")


def snap(all_names=False, force=False):
    """門の ccfXJudge/compute をそのまま走らせて今日の観測を作る（二重実装を作らない）

    A9(2026-08-04): **月次idempotent**にした。market.yml の月初判定は `date +%d ≤ 7`＝
    毎月1〜7日の平日**すべて**（月5回）発火し、snap は同日しか重複排除しないので、
    実害として 2026-08-03 と 08-04 の観測が31社×2重に積まれた（g上限の集計が二重カウント）。
    CI側の窓は残したまま、**封じる側で同月の観測があればスキップ**する——手作業に頼らない防波堤。
    やり直し（--force）のときだけ従来どおり同日分を置き換える。
    """
    today = date.today().isoformat()
    led = load_ledger()
    month_have = sorted({o["date"] for o in led["observations"]
                         if str(o.get("date", "")).startswith(today[:7])})
    if month_have and not force:
        print(f"今月({today[:7]})の観測は封印済み（{' '.join(month_have)}）→ スキップ。"
              "年率の検証に月2回目は要らない（月次idempotent・A9）。やり直すなら --force")
        return 0
    js = r"""
const fs=require('fs'),path=require('path');
const ROOT=process.argv[2], ALL=process.argv[3]==='1';
const {scorePack}=require(ROOT+'/night/score_all.js');
const out=[];
for(const f of fs.readdirSync(ROOT+'/out')){
  if(!f.endsWith('_gate_pack.json'))continue;
  const t=f.split('_gate_pack')[0];
  let d; try{d=JSON.parse(fs.readFileSync(ROOT+'/out/'+f,'utf8'));}catch{continue;}
  let r; try{r=scorePack(d);}catch{continue;}
  const s=parseFloat(r.evalScore); if(!isFinite(s)||s<=0)continue;
  if(!ALL&&s<75)continue;
  let x={},mg={};
  try{x=ccfXJudge(d,s)||{};}catch{}
  try{mg=ccfMoatGate(r,d)||{};}catch{}
  out.push({t,omega:+s.toFixed(1),tier:r.tierShort,
    er:x.xEr==null?null:+x.xEr.toFixed(2), xPass:x.xPass===true,
    g:x.g==null?null:+x.g.toFixed(2), shy:x.shy==null?null:+x.shy,
    gcap:x.gcap==null?null:+x.gcap.toFixed(2), gcapSrc:x.gcapSrc||null,
    per:d.per==null?null:+d.per, px:d.px==null?null:+d.px,
    moat:mg.idx==null?null:+mg.idx.toFixed(1), moatOK:!!mg.pass,
    buy:s>=75&&x.xPass===true&&mg.pass===true,
    ccy:/^\d{4,5}$/.test(String(d.nm||t).trim().split(/\s/)[0])?'JPY':'USD'});
}
console.log(JSON.stringify(out));
"""
    p = os.path.join(BASE, "night", "_snap_tmp.js")
    open(p, "w", encoding="utf-8").write(js)
    try:
        r = subprocess.run(["node", p, BASE, "1" if all_names else "0"],
                           capture_output=True, text=True, cwd=BASE)
        if r.returncode != 0:
            print("採点の実行に失敗:", r.stderr[-500:]); return 1
        recs = json.loads(r.stdout)
    finally:
        os.remove(p)

    # A9(d): 配当利回り divY の分離保存。E[r] の shy は配当＋自社株買いの合算で、価格リターンには
    #   配当が入らないため、**配当分離は突合時の補正に必須**（分離せずに観測を積み始めると、
    #   後からでは補正不能な偏りが確定する＝B3）。out/divy.json（{TICKER: 配当利回り%}）があれば読む。
    #   ファイルが無い・銘柄が無いときは null——**0では埋めない**（0は「無配と測った」の意味。
    #   欠測をゼロと読むな＝絶対のルール7）。
    divy = {}
    p_divy = os.path.join(BASE, "out", "divy.json")
    if os.path.exists(p_divy):
        try:
            _dj = json.load(open(p_divy, encoding="utf-8"))
            # 形式は2通りを受ける: {"asof":…, "divY":{T:pct}}（night/fill_divy.py）または素の {T:pct}
            _map = _dj.get("divY") if isinstance(_dj.get("divY"), dict) else _dj
            divy = {str(k).upper(): v for k, v in _map.items()}
        except Exception:
            print("⚠ out/divy.json が読めない——divY は全社 null で封じる（誤値より空欄）")
            divy = {}
    for x in recs:
        _dv = divy.get(str(x.get("t", "")).upper())
        x["divY"] = float(_dv) if isinstance(_dv, (int, float)) else None

    # --force の再実行では同日分だけを置き換える（同月の別日はガードが上で止めている）
    led["observations"] = [o for o in led["observations"] if o.get("date") != today]
    n_px = 0
    for x in recs:
        if x.get("px"):
            n_px += 1
        led["observations"].append({"date": today, **x})
    led["observations"].sort(key=lambda o: (o["date"], o["t"]))
    json.dump(led, open(LEDGER, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    buy = [x["t"] for x in recs if x["buy"]]
    print(f"{today} の観測を {len(recs)}社ぶん封じた（うち px あり {n_px}社 / 投下可 {len(buy)}社: {' '.join(buy)}）")
    print(f"→ {os.path.relpath(LEDGER, BASE)}（累計 {len(led['observations'])}件・"
          f"観測日 {sorted({o['date'] for o in led['observations']})}）")
    print("\n※ px が無い社は突合せの対象外になる（価格が無ければ実現リターンが出せない）。")
    print("  次にやること: このファイルをコミットする。**記録は残さなければ存在しない**。")
    return 0


def review():
    led = load_ledger()
    obs = led["observations"]
    if not obs:
        print("観測がまだ無い。まず `python3 night/audit_er_realized.py --snap` で t=0 を封じること。")
        return 0
    q, asof = current_px()
    if not q:
        print("out/dashboard.json が無いので現在値が取れない。")
        return 1
    today = datetime.fromisoformat((asof or date.today().isoformat()).replace("Z", "+00:00")).date() \
        if asof else date.today()

    rows = []
    for o in obs:
        cur = q.get(o["t"].upper())
        if not (cur and cur.get("px") and o.get("px") and o.get("er") is not None):
            continue
        d0 = date.fromisoformat(o["date"])
        # 観測日より dashboard の asof が古いと days が負になる（初回スナップ当日に起きる）。
        #   負の経過日数で年率を出すと符号ごと壊れるので 0 で床を張り、鮮度は別途警告する。
        days = max(0, (today - d0).days)
        pr = (cur["px"] / o["px"] - 1) * 100
        rows.append({**o, "days": days, "pxNow": cur["px"], "priceRet": pr,
                     "ann": ((cur["px"] / o["px"]) ** (365 / days) - 1) * 100 if days >= MIN_DAYS else None})
    if not rows:
        print("突合せできる観測がまだ無い（px を持つ観測と現在値の両方が要る）。")
        return 0

    stale = [r for r in rows if date.fromisoformat(r["date"]) > today]
    if stale:
        print(f"⚠ dashboard.json の価格日({today}) が観測日より古い {len(stale)}件ある"
              f"——初回スナップ当日は正常。翌営業日の価格取得後に再実行せよ。\n")
    ready = [r for r in rows if r["ann"] is not None]
    print(f"観測 {len(obs)}件 / 価格が付き合わせられた {len(rows)}件 / "
          f"**年率換算できる（{MIN_DAYS}日以上）{len(ready)}件**\n")
    if not ready:
        oldest = min(r["days"] for r in rows)
        print(f"■ まだ答えは出ない。最も古い観測でも経過 {oldest}日（{MIN_DAYS}日必要）。")
        print("  **数日の値動きを年率にすると桁が暴れる**ので、ここでは意図的に何も出さない。")
        print("  いま出せるのは『記録が動いているか』の確認だけ:\n")
        rows.sort(key=lambda r: -r["er"])
        print(f"  {'':6s} {'観測日':>10s} {'経過':>5s} {'E[r]':>7s} {'g':>6s} {'shy':>6s} "
              f"{'観測時px':>10s} {'現在px':>10s} {'価格変化':>9s}")
        for r in rows[:20]:
            print(f"  {r['t']:6s} {r['date']:>10s} {r['days']:4d}日 {r['er']:6.1f}% "
                  f"{(r['g'] or 0):5.1f}% {(r['shy'] or 0):5.2f}% "
                  f"{r['px']:10.2f} {r['pxNow']:10.2f} {r['priceRet']:+8.1f}%")
        print(f"\n  ※ 価格変化に**配当は入っていない**。E[r] の shy(純還元)は配当＋自社株買いなので、")
        print(f"    突き合わせるときは価格変化に配当分を足して読むこと。")
        cap = [r for r in rows if r.get("g") is not None and r["g"] >= 19.99]
        if cap:
            print(f"\n■ いま封じた観測で気づくこと: **成長 g が上限20%に張り付いている {len(cap)}/{len(rows)}社**")
            print(f"    {' '.join(r['t'] for r in cap)}")
            print(f"    g=min(実績cagr, 実力gcap, 20%) の**20%上限が効いている**＝E[r]は「20%成長」を前提に置いている。")
            print(f"    実際の持続成長がこれ未満なら E[r] はその分だけ過大に出る。")
            print(f"    **予実がここで効く**——差が安定して負なら、上限20%かハードル12%のどちらかが緩い。")
        return 0

    ready.sort(key=lambda r: -r["er"])
    print(f"{'':6s} {'観測日':>10s} {'経過':>6s} {'E[r]予':>7s} {'実現(年率)':>10s} {'差':>8s}  内訳")
    for r in ready:
        print(f"  {r['t']:6s} {r['date']:>10s} {r['days']:5d}日 {r['er']:6.1f}% {r['ann']:9.1f}% "
              f"{r['ann'] - r['er']:+7.1f}%  g={r['g']} shy={r['shy']} Ω{r['omega']}")
    er = sorted(x["er"] for x in ready); an = sorted(x["ann"] for x in ready)
    me, ma = er[len(er) // 2], an[len(an) // 2]
    print(f"\n■ 中央値: E[r]予 {me:.1f}% → 実現 {ma:.1f}%（差 {ma - me:+.1f}%）")
    print(f"  **配当分は実現側に入っていない**ので、真の差はこれより小さい。")
    print(f"  この差が安定して負なら、門Xのハードル(現行12%)をその分だけ上げるのが筋。")
    return 0


def main():
    if "--snap" in sys.argv:
        return snap(all_names="--all" in sys.argv, force="--force" in sys.argv)
    return review()


if __name__ == "__main__":
    sys.exit(main())
