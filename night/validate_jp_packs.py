#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/validate_jp_packs.py — 日本株パックの納品検査（2026-07 JP検問の実装側チェック）

夜間審査で書き出した out/{コード}_gate_pack.json が門に取り込める形かを機械検査する。
門の ccfJpRoicSuspect()（index.html）は nm が /^\\d{4,5}(\\s|$|\\.)/ の銘柄について
roic>40 かつ roicEx無しを取込拒否する。ここではそれに加え、審査官が守るべき
JP必須規約（ROIC三点の定義・TTM PER・スキーマ一致・列挙値・_meta必須）を落とす。

ROIC規約(2026-07-28改定): NOPAT=営業利益×0.70、過剰現金は控除しない。
  roic = min(NOPAT÷(有利子負債+自己資本−のれん), 60)  roicg = min(NOPAT÷(有利子負債+自己資本), 60)
  roicEx = roic 同値。旧・門式(投下資本−過剰現金)は資産軽量企業で分母が縮退して
  発散したため廃止（実測 957.7%/502.6%/256.0%）。roicg≤roic が定義上の帰結。

使い方: python3 night/validate_jp_packs.py            (out/ の日本株パック全部)
        python3 night/validate_jp_packs.py 7034 6920  (指定コードのみ)
終了コード: 致命(FAIL)が1件でもあれば 1。警告(WARN)のみなら 0。
"""
import json, glob, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)

SCHEMA = "out/ASR_gate_pack.json"          # 様式見本(最低限これは埋まっていること)
GATE = "index.html"                         # 受理キーの正＝門の applyFields マップ
CAP = 60                                    # ROIC上限(2026-07-28規約・門Xの60%キャップと同思想)
ENUMS = {
    "erosion": {"none", "emerging", "active"},
    "disrupt": {"settled", "unsettled", "threat"},
    "expiry": {"no", "yes", "na"},
    "moatdecay": {"no", "yes"},
    "gmt": {"up", "flat", "down"},
    "roict": {"up", "flat", "down"},
    "eq": {"pos", "neg"},
    "acc": {"usgaap", "ifrs", "jgaap", "other"},
}
SCORE100 = ["dom", "irr", "rep", "dur", "p1", "p2", "p3", "p4",
            "f1", "f2", "f3", "f4", "f5"]
META_REQ = ["auditDate", "model", "kenshi", "evidence", "nulls"]


_GK = None


def gate_keys():
    """門(index.html)の applyFields マップから受理キー集合を読む＝二重正本を作らない。"""
    global _GK
    if _GK is None:
        s = open(GATE, encoding="utf-8").read()
        i = s.find("function applyFields(d)")
        j = s.find("const map={", i)
        if i < 0 or j < 0:
            raise RuntimeError("index.html に applyFields のマップが見つからない")
        _GK = set(re.findall(r"(\w+):'", s[j + 10:s.find("};", j)]))
    return _GK


def check(path):
    """1パックを検査して (fails, warns) を返す。"""
    fails, warns = [], []
    code = os.path.basename(path).split("_gate_pack")[0]
    try:
        d = json.load(open(path, encoding="utf-8"))
    except Exception as e:
        return [f"JSONが壊れている: {e}"], []

    # --- nm はコード始まり必須（門のJP判定がこれで発火する） ---
    nm = str(d.get("nm") or "").strip()
    if not re.match(r"^\d{4,5}(\s|$|\.)", nm):
        fails.append(f'nm="{nm}" がコード始まりでない→門のJP検問が発火せず素通しする')
    elif not nm.startswith(code):
        fails.append(f'nm="{nm}" がファイル名のコード {code} と不一致')

    # --- ROIC三点（2026-07-28規約: 現金非控除・60%上限・roicgはのれん込み） ---
    roic, rx, rg = d.get("roic"), d.get("roicEx"), d.get("roicg")
    if roic is None and rx is None:
        warns.append("roic/roicEx とも空欄（算出不能なら正当・kenshi要確認）")
    elif rx is None:
        fails.append(f"roicEx が無い（roic={roic}）。roicと同値で両記すること")
    elif not isinstance(rx, (int, float)):
        fails.append(f"roicEx={rx} が数値でない")
    elif roic is None:
        fails.append("roic が空でroicExだけある（両記していない）")
    elif abs(float(roic) - float(rx)) > 0.05:
        fails.append(f"roic={roic} と roicEx={rx} が不一致（同値で記す規約）")
    elif float(rx) <= 0:
        # 本業赤字＝NOPAT負は正当な審査結果。門のJP検問(roic>40)も発火しない
        warns.append(f"roic={rx}% が非正（本業赤字ならこれが実像。分母の符号を要確認）")
    elif float(rx) > CAP + 0.05:
        fails.append(
            f"roic={rx}% が上限{CAP}%を超えている。2026-07-28規約は現金非控除かつ"
            f"min(…,{CAP})でクリップする（旧・門式の現金控除は分母縮退で発散したため廃止）")

    # roicg はのれん込み＝分母がroicより大きいので roicg ≤ roic が定義上の帰結
    if isinstance(rg, (int, float)):
        if rg > CAP + 0.05:
            fails.append(f"roicg={rg}% が上限{CAP}%を超えている（roicgも同じくクリップする）")
        if isinstance(roic, (int, float)) and rg > float(roic) + 0.05:
            fails.append(
                f"roicg={rg}% > roic={roic}%。roicgはのれん込み＝分母が大きいので roicg ≤ roic のはず。"
                "roicgに「現金非控除ROIC」等の別物を入れていないか確認")
        if isinstance(roic, (int, float)) and float(roic) - rg > 15:
            warns.append(f"roicGap={round(float(roic)-rg,1)}pt>15 → 門が買収依存として減点する。"
                         "のれんが実在するなら正当な検出、そうでなければroicgの定義違い")
    elif roic is not None:
        warns.append("roicg が空欄（のれん込みROIC＝買収規律の指標。のれん無しならroicと同値を記す）")

    # --- PERはTTM実績 ---
    per = d.get("per")
    if isinstance(per, (int, float)):
        if per <= 0:
            fails.append(f"per={per} が非正（TTM実績EPSが赤字なら null にする）")
        elif per > 150:
            warns.append(f"per={per} が異常に高い。TTM実績EPSか確認（会予はperFへ）")

    # --- スキーマ一致（受理キーの正は門の applyFields。ASR見本はその部分集合） ---
    try:
        accepted = gate_keys()
        got = set(d.keys()) - {"_meta"}
        extra = got - accepted
        if extra:
            fails.append(f"門が受け取らないキー: {sorted(extra)}")
        need = set(json.load(open(SCHEMA, encoding="utf-8")).keys()) - {"_meta"}
        miss = need - got
        if miss:
            fails.append(f"様式見本のキー欠落: {sorted(miss)}")
    except Exception as e:
        warns.append(f"キー照合を省略({e})")

    # --- 列挙値・点数域 ---
    for k, allowed in ENUMS.items():
        v = d.get(k)
        if v is not None and str(v) not in allowed:
            fails.append(f"{k}='{v}' は許容外 {sorted(allowed)}")
    g = d.get("geopol")
    if g is not None and (not isinstance(g, int) or not 0 <= g <= 3):
        fails.append(f"geopol={g} は0-3の整数")
    for k in SCORE100:
        v = d.get(k)
        if v is not None and (not isinstance(v, (int, float)) or not 0 <= v <= 100):
            fails.append(f"{k}={v} は0-100の数値")

    # --- 定性の埋まり具合（空欄は許すが、堀4項目全欠は審査未了） ---
    if all(d.get(k) is None for k in ("dom", "irr", "rep", "dur")):
        fails.append("堀4項目(dom/irr/rep/dur)が全て空＝審査が成立していない")

    # --- _meta ---
    m = d.get("_meta")
    if not isinstance(m, dict):
        fails.append("_meta が無い")
    else:
        for k in META_REQ:
            if k not in m or m[k] in (None, "", [], {}):
                (fails if k in ("auditDate", "model") else warns).append(f"_meta.{k} が空")
    return fails, warns


def main():
    args = [a for a in sys.argv[1:] if re.fullmatch(r"\d{4,5}", a)]
    paths = ([f"out/{a}_gate_pack.json" for a in args] if args
             else sorted(glob.glob("out/[0-9][0-9][0-9][0-9]_gate_pack.json")
                         + glob.glob("out/[0-9][0-9][0-9][0-9][0-9]_gate_pack.json")))
    if not paths:
        print("日本株パックが見つからない（out/{コード}_gate_pack.json）")
        return 0

    nf = nw = 0
    for p in paths:
        if not os.path.exists(p):
            print(f"✗ {p}: ファイルが無い")
            nf += 1
            continue
        fails, warns = check(p)
        code = os.path.basename(p).split("_gate_pack")[0]
        if fails:
            nf += 1
            print(f"✗ {code}")
            for f in fails:
                print(f"    FAIL {f}")
        elif warns:
            print(f"△ {code}")
        else:
            print(f"✓ {code}")
        for w in warns:
            nw += 1
            print(f"    warn {w}")

    print(f"\n検査 {len(paths)}件 / 致命 {nf}件 / 警告 {nw}件")
    if nf:
        print("致命ありのパックは門が取込拒否＝審査待ちへ隔離される。審査官へ差し戻すこと")
    return 1 if nf else 0


if __name__ == "__main__":
    sys.exit(main())
