#!/usr/bin/env python3
"""night/angles_insider.py — 事前登録 out/angles4_prereg.json の B1（内部者の買い）の採取

SEC Insider Transactions Data Sets（_angles_data/{q}_form345.zip・gitignore）から、アンカー前12ヶ月に提出された
Form 4 のうち、役員・取締役（関係に Director / Officer を含む）による市場での買い（TRANS_CODE='P'）を、
発行体CIKごとに『買った人の数』『株数×単価の合計』で数える。データセットは全件なので買いの無い社は0（欠測ではない）。

使い方: python3 night/angles_insider.py   出力: out/angles_insider.json
"""
import csv, io, json, os, zipfile, datetime as dt

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(BASE, '_angles_data')
ANCH = {'2013': ['2012q3', '2012q4', '2013q1', '2013q2'], '2018': ['2017q3', '2017q4', '2018q1', '2018q2']}
csv.field_size_limit(1 << 30)

def tsv(z, name):
    with z.open(name) as f:
        yield from csv.DictReader(io.TextIOWrapper(f, 'utf-8', errors='ignore'), delimiter='\t', quoting=csv.QUOTE_NONE)

def pdate(s):
    try: return dt.datetime.strptime(s, '%d-%b-%Y').date()
    except Exception: return None

def main():
    out = {}
    for Y, qs in ANCH.items():
        lo, hi = dt.date(int(Y) - 1, 7, 1), dt.date(int(Y), 6, 30)
        buyers, value, filings = {}, {}, {}
        for q in qs:
            z = zipfile.ZipFile(os.path.join(D, f'{q}_form345.zip'))
            sub = {}
            for r in tsv(z, 'SUBMISSION.tsv'):
                d = pdate(r['FILING_DATE'])
                if r['DOCUMENT_TYPE'] in ('4', '4/A') and d and lo <= d <= hi:
                    sub[r['ACCESSION_NUMBER']] = int(r['ISSUERCIK'])
            own = {}
            for r in tsv(z, 'REPORTINGOWNER.tsv'):
                if r['ACCESSION_NUMBER'] in sub and any(k in (r['RPTOWNER_RELATIONSHIP'] or '') for k in ('Director', 'Officer')):
                    own.setdefault(r['ACCESSION_NUMBER'], set()).add(r['RPTOWNERCIK'])
            for r in tsv(z, 'NONDERIV_TRANS.tsv'):
                a = r['ACCESSION_NUMBER']
                if a in own and r['TRANS_CODE'] == 'P' and r.get('TRANS_ACQUIRED_DISP_CD') == 'A':
                    c = sub[a]
                    buyers.setdefault(c, set()).update(own[a])
                    try: value[c] = value.get(c, 0) + float(r['TRANS_SHARES'] or 0) * float(r['TRANS_PRICEPERSHARE'] or 0)
                    except ValueError: pass
            for a, c in sub.items(): filings[c] = filings.get(c, 0) + 1
        out[Y] = {str(c): dict(buyers=len(b), value=round(value.get(c, 0))) for c, b in buyers.items()}
        out[Y + '_filers'] = sorted(str(c) for c in filings)  # アンカー前12ヶ月に Form 4 を出した発行体（被覆の確認用）
        print(Y, '買いのあった発行体', len(out[Y]), '／Form 4 を出した発行体', len(filings))
    json.dump(dict(generated=dt.date.today().isoformat(), tool='night/angles_insider.py', prereg='out/angles4_prereg.json', **out),
              open(os.path.join(BASE, 'out', 'angles_insider.json'), 'w'))

if __name__ == '__main__':
    main()
