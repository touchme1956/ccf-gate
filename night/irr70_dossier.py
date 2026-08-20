#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/irr70_dossier.py — **irr=70 の二重読みのために、原本から材料を機械で配る**（2026-08-20新設）

なぜ要るか:
  2026-08-19 に買付圏の irr=70 を12社読んだら、**12社とも旧根拠が v9.9.144 の規約を満たしておらず、
  5社は刻みそのものが誤りだった**（RMD 6146 6857 ADBE MA が 70→50）。
  未検証の irr=70 は**なお200社**あり、根拠の字数は**中央値184字・0字が47社・200字未満が112社**。
  ＝この欄は「積極的な主張」に改めた（v9.9.144）のに、その主張を誰も原本で確かめていない。

  だが200社ぶんの年次報告は 1社30〜50万字ある。**読み手に丸ごと渡すのは現実的でない**ので、
  この道具が**同じ抽出を全社に掛けて材料を配る**。irr85_extract と同じ思想で、
  **判定はしない**——判定は読み手の仕事で、道具の役目は「同じ材料を全員に配る」こと（v9.9.65）。

★ 語彙は 2026-08-19 の12社の読解で**実際に効いた語**から作った（机上ではない）:
    IRMD の `proprietary disposable` ／ BR の `deferred client conversion` ／
    MCO の `remaining performance obligation` ／ ADBE の `non-cancellable` ／
    MA の `not exclusive` ／ HWM の `approval, license, and qualification requirements`。
  ⚠ **それでも網は必ず漏れる**。だから読み手には
    「怪しければ `--raw` で原本を全部読め」と渡す（本文はキャッシュに落としてある）。

使い方:
  python3 night/irr70_dossier.py --build            # 未検証の irr=70 を全部（キャッシュ利用）
  python3 night/irr70_dossier.py --build --t ETN,APH
  python3 night/irr70_dossier.py --show ETN         # 1社の材料を読む（読み手が使う）
  python3 night/irr70_dossier.py --raw ETN          # 原本の全文（キャッシュ）へのパスを出す
出力: out/irr70_dossiers/{T}.json ＋ 本文キャッシュ out/_src_cache/{T}.txt（.gitignore）
"""
import concurrent.futures as cf
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import irr85_extract as EX            # get / cik_of / latest_annual / text_of を再利用（二重実装を作らない）

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'out', 'irr70_dossiers')
CACHE = os.path.join(ROOT, 'out', '_src_cache')

# ── 語彙。**機構ごとに束ねる**（読み手が「どの機構か」を先に見られるように）──
MECH = {
 '複数年の購買義務': r'multi-?year|long-?term (?:contract|agreement)|remaining performance obligation'
   r'|non-?cancell?able|minimum purchase|take-?or-?pay|committed to (?:future )?purchas'
   r'|purchase commitment|unconditional right to invoice|contractual commitment|backlog'
   r'|term of the (?:arrangement|agreement)|subscription term|committed funds',
 '消耗品の専用性': r'proprietary|disposable|consumable|cartridge|reagent|refill'
   r'|razor|dedicated (?:media|tubing|supplies)|only with our|compatible only',
 'データ移行・再教育': r'data migration|migrat\w+ (?:their|customer|client)|deconversion|de-?convert'
   r'|convert a client|conversion cost|implementation cost|onboard\w*|re-?train\w*|learning curve'
   r'|start-?up cost|expected client life',
 '設置基盤': r'installed base|install base|installed systems|installed units|our fleet of',
 '工程への組込': r'embedded|designed into|design-?in\b|design win|integrated into (?:their|customer|client)'
   r'|workflow|mission-?critical|sign-?off|process of record|copy exact',
 '解約率・更新率': r'churn|retention rate|renewal rate|client retention|revenue retention'
   r'|net revenue retention|attrition rate|renewal(?:s)? rate',
 '認定・認証': r're-?qualif\w*|qualif\w*|certif\w*|accredit\w*|approved (?:vendor|supplier|product)'
   r'|approval, license',
 '★反証(50側)': r'low barriers to entry|barriers to entry (?:are|is) low|price erosion|commoditi[sz]'
   r'|readily available|alternative suppliers|in-?house|internally developed|insourc\w*'
   r'|terminate (?:at any time|for convenience)|no obligation to renew|short product li'
   r'|interchangeab\w*|second source|not exclusive|multi-?home',
 '★向きが逆(ONTO型)': r'reluctant to switch to (?:ours|our)|difficult (?:or cost-?prohibitive )?for us'
   r'|cost-?prohibitive for us|we may (?:be unable|experience difficulty) (?:to |in )?(?:win|sell|displac)'
   r'|difficult for us to (?:win|obtain|displace)|unable to displace',
 '乗り換えそのもの': r'switching cost|switch\w* (?:to|from) (?:a |an )?(?:alternative|competitor|another)'
   r'|lock-?in|locked in|sticky|stickiness',
}
# ── 日本語の機構語（2026-08-20 新設）────────────────────────────────
# ⚠ **これが無いと日本株の材料が空になる**。実測: 2477/3922/3939/5038/6920/9790 は
#   原本を 12k〜101k字 読めているのに候補文 **0本**——英語の正規表現しか無かったから。
#   「読めていない」ではなく「英語で探していない」だけなのに、読み手には
#   『機構が無い』に見える＝ルール7（欠測をゼロと読むな）の表示版。
# ⚠ **判定は一つも変えない**。この道具は材料を配るだけで、刻みは読み手が原本で決める。
MECH_JP = {'複数年の購買義務': '長期(?:契約|取引|供給)|複数年|継続的(?:な)?取引|基本契約|受注(?:残高|残)|購入義務|最低購入', '消耗品の専用性': '専用|純正|消耗品|替刃|カートリッジ|試薬|当社製[^。]{0,12}のみ', 'データ移行・再教育': 'データ移行|移行(?:作業|費用|コスト|期間)|切替(?:費用|コスト|作業)|切り替え(?:費用|コスト)|導入(?:費用|コスト|支援)|習熟|教育訓練|立ち上げ支援', '設置基盤': '設置台数|導入(?:実績|台数|社数)|稼働台数|納入(?:実績|台数)|保有台数|累計出荷', '工程への組込': '組み?込|作り?込|工程(?:に|へ)|生産ライン|量産(?:ライン|立ち上げ)|ワークフロー|標準採用', '解約率・更新率': '解約率|継続率|更新率|リテンション|チャーン', '認定・認証': '認定|認証|適格性|品質(?:認定|承認)|型式承認|監査を受け', '★反証(50側)': '参入障壁|価格競争|コモディティ|汎用品|標準品|内製|代替(?:品|可能|製品)|他社(?:製品|品)でも|competitors|競合他社[^。]{0,20}(?:同等|優位)', '★向きが逆(ONTO型)': '当社(?:が|は)[^。]{0,20}(?:認定|認証|承認)を(?:取得|受け)|当社(?:が|は)[^。]{0,16}審査を受け', '乗り換えそのもの': 'スイッチング|乗り換え|乗換|切替コスト|囲い?込み'}
for _k, _v in MECH_JP.items():
    MECH[_k] = MECH[_k] + '|' + _v

MECH_RE = {k: re.compile(v, re.I) for k, v in MECH.items()}
ANY_RE = re.compile('|'.join(f'(?:{v})' for v in MECH.values()), re.I)

CUST = re.compile(r'\b(our customers?|the customers?|customers[’\']|clients?|OEMs?|end users?'
                  r'|purchasers?|issuers?|subscribers?)\b'
                  r'|顧客|得意先|取引先|ユーザー|需要家|販売先|お客様', re.I)
SELF = re.compile(r'\b(we (?:are|must|need|seek|work|rely|obtain|maintain|purchase|source|defer|incur)'
                  r'|our (?:suppliers?|vendors?|subcontractors?|foundr\w+|contract manufacturers?)'
                  r'|we (?:qualify|certify)|our (?:ISO|FDA|FAA|510\(k\)|SOC))\b'
                  r'|当社(?:は|が|グループ)|弊社', re.I)
WISH = re.compile(r'\b(we (?:work closely|strive|seek|endeavor|aim)|depend(?:s|ent)? on|may be able to)\b'
                  r'|努めて|目指し|注力|取り組んで|強化して|図って', re.I)

# ⚠ 日本語は句点で切る。英語だけの `[.?!]` だと有報が数十文にしか割れず
#   （実測 5038: 12,519字 → **16文**）、機構文が長大な塊に埋もれて拾えない。
#   日本語は1文が短いので下限も分ける（15字）。
SENT = re.compile(r'[^.?!。]{25,700}[.?!]|[^。！？\n]{15,400}[。！？]')

# ★雑音。**これを落とさないと読み手が誤った材料を掴む**（2026-08-20 の ETN の試走で実測）——
#   インラインXBRLの文脈ダンプ（us-gaap:… Member 20xx-xx-xx）が「複数年の購買義務」に化け、
#   会社法の『officers … elected and qualified』が「認定・認証」に化け、
#   買収会計の『backlog intangible assets』が顧客の受注残に見えた。
#   HWM の certif 17件が授業料補助・Certificate of Retirement・SOX証明だったのと同じ族。
NOISE = re.compile(
    r'us-gaap:|ifrs-full:|srt:|dei:|xbrl|Inline XBRL|Instance Document|:\w+Member'
    r'|elected and qualified|duly qualified|Certificate of (?:Retirement|Incorporation|Designation)'
    r'|Section (?:302|906)|Sarbanes|immigration|tuition|Power of Attorney'
    r'|intangible assets? (?:of|acquired)|purchase price allocation'
    r'|qualified (?:employees|candidates|personnel|individuals|workforce|staff|successors|management)'
    r'|retain qualified|confidential (?:and|or) proprietary|proprietary information'
    r'|estimated useful li|amortiz(?:ed|ation) over'
    # ⚠ 日本語の雑音。とくに **『移行』は TCFD の移行リスクが圧倒的多数**で顧客の移行ではない。
    r'|移行リスク|気候変動|TCFD|脱炭素|カーボン|温室効果|サステナ'
    r'|退職給付|会計基準|税効果|のれんの償却|株主総会|取締役会?の|監査役|内部統制|コーポレート'
    r'|新型コロナ|反社会的|コンプライアンス研修|人材の(?:確保|育成)|従業員の(?:確保|育成)', re.I)


def norm(s):
    return re.sub(r'\s+', ' ', s).strip()


def cache_path(t):
    return os.path.join(CACHE, f'{t}.txt')


def fetch_src(t, pack):
    """原本の本文を取る。SEC(10-K/20-F/40-F) と EDINET(有報PDF) の両方。
    ⚠ **取れなかったら空を返さず None を返す**——『機構が無い』と『読めていない』は別物（ルール7）"""
    p = cache_path(t)
    if os.path.exists(p) and os.path.getsize(p) > 5000:
        return open(p, encoding='utf-8', errors='ignore').read(), 'cache'
    src = (pack.get('_meta') or {}).get('source') or ''
    txt, how = None, None
    # ⚠ **日本株の source は一様ではない**（2026-08-20 に実測）——EDINET直PDF / Yahooのdisclosure /
    #   irbank / 日経 / 会社IRのPDF が混在する。しかも EDINET の docID は **8文字**（S + 7）で、
    #   9文字を期待する正規表現だと 2477 の S100WQOA を取り落とす。
    if not txt and re.search(r'\.pdf(\?|$|\s|／)', src, re.I) or 'edinet' in src.lower():
        m = re.search(r'\bS[0-9A-Z]{7}\b', src)
        if m:
            try:
                import pypdf, io, urllib.request
                u = f'https://disclosure2dl.edinet-fsa.go.jp/searchdocument/pdf/{m.group(0)}.pdf'
                b = urllib.request.urlopen(urllib.request.Request(u, headers=EX.UA), timeout=120).read()
                r = pypdf.PdfReader(io.BytesIO(b))
                txt = ''.join((pg.extract_text() or '') for pg in r.pages)
                how = f'EDINET {m.group(0)}'
            except BaseException as e:
                how = f'EDINET失敗: {e}'
    if txt is None:
        # docID が無くても PDF の直URLなら取れる（Yahoo disclosure・会社IR・日経など）
        for u in re.split(r'[\s／]+', src):
            if not re.match(r'https?://', u) or not re.search(r'\.pdf(\?|$)', u, re.I):
                continue
            try:
                import pypdf, io, urllib.request
                b = urllib.request.urlopen(urllib.request.Request(u, headers=EX.UA), timeout=120).read()
                r = pypdf.PdfReader(io.BytesIO(b))
                txt = ''.join((pg.extract_text() or '') for pg in r.pages)
                how = 'PDF ' + u.rsplit('/', 1)[-1][:40]
                break
            except BaseException as e:
                how = f'PDF失敗: {type(e).__name__}'
    if txt is None and re.match(r'^\d{4,5}$', t):
        # 日本株で PDF も docID も無い＝SECへ落とすと必ず CIK不明。**穴として明示する**（ルール7）
        return None, (how or '') + '｜日本株だが原本のPDF/docIDが _meta.source に無い（EDINET経路の穴）'
    if txt is None:
        try:
            if src.startswith('http') and '/Archives/' in src:
                txt, how = EX.text_of(src), 'source URL'
            else:
                fi = EX.latest_annual(EX.cik_of(t))
                txt, how = EX.text_of(fi['url']), f"{fi['form']} {fi['report']} filed {fi['filed']}"
        # ⚠ **BaseException で受ける**——irr85_extract.cik_of は `raise SystemExit` するので
        #   Exception だけだとスレッドプールを突き抜けて**全体が1社で止まる**（2026-08-20 に実測）
        except BaseException as e:
            return None, f'取得失敗: {type(e).__name__}: {e}'
    if not txt or len(txt) < 5000:
        return None, (how or '') + '（本文が短すぎる）'
    os.makedirs(CACHE, exist_ok=True)
    open(p, 'w').write(txt)
    return txt, how


def dossier(t, pack):
    txt, how = fetch_src(t, pack)
    m = pack.get('_meta') or {}
    rec = {'t': t, 'src_how': how, 'irr_evidence': (m.get('evidence') or {}).get('irr') or '',
           'irr_nulls': (m.get('nulls') or {}).get('irr') or '', 'source': m.get('source') or '',
           'rep': pack.get('rep'), 'dom': pack.get('dom'), 'dur': pack.get('dur'), 'moatW': pack.get('moatW')}
    if txt is None:
        rec['error'] = how
        return rec
    s = norm(txt)
    rec['chars'] = len(s)
    # ★材料の質を申告する。**日本株は原本の入手経路が一様でない**（2026-08-20 実測）——
    #   有報のPDFが取れる社もあれば、_meta.source が**決算短信**や irbank しか指していない社もある。
    #   決算短信には【事業の内容】【事業等のリスク】が無く、irr の機構はそこにしか書かれない。
    #   ⚠ 薄い材料で 50 と判定すると『読めていない』を『機構が無い』に化かす（ルール7）ので、
    #     読み手へ**材料が薄いことを明示**して判定を保留させる。
    if re.match(r'^\d{4,5}$', t):
        need = ['事業等のリスク', '事業の内容']
        miss = [x for x in need if x not in s]
        if miss:
            rec['caveat'] = ('⚠材料が薄い: 原本に ' + '／'.join(miss) + ' が無い'
                             + ('（決算短信の公算）' if '決算短信' in s[:4000] else '')
                             + '。**この材料だけで50と判定しないこと**——有報が取れるまで保留が正しい')
    # ★PDF から抜いた日本語は**文の途中で改行が入る**ので、そのままだと文に割れない。
    #   実測 9790: 「。」が845個あるのに文は94本しか取れず、1文が平均1,082字の塊になっていた。
    #   日本語は語間に空白を置かないので、**行を素直に連結してよい**（英語では駄目なので
    #   「。が200個以上＝日本語の原本」と判ってから掛ける）。
    if s.count('。') >= 200:
        s = re.sub(r'\n+', '', s)
    sents = [m.group(0).strip() for m in SENT.finditer(s)]
    clean = [x for x in sents if not NOISE.search(x)]
    rec['n_sent'] = len(sents)
    # ⚠ カウントは**雑音を落とした文の数**で数える。語の生カウントは誤誘導する
    #   （ETN: 認定・認証 の生カウント23 → 雑音を落とすと実質2件）
    rec['counts'] = {k: sum(1 for x in clean if r.search(x)) for k, r in MECH_RE.items()}
    hits = {}
    for k, r in MECH_RE.items():
        seen, out = set(), []
        for mm in SENT.finditer(s):
            sent = mm.group(0).strip()
            if not r.search(sent) or NOISE.search(sent):
                continue
            key = sent[:60]
            if key in seen:
                continue
            seen.add(key)
            out.append({'s': sent[:640],
                        'dir': ('顧客側' if CUST.search(sent) else '') + ('/当社側' if SELF.search(sent) else '')
                               + ('/願望形' if WISH.search(sent) else '')})
            if len(out) >= 14:
                break
        if out:
            hits[k] = out
    rec['hits'] = hits
    # Competition 節（50側の証拠がいちばん出る場所）
    for pat in [r'\bCompetition\b', r'\bCOMPETITION\b', r'競合', r'競争']:
        i = re.search(pat, s)
        if i:
            rec['competition'] = s[i.start():i.start() + 2600]
            break
    return rec


def main():
    a = sys.argv[1:]
    only = None
    if '--t' in a:
        only = [x.strip() for x in a[a.index('--t') + 1].split(',') if x.strip()]
    if '--show' in a or '--raw' in a:
        t = a[a.index('--show' if '--show' in a else '--raw') + 1]
        if '--raw' in a:
            print(cache_path(t)); return
        print(json.dumps(json.load(open(os.path.join(OUT, f'{t}.json'))), ensure_ascii=False, indent=1)); return

    rows = json.load(open(os.path.join(ROOT, 'out', 'score_all.json')))
    todo = []
    for r in rows:
        if r.get('irr') != 70:
            continue
        p = os.path.join(ROOT, 'out', f"{r['t']}_gate_pack.json")
        if not os.path.exists(p):
            continue
        d = json.load(open(p))
        if any(x.get('rung') == 70 for x in ((d.get('_meta') or {}).get('irr85_verify') or [])):
            continue
        if only and r['t'] not in only:
            continue
        todo.append((r['t'], d))
    os.makedirs(OUT, exist_ok=True)
    ok = err = 0
    # SEC は 10req/s なので 6並列に抑える
    with cf.ThreadPoolExecutor(max_workers=6) as ex:
        for rec in ex.map(lambda x: dossier(*x), todo):
            json.dump(rec, open(os.path.join(OUT, f"{rec['t']}.json"), 'w'), ensure_ascii=False, indent=1)
            if rec.get('error'):
                err += 1; print(f"  ✗ {rec['t']:6} {rec['error'][:90]}")
            else:
                ok += 1
    print(f'\n材料を作った {ok}社 / 取得できず {err}社  → {OUT}')
    print('⚠ 取得できなかった社は「機構が無い」ではなく「読めていない」——読み手に渡さないこと（ルール7）')


if __name__ == '__main__':
    main()
