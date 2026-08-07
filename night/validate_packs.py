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
    # ただし**規約が「開示が無ければこの値を書け」と定めた既定値**は別扱い（2026-07-29）。
    #   審査プロトコル『nrr: 開示値、なければ既定105』——105は測定値ではなく規約の代替値なので、
    #   原本根拠を要求するのは審査官に「規約どおり書いたら差し戻し」を強いることになる。
    #   実測(全317パック)で nrr の根拠なしは **187社=59.0%** と全項目で最多だった。
    #   **鳴りすぎる警報は鳴らないのと同じ**なので、既定値だと判るものは warn へ落とし、
    #   それ以外の判断項目は従来どおり FAIL のまま残す（検査の強さは下げない）。
    #   なお105が**実測のNRR**なら evidence を、非開示なら _meta.nulls.nrr に一行を書くのが正しい姿。
    PROTOCOL_DEFAULT = {"nrr": 105}
    nj, nd = [], []
    for k in JUDGE:
        if not has_val(d.get(k)) or ev_of(meta, k):
            continue
        if k in PROTOCOL_DEFAULT and d.get(k) == PROTOCOL_DEFAULT[k] and not (meta.get("nulls") or {}).get(k):
            nd.append(k)
        elif k not in PROTOCOL_DEFAULT or d.get(k) != PROTOCOL_DEFAULT[k]:
            nj.append(k)
    if nj:
        fails.append(f"判断項目に根拠が無い: {' '.join(f'{k}={d[k]}' for k in nj)}"
                     f"（原本根拠が必須。憶測なら空欄にせよ＝絶対のルール2）")
    for k in nd:
        warns.append(f"{k}={d[k]} は規約の既定値（開示なし想定）。実測なら evidence を、"
                     f"非開示なら _meta.nulls.{k} に一行を書くこと")
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

        # --- 株数スケール誤り（株式分割をまたぐ）の署名（2026-07-29新設）--------
        # 実害: **KLACは2026-06-12の10:1分割をまたいでいた**。FY2025の申告株数(132百万株)は分割前、
        #   市場株価($170.19)は分割後で、基準の違う二つを割っていた。結果:
        #     per = 170.19 ÷ (純利益÷分割前株数=30.37) = 5.60  ← 帯8-200の**下**へ外れる
        #     shy = 純還元2.90 ÷ (分割前株数×株価=22.5十億$)  = 12.92% ← 帯−5〜12の**上**へ外れる
        #   **同じ株数誤りが per を下げ shy を上げる**——逆方向に同時に外れるのがこの事故の署名。
        #   当初これを「株価が誤っている」と誤診した（株価は正しかった）。二つが逆向きに外れたら
        #   疑うべきは株価でも純利益でもなく**株数のスケール**である。
        #   分割は eps・per・shy・mcap を同時に壊すので、1欄だけ直しても整合しない。
        per_v, shy_v = d.get("per"), d.get("shy")
        if isinstance(per_v, (int, float)) and isinstance(shy_v, (int, float)):
            if per_v < 8 and shy_v > 12:
                fails.append(f"per={per_v} が帯下・shy={shy_v}% が帯上へ**逆方向に同時に外れている**"
                             f"＝株数のスケール誤りの署名（株式分割をまたいだ疑い）。"
                             f"分割履歴を確認し eps/per/shy/mcap を同じ基準へ揃えよ")
            elif per_v > 200 and shy_v < 0:
                fails.append(f"per={per_v} が帯上・shy={shy_v}% が帯下へ逆方向に外れている"
                             f"＝株数を過大に取っている疑い（複数クラス株の二重計上など）")

        # --- per ≠ px/eps の恒等式検査（2026-07-30新設・門の全件点検の端末側の相方）-------------
        # 門(ブラウザ)側の ccfAudit は _meta を持てないので warn 止まり。ここは _meta が見えるので
        #   **基準の記録がある社を免除したうえで FAIL にできる**＝二層で守る設計の下半分。
        # 実測の教訓（2026-07-30・全317パック）:
        #   ・per=px÷eps は**この台帳では恒等式ではない**——eps欄の定義が TTM実績 と 通期実績 に割れている。
        #     ADBEはTTM(93.90)を格納し、MSFT/NVDA/DXC/TSM/SAPは「機械算出…（TTMではなく通期実績）」を格納。
        #   ・TSM/SAP は per の基準が原本根拠つきで確定済（ADRの通貨・株数比まで明記）＝**誤検出**だった。
        #     evidence.per に基準が書いてあれば免除する。
        #   ・書いていないのにズレる社は本物——GOOGL/ETN は通期epsから説明できずnull化、DXCは373%差。
        px_v, eps_v = d.get("px"), d.get("eps")
        if all(isinstance(x, (int, float)) for x in (px_v, eps_v, per_v)) and px_v > 0 and per_v > 0 and eps_v:
            dev = abs(px_v / eps_v - per_v) / per_v * 100
            if dev > 10:
                basis = str(((meta or {}).get("evidence") or {}).get("per") or "")
                if not any(w in basis for w in ("TTM", "ADR", "ADS", "通貨", "通期")):
                    fails.append(f"per={per_v} と px/eps={px_v/eps_v:.2f} が {dev:.0f}% ずれ、"
                                 f"_meta.evidence.per に基準の記録も無い"
                                 f"（perがTTM・epsが通期なら evidence.per にそう書く。ADRなら通貨と株数比も）")

        # --- _meta の型（2026-07-29新設）--------------------------------------
        # 実害: **91パックで _meta.kenshi が配列でなく文字列**だった。ASR様式は配列が正で、
        #   道具はどれも `meta.setdefault("kenshi", []).append(...)` で追記する。文字列だと
        #   そこで落ちる＝**その社だけ監査の記録が伸びなくなる**（本日 fix_acq5 で実際に落ちた）。
        #   値が壊れるのではなく「記録が静かに止まる」ので、採点を見ていても一生気づかない。
        for k, want in (("kenshi", list), ("evidence", dict), ("nulls", dict), ("provenance", dict)):
            v = meta.get(k)
            if v is not None and not isinstance(v, want):
                fails.append(f"_meta.{k} の型が {type(v).__name__}（正は {want.__name__}）"
                             f"——検死の追記がここで落ちるので記録が伸びなくなる")

        # --- 原本の鮮度（2026-07-29新設）------------------------------------
        # 実害を踏んだ: **DSGX は 2005年1月期の20-F で審査されていた**（21年前の書類）。
        #   採取器は「系列の最新年から2年遅れたら算出不能」という年検問を持つが、それは
        #   *機械値*にしか効かない。定性の判断（dom/irr/rep/dur/p/f）が**どの年の書類から
        #   読まれたか**は誰も見ていなかった——審査日(auditDate)は今日でも、読んだ紙が
        #   20年前ということが起こりうる。絶対のルール7(c)「保管された値も毎回検問する」の同型。
        rdate = str(meta.get("reportDate") or "")[:4]
        adate = str(meta.get("auditDate") or "")[:4]
        if rdate.isdigit() and adate.isdigit():
            lag = int(adate) - int(rdate)
            if lag >= 3:
                fails.append(f"原本が古すぎる: _meta.reportDate={meta.get('reportDate')} は "
                             f"審査日({meta.get('auditDate')})から{lag}年前の書類。"
                             f"定性判定を古い開示から読んでいる疑い＝原本を取り直して再審査せよ")
            elif lag == 2:
                warns.append(f"原本が2年前: _meta.reportDate={meta.get('reportDate')}。"
                             f"直近の年次報告が出ていないか確認せよ")

    # --- 日本株はJP規約（ROIC三点・TTM PER・gm粗利混入）も併せて ---
    if re.match(r"^\d{4,5}$", code):
        jf, jw = VJ.check(path)
        fails += [f"[JP] {x}" for x in jf]
        warns += [f"[JP] {x}" for x in jw]
    return fails, warns




def main():
    summary = "--summary" in sys.argv
    new_only = "--new" in sys.argv
    # --json [path]: FAIL を機械可読で吐く（第四の関門が読む・v9.9.95）。
    #   判定の正本はこの check() のまま＝門も score_all も再実装せずここの結論を読む（v9.9.65の掟）。
    #   出力先は**パスに見えるときだけ**次の語を採る。「--で始まらなければパス」と素朴に書くと
    #   `--json MSI` の MSI をパスと読む（実際に自分で踏んだ）。採ったパスは位置引数から外す。
    emit, emit_path_arg = None, None
    if "--json" in sys.argv:
        i = sys.argv.index("--json")
        nxt = sys.argv[i + 1] if len(sys.argv) > i + 1 else ""
        if nxt.endswith(".json") or "/" in nxt:
            emit = emit_path_arg = nxt
        else:
            emit = os.path.join("out", "validate_fail.json")
    args = [a for a in sys.argv[1:] if not a.startswith("--") and a != emit_path_arg]

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
    items = {}
    for p in paths:
        fails, warns = check(p)
        code = os.path.basename(p).split("_gate_pack")[0]
        nf += len(fails)
        nw += len(warns)
        if fails:
            bad += 1
            items[code] = {"n": len(fails), "fails": fails}
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

    if emit:
        # 全パックを検査したときだけ正本を書く。**部分実行で正本を潰さない**
        #   ——score_all.js が `--jp/--us` で out/score_all.json を約40行に縮めた事故
        #   （2026-08-04の全コード監査 A-系）と同型を、ここで先回りして塞ぐ。
        if args or new_only:
            print(f"（部分実行なので {emit} は書かない。全件で回すこと）")
        else:
            json.dump({"asof": str(date.today()),
                       "rule": "納品検査(validate_packs)のFAIL。第四の関門が読む",
                       "items": items},
                      open(emit, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            print(f"→ {emit} を更新（FAILを持つ {len(items)}社）")
            # **出力器として回したときは FAIL を終了コードにしない。**
            #   納品検査としての exit 1 は「この納品を差し戻す」という意味だが、
            #   全台帳の FAIL は既知の積み残し（283社）なので、そこで落とすと CI が常時赤
            #   ＝鳴りすぎる警報は鳴らないのと同じ。**落とす仕事は第四の関門が引き受けた**
            #   （投下可・次点に FAIL があれば audit_promotion_ready が落とす）。
            print(f"検査 {len(paths)}件 / 致命を持つパック {bad}件（FAIL {nf}件 / warn {nw}件）")
            return 0

    print(f"\n検査 {len(paths)}件 / 致命を持つパック {bad}件（FAIL {nf}件 / warn {nw}件）")
    if bad:
        print("致命ありは納品不可＝審査官へ差し戻す。"
              "既存台帳の一括是正は night/audit_evidence.py の作業リストで進めること")
    return 1 if nf else 0


if __name__ == "__main__":
    sys.exit(main())
