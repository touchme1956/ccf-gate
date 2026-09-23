#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/audit_deadweight.py — 投資基準のうち「書いてあるが働いていない項」を実測する（2026-07-29新設）

問い: **門の投資基準に無駄はないか。**
  基準が増えるほど門は賢くなる、わけではない。動かない項は
    (a) 読む人の注意を食う（本当に効く項が埋もれる）
    (b) 「測っている」という錯覚を作る（穴を穴として認識できなくなる）
  ので、実測して仕分ける。判定は門そのもの(compute/ccfXJudge/ccfMoatGate)を回して出す。

見るもの（2つは別の病気）:
  ■ 死因A「入力が空で規則が発火しない」——基準は正しいのに台帳が空欄で、警報が構造的に鳴らない。
    これは**無駄ではなく穴**。直し方は基準を消すことではなく、採取・審査で埋めること。
  ■ 死因B「入力があっても判定が動かない」——値は入っているのに Ω・投下可・門X・間・出口・キルの
    どれも変わらない。これが**本当の無駄**（または意図的な表示専用）。

初回実測（2026-07-29・全317パック）で判ったこと:
  ■ 死因A の筆頭は **sht（シェア趨勢）が全317社で空欄** だったこと。SELECTの既定 'flat' に化けるので、
    sht を使う**5つの規則がまるごと不発**になっていた:
      1. pm += {up:+3, flat:0, down:-10}[sht]        → 全社 +0（MOAT柱の調整が効かない）
      2. indG='below' ∧ sht='up' → 地味業界の勝者 +2  → 一度も成立せず
      3. gmt='down' ∧ sht='down' → **Intel警報**      → 一度も成立せず
      4. S2売却規律「堀の軌道反転(粗利×シェア同時低下)」→ 一度も発火せず
      5. S2「ROIC×(粗利orシェア)同時劣化」            → shtの側だけ死んでいる（gmtの側は生きている）
    **Intel警報は「20年で崩れた堀」の実例から作った先行検出**なのに、入力が無いので一度も鳴っていない。
    門の設計が悪いのではなく、シェア趨勢という次元が台帳から丸ごと抜けている。
  ■ 同種: gls(企業文化)は305社空欄＋12社が0 → ccfMoatの文化調整 −2 は**0社**で発動。
          nrr は313/317が既定105 → 「nrr<100 で pm −6」は**0社**。
          idx は302社空欄 → 発見度 ±1.5/−1.0 はほぼ不発。
          rak は317社すべて空欄（既定yes）→「取引不可」の検問は一度も作動していない（保険としては正常）。
  ■ 死因B（値はあるが判定が動かない）:
          dilNet … コードに『表示のみ・v9.6』と明記。>5で『殺相当』と書くが**自動では何も起きない**
                   （5社が該当）。純還元の信号は shy が純額で持っているので二重ではある。
          acc  … jgaap/ifrs の注意書きを出すだけ（意図的な読み手向け注記）。
          founder … 26社に立つが判定を1件も動かさない（F10へ+8→Ωで約0.1pt）。

使い方:
  python3 night/audit_deadweight.py           発火率（死因A）
  python3 night/audit_deadweight.py --swing   欄を端から端まで振って判定が動くかを実測（死因B・遅い）
"""
import glob
import json
import os
import subprocess
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)

# 「この条件が成立したときだけ働く規則」を、成立回数で測る。正は index.html の compute()。
RULES = [
    ("sht='up' → pm+3 / 地味業界の勝者+2", lambda d: d.get("sht") == "up"),
    ("sht='down' → pm−10", lambda d: d.get("sht") == "down"),
    ("gmt='down' ∧ sht='down' → Intel警報・S2堀の軌道反転", lambda d: d.get("gmt") == "down" and d.get("sht") == "down"),
    # v9.9.193: gls の文化調整・nrr<100 の pm−6 は門から撤去したので外した
    ("rak='no' → 「取引不可」", lambda d: d.get("rak") == "no"),
    ("idx='no' → 発見度 +1.5", lambda d: d.get("idx") == "no"),
    ("indG='below' → 地味業界（sht='up'との同時成立が要る）", lambda d: d.get("indG") == "below"),
    ("founder='yes' → F10 +8", lambda d: d.get("founder") == "yes"),
    ("dilNet>5 → 『殺相当』の警告（自動では何も起きない）", lambda d: isinstance(d.get("dilNet"), (int, float)) and d["dilNet"] > 5),
    ("sbc>10 → 株式報酬の重さ", lambda d: isinstance(d.get("sbc"), (int, float)) and d["sbc"] > 10),
    ("geopol≥2 → 地政学の減点", lambda d: isinstance(d.get("geopol"), (int, float)) and d["geopol"] >= 2),
    ("expiry='yes' → 期限型独占キル", lambda d: d.get("expiry") == "yes"),
    ("eq='neg' → 債務超過キル", lambda d: d.get("eq") == "neg"),
    ("erosion='active' → 堀の減衰キル", lambda d: d.get("erosion") == "active"),
    ("moatdecay='yes' → 堀の明確な減衰キル", lambda d: d.get("moatdecay") == "yes"),
    ("acq5='no' → のれん乖離 −6 の免除", lambda d: d.get("acq5") == "no"),
]
# 空欄率も併せて見る——空欄が既定値へ化ける欄は「測っていない」が「測って既定だった」になる
BLANKS = ["sht", "gls", "nrr", "rak", "idx", "indG", "founder", "dilNet", "sbc", "geopol"]

SWING_JS = r"""
const {scorePack} = require('%s/night/score_all.js');
const fs = require('fs');
const R = %s;
const packs = fs.readdirSync('out').filter(f=>f.endsWith('_gate_pack.json'))
  .map(f=>{try{return JSON.parse(fs.readFileSync('out/'+f,'utf8'));}catch(e){return null;}}).filter(Boolean);
const out=[];
for (const k of Object.keys(R)) {
  const [lo,hi]=R[k]; let n=0,sum=0,mx=0,buy=0,xp=0,act=0,ex=0,kl=0;
  for (const d of packs) {
    let a,b,xa,xb,ma,mb;
    try{
      a=scorePack({...d,[k]:lo}); xa=ccfXJudge({...d,[k]:lo},+a.evalScore)||{}; ma=ccfMoatGate(a,{...d,[k]:lo})||{};
      b=scorePack({...d,[k]:hi}); xb=ccfXJudge({...d,[k]:hi},+b.evalScore)||{}; mb=ccfMoatGate(b,{...d,[k]:hi})||{};
    }catch(e){continue;}
    const sa=+a.evalScore, sb=+b.evalScore; if(!isFinite(sa)||!isFinite(sb))continue;
    n++; const dd=Math.abs(sb-sa); sum+=dd; if(dd>mx)mx=dd;
    if((sa>=75&&xa.xPass===true&&ma.pass===true)!==(sb>=75&&xb.xPass===true&&mb.pass===true))buy++;
    if(xa.xPass!==xb.xPass)xp++;
    if(a.act!==b.act)act++;
    if((a.exit&&a.exit.level)!==(b.exit&&b.exit.level))ex++;
    if((a.kills>0)!==(b.kills>0))kl++;
  }
  out.push({k,n,avg:sum/Math.max(n,1),mx,total:buy+xp+act+ex+kl,buy,xp,act,ex,kl});
}
out.sort((x,y)=>(y.avg+y.total*0.05)-(x.avg+x.total*0.05));
console.log(JSON.stringify(out));
"""

RANGES = {
    "dom": [50, 100], "irr": [50, 100], "rep": [35, 100], "dur": [55, 100], "moatW": [50, 100],
    "p1": [50, 95], "p2": [50, 95], "p3": [50, 95], "p4": [50, 90],
    "f1": [45, 90], "f2": [50, 90], "f3": [55, 90], "f4": [50, 80], "f5": [45, 85],
    "roic": [5, 60], "roicg": [5, 60], "gm": [5, 50], "cagr": [0, 30], "nde": [-1, 4],
    "gpa": [5, 60], "accr": [-10, 15], "z": [1, 9], "sbc": [0, 10], "dilNet": [-3, 6],
    "nrr": [85, 130], "geopol": [0, 3], "roiic": [0, 40], "shy": [-2, 6], "gls": [1, 5],
    "erosion": ["none", "active"], "disrupt": ["settled", "threat"], "moatdecay": ["no", "yes"],
    "expiry": ["no", "yes"], "gmt": ["down", "up"], "roict": ["down", "up"], "sht": ["down", "up"],
    "acq5": ["yes", "no"], "fin": ["no", "yes"], "eq": ["pos", "neg"], "acc": ["usgaap", "jgaap"],
    "founder": ["no", "yes"], "rak": ["no", "yes"], "indG": ["below", "above"], "idx": ["no", "yes"],
    # v9.9.171(2026-09-19): **発見度(negS)の入力3本がこの表から抜けていた**。negS は evalScore を
    #   ±1.5/−1.0 **直接**動かす唯一の修飾子なのに、idx だけが載っていて「0.09pt＝ほぼ動かない」に見えていた。
    #   ＝Ωを直接動かす経路が「無駄か否か」の検査を一度も受けていなかった。詳細は night/audit_neglect.py。
    #   ⚠ negS は v9.9.171 でΩから外したので、以後この3本は0と出るのが正常（表示専用になった証拠）。
    "analysts": [3, 50], "instOwn": [20, 90], "mcap": [1, 200],
}


def main():
    packs = []
    for f in sorted(glob.glob("out/*_gate_pack.json")):
        try:
            packs.append(json.load(open(f, encoding="utf-8")))
        except Exception:
            pass
    n = len(packs)

    if "--swing" not in sys.argv:
        print(f"■ 死因A: 条件が成立しないと働かない規則の発火率（全{n}社）\n")
        dead = []
        for lab, f in RULES:
            c = sum(1 for d in packs if f(d))
            tag = "  ← **一度も成立しない＝この規則は働いていない**" if c == 0 else ""
            if c == 0:
                dead.append(lab)
            print(f"  {c:4d}/{n} = {c/n*100:5.1f}%  {'█'*round(c/n*30):30s} {lab}{tag}")
        print(f"\n■ 空欄率（空欄がSELECTの既定値へ化ける欄は「測っていない」が「測って既定だった」になる）\n")
        for k in BLANKS:
            c = sum(1 for d in packs if d.get(k) in (None, ""))
            tag = "  ← **全社空欄＝この次元は台帳に存在しない**" if c == n else ""
            print(f"  {c:4d}/{n} = {c/n*100:5.1f}%  {k}{tag}")
        if dead:
            print(f"\n**働いていない規則 {len(dead)}件**——これは無駄ではなく**穴**。")
            print("  直し方は規則を消すことではなく、採取・審査で入力を埋めること。")
            print("  基準を消すと『測らなかった』という事実まで消える（穴が穴として見えなくなる）。")
        print("\n※--swing で「値はあるが判定が動かない欄」（死因B＝本当の無駄）も測る（遅い）")
        return 0

    print("■ 死因B: 欄を規約の端から端まで振って、判定が動くかを門そのもので実測する\n")
    r = subprocess.run(["node", "-e", SWING_JS % (BASE, json.dumps(RANGES))],
                       capture_output=True, text=True, cwd=BASE)
    try:
        rows = json.loads(r.stdout.strip().splitlines()[-1])
    except Exception:
        print("実測に失敗:", (r.stderr or "")[-500:])
        return 1
    print(f"{'欄':10s}{'平均ΔΩ':>8s}{'最大':>7s}{'投下可':>7s}{'門X':>6s}{'間act':>7s}{'出口':>6s}{'キル':>6s}{'計':>7s}")
    for x in rows:
        tag = "  ← 全社で何一つ動かない" if x["total"] == 0 and x["avg"] < 0.01 else ""
        print(f"{x['k']:10s}{x['avg']:8.2f}{x['mx']:7.1f}{x['buy']:7d}{x['xp']:6d}"
              f"{x['act']:7d}{x['ex']:6d}{x['kl']:6d}{x['total']:7d}{tag}")
    print("\n※fcf/ni は門が比(conv=fcf/ni)でしか使わないので、片方ずつ振ると効かなく見える。")
    print("  比で振ると 平均ΔΩ1.76 / 最大5.4 / 213社が0.5pt超で動く＝生きている。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
