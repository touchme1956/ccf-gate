#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/irr85_screen_local.py — **台帳の irr=70 の原本を、85の語彙で自分たちに当て直す**（2026-08-20新設）

なぜ要るか（穴の名前）:
  85 の狩りは二度やった（2026-08-08 実文由来の語彙で441社／2026-08-19 意味由来の352本で1,782社）。
  だが**どちらも「台帳の外」を掘っていた**——第一次は「既存パック38・未審査403社」、
  第二次は「第一次が触れた518社と重なり0」。
  ⇒ **台帳自身の irr=70（213社）は、85の語彙で一度も screen されていない。**

  そしてそれが実害だと判った。2026-08-20 の全数二重読みで、**KLAC** の FY2026 10-K に
  『Semiconductor manufacturers generally **must commit significant resources to qualify,
  install and integrate** ... into a semiconductor production line』がある——
  **LRCX が85を取っている引用とほぼ同一構文**。KLAC は Ω79.5・キル0・点検0で
  **堀 69.3 が関門70を 0.7pt 割っているだけ**なので、85 になれば投下可の顔ぶれが動く。

  ★**この母集団で今日の買付を動かせる向きは 85 への昇格だけ**（70→50 は買付圏に1社も居ないので動かさない）。
  だから 85 の見落としだけは潰しておく。

何をするか（**判定はしない。読む先を絞る**）:
  ・`out/_src_cache/{T}.txt`（既に手元にある原本の全文）に対して
    `night/irr85_vocab2.json` の **dir=customer_bears / lock_evidence** の語だけを当てる
    （neutral は「顧客の側の10-Kに必ず出る」と第二次が名指しで警告している語なので除く）
  ・既に85が付いている社の実文（LRCX/CW/RBC/TDG/WST/LOAR/HXL/ST/KRMN…）から
    **顧客が費用を負う構文**を正規表現にしたものも当てる
  ・当たった**文そのもの**を、向きの手がかりつきで出す

使い方:
  python3 night/irr85_screen_local.py            # 上位から
  python3 night/irr85_screen_local.py --all
  python3 night/irr85_screen_local.py --t KLAC
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, 'out', '_src_cache')
VOCAB = os.path.join(ROOT, 'night', 'irr85_vocab2.json')

# ★85の実文から作った構文。**顧客が主語で、費用・時間・再認定を負う**形だけ
BEAR = [
 (r'(?:customers?|manufacturers?|OEMs?|users?|clients?)[^.]{0,120}\bmust\b[^.]{0,140}'
  r'(?:qualif\w+|re-?qualif\w+|certif\w+|re-?certif\w+|validat\w+|re-?validat\w+|generate|invest|commit)', '顧客がmust'),
 (r'\bmust (?:also )?be (?:certif|qualif|approv|validat)\w+ by[^.]{0,80}'
  r'(?:customers?|OEMs?|manufacturers?|clients?)', '顧客に認定される'),
 # ⚠ **『more expensive for customers』は値段の話であって乗り換え費用ではない**（2026-08-20 実測）——
 #   関税・インフレ・信用収縮のリスク文が全社で当たり、上位を埋めた。
 #   採るのは「**乗り換え・置き換え・再実装が**顧客にとって高い」形だけ。
 (r'(?:costly|expensive|time[- ]consuming|difficult|impractic\w+|burdensome|not (?:typically )?economical)'
  r'[^.]{0,80}for (?:our |their |the )?(?:customers?|OEMs?|clients?|manufacturers?)'
  r'[^.]{0,120}(?:switch|replac|migrat|convert|transition|re-?implement|re-?qualif|re-?certif|re-?validat|change (?:suppliers?|vendors?|providers?))'
  r'|(?:switch|replac|migrat|convert|transition|re-?implement)\w*[^.]{0,80}'
  r'(?:is|are|would be|can be|could be) (?:costly|expensive|time[- ]consuming|difficult|burdensome)'
  r'[^.]{0,60}for (?:our |their |the )?(?:customers?|clients?|OEMs?)', '顧客に乗り換え費用'),
 (r'(?:customers?|manufacturers?|OEMs?)[^.]{0,100}(?:would|will|may) (?:have to|need to|be required to)'
  r'[^.]{0,120}(?:re-?qualif\w+|re-?certif\w+|re-?validat\w+|re-?test|requalification)', '顧客が再認定'),
 (r'\bre-?qualif\w+ (?:by|from|of) (?:our |their |the )?(?:customers?|OEMs?|clients?)', '顧客による再認定'),
 (r'once[^.]{0,120}(?:qualified|certified|approved|selected)[^.]{0,140}'
  r'(?:generally )?(?:maintains?|relies upon|continues?|remains?)', 'once…維持する'),
 # ⚠ **『approved by the FDA』を素で拾ってはいけない**——製薬の10-Kでは
 #   それは**自社製品の承認**＝型(1)自社が取得する側で、85 の向きと逆。
 #   RBC の実文は『qualified **for the application by** the OEM, the DOD, the FAA』なので
 #   「用途について」認定される形だけを採る。
 (r'(?:qualified|approved|certified|specified) for (?:the |a |an )?(?:application|use|program|platform)'
  r'[^.]{0,40}by (?:the )?(?:OEM|OEMs|DOD|DoD|FAA|EASA|NRC|customers?|end users?)'
  r'|(?:qualified|approved|certified) by (?:our |their |the )?(?:individual )?'
  r'(?:OEM|OEMs|customers?|clients?|end users?)\b',
  '第三者/顧客が用途を認定'),
 (r'\brequire[sd]? (?:customer|OEM|client)s? (?:approval|qualification|certification|re-?validation)', '顧客の承認が要る'),
 # ⚠ `NDA` は **`standards` の中の nda に当たる**（大小無視）。**必ず語境界を置く**——
 #   これを外していたので 10-K の表紙定型文『new or revised financial accounting standards』が
 #   全社で当たり、上位が製薬とカバーページで埋まった（2026-08-20 に実測）。
 (r'(?:amend|revise|update)[^.]{0,60}\b(?:type certificate|NDA|ANDA|BLA|PMA|510\(k\)|'
  r'marketing authorization|drug master file)\b',
  '顧客の申請書の改訂'),
 (r'to reference (?:our|the Company\'?s) (?:drug master file|DMF|device master file)', 'DMF参照'),
 (r'copy exact', 'copy exact'),
 (r'\bdesign(?:ed)?[- ]in\b[^.]{0,120}(?:life of the (?:program|platform|aircraft|vehicle)|for the life)',
  '設計組込＋機体寿命'),
]
BEAR_RE = [(re.compile(p, re.I), n) for p, n in BEAR]

# 向きが逆／当社が損をする側（ONTO型）——当たったら**下げる**
ONTO = re.compile(
    r'(?:difficult|hard|cost-?prohibitive|challenging)[^.]{0,40}for us\b'
    r'|we may (?:be unable|experience difficulty|not be able)[^.]{0,60}(?:win|sell|displace|obtain)'
    r'|if (?:we|the Company) fail[^.]{0,60}(?:design win|qualif|certif)'
    r'|difficult for us to (?:win|obtain|displace|sell)', re.I)
SELF = re.compile(
    r'\bwe (?:are|have been|must|need to|seek to|obtain|maintain|hold)\b[^.]{0,60}'
    r'(?:ISO|FDA|FAA|510\(k\)|SOC|certif\w+|accredit\w+)'
    r'|our (?:suppliers?|vendors?|subcontractors?|foundr\w+|contract manufacturers?)', re.I)

SENT = re.compile(r'[^.?!]{30,700}[.?!]')

# ★雑音。10-Kの**表紙と法定文**は全社に同じ文が出るので、当たると上位が定型文で埋まる
NOISE = re.compile(
    r'accelerated filer|emerging growth company|Exchange Act|Securities Act|Rule 12b-2'
    r'|Financial Accounting Standards Board|Accounting Standards Codification'
    r'|Sarbanes|Section (?:13\(a\)|302|906)|shell company|Item 405 of Regulation', re.I)


def targets():
    sa = json.load(open(os.path.join(ROOT, 'out', 'score_all.json')))
    rws = sa['rows'] if isinstance(sa, dict) else sa
    out = []
    for r in rws:
        if r.get('irr') != 70:
            continue
        p = os.path.join(ROOT, 'out', f"{r['t']}_gate_pack.json")
        if not os.path.exists(p):
            continue
        out.append(dict(t=r['t'], s=r.get('s') or 0, moat=r.get('moat') or 0, buy=r.get('buy')))
    return out


def vocab_phrases():
    d = json.load(open(VOCAB, encoding='utf-8'))
    ps = [x for x in d.get('phrases', [])
          if x.get('dir') in ('customer_bears', 'lock_evidence')
          and x.get('specificity') == 'high']
    return [x['p'] for x in ps]


def vocab_re(phrases):
    """★語を1本の正規表現に束ねる。**1本ずつ `in` で回すと 200社×5千文×百語で百M回**になり
    実測で2分を超えた（この道具は何度も回すので、遅いと回さなくなる＝検査が死ぬ）。"""
    return re.compile('|'.join(re.escape(q) for q in sorted(phrases, key=len, reverse=True)), re.I)


def scan(t, phrases, vre=None):
    p = os.path.join(CACHE, f'{t}.txt')
    if not os.path.exists(p):
        return None
    s = open(p, encoding='utf-8', errors='ignore').read()
    if len(s) < 5000:
        return None
    hits = []
    seen = set()
    for m in SENT.finditer(s):
        snt = m.group(0).strip()
        if NOISE.search(snt):
            continue
        names = [n for r, n in BEAR_RE if r.search(snt)]
        vp = ([m2.group(0).lower() for m2 in vre.finditer(snt)][:3] if vre else [])
        if not names and not vp:
            continue
        if ONTO.search(snt):
            names = [n + '(⚠ONTO型が同居)' for n in names]
        k = snt[:70]
        if k in seen:
            continue
        seen.add(k)
        hits.append(dict(s=snt[:520], why=names + vp,
                         onto=bool(ONTO.search(snt)), self=bool(SELF.search(snt))))
    # 強さ＝ONTO/自社側でない当たりの数
    strong = sum(1 for h in hits if not h['onto'] and not h['self'])
    return dict(t=t, n=len(hits), strong=strong, chars=len(s), hits=hits[:12])


def main():
    only = None
    if '--t' in sys.argv:
        only = set(sys.argv[sys.argv.index('--t') + 1].split(','))
    allf = '--all' in sys.argv
    as_json = '--json' in sys.argv
    ph = vocab_phrases()
    vre = vocab_re(ph)
    tg = targets()
    res, miss = [], []
    for x in tg:
        if only and x['t'] not in only:
            continue
        r = scan(x['t'], ph, vre)
        if r is None:
            miss.append(x['t']); continue
        r.update(s=x['s'], moat=x['moat'], buy=x['buy'])
        res.append(r)
    res.sort(key=lambda r: (-r['strong'], -r['s']))
    if as_json:
        print(json.dumps(dict(n=len(res), missing=miss, rows=res), ensure_ascii=False, indent=1))
        return 0
    print(f'■ 台帳の irr=70 を **85の語彙**で screen（{len(res)}社・語彙 {len(ph)}本＋構文 {len(BEAR)}本）')
    print(f'  ⚠ 原本のキャッシュが無くて測れない {len(miss)}社: ' + ' '.join(miss[:20]))
    print('  ⚠ **これは判定ではない。読む先を絞る道具**——当たっても向きと射程は原本で裁くこと\n')
    show = res if allf else [r for r in res if r['strong'] > 0][:25]
    for r in show:
        flag = '★' if (r['moat'] >= 66 and r['s'] >= 70) else ' '
        print(f"{flag}{r['t']:6} Ω{r['s']:5.1f} 堀{r['moat']:5.1f} buy={str(r['buy']):5} "
              f"当たり{r['n']:3}（うち向きが良い {r['strong']:2}）")
        for h in r['hits'][:2]:
            if h['onto'] or h['self']:
                continue
            print(f"     [{'/'.join(h['why'][:2])}] {h['s'][:210]}")
    print(f"\n★印 = 堀66+ かつ Ω70+ ＝**85なら関門を通りうる社**")
    return 0


if __name__ == '__main__':
    sys.exit(main())
