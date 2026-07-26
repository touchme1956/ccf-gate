# -*- coding: utf-8 -*-
"""14社の10-K原本から v4審査に要る3点を機械抽出:
   ①Competition節(実名競合) ②市場シェア%の自社開示 ③乗換コストの年数/金額記載"""
import re,time,json,os,urllib.request
EMAIL="fortis5280@gmail.com"
HDRS={"User-Agent":f"hachimon-gate {EMAIL}"}
T=["NVDA","MSFT","RMD","V","CTAS","MA","IDXX","ADBE","WDFC","JKHY","WTS","KLAC","ASML","IRMD"]
def url_of(t):
    with open(f"out/{t}_hits.txt",encoding="utf-8",errors="ignore") as f:
        for line in f:
            if line.startswith("http"): return line.strip()
    return None
def clean(h):
    h=re.sub(r'(?is)<(script|style|table)[^>]*>.*?</\1>',' ',h)
    h=re.sub(r'(?s)<[^>]+>',' ',h)
    h=h.replace('&#160;',' ').replace('&nbsp;',' ').replace('&amp;','&').replace('&#8217;',"'").replace('&#8212;','—').replace('&#39;',"'").replace('&quot;','"')
    return re.sub(r'\s+',' ',h)
SHARE=re.compile(r"[^.]{0,220}\b(?:market share|share of (?:the )?(?:global |worldwide )?market|leading (?:global )?(?:market )?position|we are the (?:largest|leading)|number one|#1)\b[^.]{0,220}\.",re.I)
SWITCH=re.compile(r"[^.]{0,220}\b(?:switching cost|cost(?:s)? (?:of|to) switch|convert(?:ing)? to (?:a )?(?:new|competing)|migrat\w+ to (?:a )?(?:new|competing|another)|requalif\w+|re-qualif\w+|qualification (?:process|period|cycle)|long-term contracts? (?:of|with) [^.]{0,40}years|multi-year (?:contract|agreement))\b[^.]{0,220}\.",re.I)
out={}
for t in T:
    u=url_of(t)
    if not u: out[t]={"err":"no url"}; continue
    try:
        req=urllib.request.Request(u,headers=HDRS)
        raw=urllib.request.urlopen(req,timeout=90).read().decode("utf-8","ignore")
    except Exception as e:
        out[t]={"err":str(e)[:120]}; time.sleep(0.5); continue
    txt=clean(raw)
    # Competition節
    comp=""
    for m in re.finditer(r"Competition",txt):
        seg=txt[m.start():m.start()+2600]
        if re.search(r"(?i)compet(e|itors|ition)",seg) and len(seg)>400:
            # 実名らしさ: 大文字連語が多い節を選ぶ
            names=re.findall(r"\b[A-Z][A-Za-z&.\-]+(?: [A-Z][A-Za-z&.\-]+){0,3}\b(?=,| and |;|\.)",seg)
            if len(names)>8: comp=seg; break
    if not comp:
        m=re.search(r"(?i)(?:we (?:face|encounter) (?:intense |significant |substantial )?competition|competitive landscape|our (?:principal |primary |main )?competitors)",txt)
        if m: comp=txt[max(0,m.start()-200):m.start()+2200]
    out[t]={"url":u,"len":len(txt),
            "competition":comp[:2400],
            "share":[s.strip()[:300] for s in SHARE.findall(txt)][:6],
            "switch":[s.strip()[:300] for s in SWITCH.findall(txt)][:6]}
    time.sleep(0.35)
json.dump(out,open("out/us_v4/raw_evidence.json","w"),ensure_ascii=False,indent=1)
for t in T:
    d=out[t]
    print(f"### {t}  {'ERR:'+d['err'] if 'err' in d else str(d['len'])+'字'}  share_hits={len(d.get('share',[]))} switch_hits={len(d.get('switch',[]))} comp={'有' if d.get('competition') else '無'}")
