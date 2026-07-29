#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/audit_moat_gap.py — 堀のふるい(絶対MOAT指数70+)に**あと何が足りないか**を刻み単位で出す（2026-07-29新設）

audit_moat.py との違い:
  audit_moat は「根拠の質」を見る（測っているか）。こちらは「**あと一段上げれば通るか**」を見る。
  再監査は原本を読む重い作業なので、**読んでも合否が動かない社を先に外す**のがこの道具の仕事。

なぜ要るか（初回実測 2026-07-29・当時の関門は75）:
  Ω75+ は29社あるのに、三段関門（Ω75+ ∧ 門X4条件 ∧ 堀75+）を通るのは3社しかなかった。
  堀で止まっている19社を仕分けたところ、**原本を読む価値があるのは6社だけ**だった:
    ・門X4条件でも落ちている社（V/IDXX/SAP/CTAS/JKHY）は、堀が上がっても買えない
    ・市場データ未取得で門Xが評価不能の社（RELX/APH/KLAC/6146/RACE）は、先に market_fetch が要る
    ・単独昇格では届かない社（3922/RACE/5038/8136）は、一本読んでも合否が動かない
    ・必要なのが規約の**最上段**（irr100=唯一供給 / rep100=複製不能$10B級）だけの社は、到達が稀なので外す
  **残る社（Ω75+ ∧ 門X通過ずみ ∧ 堀だけが未達 ∧ 未読の本が残る）が、原本を読む価値のある全部**である。

刻みは規約の値しか許さない（ここが肝）:
  dom 50/70/85/100 ・ irr 50/70/85/100 ・ rep 35/60/80/100 ・ dur 55/75/85/100 ・ moatW 50/70/85/100
  「dom を 70→80 にすれば通る」という助言は**存在しない刻みなので実行不能**。
  中間値を提示すると、審査官が刻みを無視して数字を作る誘因になる（絶対のルール2の逆走）。

初回の作業リストを実際に原本まで追った結果（2026-07-29・★6社）:
  ★NVDA  dom は FY2026 10-K Item1 Competition 全文精査で開示なし＝空欄が正（既に再監査ずみ）。
         moatW=50 も報告セグメント実数(C&N 89.6%)で確定ずみ → **堀73.6 が実力**
  ★MA    irr 70→85 を検討。10-K の Franchise 節は確かに『setting standards and rules』『Participant Onboarding…
         meets the necessary prerequisites』『Operating Standards…required to uphold』と書くが、これは
         **新規参加者への入場要件**であって既存顧客の離脱を妨げる認証ではない。刻み85『認証・規格ロック』は
         顧客自身の工程が当社仕様で認定され代替品に替えると顧客側の再認定が要る型(航空部品・医療機器・
         半導体材料のプロセス認定)を指す → **70を維持**。moatW も Note22『All of the segment's activities are
         interrelated, and each activity is dependent upon and supportive of the other.』が独立堀を否定 → 70維持
  ★6857  irr 70→85 を検討。第84期有報**全193頁を抽出走査**したが、顧客の量産ライン認定の記述は一件も無い
         （『認証』2件=ISO27001と労働安全衛生／『認定』3件=自社グリーン製品自主基準）。旧根拠に書かれていた
         「顧客の量産ライン認定に紐づく」は**原本に無い文だった** → **70を維持**（根拠だけ原本の実記述へ差替）
  ★ADBE  irr 70→85・rep 60→80 を検討。10-K全文走査で**両方とも原本が逆を述べていた**——『certif』19件は
         すべて自社が取得する側／自社研修の受講認定で、顧客を認定する構造は無い。Item1 COMPETITION と
         Item1A が二度『new industry standards, evolving distribution and sales models, **limited barriers to entry**,
         short product life cycles』と書き、当社が規格の**受け手**であることを自認 → irr70・rep60を維持
  ★3923/4071  必要なのは irr 70→**100**(唯一供給) か rep 60→**100**(複製不能$10B級)＝最上段のみ。到達しない

  → **6社すべて据置。堀のふるいで止まっている19社は、測り漏れではなく実力どおり**だった。
     投下可が3社(IRMD/MSFT/TSM)しかないのは審査の手抜きの結果ではない、と原本で確認できた。
     この道具の値打ちは「上がる社を見つけたこと」ではなく、**原本を読む先を19→6社に絞り、
     読んだ結果が全部×だと確定させたこと**にある（次に堀を疑うときはここから再開すればよい）。

そして、その「全部×」が関門そのものの較正へつながった（v9.9.49・2026-07-29 ユーザー明示指示で 75→70）:
  6社とも実力どおりだと確定したうえで分布を見ると、**関門75は規約の刻みの空白の中にあった**——
  5本そろいの堀は 最上段96.0 / 2段目84.0 / **3段目68.4** / 最下段47.1 で、68.4と84.0の間に刻みが無い。
  実測の山も 70-74 が最大（59社）で 75-79 は22社へ落ちる＝**いちばん厚い山の肩を切っていた**。
  原因は重み上位2本の上段が業種によって届かないこと: irr は 70=149社/85=54社（85は顧客側の再認定を
  要する型なので決済網・SW・SaaSは定義上到達不可）、dom は 50=164社/85+=28社（85以上は原本内の
  数値開示が要る＝測っているのは堀でなく開示習慣）。70は「3段目そろい68.4のすぐ上」＝**全部が3段目
  ではない**という意味で、規約の刻みと対応が取れる。投下可は 3社→7社（+NVDA/MA/6857/ADBE）。

出力は作業リストであって有罪判決ではない。刻みを上げる根拠は原本にしか無い。

使い方:
  python3 night/audit_moat_gap.py          Ω75+ で堀が関門(CCF_MOAT_GATE)に届かない全社
  python3 night/audit_moat_gap.py --all    Ω・門Xを問わず堀が関門に届かない全社
  python3 night/audit_moat_gap.py --list   原本を読む価値のある社（コード列）だけ
"""
import json
import math
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "out")

# 正は index.html の ccfMoat（v9.9.36の5本重み）
W = {"dom": .25, "irr": .25, "rep": .20, "dur": .12, "moatW": .18}
# 正は index.html の SELECT／審査プロトコル。**規約に無い刻みは提示しない**
GRADES = {"dom": [50, 70, 85, 100], "irr": [50, 70, 85, 100], "rep": [35, 60, 80, 100],
          "dur": [55, 75, 85, 100], "moatW": [50, 70, 85, 100]}
# 正は index.html の CCF_MOAT_GATE（v9.9.49 で 75→70・2026-07-29 ユーザー明示指示）
PASS = 70.0


def num(v):
    if v is None:
        return None
    s = str(v).strip()
    if s == "":
        return None
    try:
        x = float(s)
    except ValueError:
        return None
    return None if x <= 0 else x


def moat_idx(d):
    """index.html の ccfMoat と同値（cultAdj -2 まで含める）。4本未満はNA。"""
    legs = [(k, num(d.get(k))) for k in W]
    legs = [(k, v) for k, v in legs if v is not None]
    if len(legs) < 4:
        return None
    sw = sum(W[k] for k, _ in legs)
    gls = num(d.get("gls"))
    cult = -2 if (gls is not None and gls <= 3.3
                  and (d.get("disrupt") or "settled") != "threat"
                  and (d.get("erosion") or "none") != "active") else 0
    g = math.exp(sum(W[k] / sw * math.log(max(min(96, v), 1)) for k, v in legs))
    return max(0.0, min(96.0, g + cult))


def main():
    show_all = "--all" in sys.argv
    list_only = "--list" in sys.argv
    sc = {r["t"]: r for r in json.load(open(os.path.join(OUT, "score_all.json"), encoding="utf-8"))}

    rows = []
    for t, r in sc.items():
        if r.get("moatOK") or r.get("moatNA"):
            continue
        if not show_all and r.get("s", 0) < 75:
            continue
        try:
            d = json.load(open(os.path.join(OUT, f"{t}_gate_pack.json"), encoding="utf-8"))
        except Exception:
            continue
        cur = moat_idx(d)
        if cur is None or cur >= PASS:
            continue
        # 各本を規約の刻みで一段ずつ上げたとき、単独で75に届くか
        # 既に原本まで追って据置と決めた本は「再監査ずみ」と印を付ける——付けないと、
        # この道具は同じ6社へ永久に送り返す（＝読んだ事実が台帳に残っているのに道具が知らない）。
        _m = d.get("_meta") or {}
        ev, nu = (_m.get("evidence") or {}), (_m.get("nulls") or {})
        def audited(k):   # 据置と決めた記録は evidence にも nulls にも残りうる
            return "再監査" in (str(ev.get(k, "")) + str(nu.get(k, "")))
        single, fresh = [], []
        for k in W:
            v = num(d.get(k))
            best = None
            for g in GRADES[k]:
                if v is not None and g <= v:
                    continue
                d2 = dict(d)
                d2[k] = g
                if (moat_idx(d2) or 0) >= PASS:
                    best = g
                    break
            if best is None:
                continue
            lab = f"{k} {('空欄' if v is None else int(v))}→{best}"
            top = (best == GRADES[k][-1])
            if top:
                lab += "(規約の最上段＝唯一供給/複製不能級。到達は稀)"
            if audited(k):
                lab += "(再監査ずみ・据置)"
            single.append(lab)
            # 未読の作業として残すのは「まだ読んでいない」かつ「最上段でない」本だけ。
            # 最上段(irr100=唯一供給 / rep100=複製不能$10B級)しか道が無い社を作業リストに残すと、
            # 原本を読む先が実質ゼロの社で毎回埋まる（3923/4071が実例）。
            if not audited(k) and not top:
                fresh.append(lab)
        # 全本を満点にしても届かないか（＝原本を読むだけ無駄）
        dmax = dict(d)
        for k in W:
            dmax[k] = GRADES[k][-1]
        hopeless = (moat_idx(dmax) or 0) < PASS
        rows.append((t, r, d, cur, single, hopeless, fresh))

    rows.sort(key=lambda x: -x[3])
    # 原本を読む価値がある＝Ω75+ ∧ 門X通過ずみ ∧ 単独昇格で届く
    # ★＝まだ原本を読んでいない本が残っている社だけ（読み終えた社は落とす）
    worth = [x for x in rows if x[1].get("s", 0) >= 75 and x[1].get("xPass") is True and x[5] is False and x[6]]
    if list_only:
        print(" ".join(t for t, *_ in worth))
        return 0

    print(f"堀のふるい(絶対MOAT指数≥{PASS:.0f})で止まっている{len(rows)}社\n")
    print(f"{'':7s} {'Ω':>5s} {'堀':>5s} {'門X':>6s}  規約の刻みで**単独昇格すれば通る**本 / 所見")
    for t, r, d, cur, single, hopeless, fresh in rows:
        xp = r.get("xPass")
        xs = "落選" if xp is False else ("未評価" if xp is None else f"通過{r.get('xEr')}%")
        if hopeless:
            note = f"**全本を満点にしても{PASS:.0f}に届かない＝原本を読んでも動かない**"
        elif not single:
            note = "単独昇格では届かない（複数本の同時昇格が要る）"
        else:
            note = " / ".join(single)
        mark = "★" if (t, r, d, cur, single, hopeless, fresh) in worth else "  "
        print(f"{mark}{t:5s} {r.get('s',0):5.1f} {cur:5.1f} {xs:>6s}  {note}")

    print(f"\n★ = **まだ原本を読んでいない社**（Ω75+ ∧ 門X通過ずみ ∧ 堀だけが未達 ∧ 単独昇格で届く ∧ 未再監査の本が残る）: {len(worth)}社")
    print("   " + (" ".join(t for t, *_ in worth) if worth else "なし"))
    nx = [t for t, r, *_ in rows if r.get("xPass") is None]
    if nx:
        print(f"\n門Xが未評価（市場データ未取得＝先に python market_fetch.py が要る）: {len(nx)}社")
        print("   " + " ".join(sorted(nx)))
    hp = [t for t, r, d, cur, s, h, fr in rows if h]
    if hp:
        print(f"\n刻みを最大にしても75に届かない（堀の再監査は無駄）: {len(hp)}社")
        print("   " + " ".join(sorted(hp)))
    print("\n※これは作業リストであって有罪判決ではない。刻みを上げる根拠は原本にしか無い（絶対のルール2）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
