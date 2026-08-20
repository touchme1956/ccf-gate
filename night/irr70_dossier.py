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
MECH_RE = {k: re.compile(v, re.I) for k, v in MECH.items()}
ANY_RE = re.compile('|'.join(f'(?:{v})' for v in MECH.values()), re.I)

CUST = re.compile(r'\b(our customers?|the customers?|customers[’\']|clients?|OEMs?|end users?'
                  r'|purchasers?|issuers?|subscribers?)\b', re.I)
SELF = re.compile(r'\b(we (?:are|must|need|seek|work|rely|obtain|maintain|purchase|source|defer|incur)'
                  r'|our (?:suppliers?|vendors?|subcontractors?|foundr\w+|contract manufacturers?)'
                  r'|we (?:qualify|certify)|our (?:ISO|FDA|FAA|510\(k\)|SOC))\b', re.I)
WISH = re.compile(r'\b(we (?:work closely|strive|seek|endeavor|aim)|depend(?:s|ent)? on|may be able to)\b', re.I)

SENT = re.compile(r'[^.?!]{25,700}[.?!]')

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
    r'|estimated useful li|amortiz(?:ed|ation) over', re.I)


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
                u = f'https://disclosure2dl.edinet-fsa.go.jp/searchdocument/pdf/{m.group(1)}.pdf'
                b = urllib.request.urlopen(urllib.request.Request(u, headers=EX.UA), timeout=120).read()
                r = pypdf.PdfReader(io.BytesIO(b))
                txt = ''.join((pg.extract_text() or '') for pg in r.pages)
                how = f'EDINET {m.group(1)}'
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
