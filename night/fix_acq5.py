#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/fix_acq5.py — acq5（直近5年に大型買収があったか）の不正値を、のれん系列から機械で確定する（2026-07-29新設）

■ 何が起きていたか
  acq5 は yes/no の列挙なのに、**全317パック中38社に数値が入っていた**（2.8 / 9.1 / 50.5 / 2411.6 …）。
  門はこう書いている:
      const acq5 = ($('acq5') && $('acq5').value) ? $('acq5').value : 'yes';
      if (roicg && roicGap > 15) {
        if (acq5 === 'no') …減点免除（遺産のれん）
        else { amberPen += 6; …「のれん込みROIC乖離——買収規律に疑義 −6」 }
      }
  **文字列の完全一致でしか免除されない**ので、数値が入っている社は自動的に −6 を食う。
  実測: 38社のうち roic−roicg>15pt で罰が実際に効いていたのは **9社**
        （RMD / ADBE / MSA / INTU / PAYX / EME / HALO / AMBI / CLMB）。
  ADBE は原本で確認したところ 5年でのれん +1.5%・Business Combination注記なし・Semrush は未完了＝**no** が正しく、
  是正で Ω 75.2 → **81.2**（ティアが堅実→最上位に変わり目標ウェイトが5%→8%になる帯）。
  門のソース自身が『遺産のれん——減点免除（Visa/**Adobe**型の誤爆防止・v9.1）』と名指ししている、
  まさにその誤爆を、データ型の不一致で踏んでいた。

■ なぜ機械で決めてよいか（絶対のルール2との関係）
  acq5 は「定性の判断」ではなく**貸借対照表から直接読める事実**——大型買収をすれば、のれんが増える。
  だから dom/irr/rep/dur/moatW（原本の記述を読む項目）とは扱いが違い、roiic と同じ機械項目として
  式と実額つきで刻んでよい（_meta.provenance="machine"）。判定規則は下の JUDGE を見よ。
  **迷う帯は空欄に倒す**——空欄だと門は既定の 'yes'（＝罰あり）で裁くので、保守側に転ぶ。

■ 判定規則（「今のれんの何割が直近5年に入ってきたか」）
  門が acq5 を見る目的は一つだけ——**roic と roicg の乖離を作っているのれんが「今の経営の買収」か
  「昔の遺産」か**を分けること。だから測るべきは増加率そのものではなく、**直近ののれん残高のうち
  5年以内に増えた分の割合**である。
      新しさ = (のれん_直近 − のれん_5年前) ÷ のれん_直近
  yes : 新しさ ≥ 30%（今あるのれんの3分の1以上が直近5年に入った＝現経営陣の買収）
  no  : 新しさ < 10%（ほぼ全部が遺産のれん）
  空欄: その間（10〜30%）／のれん系列が2年ぶんも取れない → 理由を _meta.nulls.acq5 に書き審査官へ

  **単純な増加率で測ってはいけない**（最初この誤りを踏んだ）:
    ・DXCM は5年変化+25%と出るが、のれんは 0.02→0.03→0.02十億$ ＝ 2千万$規模の揺れで買収ではない
    ・TRN は「最大の単年増+27%」だが、実体は 0.21→0.15→0.22 の**減損からの戻り**であって買収ではない
    ・CLMB/ISSC/MPWR も残高が数千万$しかなく、率だけ見ると必ず跳ねる
  「新しさ」で測ると DXCM≈0% / TRN 4.5% で正しく no に落ち、INTU 88% / ULTA 96% は yes に残る。

使い方:
  python3 night/fix_acq5.py              判定だけ表示（書き換えない）
  python3 night/fix_acq5.py --write      不正値の社だけ書き換える（yes/no が既に入っている社は触らない）
  python3 night/fix_acq5.py --all        既に yes/no が入っている社も判定を突き合わせて表示（検算用・書き換えない）
  python3 night/fix_acq5.py --blank      **空欄の社も対象に含める**（--write と併用で充填。単独なら表示のみ）
  python3 night/fix_acq5.py --only A,B   銘柄を絞る

**--blank を後から足した理由（2026-08-03）**: 初版の対象は `bad = 値があって列挙外` だけで、
**空欄は一度も触っていなかった**。ところが門は空欄を SELECT 既定の 'yes' に化かすので、
空欄は「未測定」ではなく**『大型買収あり』と断定されたのと同じ扱い**——のれん込みROIC乖離 −6 が
黙って効く。不正値（数値が入っている）と空欄は、門から見れば**まったく同じ壊れ方**をしている。
実測: Ω72+ の警告39件のうち16件がこの空欄で、投下可の IRMD/NVDA/TSM を含んでいた。
判定不能（10〜30%の中間帯）の社は空欄のまま残し、理由を _meta.nulls.acq5 に書く＝保守側に倒す。

日本株（コード始まり）は EDINET 経路なので対象外。
"""
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.chdir(BASE)

import hachimon_fetch as H       # noqa: E402

OUT = os.path.join(BASE, "out")
# B19(2026-08-04): 'na' を外した。門のSELECTと validate_jp_packs.ENUMS は yes/no だけで、
#   'na' は取込時に既定 'yes' へ化けて罰が黙って効く＝この道具が直すべき不正値そのもの。
#   VALID に入れたままだと「validatorはFAIL・門は罰・fix_acq5は素通し」の三者バラバラになる。
VALID = {"yes", "no"}


def judge(gw, eq=None):
    """のれん系列 {year: value} → ('yes'/'no'/None, 理由の文)

    測るのは「増えたか」ではなく「**今あるのれんの何割が直近5年に入ってきたか**」。
    門が acq5 を使うのは roic−roicg の乖離を作るのれんの**出どころ**を分けるためだから。
    """
    ys = sorted(gw)[-6:]
    if not ys:
        return None, "のれん系列が取れない（タグ不在）"
    a, b = gw[ys[0]], gw[ys[-1]]
    if len(ys) < 2:
        return None, "のれん系列が2年ぶんも取れない（タグ不在）"
    ser = " → ".join(f"{y} {gw[y]/1e9:.2f}" for y in ys)
    if b <= 0:
        return "no", f"のれん残高(十億$) {ser}。直近ののれんが0＝乖離を作るのれんが無い → **no**"
    # 起点の補正（2026-07-29）: 5年窓の古い側で**のれんタグだけ無く自己資本タグはある**年は、
    #   のれん=0 と読む。米国会計基準ではのれんは金額があれば独立行で表示が要るので、
    #   「自己資本は報告しているのにのれん行が無い」は**当時のれんが無かった**ことを意味する。
    #   絶対のルール7「欠測をゼロと読むな」の例外にあたるので、根拠の文に必ず明示する。
    y0, a0, note0 = ys[0], a, ""
    if eq:
        older = [y for y in sorted(eq) if y < ys[0] and y >= ys[-1] - 5]
        if older:
            y0, a0 = older[0], 0.0
            note0 = (f"（起点は{y0}年＝当時**のれんの行が無く自己資本は報告されている**ので0と読む。"
                     f"のれんは金額があれば独立行の表示が要るため、行が無い＝当時のれんが無かった）")
    fresh = (b - a0) / b * 100
    base = (f"のれん残高(十億$) {ser}。**新しさ =(直近 {b/1e9:.2f} − {y0}年 {a0/1e9:.2f})÷直近 "
            f"= {fresh:+.1f}%**（今あるのれんのうち直近5年に増えた割合）{note0}")
    if fresh >= 30:
        return "yes", base + " → **大型買収あり=yes**（3分の1以上が直近5年＝現経営陣の買収）"
    if fresh < 10:
        return "no", base + " → **大型買収なし=no**（ほぼ全部が遺産のれん）"
    return None, base + " → 判定不能（10〜30%の中間帯）。原本の Business Combination 注記で確認せよ"


def main():
    write = "--write" in sys.argv
    show_all = "--all" in sys.argv
    do_blank = "--blank" in sys.argv
    only = set()
    if "--only" in sys.argv:
        only = {x.strip().upper() for x in sys.argv[sys.argv.index("--only") + 1].split(",") if x.strip()}
    scores = {}
    try:
        scores = {r["t"]: r for r in json.load(open(os.path.join(OUT, "score_all.json"), encoding="utf-8"))}
    except Exception:
        pass

    targets = []
    for f in sorted(os.listdir(OUT)):
        if not f.endswith("_gate_pack.json"):
            continue
        t = f.split("_gate_pack")[0]
        if t[0].isdigit():                      # 日本株はEDINET経路
            continue
        if only and t.upper() not in only:
            continue
        d = json.load(open(os.path.join(OUT, f), encoding="utf-8"))
        v = d.get("acq5")
        blank = v is None or str(v).strip() == ""
        # 門は空欄を SELECT 既定 'yes' に化かす＝不正値と同じく「罰が黙って効く」壊れ方
        bad = (not blank) and str(v) not in VALID
        if bad or (do_blank and blank) or show_all or only:
            targets.append((t, d, v, bad or (do_blank and blank)))

    print(f"対象 {len(targets)}社（書換対象 {sum(1 for x in targets if x[3])}社）\n")
    print(f"{'':7s} {'現値':>9s} {'判定':>5s} {'Ω':>6s}  根拠")
    n_fix = n_blank = n_same = 0
    for t, d, v, bad in targets:
        try:
            _f = H.facts_of(H.cik_of(t))
            gw = H.series(_f, H.TAGS["gw"])[0]
            eq = H.series(_f, H.TAGS["eq"])[0]
        except (Exception, SystemExit):
            print(f"{t:7s} {str(v):>9s} {'—':>5s} {'':>6s}  のれん取得失敗（SECにCIKまたはタグが無い＝手作業へ）")
            continue
        new, why = judge(gw, eq)
        s = scores.get(t, {}).get("s")
        print(f"{t:7s} {str(v):>9s} {str(new or '空欄'):>5s} {(s or 0):6.1f}  {why}")
        if not (write and bad):
            continue
        m = d.setdefault("_meta", {})
        was_blank = v is None or str(v).strip() == ""
        stamp = "2026-08-03" if was_blank else "2026-07-29"
        if new:
            d["acq5"] = new
            m.setdefault("evidence", {})["acq5"] = f"【{stamp} 機械判定】{why}（出典: SEC XBRL companyfacts の Goodwill 系列）"
            m.setdefault("provenance", {})["acq5"] = "machine"
            m.get("nulls", {}).pop("acq5", None)
            n_fix += 1
        else:
            d["acq5"] = None
            m.setdefault("nulls", {})["acq5"] = (
                f"【{stamp}】{why}" if was_blank else
                f"【{stamp}】旧値 {v!r} は yes/no 以外の不正値で棄却。{why}")
            m.setdefault("evidence", {}).pop("acq5", None)
            n_blank += 1
        cause = ("空欄だったが、門は SELECT 既定の 'yes' に化かすので**『大型買収あり』と断定されたのと同じ**"
                 if was_blank else
                 "列挙(yes/no)の欄に数値が入っており、門は文字列比較でしか読まない")
        line = (
            f"{stamp} acq5 {v!r} → {d['acq5']!r}。{cause}——"
            f"門は acq5==='no' でしか『のれん込みROIC乖離 −6』を免除しないため**罰が黙って効いていた**。"
            f"のれん系列から機械判定した（判定規則は night/fix_acq5.py）。")
        # B20(2026-08-04): kenshi が文字列のパック（記録済みの91パック事故）で setdefault().append が
        #   落ちると、その社だけ監査記録が静かに止まる。fill_roiic / backfill と同じ型ガードで追記する。
        k = m.get("kenshi")
        if isinstance(k, list):
            k.append(line)
        elif isinstance(k, str) and k:
            m["kenshi"] = k + "\n" + line
        else:
            m["kenshi"] = [line]
        json.dump(d, open(os.path.join(OUT, f"{t}_gate_pack.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)

    if write:
        print(f"\n→ yes/no を確定 {n_fix}社 / 判定不能で空欄化 {n_blank}社")
        print("  空欄は門が既定の 'yes'（＝罰あり）で裁く＝保守側。原本で埋め直す作業リストとして残る。")
        print("  書き換え後は `node night/score_all.js` で誰がどう動いたかを実測すること。")
    else:
        print("\n※--write で書き換える（yes/no が既に入っている社は触らない）。空欄も直すなら --blank を併用")
    return 0


if __name__ == "__main__":
    sys.exit(main())
