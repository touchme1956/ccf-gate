#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/validate_jp_packs.py — 日本株パックの納品検査（2026-07 JP検問の実装側チェック）

夜間審査で書き出した out/{コード}_gate_pack.json が門に取り込める形かを機械検査する。
門の ccfJpRoicSuspect()（index.html）は nm が /^\\d{4,5}(\\s|$|\\.)/ の銘柄について
roic>40 かつ roicEx無しを取込拒否する。ここではそれに加え、審査官が守るべき
JP必須規約（門式ROICの両記・TTM PER・スキーマ一致・列挙値・_meta必須）を落とす。

使い方: python3 night/validate_jp_packs.py            (out/ の日本株パック全部)
        python3 night/validate_jp_packs.py 7034 6920  (指定コードのみ)
終了コード: 致命(FAIL)が1件でもあれば 1。警告(WARN)のみなら 0。
"""
import json, glob, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)

SCHEMA = "out/ASR_gate_pack.json"          # 様式見本(最低限これは埋まっていること)
GATE = "index.html"                         # 受理キーの正＝門の applyFields マップ
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

    # --- 門式ROICの両記（JP検問の本体） ---
    roic, rx = d.get("roic"), d.get("roicEx")
    if roic is None and rx is None:
        warns.append("roic/roicEx とも空欄（ネットキャッシュ超過で分母負なら正当・kenshi要確認）")
    elif rx is None:
        fails.append(f"roicEx が無い（roic={roic}）。門式ROICを両方に記すこと")
    elif not isinstance(rx, (int, float)):
        fails.append(f"roicEx={rx} が数値でない")
    elif roic is None:
        fails.append("roic が空でroicExだけある（両記していない）")
    elif abs(float(roic) - float(rx)) > 0.05:
        fails.append(f"roic={roic} と roicEx={rx} が不一致（門式を両方に同値で記す規約）")
    elif float(rx) <= 0:
        # 本業赤字＝NOPAT負は正当な審査結果。門のJP検問(roic>40)も発火しない
        warns.append(f"門式ROIC={rx}% が非正（本業赤字ならこれが実像。分母負によるものでないか要確認）")
    elif float(rx) > 150:
        # 門式は「投下資本−過剰現金」なので、自己資本の大半が現金の資産軽量企業では
        # 分母が0へ縮退してROICが発散する。生EDINET値と同じく採点を壊すので取込前に止める
        rg = d.get("roicg")
        fails.append(
            f"門式ROIC={rx}% は分母縮退による発散（現金控除で投下資本がほぼ0）。"
            + (f"現金非控除のroicg={rg}%が実像に近い。" if isinstance(rg, (int, float)) else "")
            + "この値のまま取り込むと偽の怪物として採点される→規約判断待ち")
    elif float(rx) > 40:
        warns.append(f"門式ROIC={rx}% がなお40%超。過剰現金控除の分母縮退でないか検死で確認")

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
