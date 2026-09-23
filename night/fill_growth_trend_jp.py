#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/fill_growth_trend_jp.py — **日本株の成長の軌道 cagrT を、EDINET の有報PDF「主要な経営指標等の推移」から機械算出する**（2026-09-23新設）

発端（todo `cagrT_jp_gap`）:
  cagrT（v9.9.123 の減速の減点。−10ptから減点が始まり −30ptで最大−4）は night/fill_growth_trend.py が SEC XBRL から埋める。
  日本株68社は SEC の外なので全社空欄だった＝**空欄では罰が発火しない＝未測定が最良ケース**で、日本株が構造的に有利だった。
  2026-09-23 に有報PDFから38社を埋め、30社を理由つき空欄にした。この道具はその手順を、次の有報が来ても同じに回すためのもの。

【定義は発明しない——night/fill_growth_trend.py と同一】
  窓 = パックの会計年度 a（_meta.reportDate の年月）と、その前の5年＝a-5…a の6つの年次売上。
  A案(端点)   = CAGR(a-2→a, 2年) − CAGR(a-5→a-2, 3年)        ＝ night/retro_features2.py の accel
  B案(中央値) = 新2年のYoY（a-1・a）の中央値 − 前3年のYoY（a-4・a-3・a-2）の中央値（1年の暴落・反動に強い）
  **cagrT = max(A, B)**（両案が同意した分だけ罰する＝負の側で絶対値の小さいほう）。小数2桁で書く。

【原本と docID】
  ・最新の有報（FY a）の5年表 → a-4…a。本文は night/rebuild_src_cache_jp.py が作る out/_src_cache/{T}.txt を使う
  ・前年の有報（FY a-1）の5年表 → a-5。**重なる4年（a-4…a-1）が新旧で0.5%以内に一致**することを確かめる。
    前年の有報が無ければ a-5 を含むいちばん新しい有報で代える。**docID がパックに無ければ名指しで報告する**
    （EDINET の書類検索で探してパックの source に足すこと。**この道具は EDINET_DB MCP を呼ばない**）
  ・docID はパックに刻まれたもの（_meta.source・source_note・evidence・kenshi・nulls.cagrT の S100xxxx）だけ。
    表紙（【提出書類】＝有価証券報告書・【事業年度】・会社名/Eコード）で年度と会社を確かめてから使う
  ・PDF は rebuild_src_cache_jp.fetch_pdf で落とす（**User-Agent にメールアドレスを載せない・1.2秒以上の間隔**）。
    本文は out/_src_cache/_yuho/{docID}.json（.gitignore＝コミットしない）に置き、次からは落とさない

【基準の検問——窓の中で基準が変わるなら空欄（絶対のルール7: 二つの基準を黙って接がない）】
  SCOPE     連結の6年系列が作れない——連結の開始（連結の列が提出会社の列より短い・前年の表の連結が a-5 に届かない）・中断（連結欄の空欄）、
            5年表の連結欄を一部の年だけ提出会社の数値で埋めている（『連結経営指標等に代えて』『-単体-』）。
            **連結財務諸表を一度も作っていない会社は提出会社の6年系列でよい**。連結の範囲だけが問題の社には、提出会社の6年系列を参考値に出す
  FRAMEWORK 会計基準の枠組みが窓の中で変わる（日本基準・米国基準 → IFRS 等。5年表の別ブロックで検出）
  PERIOD    12か月でない期・決算月の変更が窓の中にある
  RECLASS   重なる年が新旧の有報で0.5%を超えて食い違う（組替え・遡及）。人が原本で読んで受け入れた例外だけ ACCEPT_OVERLAP に置く
  REV_*     **収益認識会計基準の適用年度が窓の中（a-5 より後）**なら、適用年度の有報の会計方針の変更を読む:
              影響なし（none）／軽微（immaterial）／損益への言及なし＝表示替え・経過措置だけ（silent）→ 同じ基準として受け入れる
              遡及適用（retro）→ 組み替えが a-5 まで届いていれば受け入れる（届かない・どこまでか分からない → REV_UNKNOWN・要判断）
              売上高の影響額が明記され（quantified）**同年度の売上高の0.5%以内** → 受け入れる
                （0.5% は night/fill_growth_trend.py の splice が二つの売上系列を同じと見なす許容差＝新しい定数ではない）
              0.5%を超える → **REV_IMPACT で空欄** ／ 適用年度の影響を有報で確かめられない（上場前の適用）→ **REV_UNKNOWN で空欄**
            適用年度が a-5 以前（2018年版の早期適用など）なら窓の6年はすべて新基準＝検問不要。
            **IFRS の連結は検問しない**（IFRS第15号の適用は2018年＝どの窓よりも前）
  事実（適用年度・影響の書き方・頁・原文）は**人が原本で読んだものを REV に置く**。REV に無い社は機械で抜き（auto）、
  機械の 'silent'（損益への言及が見つからない）は読み落としと区別できないので**要判断**として書かない。
  表の形で既に空欄と決まった社（SCOPE・FRAMEWORK・PERIOD・RECLASS）と IFRS の連結は、収益認識を読まない。

機械で読むときに踏んだ落とし穴（2026-09-23）:
  ・IFRS の5年表の『移行日』の列（『2022年4月1日』）は決算期ではない——決算年月として読むと、期間の変更と連結の空欄に化ける（6981）。
    **9552 のパックの空欄理由『決算年月も2023年10月→2024年9月と揃っていない（決算期の変更）』はこの読み違い**（2026-09-23 にパックを訂正済み）で、
    空欄は基準の枠組み（日本基準→IFRS）と連結の範囲（連結は第5期から）で成り立つ
  ・経営成績の分析の中の参照『…注記事項(会計方針の変更)(収益認識…)」をご参照ください』は会計方針の段落ではない（2222 p.14）
  ・日本基準の社も注記で IAS・IFRS に触れる（6367）——IFRS かは5年表の基準のブロックか、IFRS にしか無い行の名前
    （親会社の所有者に帰属する・親会社所有者帰属持分・税引前当期利益）で判る
  ・『期首の利益剰余金に与える影響は軽微』は損益の話ではない（3436）——軽微・影響なしは損益の語を含む文だけを数える
  ・見出しは『(会計方針の変更)(収益認識に関する会計基準等の適用)』だけでなく『(会計方針の変更)1収益認識…』（8035）
    『(会計方針の変更)収益認識に関する会計基準の適用』（4393）もある

⚠ **空欄は会社に有利**: 空欄では減点が発火しない（index.html CCF_BLANK の 'best'）。空欄の理由には参考値（採点に使わない）を書き、
  参考値が減点の入口 −10 を越える社は「空欄が有利に働く」と名指しする（2026-09-23 時点: 4431・2222・7373・6565）。
  空欄を埋めるか（単体系列を採る・基準をまたいだ系列を承知で採る）は人の判断であって、この道具は決めない。

書き方（--write）:
  ・値が変わる社だけ cagrT／_meta.evidence.cagrT／_meta.nulls.cagrT と日付つきの kenshi 1行を書き、_meta.provenance.cagrT='machine'
  ・**値が今のパックと同じ社は provenance.cagrT='machine' を足すだけ**（evidence・kenshi は書き換えない＝人が書いた検問の文を消さない）
  ・空欄の判定で、パックも空欄なら触らない（理由の差は一覧に出す）。パックに値があれば空欄にし理由を書く
  ・取得失敗・表が読めない・要判断は**書かない**（測れなかった≠無い。既にある値を消さない）

使い方:
  python3 night/fill_growth_trend_jp.py                    # 読むだけ: 社ごとの cagrT・A/B・基準の判定・パックとの差
  python3 night/fill_growth_trend_jp.py --only 3923,6146 -v
  python3 night/fill_growth_trend_jp.py --write
  --no-fetch    キャッシュにある本文だけで回す（PDF を落とさない）
  --audit-rev   REV の引用を原文と照合し、同じ有報を機械でも読んで結論が同じかを並べる（窓の中の有報を追加で読む）
                2026-09-23: 引用 45/45 が原文と一致（5570 は引用なし）・46社すべてで機械も同じ適用年度・書き方・金額・結論を読んだ
  --json PATH   結果を JSON で書き出す（既定では何もファイルに書かない）
"""
import datetime
import json
import os
import re
import statistics
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rebuild_src_cache_jp as R      # fetch_pdf / pdf_pages / cover_info / doc_ids を再利用（二重実装を作らない）

ROOT = R.ROOT
DOC_DIR = os.path.join(R.CACHE, '_yuho')      # 有報の本文（ページごと）。out/_src_cache/ の下＝.gitignore
TODAY = datetime.date.today().isoformat()
TOL = 0.005                                   # 0.5%（fill_growth_trend.splice の許容差と同じ）
UNIT = {'円': 1, '千円': 1e3, '百万円': 1e6}

# ── 人が原本で読んで確かめた「収益認識会計基準の適用」の事実（2026-09-23）──────────────────
#   道具はこれを**事実**として使い、窓の中かどうか・許容差の内かは毎回計算する（窓は年ごとに動くので判定は焼き付けない）。
#   fy=適用年度（会計年度の末日の年） kind: none / immaterial / silent / quantified（amount・unit）/ retro（retro_from 年まで遡及）/
#   early（2018年版の早期適用）/ unknown（適用年度の影響を有報で確かめられない）  doc・page・quote=原文（NFKC・空白なし・『…』で断片をつなぐ）
#   --audit-rev が quote を原文と照合し、同じ有報を機械でも読んで結論が同じかを並べる。
def _r(fy, kind, doc=None, page=None, quote='', **kw):
    return dict(fy=fy, kind=kind, doc=doc, page=page, quote=quote, **kw)


REV = {
    # ── 影響なしと明記（none）──
    '3939': _r(2022, 'none', 'S100PUK1', 65, 'この結果、当連結会計年度の損益に与える影響はありません'),
    '4732': _r(2022, 'none', 'S100OCIU', 65, 'また、収益認識会計基準等の適用による、連結財務諸表に与える影響はありません'),
    '5032': _r(2022, 'none', 'S100OTD2', 80, 'この結果、当事業年度の損益に与える影響はありません'),
    '6200': _r(2022, 'none', 'S100PTKM', 53, '当該会計方針の変更による連結財務諸表に与える影響はありません'),
    '3496': _r(2022, 'none', 'S100PUJU', 61, 'また、当該会計基準等の適用により当連結会計年度の連結財務諸表に与える影響はありません'),
    '5139': _r(2022, 'none', 'S100QIQS', 55, '当事業年度の繰越利益剰余金の当期首残高、当事業年度の損益に与える影響はありません'),
    '3984': _r(2022, 'none', 'S100P86Q', 48, 'この変更が、当事業年度の売上高、売上原価、売上総利益、販売費及び一般管理費、営業利益、経常利益及び'
                                            '税引前当期純利益並びに1株当たり情報に与える影響はありません'),
    '2303': _r(2022, 'none', 'S100P2WK', 49, 'この結果、当事業年度の損益及び期首利益剰余金に与える影響はありません'),
    '3064': _r(2022, 'none', 'S100QHPG', 46, 'また、収益認識会計基準等の適用による損益に与える影響はありません'),
    '4393': _r(2022, 'none', 'S100PW7J', 57, '当連結会計年度の期首の利益剰余金及び損益に与える影響はありません'),
    '7747': _r(2022, 'none', 'S100P9GU', 69, 'この結果、当連結会計年度の売上高および営業利益に与える影響はありません'),
    '6954': _r(2022, 'none', 'S100O9SD', 52, '当該会計基準の適用が連結財務諸表に及ぼす影響はありません'),
    '3901': _r(2022, 'none', 'S100QG42', 53, '当連結会計年度の損益及び利益剰余金期首残高に与える影響はありません'),
    # ── 軽微と明記（immaterial）──
    '9697': _r(2022, 'immaterial', 'S100OF9W', 66, 'この結果、当連結会計年度において、連結財務諸表に与える影響は軽微であります'),
    '4063': _r(2022, 'immaterial', 'S100OLVL', 78, '収益認識会計基準等の適用が当連結会計年度の売上高、売上総利益、営業利益、経常利益、'
                                                  '税金等調整前当期純利益及び1株当たり情報に与える影響は軽微です',
               note='提出会社の売上高は321,985百万円減少（p.122）だが連結では消去される取引'),
    '6367': _r(2022, 'immaterial', 'S100OG1V', 72, 'この結果、当連結会計年度の連結財務諸表に与える影響は軽微であります'),
    '6861': _r(2023, 'immaterial', 'S100QY7Y', 40, 'この結果、当該会計基準の適用が当連結会計年度の連結財務諸表に与える影響は軽微であります'),
    '6273': _r(2022, 'immaterial', 'S100OK2Y', 50, 'この結果、当該会計基準の適用が連結財務諸表に与える影響は軽微であります'),
    '4661': _r(2022, 'immaterial', 'S100OI12', 70, 'この変更が連結財務諸表及び1株当たり情報に与える影響は軽微であります'),
    '3436': _r(2021, 'immaterial', 'S100NPKM', 63, 'なお、当連結会計年度において、当期連結財務諸表に与える損益影響は軽微であります',
               note='2018年版の早期適用'),
    # ── 損益への言及なし＝表示替えと経過措置だけ（silent・人が読んで確かめた）──
    '3923': _r(2022, 'silent', 'S100OHBV', 53, '前連結会計年度の連結貸借対照表において、「流動負債」に表示していた「前受金」は、'
                                             '当連結会計年度より「契約負債」に含めて表示しております',
               note='重要な影響があれば注記が要る＝記載なし＝重要性なしと読んだ'),
    # ── 遡及適用（retro）・窓の前に適用（early）──
    '4828': _r(2022, 'retro', 'S100OC4W', 46, '当該会計方針の変更は、原則として遡及適用され、前連結会計年度については遡及適用後の連結財務諸表となっております',
               retro_from=2021),
    '6146': _r(2020, 'early', 'S100OJ7R', 2, '(企業会計基準第29号2018年3月30日)…を第81期の期首から適用しており、その累積的影響額を期首の利益剰余金に加減しております'),
    '6920': _r(2020, 'early', 'S100MI7Y', 51, 'なお、「収益認識に関する会計基準」(2018年3月30日)等については前連結会計年度の期首から適用しており'),
    '4967': _r(2020, 'early', 'S100NR6F', 2, 'を第103期の期首より適用しており…第100期及び第101期の売上高についても遡及修正した数値となっております',
               retro_from=2017),
    # ── 売上高への影響額の明記（quantified）──
    '4776': _r(2022, 'quantified', 'S100QFC3', 49, '当連結会計年度の連結損益計算書において、売上高は58百万円増加し', amount=58, unit='百万円'),
    '6777': _r(2022, 'quantified', 'S100OL8Z', 46, '当連結会計年度の連結損益計算書は、売上高は16,989千円減少し', amount=-16989, unit='千円'),
    '2477': _r(2022, 'quantified', 'S100P7UU', 41, 'この結果、当事業年度の売上高、営業利益、経常利益及び税引前当期純利益はそれぞれ470千円減少しており',
               amount=-470, unit='千円'),
    '7730': _r(2022, 'quantified', 'S100PO97', 53, 'この結果、当連結会計年度の売上高については43百万円減少しておりますが', amount=-43, unit='百万円'),
    '8136': _r(2022, 'quantified', 'S100OFCY', 57, '当連結会計年度の連結損益計算書は、売上高は446百万円減少し', amount=-446, unit='百万円'),
    '9790': _r(2022, 'quantified', 'S100ODXJ', 43, '当連結会計年度の連結損益計算書は、売上高は135百万円減少し', amount=-135, unit='百万円'),
    '3092': _r(2022, 'quantified', 'S100O8T2', 71, '当連結会計年度の連結損益計算書は、売上高は3,934百万円減少', amount=-3934, unit='百万円'),
    '5132': _r(2022, 'quantified', 'S100Q0S6', 69, 'この結果、当事業年度の売上高は7,487千円減少', amount=-7487, unit='千円'),
    '3763': _r(2022, 'quantified', 'S100OCJX', 48, '当連結会計年度の連結損益計算書は、売上高は44百万円減少し', amount=-44, unit='百万円'),
    '2222': _r(2022, 'quantified', 'S100OETK', 50, '上記等の結果、当連結会計年度の売上高は1,131,195千円増加し', amount=1131195, unit='千円'),
    '4684': _r(2022, 'quantified', 'S100OF9D', 43, 'この結果、当連結会計年度の売上高は28億79百万円減少し', amount=-2879, unit='百万円'),
    '3798': _r(2022, 'quantified', 'S100OGPU', 57, '当連結会計年度の連結損益計算書は、売上高は122,172千円減少し', amount=-122172, unit='千円'),
    '7373': _r(2022, 'quantified', 'S100PQ0U', 62, 'この結果、当連結会計年度の売上高は66,197千円減少し', amount=-66197, unit='千円'),
    '3649': _r(2022, 'quantified', 'S100QGXP', 45, 'この結果、当連結会計年度の売上高は216,572千円増加し', amount=216572, unit='千円'),
    '8035': _r(2022, 'quantified', 'S100OA3X', 82, '当連結会計年度の連結損益計算書は、売上高が195,058百万円増加し', amount=195058, unit='百万円',
               note='p.117 のセグメント情報の半導体製造装置 +188,757百万円・FPD製造装置 +6,301百万円の合計と一致'),
    '4262': _r(2022, 'quantified', 'S100O9WK', 55, 'この結果、当連結会計年度の売上高および売上原価が30,537千円減少しておりますが', amount=-30537, unit='千円'),
    '6565': _r(2022, 'quantified', 'S100OHSP', 43, 'この結果、当事業年度の売上高は54,299千円、売上原価は53,809千円、販売費及び一般管理費は490千円それぞれ減少しておりますが',
               amount=-54299, unit='千円'),
    '2815': _r(2022, 'quantified', 'S100OBJI', 45, '当連結会計年度の売上高は869,399千円減少し', amount=-869399, unit='千円'),
    # ── 適用年度の影響を有報で確かめられない（unknown）──
    '5038': _r(2021, 'unknown', 'S100QGK5', 3, '「収益認識に関する会計基準」(企業会計基準第29号2020年3月31日)等を第10期の期首から適用しており',
               note='第10期＝FY2021/12 は上場（2022年9月）前の年度で、その年度の有報が無い'),
    '5582': _r(2022, 'unknown', 'S100WQ2M', 2, '「収益認識に関する会計基準」(企業会計基準第29号2020年3月31日)等を第13期の期首から適用しており',
               note='第13期＝FY2022/6 は上場前の年度で、その年度の有報が無い'),
    '5570': _r(2022, 'unknown', note='強制適用の最初の年度 FY2022/9 は上場前。上場後の有報3冊（S100SIYK・S100V07B・S100XC8W）のどれにも'
                                     '適用年度・影響額の記載が無い'),
}

# 重なる年の食い違いを人が原本で読んで受け入れた例外（{T: {年: 理由}}）
ACCEPT_OVERLAP = {
    '7378': {2024: '最新の有報で FY2024/10 を継続事業へ組替え（株式会社ヒトタスの人材派遣事業を非継続事業へ・S100XHO2 p.2 の注記6）。'
                   '同事業は2023年11月＝FY2024/10 に始まった（S100SOLV の沿革）ので FY2023/10 以前には元から含まれない'
                   '＝組替え後の値で6年の範囲が揃う'},
}


def nf(s):
    return unicodedata.normalize('NFKC', s or '')


def squash(s):
    return re.sub(r'\s+', '', nf(s))


# ══ 本文の取得 ══════════════════════════════════════════════════════════════════
def _latest_from_cache(t):
    """rebuild_src_cache_jp が作った最新の有報の本文を、ページに戻して返す（src.json のページ開始位置で割る）。"""
    sp, tp = os.path.join(R.CACHE, f'{t}.src.json'), os.path.join(R.CACHE, f'{t}.txt')
    if not (os.path.exists(sp) and os.path.exists(tp)):
        return None
    m = json.load(open(sp, encoding='utf-8'))
    txt = open(tp, encoding='utf-8').read()
    offs = list(m.get('page_offsets') or []) + [len(txt) + 1]
    pages = [txt[offs[i]:offs[i + 1] - 1] for i in range(len(offs) - 1)]
    cov = {k: m.get(k) for k in ('kind', 'fy', 'fy_end', 'company', 'ecode')}
    return {'docID': m['docID'], 'cover': cov, 'pages': pages}


def get_doc(did, t=None, fetch=True):
    """docID の本文（ページごと・EDINET の帯は落とした後）。①最新の有報のキャッシュ ②_yuho ③落とす（1.2秒以上の間隔）。"""
    if t:
        lc = _latest_from_cache(t)
        if lc and lc['docID'] == did:
            return lc
    p = os.path.join(DOC_DIR, did + '.json')
    if os.path.exists(p):
        return json.load(open(p, encoding='utf-8'))
    if not fetch:
        return None
    b, why = R.fetch_pdf(did)
    if b is None:
        raise RuntimeError(f'{did}: 取得失敗 {why}')
    raw, _ = R.pdf_pages(b)
    d = {'docID': did, 'cover': R.cover_info(raw[0] if raw else ''), 'pages': [R.strip_footer(pg)[0] for pg in raw]}
    os.makedirs(DOC_DIR, exist_ok=True)
    json.dump(d, open(p + '.tmp', 'w', encoding='utf-8'), ensure_ascii=False)
    os.replace(p + '.tmp', p)
    return d


def candidates(pack):
    """パックに刻まれた docID（新しい順）。rebuild_src_cache_jp.doc_ids に、この道具が前回 nulls.cagrT に書いた docID を足す。"""
    prio, rest = R.doc_ids(pack)
    extra = R.DOCID.findall(str(((pack.get('_meta') or {}).get('nulls') or {}).get('cagrT') or ''))
    return sorted(set(prio + rest + extra), reverse=True)


def find_yuho(t, pack, stop, fetch=True):
    """docID の新しい順に表紙を読み、この社の有価証券報告書を {会計年度: doc} に集める。stop(found) が真になったら止める。"""
    found, log = {}, []
    for did in candidates(pack):
        if stop(found):
            break
        try:
            d = get_doc(did, t, fetch)
        except Exception as e:
            log.append(str(e))
            continue
        if d is None:
            log.append(f'{did}: 本文がキャッシュに無い（--no-fetch）')
            continue
        cov = d.get('cover') or {}
        if not R.is_yuho(cov.get('kind')) or not R.same_company(pack, cov) or not cov.get('fy_end'):
            continue
        found.setdefault(int(cov['fy_end'][:4]), d)
    return found, log


# ══ 5年表の読み取り ══════════════════════════════════════════════════════════════
REVL = r'(売上高|売上収益|営業収益|営業収入|純売上高|売上高及び営業収入|収益合計|収益)'
YM = re.compile(r'(令和|平成)?\s*(\d{1,4}|元)年\s*(\d{1,2})月(\s*\d{1,2}\s*日)?')   # 『…月1日』＝IFRS の移行日の列（実測 6981）
NUM = re.compile(r'(△|▲)?\s*(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|(?<![\d,])[-―—](?![\d])')


def _ym(e, y, m):
    y = 1 if y == '元' else int(y)
    y += {'令和': 2018, '平成': 1988}.get(e, 0)
    return (y, int(m))


def _yms(span):
    """決算年月の並び（年, 月）と、日付まで書いた列（IFRS の移行日＝決算期ではない）の位置。"""
    allm = YM.findall(span.replace('\n', ' '))
    return [_ym(e, a, b) for e, a, b, _ in allm], {i for i, x in enumerate(allm) if x[3]}


def _unit(seg):
    # 括弧つき『(百万円)』が主。括弧なし『売上高 百万円 155,252』の書式もある（実測 4967・4661・6981）
    return (re.search(r'\((百万円|千円|円|百万ドル|千ドル)\)', seg)
            or re.search(r'(?<![\d,])(百万円|千円)(?=\s)', seg))


def _nums(seg, um):
    vals = []
    for mm in NUM.finditer(seg[um.end():]):
        if mm.group(2) is None:
            vals.append(None)                       # 『－』＝その年の値が無い（0 と読まない）
        else:
            v = float(mm.group(2).replace(',', ''))
            vals.append(-v if mm.group(1) else v)
    return vals


def _section(pages):
    """「主要な経営指標等の推移」の本文（最大4頁）と、文字位置→頁の対応。"""
    start = None
    for i, pg in enumerate(pages):
        s = nf(pg)
        if re.search(r'主要な経営指標等の推移', s) and (
                re.search(r'決算年月', s) or (i + 1 < len(pages) and re.search(r'決算年月', nf(pages[i + 1])))):
            start = i
            break
    if start is None:
        return None, None
    text, pmap = '', []
    for j in range(start, min(start + 4, len(pages))):
        pmap.append((len(text), j))
        text += nf(pages[j]) + '\n'
    m = re.search(r'\n\s*2\s*【\s*沿革\s*】', text)
    return (text[:m.start()] if m else text), pmap


def _page(pmap, pos):
    pg = pmap[0][1]
    for off, j in pmap:
        if off <= pos:
            pg = j
    return pg + 1


def _block(text, pmap, p0, p1):
    blk = text[p0:p1]
    out = {'text': blk}
    m = re.search(r'決算年月', blk)
    if not m:
        out['err'] = '決算年月の行が無い'
        return out
    after = blk[m.end():m.end() + 200]
    cut = re.search(r'\n\s*' + REVL, after)
    span = after[:cut.start()] if cut else after.split('\n')[0]
    cols, skip = _yms(span)
    yms = [x for i, x in enumerate(cols) if i not in skip]
    out['yms'] = yms
    kai = re.search(r'回次', blk)
    out['ki'] = [int(k) for k in re.findall(r'第\s*(\d+)\s*期', blk[kai.end():m.start()])] if kai and kai.start() < m.start() else []
    out['tanntai_mark'] = bool(kai and re.search(r'-\s*単体\s*-', blk[kai.end():m.start()]))
    lines = blk[m.end():].split('\n')
    for k, ln in enumerate(lines):
        if re.match(r'\s*' + REVL, ln) and not re.match(r'\s*収益性', ln):
            seg, k2, um = ln, k, _unit(ln)
            while (not um or len(_nums(seg, um)) < len(cols)) and k2 + 1 < len(lines) and k2 - k < 3:
                k2 += 1
                seg += ' ' + lines[k2]
                um = _unit(seg)
            out['label'] = re.sub(r'\s*(百万円|千円|円)\s*$', '', re.match(r'\s*([^\d(△▲\-―]*)', ln).group(1).strip())
            out['unit'] = um.group(1) if um else None
            vals = _nums(seg, um) if um else []
            out['vals'] = [v for i, v in enumerate(vals[:len(cols)]) if i not in skip] if cols else vals
            out['page'] = _page(pmap, p0 + m.end() + sum(len(x) + 1 for x in lines[:k]))
            break
    else:
        out['err'] = '売上の行が無い'
    nm = re.search(r'\(注\)', blk)
    out['notes'] = blk[nm.start():][:1500] if nm else ''
    return out


def parse_table(doc):
    """5年表を {'連結': …, '単体': …} か {'単一': …}（連結の見出しも提出会社の見出しも無い表）に。"""
    text, pmap = _section(doc['pages'])
    if text is None:
        return {'err': '主要な経営指標等の推移が見つからない'}
    res = {}
    im, tm = re.search(r'連結経営指標等', text), re.search(r'提出会社の経営指標等', text)
    if im:
        res['連結'] = _block(text, pmap, im.start(), tm.start() if (tm and tm.start() > im.start()) else len(text))
    if tm:
        res['単体'] = _block(text, pmap, tm.start(), len(text))
    if not im and not tm:
        res['単一'] = _block(text, pmap, 0, len(text))
    return res


def _tab(t, k):
    b = t.get(k)
    return b if (b and b.get('vals')) else None


def _ki2y(block, ki):
    """第N期 → 会計年度（5年表の回次と決算年月の並びから。表の外の期は1年ずつ外挿する）。"""
    ks, ys = block.get('ki') or [], [y for y, _ in (block.get('yms') or [])]
    if not ks or len(ks) != len(ys):
        return None
    return ys[0] + (ki - ks[0])


# ══ 系列と基準の検問 ══════════════════════════════════════════════════════════════
def _cagr(v0, v1, n):
    if v0 is None or v1 is None or v0 <= 0 or v1 <= 0:
        return None
    return (v1 / v0) ** (1.0 / n) - 1


def compute(ser, a):
    """fill_growth_trend.py と同じ式。6年のどれかが欠けたり0以下なら None。"""
    if any(ser.get(y) is None or ser[y] <= 0 for y in range(a - 5, a + 1)):
        return None
    c2, c1 = _cagr(ser[a - 2], ser[a], 2), _cagr(ser[a - 5], ser[a - 2], 3)
    yoy = {y: (ser[y] / ser[y - 1] - 1) * 100 for y in range(a - 4, a + 1)}
    A = (c2 - c1) * 100
    B = statistics.median([yoy[a - 1], yoy[a]]) - statistics.median([yoy[a - 4], yoy[a - 3], yoy[a - 2]])
    return {'c2': c2 * 100, 'c1': c1 * 100, 'A': A, 'B': B, 'cagrT': max(A, B), 'yoy': yoy,
            'm2': statistics.median([yoy[a - 1], yoy[a]]), 'm1': statistics.median([yoy[a - 4], yoy[a - 3], yoy[a - 2]])}


def build_series(t, lat, pri, a, mon, basis):
    """最新の表から a-4…a、前年（か代わり）の表から a-5 を取り、重なる年を突き合わせる。"""
    Lt, out = lat['table'], {'issues': [], 'codes': set(), 'overlap': []}
    L = _tab(Lt, basis)
    if L is None:
        out['issues'].append(f'最新の表に {basis} の売上の行が無い')
        return out
    out['label'], out['unit'] = L.get('label'), L.get('unit')
    yl = [tuple(x) for x in L['yms']]
    exp = [(y, mon) for y in range(a - len(yl) + 1, a + 1)]   # 列が5年に満たない表（連結の開始・IFRS の移行）は範囲の問題で、期間の問題ではない
    if yl != exp:
        out['codes'].add('PERIOD')
        out['issues'].append(f"最新の決算年月 {[f'{y}/{m}' for y, m in yl]} が FY{a} までの{mon}月決算の連続した年と揃わない")
    ser, src = {}, {}
    for (y, m), v in zip(L['yms'], L['vals']):
        if v is not None:
            ser[y] = v * UNIT.get(L['unit'], float('nan'))
            src[y] = (lat['docID'], L['page'], v, L['unit'])
    if pri is not None:
        Pt = pri['table']
        P = _tab(Pt, basis) or (_tab(Pt, '単一') if basis == '単体' else None) or (_tab(Pt, '単体') if basis == '単一' else None)
        if P is None:
            out['issues'].append(f"前年の表（{pri['docID']}）に {basis} の売上の行が無い")
        else:
            if P.get('label') != L.get('label'):
                out['issues'].append(f"売上の科目名が違う: 前年 {P.get('label')} ／ 最新 {L.get('label')}")
            if any(m != mon for _, m in P['yms']):
                out['codes'].add('PERIOD')
                out['issues'].append(f"前年の表の決算月が揃っていない {[f'{y}/{m}' for y, m in P['yms']]}")
            for (y, m), v in zip(P['yms'], P['vals']):
                vv = None if v is None else v * UNIT.get(P['unit'], float('nan'))
                if y in ser and vv is not None:
                    d = abs(vv - ser[y]) / ser[y]
                    out['overlap'].append((y, d))
                    if d > TOL and y not in ACCEPT_OVERLAP.get(t, {}):
                        out['codes'].add('RECLASS')
                        out['issues'].append(f"重なる年 FY{y} が新旧の有報で {d*100:.2f}% 食い違う"
                                             f"（{pri['docID']} {v:,.0f}{P['unit']} ／ {lat['docID']} {src[y][2]:,.0f}{src[y][3]}）")
                elif y == a - 5:
                    if vv is None:
                        out['issues'].append(f'FY{y} の売上が前年の表（{pri["docID"]}）で空欄')
                    else:
                        ser[y] = vv
                        src[y] = (pri['docID'], P['page'], v, P['unit'])
    out['ser'], out['src'] = ser, src
    out['res'] = compute(ser, a)
    return out


def _std_blocks(block_text):
    """連結の5年表の中の会計基準の別ブロック（『回次 日本基準』『回次 米国会計基準』…）と、その決算年月の年。"""
    out = []
    for m in re.finditer(r'回次\s*(日本基準|日本会計基準|米国会計基準|国際会計基準)', block_text):
        seg = block_text[m.end(): m.end() + 400]
        ym = re.search(r'決算年月', seg)
        cols, skip = _yms(seg[ym.end(): ym.end() + 120]) if ym else ([], set())
        yrs = [x[0] for i, x in enumerate(cols) if i not in skip]
        out.append((m.group(1).replace('日本会計基準', '日本基準'), yrs))
    return out


def scope_checks(lat, pri, a, basis_lat):
    """SCOPE / FRAMEWORK / PERIOD（表の形と注記から機械で分かるもの）。"""
    codes, issues = set(), []
    win = range(a - 5, a + 1)
    L, P = lat['table'], (pri['table'] if pri else {})
    if basis_lat == '連結(欠)':
        miss = [y for (y, _), v in zip(L['連結']['yms'], L['連結']['vals']) if v is None]
        codes.add('SCOPE')
        issues.append(f"最新の5年表で連結の売上が空欄の年 {miss}（連結財務諸表を作っていない年がある）")
    if basis_lat == '連結':
        lc = [y for y, _ in L['連結']['yms']] + [y for _, ys in _std_blocks(L['連結'].get('text', '')) for y in ys]
        st = [y for y, _ in (_tab(L, '単体') or {}).get('yms', [])]
        if lc and st and min(lc) > min(st):
            codes.add('SCOPE')
            issues.append(f"最新の5年表で連結は FY{min(lc)} から（提出会社は FY{min(st)} から）＝連結財務諸表の作成が窓の中で始まった")
    if basis_lat == '連結' and pri is not None:
        Pc = _tab(P, '連結')
        if Pc:
            v5 = {y: v for (y, _), v in zip(Pc['yms'], Pc['vals'])}
            pc = list(v5) + [y for _, ys in _std_blocks(P['連結'].get('text', '')) for y in ys]
            if (a - 5) in v5 and v5[a - 5] is None:
                codes.add('SCOPE')
                issues.append(f"窓の初年度 FY{a-5} の連結の売上が前年の表（{pri['docID']}）で空欄（その年は連結財務諸表が無い）")
            elif pc and min(pc) > a - 5:
                codes.add('SCOPE')
                issues.append(f"前年の表（{pri['docID']}）の連結は FY{min(pc)} から＝窓の初年度 FY{a-5} の連結の売上が無い（連結財務諸表の作成が窓の中で始まった）")
        elif P.get('単体') or P.get('単一'):
            codes.add('SCOPE')
            issues.append(f"前年の表（{pri['docID']}）に連結の表が無い")
    if basis_lat in ('単一', '単体') and pri is not None and _tab(P, '連結'):
        vs = [v for (y, _), v in zip(P['連結']['yms'], P['連結']['vals']) if y in win and v is not None]
        if vs:
            codes.add('SCOPE')
            issues.append(f"最新の表は提出会社だけだが、前年の表（{pri['docID']}）には窓の中の連結の売上がある")
    for d in [x for x in (lat, pri) if x]:
        c = d['table'].get('連結')
        if not c:
            continue
        if c.get('tanntai_mark'):
            codes.add('SCOPE')
            issues.append(f"{d['docID']} の5年表の連結欄に『-単体-』の年がある")
        for m in re.finditer(r'第\s*(\d+)\s*期(?:から第\s*(\d+)\s*期まで)?(?:は|について)[^。]{0,40}連結経営指標等に代えて', c.get('notes', '')):
            k0, k1 = int(m.group(1)), int(m.group(2) or m.group(1))
            ys = [_ki2y(c, k) for k in range(k0, k1 + 1)]
            if any(y is None or y in win for y in ys):
                codes.add('SCOPE')
                issues.append(f"{d['docID']} の5年表の注記: 第{k0}〜{k1}期は『連結経営指標等に代えて』提出会社の数値")
        stds = _std_blocks(c.get('text', ''))
        inwin = {s for s, yrs in stds if any(y in win for y in yrs)}
        if len(inwin) > 1:
            codes.add('FRAMEWORK')
            issues.append(f"{d['docID']} の連結の5年表に窓の中の会計基準のブロックが複数ある {sorted(inwin)}")
        for m in re.finditer(r'(\d+)\s*か月', c.get('notes', '')):
            if int(m.group(1)) != 12:
                codes.add('PERIOD')
                issues.append(f"{d['docID']} の5年表の注記に {m.group(1)}か月の期がある")
                break
        if re.search(r'決算期を[^。]{0,30}変更|決算日を[^。]{0,30}変更', c.get('notes', '')):
            codes.add('PERIOD')
            issues.append(f"{d['docID']} の5年表の注記に決算期の変更がある")
    for d in [x for x in (lat, pri) if x]:
        for k in ('単一', '単体'):
            b = d['table'].get(k)
            if basis_lat in ('単一', '単体') and b:
                for m in re.finditer(r'(\d+)\s*か月', b.get('notes', '')):
                    if int(m.group(1)) != 12:
                        codes.add('PERIOD')
                        issues.append(f"{d['docID']} の5年表の注記に {m.group(1)}か月の期がある")
                        break
                if re.search(r'決算期を[^。]{0,30}変更|決算日を[^。]{0,30}変更', b.get('notes', '')):
                    codes.add('PERIOD')
                    issues.append(f"{d['docID']} の5年表の注記に決算期の変更がある")
    return codes, list(dict.fromkeys(issues))


NONCONSOL = re.compile(r'連結財務諸表[をは]作成して(?:おりません|いない|いません)')   # 5年表の注記、または経理の状況の冒頭（実測 2477）


def is_ifrs(lat):
    """最新の連結の5年表が IFRS か。基準のブロックがあれば最初（＝最新）のブロック、無ければ IFRS にしか無い行の名前で判る。
    『IFRS』という語の有無では判らない（日本基準の社も注記で IAS・IFRS 解釈指針に触れる＝実測 6367）。"""
    txt = (lat['table'].get('連結') or {}).get('text') or ''
    blocks = _std_blocks(txt)
    if blocks:
        return blocks[0][0] == '国際会計基準'
    return bool(re.search(r'親会社の所有者に帰属する|親会社所有者帰属持分|税引前当期利益', squash(txt)))


# ══ 収益認識会計基準の事実（機械で抜く側） ══════════════════════════════════════════
# 段落の見つけ方は三段: ①『(会計方針の変更)』の直後に収益認識 ②『(収益認識に関する会計基準等の適用)』の見出し
# ③ ゆるい言い回し（5年表の注記など）。①②を先に探さないと、前の頁の経営成績の分析や5年表の注記を掴む（初版で踏んだ）
PARA = (re.compile(r'\(会計方針の変更\)(?:\(|「)?(?:\d{1,2}\.?|\(\d\))?収益認識'),         # 『(会計方針の変更)1収益認識…』（実測 8035）も
        re.compile(r'\(収益認識に関する会計基準等の適用\)'),
        re.compile(r'収益認識会計基準等の適用については|収益認識に関する会計基準」[^。]{0,120}?当(?:連結)?(?:会計|事業)年度の期首から適用'))
PARA_END = re.compile(r'\(?(?:\d\.?)?時価の算定に関する会計基準等の適用'          # 次の見出し（別の会計方針の変更・注記の区分）で切る
                      r'|\((?!収益認識)[^()「」]{2,40}(?:の適用|の変更)\)|\(会計上の見積りの変更'
                      r'|\((?:追加情報|未適用の会計基準等|(?:連結)?(?:貸借対照表|損益計算書|株主資本等変動計算書|キャッシュ・フロー計算書)関係)\)')
_Q = r'(?:(\d+)億)?([\d,]+)(百万円|千円)'
AMTS = (  # 売上高への影響額の書き方（実測した4通り）。増加は＋・減少は−
    re.compile(r'売上(?:高|収益)(?:及び売上原価|および売上原価)?(?:については|は|が)' + _Q + r'(?:それぞれ)?(減少|増加)'),
    re.compile(r'売上(?:高|収益)(?:は|が)' + _Q + r'、[^。]{0,120}?それぞれ(減少|増加)'),           # 6565 型
    re.compile(r'売上(?:高|収益)、[^。]{0,80}?(?:は|が)それぞれ' + _Q + r'(減少|増加)'),           # 2477 型
)
SEG = re.compile(r'セグメントごとの売上(?:高|収益)は、?((?:「[^」]+」で' + _Q + r'(?:増加|減少)し?(?:ております)?、?)+)')   # 8035 型
PL = r'損益|売上|営業利益|経常利益|純利益|連結財務諸表|財務諸表|経営成績|経営指標'   # 利益剰余金だけの文は損益の影響ではない


def _xref(s, m):
    """本文中の参照（『…注記事項(会計方針の変更)(収益認識…)」をご参照ください』）は段落ではない（実測 2222 p.14・8035 p.117）。"""
    return bool(re.search(r'(?:注記事項|経理の状況)[^。]*$', s[max(0, m.start() - 80):m.start()])
                or re.match(r'[^。「]{0,40}」(?:を|に|の)', s[m.end():]))


def rev_paragraph(doc):
    """会計方針の変更の『収益認識』の段落（最初に出るもの＝連結の注記。連結の無い社は提出会社の注記）と頁。"""
    pages = doc['pages']
    sq = [squash(pg) for pg in pages]
    for pat in PARA:
        for i, s in enumerate(sq):
            m = next((m for m in pat.finditer(s) if not _xref(s, m)), None)
            if not m:
                continue
            s2 = s + (sq[i + 1] if i + 1 < len(sq) else '')
            seg = s2[m.start():m.start() + 4000]
            e = PARA_END.search(seg, 30)
            return (seg[:e.start()] if e else seg), i + 1
    return None, None


def _amt(g1, g2):
    return int(g2.replace(',', '')) + (int(g1) * 100 if g1 else 0)


def classify(par):
    """段落から影響の書き方を読む。retro（前年度を組み替えた）> quantified > immaterial > none > silent の順。
    軽微・影響なしは**損益の語を含む文だけ**を数える（『期首の利益剰余金に与える影響は軽微』は損益の話ではない＝実測 3436）。"""
    if not par:
        return {'kind': 'unknown'}
    sents = [s for s in par.split('。') if s]
    for s in sents:
        if re.search(r'遡及適用され|遡及適用後の|遡って適用した後の', s):
            return {'kind': 'retro', 'quote': s[:160]}
    for pat in AMTS:
        m = pat.search(par)
        if m:
            amt = _amt(m.group(1), m.group(2))
            return {'kind': 'quantified', 'amount': amt if m.group(4) == '増加' else -amt, 'unit': m.group(3), 'quote': m.group(0)}
    m = SEG.search(par)
    if m:
        parts = re.findall(r'「[^」]+」で' + _Q + r'(増加|減少)', m.group(1))
        if len({u for _, _, u, _ in parts}) == 1:
            tot = sum(_amt(g1, g2) * (1 if d == '増加' else -1) for g1, g2, _, d in parts)
            return {'kind': 'quantified', 'amount': tot, 'unit': parts[0][2], 'quote': m.group(0), 'note': 'セグメントの増減額の合計'}
    for kind, pat in (('immaterial', r'軽微'), ('none', r'影響はありません|影響はない|影響はございません')):
        for s in sents:
            if re.search(pat, s) and re.search(PL, s):
                return {'kind': kind, 'quote': s[:160]}
    return {'kind': 'silent', 'quote': ''}


def _mandatory_fy(mon):
    """収益認識会計基準の強制適用＝2021年4月1日以後に始まる事業年度。その最初の年度の末日の年。"""
    for y in range(2021, 2024):
        sy, sm = (y, 1) if mon == 12 else (y - 1, mon + 1)
        if (sy, sm) >= (2021, 4):
            return y
    return 2023


NOTE_ADOPT = re.compile(r'収益認識に関する会計基準」?\(企業会計基準第29号(\d{4})年[^)]*\)[^。]*?'
                        r'(?:第(\d+)期|(\d{4})年(\d{1,2})月期|(\d{4})年度)の(?:連結会計年度の)?期首(?:から|より)適用([^。]*)')
EARLY_PRIOR = re.compile(r'2018年3月30日\)等(?:について)?は、?前(?:連結)?(?:会計|事業)年度の期首から適用')


def auto_rev(docs, a, mon):
    """REV に無い社の事実を機械で抜く。①手元の有報の5年表の注記『第N期の期首から適用』（新しい有報から）
    ②適用年度（分からなければ窓の中の各年度）の有報の会計方針の変更の段落。"""
    fy, early, retro_from, how = None, False, None, ''
    for d in sorted(docs.values(), key=lambda x: x['docID'], reverse=True):
        for b in d['table'].values():
            if not isinstance(b, dict):
                continue
            m = NOTE_ADOPT.search(re.sub(r'\s+', '', b.get('notes') or ''))
            if not m:
                continue
            if m.group(2):
                fy = _ki2y(b, int(m.group(2)))
            elif m.group(3):
                fy = int(m.group(3))
            elif m.group(5):
                fy = int(m.group(5)) + (1 if mon <= 3 else 0)
            early = m.group(1) == '2018'
            if re.search(r'遡って適用|遡及', m.group(6) or ''):
                retro_from = (fy - 1) if fy else None
            how = f"{d['docID']} の5年表の注記『{m.group(0)[:90]}』"
            break
        if fy:
            break
    fact = {'fy': fy, 'src': how}
    if fy is not None and fy <= a - 5:
        fact.update(kind='early' if early else 'outside')
        return fact
    if retro_from is not None:
        fact.update(kind='retro', retro_from=retro_from)
        return fact
    # 適用年度（分からなければ窓の中の各年度）の有報から、会計方針の変更の段落を探す
    want = [fy] if fy else list(range(a - 4, a + 1))
    for y in want:
        d = docs.get(y)
        if d is None:
            continue
        par, pg = rev_paragraph(d)
        if not par:
            continue
        if EARLY_PRIOR.search(par):              # 2018年版を前年度から早期適用・この年度の変更は開示の改正（実測 6920）
            return {'fy': y - 1, 'kind': 'early', 'doc': d['docID'], 'page': pg, 'quote': EARLY_PRIOR.search(par).group(0),
                    'src': f"{d['docID']} p.{pg} の会計方針の変更"}
        if fy or re.search(r'当(?:連結)?(?:会計|事業)年度の期首から[^。]{0,30}?適用', par):   # 『期首から収益認識会計基準等を適用し』（実測 3436）も
            c = classify(par)
            c.update(fy=y, doc=d['docID'], page=pg, src=f"{d['docID']} p.{pg} の会計方針の変更")
            return c
    fact.update(kind='unknown', fy=fy or _mandatory_fy(mon))
    fact['note'] = ((how + '。') if how else '') + '適用年度の有報がパックの docID に無い、または会計方針の変更の段落が見つからない'
    return fact


def rev_verdict(t, fact, ser, a):
    """事実と窓から、収益認識の検問の結論を出す。返り値 (code or None, 窓の外なら説明文, 要判断か)。"""
    fy, kind = fact.get('fy'), fact.get('kind')
    if fy is not None and fy <= a - 5:
        return None, f"収益認識会計基準の適用は FY{fy}（窓の初年度 FY{a-5} 以前）＝窓の6年はすべて新基準{_loc(fact, '（', '）')}", False
    if kind == 'retro':
        rf = fact.get('retro_from')
        if rf is not None and rf <= a - 5:
            return None, (f"収益認識会計基準は FY{fy} の期首から遡及適用し FY{rf} まで組み替え済み（窓の初年度 FY{a-5}）"
                          f"＝窓の6年は同じ基準{_loc(fact, '（', '）')}"), False
        return 'REV_UNKNOWN', None, rf is None     # 組み替えが窓の初年度まで届かない／どこまで遡ったか分からない
    if kind in ('none', 'immaterial'):
        return None, None, False
    if kind == 'silent':                            # 人が読んで確かめた silent だけ受け入れる（機械の silent は読み落としと区別できない）
        return None, None, t not in REV
    if kind == 'quantified':
        base = ser.get(fy)
        amt = fact['amount'] * UNIT.get(fact.get('unit'), float('nan'))
        pct = abs(amt) / base * 100 if base else None
        fact['pct'] = pct
        if pct is not None and pct <= TOL * 100:
            return None, None, False
        return ('REV_IMPACT', None, False) if pct is not None else ('REV_UNKNOWN', None, False)
    return 'REV_UNKNOWN', None, False               # unknown／窓の中の early・outside（2018年版の窓の中での適用は影響を読むまで分からない）


def quote_check(t, fact, fetch=True):
    """REV の引用が原文（その頁と次の頁・NFKC・空白なし）にあるか。『…』で区切った断片ごとに照合する。"""
    if not fact.get('doc') or not fact.get('quote'):
        return '（引用なし）'
    try:
        d = get_doc(fact['doc'], t, fetch)
    except Exception as e:
        return f'本文を取れない（{e}）'
    if d is None:
        return '本文がキャッシュに無い'
    p = fact.get('page') or 1
    body = ''.join(squash(pg) for pg in d['pages'][p - 1:p + 1])
    miss = [q for q in fact['quote'].split('…') if q and squash(q) not in body]
    return '一致' if not miss else f"✗ p.{p} に無い: {'／'.join(m[:30] for m in miss)}"


def _loc(fact, pre='', post=''):
    """原文の在りか『S100xxxx p.N『引用』』。原文が無ければ空。"""
    if not fact.get('doc'):
        return ''
    q = f"『{fact['quote']}』" if fact.get('quote') else ''
    return f"{pre}{fact['doc']} p.{fact.get('page')}{q}{post}"


def rev_text(fact, pct=None):
    fy, kind = fact.get('fy'), fact.get('kind')
    kj = {'none': '影響なしと明記', 'immaterial': '軽微と明記', 'silent': '損益への影響額の記載なし＝表示替え・経過措置の説明だけ',
          'retro': '遡及適用', 'early': '2018年版の早期適用', 'outside': '窓の前に適用', 'unknown': '影響を有報で確かめられない'}.get(kind, kind)
    if kind == 'quantified':
        amt = fact['amount']
        kj = f"売上高 {'+' if amt > 0 else '−'}{abs(amt):,}{fact.get('unit')}" + (f"＝同年度売上高の{pct:.2f}%" if pct is not None else '')
    if fact.get('note'):
        kj += '・' + fact['note']
    return f"収益認識会計基準は FY{fy} の期首から適用{_loc(fact, '——')}（{kj}）"


# ══ 1社の判定 ══════════════════════════════════════════════════════════════════
def judge(t, pack, fetch=True, audit=False):
    m = pack.get('_meta') or {}
    rd = R.report_ym(pack)
    row = {'t': t, 'nm': pack.get('nm'), 'reportDate': rd, 'pack': pack.get('cagrT'),
           'pack_null': ((m.get('nulls') or {}).get('cagrT') or ''), 'issues': [], 'codes': [], 'missing': []}
    if not rd:
        row.update(verdict='SKIP', why='パックに reportDate が無い')
        return row
    a, mon = int(rd[:4]), int(rd[5:7])
    row['a'] = a
    need_prior = lambda f: a in f and any(k in f for k in range(a - 5, a))
    docs, log = find_yuho(t, pack, need_prior, fetch)
    row['log'] = log
    if a not in docs:
        row.update(verdict='SKIP', why=f'FY{a} の有報がパックの docID に無い／読めない')
        return row
    for y, d in docs.items():
        d['table'] = parse_table(d)
    lat = docs[a]
    pri = docs.get(a - 1)
    if pri is None:
        row['missing'].append(f'前年 FY{a-1} の有報の docID がパックに無い（EDINET の書類検索で探してパックの _meta.source に足すこと）')
        older = sorted((k for k in docs if a - 5 <= k < a - 1), reverse=True)
        pri = docs[older[0]] if older else None
        if pri is not None:
            row['issues'].append(f"a-5 は FY{older[0]} の有報（{pri['docID']}）の表から取る")
    Lt = lat['table']
    if Lt.get('err'):
        row.update(verdict='SKIP', why=f"最新の有報 {lat['docID']}: {Lt['err']}")
        return row
    if _tab(Lt, '連結'):
        basis = '連結' if all(v is not None for v in Lt['連結']['vals']) else '連結(欠)'
    else:
        basis = next((k for k in ('単一', '単体') if _tab(Lt, k)), None)
    if basis is None:
        row.update(verdict='SKIP', why=f"最新の有報 {lat['docID']} の5年表に売上の行が無い")
        return row
    if basis in ('単一', '単体') and not NONCONSOL.search(squash(''.join(lat['pages']))):
        # 提出会社だけの表を読んだのに『連結財務諸表を作成していない』の記載が無い＝連結の表を読み落とした疑い（黙って単体で埋めない）
        row.update(verdict='SKIP', why=f"最新の有報 {lat['docID']} の5年表は提出会社だけだが、連結財務諸表を作成していないという記載が見つからない")
        return row
    row['basis'] = basis
    codes, issues = scope_checks(lat, pri, a, basis)
    s = build_series(t, lat, pri, a, mon, '連結' if basis.startswith('連結') else basis)
    codes |= s['codes']
    issues += s['issues']
    row.update(series=s, ifrs=is_ifrs(lat) if basis.startswith('連結') else False)
    # 収益認識（日本基準の系列だけ。表の形で既に空欄と決まった社は読まない）
    if not row['ifrs'] and not codes:
        auto = None
        if t not in REV or audit:
            # 適用年度を探すため窓の中の有報を足す（REV に無い社・突き合わせのときだけ）
            more, _ = find_yuho(t, pack, lambda f: all(k in f for k in range(a - 4, a + 1)), fetch)
            for y, d in more.items():
                if y not in docs:
                    d['table'] = parse_table(d)
                    docs[y] = d
            auto = dict(auto_rev(docs, a, mon), origin='auto')
            row['rev_auto'] = auto
            row['rev_auto_verdict'] = rev_verdict(t, dict(auto), s.get('ser') or {}, a)[0] or '受け入れ'
        fact = dict(REV[t], origin='REV') if t in REV else auto
        code, text, needs = rev_verdict(t, fact, s.get('ser') or {}, a)
        row['rev'] = fact
        row['rev_verdict'] = code or '受け入れ'
        row['rev_text'] = text or rev_text(fact, fact.get('pct'))
        if code:
            codes.add(code)
        if needs:
            row['needs'] = ('収益認識の段落に損益への言及が見つからない（機械の silent）' if fact.get('kind') == 'silent'
                            else '遡及適用がどの年度まで届いたか分からない') + '＝人が原本を読んで REV に置くこと'
    row['codes'] = sorted(codes)
    row['issues'] = issues
    res = s.get('res')
    if res:
        row['A'], row['B'], row['value'] = res['A'], res['B'], round(res['cagrT'], 2)
    if codes:
        row['verdict'] = 'BLANK'
        row['ref'] = row.get('value')
        if codes == {'SCOPE'} and pri is not None and not res:
            # 参考: 提出会社の6年系列（採点に使わない。範囲の問題だけの社に限る＝組替え・期間の問題がある社には出さない）
            for k in ('単体', '単一'):
                if _tab(Lt, k):
                    s2 = build_series(t, lat, pri, a, mon, k)
                    if s2.get('res'):
                        row['ref'] = round(s2['res']['cagrT'], 2)
                        row['ref_basis'] = '提出会社の6年系列'
                    break
        row.pop('value', None)
    elif row.get('needs'):
        row['verdict'] = 'SKIP'
        row['why'] = row['needs']
    elif not res:
        row['verdict'] = 'SKIP'
        row['why'] = '6年の売上がそろわない（' + '；'.join(issues or row['missing'] or ['a-5 が取れない']) + '）'
    else:
        row['verdict'] = 'FILL'
    return row


# ══ 文面 ══════════════════════════════════════════════════════════════════════
TOOLNOTE = ('定義は night/fill_growth_trend.py と同一（A案＝端点 CAGR(a-2→a,2年)−CAGR(a-5→a-2,3年)＝retro_features2 の accel／'
            'B案＝新2年YoYの中央値−前3年YoYの中央値／**採用は両案の大きいほう**＝負の側で絶対値の小さいほう）')
SCOPE_JP = {'連結': '(1)連結経営指標等', '単一': '提出会社の経営指標等（連結財務諸表を作成していない会社）', '単体': '(2)提出会社の経営指標等'}
CODE_JP = {'SCOPE': '連結の6年系列が作れない（連結と単体を接がない）', 'FRAMEWORK': '会計基準の枠組みが窓の中で変わる',
           'PERIOD': '12か月でない期・決算月の変更が窓の中にある', 'RECLASS': '重なる年が新旧の有報で0.5%を超えて食い違う（組替え・遡及）',
           'REV_IMPACT': '収益認識会計基準の売上高への影響が許容差0.5%を超える', 'REV_UNKNOWN': '収益認識会計基準の売上高への影響を有報で確かめられない'}


def _fy(y, mon):
    return f'FY{y}/{mon}'


def series_text(row):
    s, a, mon = row['series'], row['a'], int(row['reportDate'][5:7])
    src = s['src']
    ys = sorted(src)
    lat = src[a][0]
    parts = [f"{_fy(y, mon)} {src[y][2]:,.0f}" + (f"［{src[y][0]} p.{src[y][1]}］" if src[y][0] != lat else '') for y in ys]
    first = min(y for y in ys if src[y][0] == lat)
    units = sorted(set(src[y][3] for y in ys))
    return (' → '.join(parts) + f"［{_fy(first, mon)}〜{_fy(a, mon)} は {lat} p.{src[a][1]}］",
            units[0] if len(units) == 1 else '/'.join(units) + '（単位を揃えて計算）')


def evidence(row):
    r, a, mon = row['series']['res'], row['a'], int(row['reportDate'][5:7])
    ser_txt, unit = series_text(row)
    yy = '{' + ', '.join(f"{y}: {v:.1f}" for y, v in sorted(r['yoy'].items())) + '}'
    ov = row['series']['overlap']
    b = SCOPE_JP.get(row['basis'], row['basis'])
    docs = sorted(set(x[0] for x in row['series']['src'].values()))
    basis = [('連結は窓の6年すべてで作成' if row['basis'] == '連結' else '連結財務諸表を作成していない会社＝提出会社の6年系列'),
             (f"重なる年 {_fy(min(y for y, _ in ov), mon)}〜{_fy(max(y for y, _ in ov), mon)} は新旧の有報（{'・'.join(docs)}）で一致"
              f"（最大差 {max(d for _, d in ov)*100:.2f}%）" if ov else '重なる年の突き合わせなし')]
    if row.get('ifrs'):
        basis.append('IFRS の連結（IFRS第15号は窓の前）')
    elif row.get('rev_text'):
        basis.append(row['rev_text'] + ('' if row['rev'].get('origin') == 'REV' else '〔機械抽出〕'))
    return (f"機械算出（night/fill_growth_trend_jp.py・EDINET 有報PDF「主要な経営指標等の推移」{b}・{row['series']['label']}・{unit}）: "
            f"{ser_txt}。A案(端点) 直近2年CAGR {r['c2']:.2f}% − その前3年CAGR {r['c1']:.2f}% = {r['A']:+.2f}pt ／ "
            f"B案(中央値) 新2年YoYの中央値 {r['m2']:.2f}% − 前3年YoYの中央値 {r['m1']:.2f}% = {r['B']:+.2f}pt ／ 年次YoY(%) {yy} "
            f"→ **採用 {row['value']:+.2f}pt**。{TOOLNOTE}。基準の検問: {'／'.join(basis)}")


def null_reason(row):
    why = '；'.join(CODE_JP[c] for c in row['codes'])
    det = '；'.join(row['issues'][:4])
    if row.get('rev') and row['rev'].get('kind') in ('quantified', 'unknown'):
        det = (det + '；' if det else '') + rev_text(row['rev'], row['rev'].get('pct'))
    ref = row.get('ref')
    txt = f"成長の軌道を算出できない（{TODAY}・night/fill_growth_trend_jp.py・EDINET 有報PDFの5年表で検問）: {why}。{det}"
    if ref is not None:
        txt += f"。参考（採点に使わない）: {row.get('ref_basis') or '基準をまたいだ未調整の系列'}では {ref:+.2f}pt"
        if ref <= -10:
            txt += '——⚠これは減点の入口 −10 を越える＝**空欄はこの社に有利に働いている**（埋めるかは人の判断）'
    return txt


# ══ 書き込み ══════════════════════════════════════════════════════════════════════
def write_row(row):
    """1社ぶんを書く。書く直前にパックを読み直す（他の班が同じ木を編集している）。返り値: 何をしたか。"""
    p = os.path.join(ROOT, 'out', f"{row['t']}_gate_pack.json")
    raw = open(p, encoding='utf-8').read()
    x = json.loads(raw)
    d = x.get('data') or x
    m = x.setdefault('_meta', {})
    old = d.get('cagrT')
    act = None
    if row['verdict'] == 'FILL':
        v = row['value']
        if old is not None and abs(float(old) - v) < 0.005 and (m.get('evidence') or {}).get('cagrT'):
            if (m.get('provenance') or {}).get('cagrT') != 'machine':
                m.setdefault('provenance', {})['cagrT'] = 'machine'
                act = 'provenance'
        else:
            d['cagrT'] = v
            m.setdefault('evidence', {})['cagrT'] = evidence(row)
            m.setdefault('provenance', {})['cagrT'] = 'machine'
            if isinstance(m.get('nulls'), dict):
                m['nulls'].pop('cagrT', None)
            m.setdefault('kenshi', []).append(
                f"{TODAY} cagrT {('空欄' if old is None else f'{float(old):+.2f}')}→{v:+.2f}（night/fill_growth_trend_jp.py・"
                f"EDINET 有報PDFの5年表から機械算出。A案 {row['A']:+.2f} ／ B案 {row['B']:+.2f}・採用は両案の大きいほう）")
            act = 'value'
    elif row['verdict'] == 'BLANK' and old is not None:
        d['cagrT'] = None
        m.setdefault('nulls', {})['cagrT'] = null_reason(row)
        (m.get('evidence') or {}).pop('cagrT', None)
        (m.get('provenance') or {}).pop('cagrT', None)
        m.setdefault('kenshi', []).append(
            f"{TODAY} cagrT {float(old):+.2f}→空欄（night/fill_growth_trend_jp.py: {'；'.join(CODE_JP[c] for c in row['codes'])}）")
        act = 'blank'
    if act:
        s = json.dumps(x, ensure_ascii=False, indent=1) + ('\n' if raw.endswith('\n') else '')
        open(p + '.tmp', 'w', encoding='utf-8').write(s)
        os.replace(p + '.tmp', p)
    return act


# ══ 一覧 ══════════════════════════════════════════════════════════════════════
def pack_codes(txt):
    """パックに今ある空欄の理由（人が書いた文も含む）を、同じ分類へ読み替える（差の一覧のため）。"""
    c = set()
    if re.search(r'連結財務諸表[^。]{0,40}(?:作成していない|作成しておりません|から作成)(?!会社)|連結の6年系列|連結経営指標等に代えて'
                 r'|連結は (?:FY\d+/\d+|第\d+期) から|連結は第\d+期から|連結(?:の)?売上[^。]{0,6}(?:も|が)?[^。]{0,16}無い', txt):
        c.add('SCOPE')
    if re.search(r'米国会計基準|IFRS は第|枠組み', txt):
        c.add('FRAMEWORK')
    if re.search(r'決算期|13か月|決算年月も', txt):
        c.add('PERIOD')
    if re.search(r'組み替え|組替え|表示方法の変更', txt) and '収益認識' not in txt[:60]:
        c.add('RECLASS')
    if re.search(r'許容差0\.5%を超え', txt) or (re.search(r'収益認識会計基準を', txt) and re.search(r'同年度売上高[\d,]+(?:百万円|千円)の[\d.]+%', txt)):
        c.add('REV_IMPACT')
    if re.search(r'上場前|確かめられない', txt) and '収益認識' in txt:
        c.add('REV_UNKNOWN')
    return c


def main():
    a = sys.argv[1:]
    only = set(a[a.index('--only') + 1].split(',')) if '--only' in a else None
    write, verbose, fetch = '--write' in a, ('-v' in a or '--verbose' in a), '--no-fetch' not in a
    audit = '--audit-rev' in a
    jpath = a[a.index('--json') + 1] if '--json' in a else None
    import glob
    rows = []
    for p in sorted(glob.glob(os.path.join(ROOT, 'out', '*_gate_pack.json'))):
        t = os.path.basename(p).split('_gate_pack')[0]
        if only and t not in only:
            continue
        pack = json.load(open(p, encoding='utf-8'))
        if not R.is_jp(pack):
            continue
        try:
            row = judge(t, pack, fetch, audit)
        except Exception as e:                      # 1社の失敗で全体を止めない（その社は書かない）
            row = {'t': t, 'nm': pack.get('nm'), 'verdict': 'SKIP', 'why': f'{type(e).__name__}: {e}', 'pack': pack.get('cagrT'),
                   'pack_null': '', 'codes': [], 'issues': [], 'missing': []}
        rows.append(row)
    # ── 差 ──
    for r in rows:
        pv = r.get('pack')
        if r['verdict'] == 'FILL':
            r['diff'] = ('SAME' if pv is not None and abs(float(pv) - r['value']) < 0.005
                         else ('FILL(空欄→値)' if pv is None else f'VALUE {float(pv):+.2f}→{r["value"]:+.2f}'))
        elif r['verdict'] == 'BLANK':
            if pv is not None:
                r['diff'] = f'BLANK(値{float(pv):+.2f}→空欄)'
            else:
                pc, tc = pack_codes(r.get('pack_null') or ''), set(r['codes'])
                r['diff'] = ('SAME' if pc == tc else
                             f"SAME≈ 理由の一部が同じ（パック{sorted(pc)}／道具{sorted(tc)}）" if (pc & tc) else
                             f"REASON パック{sorted(pc) or '（分類できない）'}／道具{sorted(tc)}")
                m = re.findall(r'→ ([+-]?\d+\.\d+)pt', r.get('pack_null') or '')
                if m and r.get('ref') is not None and abs(float(m[-1]) - r['ref']) >= 0.005:
                    r['diff'] += f"・参考値 {float(m[-1]):+.2f}→{r['ref']:+.2f}"
        else:
            r['diff'] = 'SKIP'
    # ── 表示 ──
    print(f'■ 日本株の成長の軌道 cagrT（EDINET 有報PDFの5年表・night/fill_growth_trend.py と同じ定義）: 対象 {len(rows)}社')
    for r in rows:
        nm = re.sub(r'^\d+\s*', '', str(r.get('nm') or ''))[:14]
        if r['verdict'] == 'FILL':
            core = f"cagrT {r['value']:+7.2f}（A {r['A']:+.2f}／B {r['B']:+.2f}）基準 {r['basis']}{'・IFRS' if r.get('ifrs') else ''}"
        elif r['verdict'] == 'BLANK':
            ref = f"・参考 {r['ref']:+.2f}" if r.get('ref') is not None else ''
            core = f"空欄 {'+'.join(r['codes'])}{ref}"
        else:
            core = f"見送り: {r.get('why')}"
        print(f"  {r['t']:6s} {nm:14s} FY{r.get('a', '?')}  {r['verdict']:5s} {core}  ｜パックとの差: {r['diff']}")
        if verbose:
            if r.get('series', {}).get('src'):
                st, un = series_text(r)
                print(f'         売上({un}): {st}')
            for i in r.get('issues') or []:
                print(f'         ⚠ {i}')
            if r.get('rev_text'):
                print(f"         {r['rev_text']}〔{r['rev'].get('origin')}〕")
        for mm in r.get('missing') or []:
            print(f'         ✗ {mm}')
    from collections import Counter
    cnt = Counter(r['verdict'] for r in rows)
    dif = Counter(('SAME' if r['diff'] == 'SAME' else r['diff'].split('(')[0].split(' ')[0]) for r in rows)
    print(f"\n  判定: {dict(cnt)} ／ パックとの差: {dict(dif)}")
    fav = [r['t'] for r in rows if r['verdict'] == 'BLANK' and r.get('ref') is not None and r['ref'] <= -10]
    if fav:
        print(f"  ⚠ 空欄が有利に働いている社（参考値が −10 を越える）: {' '.join(fav)}")
    if audit:
        print('\n■ REV（人が原本で読んだ事実）の引用の照合と、機械抽出との突き合わせ')
        agree = Counter()
        for r in rows:
            t = r['t']
            if t not in REV:
                continue
            h = REV[t]
            qc = quote_check(t, h, fetch)
            au = r.get('rev_auto')
            if au is None:
                print(f"  {t:6s} 引用 {qc}｜検問に来なかった（{'IFRS' if r.get('ifrs') else '+'.join(r.get('codes') or []) or r.get('why', '')}）")
                continue
            same = r.get('rev_verdict') == r.get('rev_auto_verdict')
            agree['結論一致' if same else '結論が違う'] += 1
            fmt = lambda f: f"FY{f.get('fy')} {f.get('kind')}" + (f" {f['amount']:+,}{f.get('unit')}" if f.get('amount') is not None else '')
            print(f"  {t:6s} 引用 {qc}｜結論 {'一致' if same else '違う'}: REV {fmt(h)}→{r.get('rev_verdict')} ／ "
                  f"機械 {fmt(au)}→{r.get('rev_auto_verdict')}" + ('' if (au.get('fy'), au.get('kind')) == (h.get('fy'), h.get('kind'))
                                                                 else f"（機械の出所: {au.get('src') or au.get('note') or ''}）"))
        print(f"  → {dict(agree)}（REV に無い社は機械の結論で判定する。機械の silent は要判断で書かない）")
    if write:
        acts = Counter()
        for r in rows:
            act = write_row(r)
            if act:
                acts[act] += 1
        print(f"\n→ 書き込み: {dict(acts) or 'なし'}（値が同じ社は provenance.cagrT='machine' だけ）")
    if jpath:
        def _clean(r):
            r = dict(r)
            s = r.pop('series', None) or {}
            r['series'] = {str(y): v for y, v in (s.get('src') or {}).items()}
            return r
        json.dump({'generated': TODAY, 'rows': [_clean(r) for r in rows]}, open(jpath, 'w', encoding='utf-8'),
                  ensure_ascii=False, indent=1, default=list)
        print(f'→ {jpath}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
