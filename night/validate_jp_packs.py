#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/validate_jp_packs.py — 日本株パックの納品検査（2026-07 JP検問の実装側チェック）

夜間審査で書き出した out/{コード}_gate_pack.json が門に取り込める形かを機械検査する。
門の ccfJpRoicSuspect()（index.html）は nm が /^\\d{4,5}(\\s|$|\\.)/ の銘柄について
roic>40 かつ roicEx無しを取込拒否する。ここではそれに加え、審査官が守るべき
JP必須規約（ROIC三点の定義・TTM PER・スキーマ一致・列挙値・_meta必須）を落とす。

ROIC規約(v9.9.73・2026-08-03 ユーザー明示指示で米国規約へ統一): NOPAT=営業利益×(1−実効税率)、
  過剰現金は控除しない（米国規約も控除しないので統一前から一致）。
  roic = NOPAT÷(自己資本+有利子負債−のれん−無形)   roicg = NOPAT÷(自己資本+有利子負債)
  roicEx = roic 同値。**60%上限は撤廃**し、米国側と同じIC縮退ガード（投下資本が基準の20%未満なら
  算出不能。基準は自己資本、正でなければ総資産）に置き換えた——上限は壊れた数字を60という
  もっともらしい値に化かすだけで、空欄のほうが正しい（実測でも日本株の最高は52.5%＝一度も働いていない）。
  roicg≤roic が定義上の帰結。旧・門式(投下資本−過剰現金)は資産軽量企業で分母が縮退して
  発散したため2026-07-28に廃止（実測 957.7%/502.6%/256.0%）。

使い方: python3 night/validate_jp_packs.py            (out/ の日本株パック全部)
        python3 night/validate_jp_packs.py 7034 6920  (指定コードのみ)
終了コード: 致命(FAIL)が1件でもあれば 1。警告(WARN)のみなら 0。
"""
import json, glob, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)

SCHEMA = "out/ASR_gate_pack.json"          # 様式見本(最低限これは埋まっていること)
GATE = "index.html"                         # 受理キーの正＝門の applyFields マップ
SUSPECT = 60   # v9.9.73で上限は撤廃。60超は分母縮退の作業リスト行き（night/audit_roic.py と同じ扱い）
ENUMS = {
    "erosion": {"none", "emerging", "active"},
    "disrupt": {"settled", "unsettled", "threat"},
    "expiry": {"no", "yes", "na"},
    "moatdecay": {"no", "yes"},
    "gmt": {"up", "flat", "down"},
    "roict": {"up", "flat", "down"},
    "eq": {"pos", "neg"},
    "acc": {"usgaap", "ifrs", "jgaap", "other"},
    # v9.9.49(2026-07-29追加): 門のSELECTを実測したところ、以下7欄が列挙なのに検査対象外だった。
    #   実害を踏んだ——**acq5 は yes/no なのに33パックに数値が入っていた**。門は
    #   `acq5==='no'` でしか「のれん込みROIC乖離 −6」を免除しないので、数値は文字列比較に
    #   一致せず罰が黙って効く（ADBEで Ω 81.2→75.2 相当の差。門のソース自身が
    #   「Visa/Adobe型の誤爆防止」と名指ししている、まさにその誤爆だった）。
    #   列挙欄の型検査が無いと、**値が入っているのに門が読めない**という一番静かな壊れ方をする。
    "acq5": {"yes", "no"},
    "fin": {"no", "acq", "merger", "thin", "yes"},
    "founder": {"no", "yes"},
    "idx": {"", "yes", "no"},
    "indG": {"", "below", "avg", "above"},
    "sht": {"up", "flat", "down"},
    "rak": {"yes", "no"},
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
    elif float(rx) > SUSPECT:
        # v9.9.73: 上限クリップを廃止した。高ROIC自体は異常ではない（実測で米国株は債務超過の
        # 自社株買い企業など18社が本物）ので有罪判決にはせず、分母縮退の作業リストへ回す。
        warns.append(
            f"roic={rx}% が{SUSPECT}%超。上限クリップは v9.9.73 で撤廃したので値としては正当だが、"
            "投下資本が縮退していないか night/audit_roic.py で確認すること"
            "（IC<基準の20%なら算出不能としてnull化し理由を_meta.kenshiへ）")

    # roicg はのれん込み＝分母がroicより大きい。NOPAT>0なら roicg ≤ roic が定義上の帰結。
    # NOPAT<0（本業赤字）では分母が大きいほど負が浅くなるので不等号は反転する
    if isinstance(rg, (int, float)):
        if abs(rg) > SUSPECT:
            warns.append(f"roicg={rg}% が{SUSPECT}%超（v9.9.73で上限撤廃）。roicgは のれん込み＝分母が"
                         "最大なのでここが縮退していたら本物の異常。night/audit_roic.py で確認")
        if isinstance(roic, (int, float)):
            gap = float(roic) - rg
            if float(roic) > 0 and gap < -0.05:
                fails.append(
                    f"roicg={rg}% > roic={roic}%。roicgはのれん込み＝分母が大きいので roicg ≤ roic のはず。"
                    "roicgに「現金非控除ROIC」等の別物を入れていないか確認")
            elif float(roic) < 0 and gap > 0.05:
                fails.append(
                    f"roic={roic}% > roicg={rg}%（本業赤字）。NOPAT<0では分母が大きいroicgの方が"
                    "負が浅くなるので roicg ≥ roic のはず。のれんの符号処理を確認")
            elif float(roic) > 0 and gap > 15:
                warns.append(f"roicGap={round(gap,1)}pt>15 → 門が買収依存として減点する。"
                             "のれんが実在するなら正当な検出、そうでなければroicgの定義違い")
    elif roic is not None:
        warns.append("roicg が空欄（のれん込みROIC＝買収規律の指標。のれん無しならroicと同値を記す）")

    # --- gm粗利混入の番犬(2026-07-28: 日本株36社中12社で再発。過去にも32社で検出) ---
    # 門のgm欄は営業利益率であって粗利率ではない。粗利を入れると F7収益性・F9粘着性・
    # 無形調整ROIC が一斉に甘くなり、実測でΩ中央値が5.2pt浮いた。
    # 機械では粗利率を持たないので「営業利益率として異常に高い」帯を警告する。
    g = d.get("gm")
    if isinstance(g, (int, float)):
        ev = str((d.get("_meta") or {}).get("evidence", {}).get("gm", ""))
        if g >= 50 and "営業利益" not in ev:
            warns.append(
                f"gm={g}% は営業利益率として異常に高い（50%超は稀）。粗利混入の疑い＝"
                "原本で 営業利益÷売上 を確認し、_meta.evidence.gm に営業利益と売上の実額を書くこと")
        elif g >= 50:
            warns.append(f"gm={g}% は高いが evidence に営業利益の記載あり（確認済みとして通す）")

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
