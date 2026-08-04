#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kessan_check_jp.py — 日本株の四半期点検（2026-07-29新設）

なぜ要るか:
  kessan_check.py / kessan_calendar.py はどちらも SEC 経由なので**日本株を一切点検できない**。
  監視リストには 3923/4071/6857/6920/9790 等の日本株が入っており、
  **四半期の異常検知が構造的に穴になっていた**（米国株だけ守られている状態）。

【現状の到達点（正直に書く）】
  ・**警報スキャンは機能する**。実測で 4071 の『のれん等の減損損失 1,154,121千円を計上』を拾えた
    （Ω81.4＝台帳最上位クラスの銘柄が買収子会社ののれんを減損していた）。
  ・**数値抽出(売上YoY・営業利益率差)は現状ほぼ機能しない。** 有報PDFはレイアウト都合で数値の桁が
    分断され、実測5社すべてで誤読した（6920: 売上251,477を70,248、営業利益122,843を1,228と読んだ）。
    そこで**パックのgm(審査済みの営業利益率)を錨に自己検算し、乖離が大きければ数値を破棄する**。
    5社とも破棄され、警報のみで判定している。**もっともらしい誤値を出すより空欄が正しい。**
    数値が要るなら XBRL(EDINET提出の財務諸表本体)を解く実装が別途要る——PDFのテキスト抽出では届かない。

【既知の限界（追いかけない）】
  ・当期と前期が**同じ文に同居する比較文**は切れない。実測6857『当連結会計年度のその他の損益は、
    のれん及び無形資産の一部減損損失21,393百万円を計上した前連結会計年度21,532百万円の損失から
    24,173百万円改善し』——これは前期の減損の話だが、正規表現では当期の計上と区別できない。
    人がスニペットを読めば1秒で分かるので、**ここは機械で追わない**。
    実測の到達点は5社中1件の偽陽性（着手前の米国版は28社中12件だった）。

やること（米国版と同じ枠組み・同じ判定）:
  ・EDINET直配信の四半期報告書/半期報告書PDFから 売上高・営業利益 を抜き、
    前年同期比の売上YoYと営業利益率の差(pt)を出す
  ・6砲台（誠/限/集/指針/減損/退任）に相当する日本語の警報語をスキャンする
  ・判定: 売上YoY<-5% / 営業利益率が前年同期比-3pt超の悪化 / 警報ヒット → 要審査

米国版から引き継いだ設計（同じ轍を踏まないため）:
  **「言葉の出現」ではなく「事象の発生」を見る。** 2026-07-29 の米国28社点検では
  「減損」が12社で発火し、中身は全て会計方針の定型文だった（『No impairment was recognized』
  という**減損が無かったと書いてある文**でも発火していた）。28社中12社が鳴る警報は鳴らないのと同じ。
  日本語の有報・短信はさらに定型文が多い（「〜する可能性があります」「〜のおそれがあります」）ので、
  否定・仮定・会計方針の3種を落としたうえで、金額を伴う警報は数字が無ければ落とす。
  落としたヒットは**判定に使わないが出力末尾に残す**（門番が効きすぎたときに気づけるように）。

原本の取り方:
  https://disclosure2dl.edinet-fsa.go.jp/searchdocument/pdf/{docID}.pdf  … 鍵なしで取れる（実証済み）
  ※docIDの選び方（2026-08-04是正・B15）: 環境変数 EDINET_API_KEY があれば EDINET API v2 の
    日付別一覧を過去100日走査し**最新の有報/四半期/半期報告書**を読む。鍵が無ければパックの
    _meta のdocID（＝審査時に読んだ古い書類）しか読めないため、**四半期点検として不成立**を
    明示して全社を要審査に倒す——古い書類の再走査から「異常なし」を出すのは偽の健全宣言。
    _meta にも無い銘柄は「原本未取得」として明示し、憶測で埋めない。

使い方:
  python3 kessan_check_jp.py            監視リストの日本株すべて
  python3 kessan_check_jp.py 6920 3923  指定のみ
出力: out/kessan/{code}_qcheck_jp.txt と画面のサマリー
"""
import json
import os
import re
import sys
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE)
OUTDIR = os.path.join("out", "kessan")
PDF = "https://disclosure2dl.edinet-fsa.go.jp/searchdocument/pdf/{}.pdf"
UA = {"User-Agent": "ccf-gate research fortis5280@gmail.com"}

# 6砲台の日本語版。米国版 kessan_check.py の ALERTS と一対一で対応させる
ALERTS = {
    # 「訂正報告書」を素で拾うと**臨時報告書の訂正**（子会社異動の届出訂正など、財務の誤りではない）
    #   まで鳴る（実測3923）。有価証券報告書/四半期報告書の訂正に限定する。
    "誠": [r"重要な不備が(?:発見|存在|判明)", r"内部統制.{0,20}有効でない",
          r"(?:有価証券|四半期|半期)報告書の訂正報告書", r"過年度.{0,10}(?:遡及)?修正(?:再表示)?"],
    "限": [r"特許.{0,10}(?:満了|失効)", r"独占.{0,10}(?:契約|販売権).{0,20}(?:終了|満了)", r"ライセンス.{0,10}終了"],
    "集": [r"主要な顧客", r"売上高.{0,10}[0-9]{1,2}[%％].{0,20}(?:占め|依存)", r"単一の(?:供給|仕入)"],
    "指針": [r"業績予想.{0,10}(?:修正|下方)", r"予想.{0,10}未定", r"通期.{0,10}下方修正"],
    "減損": [r"減損損失", r"のれん.{0,10}減損"],
    "退任": [r"代表取締役.{0,20}(?:辞任|退任)", r"社長.{0,10}(?:交代|退任)"],
}
# 「起きた」ではなく「起きうる/起きなかった」を落とす門番（米国版と同思想）
NEGATION = re.compile(r"計上して(?:い)?ない|認識して(?:い)?ない|該当(?:事項)?(?:は)?(?:あり|ござい)ません"
                      r"|(?:該当|重要な影響)(?:する事項)?(?:は)?ありません|発生して(?:い)?ません")
SUBJUNCTIVE = re.compile(r"可能性(?:が)?あり|おそれ(?:が)?あり|恐れ|懸念され|かもしれ|想定され(?:る|ます)"
                         # 「〜された場合には報告する」型の**条件節**。実測6857の内部統制の記述が
                         #   『重要な不備が発見された場合については、取締役会へ報告することとしており』で鳴っていた
                         r"|場合(?:に)?(?:は|つい|に)|された場合|た場合に|生じた場合|事由が生じ")
BOILERPLATE = re.compile(r"会計方針|重要な会計上の見積|リスク(?:要因|情報)|事業等のリスク"
                         r"|判断を要する|見積りの前提|将来.{0,6}変動"
                         # ガバナンス体制の説明（「〜することとしております」）は制度の記述であって事象ではない
                         r"|することとしており|体制を(?:整備|構築)|コーポレート・?ガバナンス"
                         r"|内部統制(?:システム|委員会)|監査等委員会|取締役会へ報告"
                         # 税効果注記の「差異の内訳」表に出る減損損失は率の内訳であって当期の計上ではない
                         r"|法定実効税率|負担率との間の差異|繰延税金(?:資産|負債)|税効果会計"
                         # 役員報酬のクローバック条項（実測6857『過誤による重要な過年度遡及修正の
                         #   発覚等一定の事由が生じた場合に…報酬につき将来分の減額』）は制度の記述
                         r"|報酬の返還|報酬につき|業績連動賞与|役員報酬"
                         # **前期の事象への言及**。日本語は後置修飾なので『…を計上した前連結会計年度』の形で出る
                         #   （実測6857: 前期ののれん減損21,393百万円を当期の比較として書いている）
                         r"|(?:計上|発生|認識)し(?:た|ました)?前(?:連結会計年度|年度|期|年同期)"
                         r"|前(?:連結会計)?年度に(?:計上|発生)|前年同期に(?:計上|発生)")
NEEDS_AMOUNT = {"減損", "指針"}
AMOUNT = re.compile(r"[0-9０-９][0-9０-９,，]*\s*(?:百万円|千円|億円|円|[%％])")


def http(url, timeout=90):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read()


# ── 新規提出の取得（2026-08-04是正・B15）──────────────────────────────────────
# 従来は docID を**パックの_meta（審査時に読んだ有報）から拾うだけ**だったため、四半期点検の
# たびに**同じ古いPDFを再走査して「異常なし」と印字**していた＝日本株の四半期点検が実質年1回。
# EDINET API v2（要購読キー・環境変数 EDINET_API_KEY）の日付別一覧を過去N日ぶん走査し、
# secCode→最新の 有報(120)/四半期報告書(140)/半期報告書(160) のdocIDを組む。
# 鍵が無ければ**取得不能を大声で言い、要審査に倒す**——古い書類からの「異常なし」は偽の健全宣言。
EDINET_LIST = "https://api.edinet-fsa.go.jp/api/v2/documents.json?date={}&type=2&Subscription-Key={}"


def edinet_recent_docs(days=100):
    """過去days日の提出一覧から {証券コード4桁: (docID, 提出日時, 書類名)} を返す。鍵なしはNone。"""
    key = os.environ.get("EDINET_API_KEY", "").strip()
    if not key:
        return None
    import time as _time
    from datetime import date as _d, timedelta as _td
    out = {}
    today = _d.today()
    for i in range(days):
        day = today - _td(days=i)
        try:
            j = json.loads(http(EDINET_LIST.format(day.isoformat(), key), timeout=30))
        except Exception:
            continue                      # 休日・一時失敗は飛ばす（他の日で拾える）
        for r in j.get("results", []) or []:
            if r.get("docTypeCode") not in ("120", "140", "160"):
                continue
            sec = (r.get("secCode") or "")[:4]   # EDINETのsecCodeは5桁(末尾0)
            doc = r.get("docID")
            sub = r.get("submitDateTime") or ""
            if sec and doc and (sec not in out or sub > out[sec][1]):
                out[sec] = (doc, sub, r.get("docDescription") or "")
        _time.sleep(0.1)                  # 礼儀
    return out


def pdf_text(doc_id):
    import pypdf, io as _io
    raw = http(PDF.format(doc_id))
    r = pypdf.PdfReader(_io.BytesIO(raw))
    t = "\n".join((p.extract_text() or "") for p in r.pages)
    # 有報PDFは版面の都合で語の途中に改行が入る（実測: 『前連結会計年\n度』『重要な不\n備』）。
    #   正規表現が語をまたげず門番がすり抜けるので、**走査前に空白を1つに畳む**。
    #   これは表記の正規化であって内容の改変ではない。
    return re.sub(r"[ \t\r\n\u3000]+", " ", t)


def is_real(cat, before, after):
    near = before[-200:] + " " + after[:200]
    if NEGATION.search(near):
        return False, "否定文（発生していない旨の記述）"
    if SUBJUNCTIVE.search(near):
        return False, "仮定法（起きうる、の記述であって起きた記述ではない）"
    if BOILERPLATE.search(near):
        return False, "会計方針・リスク要因の定型文"
    if cat in NEEDS_AMOUNT and not AMOUNT.search(near):
        return False, "金額・率の記載が近傍に無い"
    # 前期の事象を当期の比較として書いているだけの箇所を落とす。
    #   日本語は後置修飾なので『…減損損失21,393百万円を計上した前連結会計年度』の形で出る。
    #   近傍に「前(連結会計)年度/前年同期」があり、かつ「当(連結会計)年度/当期」が無ければ前期の話。
    if cat in NEEDS_AMOUNT:
        past = re.search(r"前(?:連結会計)?年度|前年同期|前期", near)
        now = re.search(r"当(?:連結会計)?年度|当期|当四半期|当第[０-９0-9一二三四]", near)
        if past and not now:
            return False, "前期の事象への言及（当期の計上ではない）"
    return True, ""


def scan(text, width=260, per=2):
    hits, dropped, cats = [], [], []
    for cat, pats in ALERTS.items():
        n = 0
        for p in pats:
            for m in re.finditer(p, text):
                if n >= per:
                    break
                frag = re.sub(r"\s+", " ", text[max(0, m.start() - width // 2):m.start() + width // 2])
                ok, why = is_real(cat, text[max(0, m.start() - 300):m.start()], text[m.end():m.end() + 300])
                if not ok:
                    dropped.append(f"[却下:{cat}|{why}] …{frag[:110]}…")
                    continue
                hits.append(f"[{cat}|{p}] …{frag}…")
                n += 1
        if n:
            cats.append(cat)
    return hits, dropped, cats


NUM = r"([△▲\-]?[0-9０-９][0-9０-９,，]*)"


def _f(x):
    x = x.translate(str.maketrans("０１２３４５６７８９，", "0123456789,")).replace(",", "")
    neg = x[0] in "△▲-"
    v = float(re.sub(r"[^0-9.]", "", x) or 0)
    return -v if neg else v


def pick(text, label):
    """『売上高 12,345 11,111』のように当期・前年同期が並ぶ行から2数を拾う。
    取れなければ None を返す——**推定はしない**（誤値より空欄）。"""
    for m in re.finditer(label + r"[^0-9０-９△▲\-]{0,40}" + NUM + r"[^0-9０-９△▲\-]{1,20}" + NUM, text):
        a, b = _f(m.group(1)), _f(m.group(2))
        if a and b:
            return a, b
    return None


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if args:
        codes = args
    else:
        k = json.load(open("kanshi_list.json", encoding="utf-8"))
        lst = k if isinstance(k, list) else (k.get("list") or [])
        codes = [t for t in lst if t[:1].isdigit()]
    if not codes:
        print("日本株が監視リストに無い")
        return 0
    os.makedirs(OUTDIR, exist_ok=True)
    print(f"=== 日本株 四半期点検 ({len(codes)}社) ===")
    # 2026-08-04是正(B15): まず新規提出を探す。鍵なしなら**点検不成立を明示**（下のstale_reason）
    recent = edinet_recent_docs()
    stale_reason = None
    if recent is None:
        stale_reason = ("新規提出の取得不能（EDINET鍵なし）＝この点検はパック採取時点の書類の"
                        "再走査であり四半期点検として不成立")
        print(f"⚠⚠ {stale_reason}")
        print("   （環境変数 EDINET_API_KEY を設定すれば直近提出の四半期/半期/有報を自動取得する。"
              "以下の走査結果は参考情報であり、全社を要審査として扱う）")
    for c in codes:
        pk = os.path.join("out", f"{c}_gate_pack.json")
        doc, doc_src = None, ""
        if recent and c in recent:
            doc, _sub, _desc = recent[c]
            doc_src = f"EDINET新規提出({_sub} {_desc})"
        if not doc and os.path.exists(pk):
            blob = open(pk, encoding="utf-8").read()
            # docIDは S + 7桁英数(例 S100WQ7F)の計8文字。**最新のものを採る**——_metaには
            # 過去期のdocIDも並ぶので、辞書順で最大＝最も新しい発行のものを選ぶ
            m = sorted(set(re.findall(r"S1[0-9A-Z]{6}\b", blob)))
            doc = m[-1] if m else None
            if doc:
                doc_src = ("パック採取時のdocID（鍵はあるが直近100日にこの社の新規提出なし）"
                           if recent is not None else "パック採取時のdocID（新規提出は未探索）")
        if not doc:
            print(f"  {c:<6} 原本未取得——EDINET新規提出にもパックの_metaにもdocIDが無い。手動で確認")
            continue
        try:
            t = pdf_text(doc)
        except Exception as e:
            print(f"  {c:<6} PDF取得不可({type(e).__name__})——手動確認へ")
            continue
        rev, op = pick(t, r"売上高"), pick(t, r"営業利益")
        # ── 自己検算（2026-07-29）────────────────────────────────────────────
        # 有報PDFの数値はレイアウト都合で桁が分断されることがあり（実測 6920:
        # 売上 251,477 を 70,248、営業利益 122,843 を 1,228 と誤読していた）、
        # 誤った YoY と営業利益率差を**もっともらしく**出してしまう。
        # そこで**パックの gm（営業利益率・審査済み）を錨にして自分を検算する**。
        # 乖離が大きければ抽出失敗とみなして数値を捨てる（誤値より空欄）。
        # 警報スキャンは本文テキストベースで別系統なので、数値が捨てられても機能する。
        anchor, bad = None, None
        try:
            anchor = float(json.load(open(pk, encoding="utf-8")).get("gm"))
        except Exception:
            anchor = None
        if rev and op and rev[0] and rev[1]:
            got, prev = op[0] / rev[0] * 100, op[1] / rev[1] * 100
            # 当期・前年同期の**両方**を錨と突き合わせる。片方だけだと、前年側が桁分断で
            # ほぼ0になったケース（実測 9790: 営業利益 7,263 / 19 と読み、営利差 +50.5pt という
            # ありえない値を出していた）を素通りさせる。
            if anchor is not None and abs(got - anchor) > 15:
                bad = (f"抽出した当期営業利益率 {got:.1f}% がパックの gm {anchor:.1f}% と "
                       f"{abs(got-anchor):.0f}pt 乖離")
            elif anchor is not None and abs(prev - anchor) > 20:
                bad = (f"抽出した前年同期営業利益率 {prev:.1f}% がパックの gm {anchor:.1f}% と "
                       f"{abs(prev-anchor):.0f}pt 乖離")
            elif abs(got - prev) > 15:
                # 営業利益率が1年で15pt動くのは実在しうるが極めて稀。まず誤読を疑う。
                bad = f"営業利益率が1年で {got-prev:+.1f}pt 動く抽出結果——桁分断の誤読を疑う"
            if bad:
                bad += "——PDFの桁分断による誤読と判断し数値を破棄（警報スキャンは別系統なので継続）"
                rev = op = None
        yoy = opd = None
        if rev and rev[1]:
            yoy = (rev[0] / rev[1] - 1) * 100
        if rev and op and rev[0] and rev[1]:
            opd = op[0] / rev[0] * 100 - op[1] / rev[1] * 100
        hits, dropped, cats = scan(t)
        flags = []
        if yoy is not None and yoy < -5:
            flags.append(f"売上YoY {yoy:.1f}%")
        if opd is not None and opd < -3:
            flags.append(f"営業利益率 {opd:.1f}pt")
        # 集(顧客集中)は毎期再掲される定型注記なので、米国版 kessan_check.py と同じく
        #   **前回点検に無かった新規出現**だけを警報化する（毎回鳴ると無視を学習する）
        prevf = os.path.join(OUTDIR, f"{c}_qcheck_jp.txt")
        prev_cats = set()
        if os.path.exists(prevf):
            prev_cats = set(re.findall(r"^\[(誠|限|集|指針|減損|退任)\|", open(prevf, encoding="utf-8").read(), re.M))
        for c2 in cats:
            if c2 == "集":
                if "集" not in prev_cats:
                    flags.append("警報:集(新規出現)")
            else:
                flags.append(f"警報:{c2}")
        # 2026-08-04是正(B15): 鍵なし＝古い書類の再走査からは**決して「異常なし」を出さない**。
        #   走査は参考として残すが、判定は要審査（点検不成立）へ倒す
        if stale_reason:
            flags.insert(0, f"点検不成立——{stale_reason}")
        verdict = "要審査: " + " / ".join(flags) if flags else "異常なし(機械判定)"
        if bad:
            verdict += "  ※数値は自己検算で破棄（警報のみで判定）"
        print(f"  {c:<6} YoY {('%.1f%%' % yoy) if yoy is not None else '  na':>7}"
              f"  営利差 {('%.1fpt' % opd) if opd is not None else ' na':>7}  → {verdict}")
        body = (f"{c}  docID={doc}（{doc_src}）  原本=EDINET直配信 {PDF.format(doc)}\n"
                + (f"【自己検算で数値を破棄】{bad}\n" if bad else "")
                + f"売上高(当期/前年同期)={rev}  営業利益={op}\n"
                f"売上YoY: {yoy}  営業利益率差: {opd}\n判定: {verdict}\n\n"
                "=== 警報スニペット ===\n" + "\n".join(hits) +
                "\n\n=== 定型文として却下したヒット（判定には使わない・目視用） ===\n" + "\n".join(dropped[:12]))
        open(os.path.join(OUTDIR, f"{c}_qcheck_jp.txt"), "w", encoding="utf-8").write(body)
    print("\n※数値が na の社は原本の表形式が拾えなかった＝**推定はしていない**。手動で確認すること。")
    print("  要審査は門の依頼文ボタンで門2再審査へ。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
