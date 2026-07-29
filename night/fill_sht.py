#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/fill_sht.py — sht（シェア趨勢）を同業比の売上成長から機械で出す（2026-07-29新設）

■ なぜ要るか
  night/audit_deadweight.py の実測で、**sht が全317社で空欄**だと判った。SELECTの既定 'flat' に
  化けるので、sht を使う**5つの規則がまるごと不発**になっていた:
    1. pm += {up:+3, flat:0, down:-10}[sht]          → 全社+0（MOAT柱の調整が効かない）
    2. indG='below' ∧ sht='up' → 地味業界の勝者 +2   → 一度も成立せず
    3. gmt='down' ∧ sht='down' → **Intel警報**       → 一度も成立せず
    4. S2売却規律「堀の軌道反転(粗利×シェア同時低下)」 → 一度も発火せず
    5. S2「ROIC×(粗利orシェア)同時劣化」             → shtの側だけ死んでいる
  Intel警報は「20年で崩れた堀」の実例から作った先行検出なのに、一度も鳴っていなかった。

  原因は一貫性の欠落だった——**トレンド3兄弟のうち gmt(営業利益率) と roict(ROIC) は採取器が
  機械で出しているのに、sht だけ出していない**。だから審査官が手で埋めるしかなく、誰も埋めなかった。

■ どう出すか（シェアの定義そのものから）
  シェア = 自社売上 ÷ 市場売上。よって
      シェアの変化 = ((1+自社CAGR) ÷ (1+市場CAGR))^5 − 1
  市場CAGRの代理として **同一SIC(4桁)の米国提出会社の売上5年CAGRの中央値** を使う。
  母集団は gate0_all.csv（全上場2,902社の sales_cagr5）、SICは SEC submissions API（out/_sic_cache.json）。

  **報告通貨を揃える**（2026-07-29に一度踏んだ）: 名目売上成長は現地インフレを含むので、
  ペソ・レアル建ての会社をドル建ての同業中央値と比べると**インフレをシェア獲得と読む**。
  初回実行では CEPU(ARS・名目+60.2%) や ASAIY(BRL) が 'up' に混ざった。
  → 母集団も対象も **USD報告のみ**に限る（他通貨は空欄＝門は既定'flat'で裁く）。
  ハイパーインフレ国のIAS29適用会社は審査プロトコルでも別扱いなので、同じ思想。

  刻み（門の罰が非対称〔up +3 / down −10〕なので、判定も非対称に厳しくする）:
    down : 5年でシェアが **−20%以上**（相対）縮んだ
    up   : 5年でシェアが **+25%以上**（相対）伸びた。**ただし acq5='yes' なら up にしない**
           ——買って得たシェアと勝ち取ったシェアを売上高からは区別できないため（'down'側は影響しない）
    空欄 : その間／同業が8社未満／自社CAGRが取れない → 門は既定'flat'で裁く＝現状と同じ

■ これは「定性の憶測」ではない（絶対のルール2との関係）
  sht は dom/irr/rep/dur/moatW/p1-4/f1-5 のような**原本の記述を読む項目ではない**。
  gmt/roict と同じ、原本の数値系列から出す**トレンド項**である。ただし
  **これは実シェアの開示ではなく代理指標**なので、根拠に必ずそう明示し、
  自社CAGR・同業中央値・同業社数・SIC名を実額で残す（provenance="machine"）。
  原本にシェアの実開示がある社は、審査官がそれで上書きしてよい（その場合は evidence を差し替える）。

■ 初回実測（2026-07-29・280社を判定 → down 12社 / up 35社 / 空欄 233社）
  ・**Intel警報（gmt='down' ∧ sht='down'）が初めて鳴った: 4社**
      CHKP（自社CAGR 5.9% vs 同業13.2%・erosion=active・moatdecay=yes）
      LSTR（−7.7% vs 1.1%）／ PZZA（−0.2% vs 11.3%）／ RMR（−25.9% vs 5.2%）
    4社とも既に Ω12-26・出口=s1 で門は別経路でも落としていたが、**「堀崩壊の先行パターン」という
    診断名が初めて付いた**。いずれも保有・監視には居ないので売却判断は動かない。
  ・down 12社はいずれもΩ7-57＝もともと75に遠く、買付判断は動かない（台帳が正しくなっただけ）。
  ・**up 35社のうち3社（HUBB/GRND/LRN）は出口が s1 → hold に変わった。**
    pm+3 で MOAT柱が70の線を越えたため＝**測っていないことで偽の売却シグナルが立っていた**。
    'flat' の既定値は中立ではない（柱に70の崖があるので、測らないほど不利に転ぶ）。
    3社とも非保有なので実害は無かったが、保有銘柄で同じことが起きたら誤って売る。
  ・保有・投下可への影響は NVDA のみ（Ω77.3→77.8）。Ω75線をまたぐ社は無く、投下可は7社で不変。
  ・残る死んだ規則は3つ（gls文化調整・nrr<100・rak='no'）。gls/nrr は入力がほぼ空欄、
    rak は全社通過中なので保険として正常。

■ 使い方
  python3 night/fill_sht.py            判定だけ表示（書き換えない）
  python3 night/fill_sht.py --impact   門そのものを回して「誰がどう動くか」を実測（書き換えない）
  python3 night/fill_sht.py --write    パックへ書き込む（空欄と判定した社は触らない）
  日本株（コード始まり）は母集団がSEC側に無いので対象外。
"""
import csv
import json
import os
import statistics
import subprocess
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
OUT = os.path.join(BASE, "out")
SIC_CACHE = os.path.join(OUT, "_sic_cache.json")

MIN_PEERS = 8         # 同業がこれ未満なら中央値が中央値にならない
UP_GAIN = 0.25        # 5年でシェア+25%以上 → up
DOWN_LOSS = -0.20     # 5年でシェア−20%以上 → down


def pct(v):
    """gate0_all.csv の成長率は**小数**（0.1479 = 14.79%）。百分率と取り違えると
    全社が判定帯（−20%〜+25%）へ潰れて 0社になる——実際に一度踏んだ。
    絶対のルール7の同族（単位を確かめずに前提を置く）なので、**帯で検問して**変換する。"""
    x = float(v)
    if -2.0 < x < 3.0:          # 小数表記（-200%〜+300%）
        return x * 100.0
    return x                    # 既に百分率


def load_universe():
    """gate0_all.csv（全上場の売上5年CAGR）と SICキャッシュを突き合わせる"""
    if not os.path.exists(SIC_CACHE):
        sys.exit(f"{SIC_CACHE} が無い。先にSICキャッシュを作ること（SEC submissions API）")
    sic = json.load(open(SIC_CACHE, encoding="utf-8"))
    uni = []
    for r in csv.DictReader(open("gate0_all.csv", encoding="utf-8-sig")):
        t = (r.get("ticker") or "").upper()
        try:
            g = pct(r.get("sales_cagr5"))
        except (TypeError, ValueError):
            continue
        s = (sic.get(t) or {}).get("sic")
        # 報告通貨がUSD以外の社は母集団から外す（名目成長に現地インフレが乗るため）
        if (r.get("ccy") or "").upper() != "USD":
            continue
        if not s or not (-50 < g < 200):        # 常識帯の外は母集団から外す
            continue
        uni.append((t, str(s), g, (sic.get(t) or {}).get("desc") or ""))
    return sic, uni


def peer_stats(uni):
    """SIC(4桁)ごとの売上5年CAGR中央値。8社未満のSICは3桁へ丸めて救済する"""
    by4, by3 = {}, {}
    for t, s, g, d in uni:
        by4.setdefault(s, []).append(g)
        by3.setdefault(s[:3], []).append(g)
    return by4, by3


def judge(own, s, by4, by3, desc, acq5):
    """(sht, 根拠の文) を返す。判定できないときは (None, 理由)"""
    grp, lvl = by4.get(s, []), f"SIC{s}"
    if len(grp) < MIN_PEERS:
        grp, lvl = by3.get(s[:3], []), f"SIC{s[:3]}x（4桁では{len(by4.get(s,[]))}社しか無く3桁へ丸めた）"
    if len(grp) < MIN_PEERS:
        return None, f"同業が{len(grp)}社しか取れない（{MIN_PEERS}社未満では中央値が中央値にならない）"
    med = statistics.median(grp)
    if own <= -100 or med <= -100:
        return None, "成長率が常識帯の外"
    ratio = ((1 + own / 100) / (1 + med / 100)) ** 5 - 1
    base = (f"自社の売上5年CAGR **{own:.1f}%** / 同業（{lvl}「{desc}」・{len(grp)}社）の中央値 **{med:.1f}%**。"
            f"シェア = 自社売上 ÷ 市場売上 なので、5年のシェア変化 = ((1+{own:.1f}%)÷(1+{med:.1f}%))^5 − 1 = "
            f"**{ratio*100:+.1f}%**（相対）。出典: 売上系列=SEC XBRL / 母集団=gate0_all.csv 全上場の sales_cagr5 / "
            f"業種=SEC submissions の SIC。**これは実シェアの開示ではなく代理指標**（原本にシェアの実開示が"
            f"あればそちらを優先し、evidence を差し替えること）。")
    if ratio <= DOWN_LOSS:
        return "down", base + f" → 5年で{abs(DOWN_LOSS)*100:.0f}%以上縮んだ＝**down**"
    if ratio >= UP_GAIN:
        if acq5 == "yes":
            return None, base + (f" → +{UP_GAIN*100:.0f}%以上だが **acq5='yes'（直近5年に大型買収）**なので up にしない"
                                 f"——買って得たシェアと勝ち取ったシェアを売上高からは区別できない（保守側＝空欄）")
        return "up", base + f" → 5年で{UP_GAIN*100:.0f}%以上伸びた＝**up**"
    return None, base + f" → 判定帯（−{abs(DOWN_LOSS)*100:.0f}%〜+{UP_GAIN*100:.0f}%）の中＝空欄（門は既定'flat'で裁く）"


def collect():
    sic, uni = load_universe()
    med_all = statistics.median([g for _, _, g, _ in uni])
    if not (0.5 < med_all < 30):
        sys.exit(f"母集団の売上CAGR中央値が {med_all:.2f}% ＝常識帯の外。単位変換(pct)を疑え")
    by4, by3 = peer_stats(uni)
    own_cagr, ccy = {}, {}
    for r in csv.DictReader(open("gate0_all.csv", encoding="utf-8-sig")):
        t = (r.get("ticker") or "").upper()
        ccy[t] = (r.get("ccy") or "").upper()
        try:
            own_cagr[t] = pct(r.get("sales_cagr5"))
        except (TypeError, ValueError):
            pass
    res = []
    for fn in sorted(os.listdir(OUT)):
        if not fn.endswith("_gate_pack.json"):
            continue
        t = fn.split("_gate_pack")[0]
        if t[0].isdigit():
            continue                                   # 日本株は母集団がSECに無い
        d = json.load(open(os.path.join(OUT, fn), encoding="utf-8"))
        if d.get("sht") not in (None, ""):
            continue                                   # 既に入っている社は触らない
        s = (sic.get(t.upper()) or {}).get("sic")
        desc = (sic.get(t.upper()) or {}).get("desc") or ""
        own = own_cagr.get(t.upper())
        if own is None:
            own = d.get("cagr") if isinstance(d.get("cagr"), (int, float)) else None
        if own is None or not s:
            res.append((t, d, None, "自社CAGRまたはSICが取れない"))
            continue
        cu = ccy.get(t.upper())
        if cu and cu != "USD":
            res.append((t, d, None, f"報告通貨が{cu}＝ドル建ての同業中央値と比べられない"
                                    f"（名目成長に現地インフレが乗る）。空欄＝門は既定'flat'で裁く"))
            continue
        v, why = judge(own, str(s), by4, by3, desc, d.get("acq5"))
        res.append((t, d, v, why))
    return res


def main():
    res = collect()
    ups = [x for x in res if x[2] == "up"]
    dns = [x for x in res if x[2] == "down"]
    print(f"対象 {len(res)}社 → **down {len(dns)}社 / up {len(ups)}社 / 空欄 {len(res)-len(ups)-len(dns)}社**\n")
    for lab, grp in (("down（pm−10・Intel警報・S2の入力になる）", dns), ("up（pm+3）", ups)):
        print(f"■ {lab}")
        for t, d, v, why in sorted(grp):
            head = why.split("。")[0]
            print(f"   {t:7s} {head}")
        print()

    if "--impact" in sys.argv:
        payload = {t: v for t, d, v, why in res if v}
        js = ("const {scorePack}=require('%s/night/score_all.js');const fs=require('fs');"
              "const P=%s;const out=[];"
              "for(const t of Object.keys(P)){const d=JSON.parse(fs.readFileSync('out/'+t+'_gate_pack.json','utf8'));"
              "const a=scorePack(d), b=scorePack({...d,sht:P[t]});"
              "out.push([t,+a.evalScore,+b.evalScore,(a.exit&&a.exit.level),(b.exit&&b.exit.level),a.act,b.act]);}"
              "console.log(JSON.stringify(out));" % (BASE, json.dumps(payload)))
        r = subprocess.run(["node", "-e", js], capture_output=True, text=True, cwd=BASE)
        try:
            rows = json.loads(r.stdout.strip().splitlines()[-1])
        except Exception:
            print("実測に失敗:", (r.stderr or "")[-400:])
            return 1
        print("■ 門そのものを回した実測（shtを入れると誰がどう動くか）")
        print(f"{'':7s}{'現Ω':>7s}{'sht後':>7s}{'差':>7s}  出口 / 間")
        for t, a, b, ea, eb, aa, ab in sorted(rows, key=lambda x: x[2]-x[1]):
            ch = []
            if ea != eb:
                ch.append(f"**出口 {ea}→{eb}**")
            if aa != ab:
                ch.append(f"間 {aa}→{ab}")
            print(f"{t:7s}{a:7.1f}{b:7.1f}{b-a:+7.1f}  " + " / ".join(ch))
        return 0

    if "--write" not in sys.argv:
        print("※--impact で「誰がどう動くか」を実測 / --write でパックへ書き込む")
        return 0

    n = 0
    for t, d, v, why in res:
        if not v:
            continue
        m = d.setdefault("_meta", {})
        d["sht"] = v
        m.setdefault("evidence", {})["sht"] = f"【2026-07-29 機械算出】{why}"
        m.setdefault("provenance", {})["sht"] = "machine"
        m.setdefault("kenshi", []).append(
            f"2026-07-29 sht 空欄 → '{v}'。**全317社でshtが空欄**でSELECT既定'flat'に化けており、"
            "shtを使う5規則（pm±3/−10・地味業界の勝者+2・Intel警報・S2の2本）が一度も働いていなかった"
            "（night/audit_deadweight.py の実測）。gmt/roict と同じトレンド項なのに採取器が出していなかったのが原因。"
            "同業比の売上成長からシェア変化を算出して充填した（判定式は night/fill_sht.py）。")
        json.dump(d, open(os.path.join(OUT, f"{t}_gate_pack.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        n += 1
    print(f"→ {n}社に書き込んだ。`node night/score_all.js` で誰がどう動いたかを実測すること。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
