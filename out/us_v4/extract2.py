# -*- coding: utf-8 -*-
import re,time,json,urllib.request
EMAIL="fortis5280@gmail.com"; HDRS={"User-Agent":f"hachimon-gate {EMAIL}"}
T=["NVDA","MSFT","RMD","V","CTAS","MA","IDXX","ADBE","WDFC","JKHY","WTS","KLAC","ASML","IRMD"]
def url_of(t):
    for line in open(f"out/{t}_hits.txt",encoding="utf-8",errors="ignore"):
        if line.startswith("http"): return line.strip()
def clean(h):
    h=re.sub(r'(?is)<(script|style|table)[^>]*>.*?</\1>',' ',h); h=re.sub(r'(?s)<[^>]+>',' ',h)
    for a,b in [('&#160;',' '),('&nbsp;',' '),('&amp;','&'),('&#8217;',"'"),('&#8220;','"'),('&#8221;','"'),('&#8211;','-')]: h=h.replace(a,b)
    return re.sub(r'\s+',' ',h)
PAT={
 "唯一供給":r"[^.]{0,200}\b(?:sole (?:supplier|source|provider)|only (?:supplier|company|manufacturer|producer) (?:in the world |globally )?(?:that|who|to|able)|we are the only|no (?:other|alternative) (?:supplier|source)|exclusive(?:ly)? suppl)\b[^.]{0,200}\.",
 "認証規制":r"[^.]{0,200}\b(?:FDA (?:510\(k\)|clearance|approval|premarket)|CE mark|regulatory approval (?:is )?required|certif\w+ (?:by|process|requirement)|qualified (?:by|with) (?:our )?customers|qualification (?:process|cycle|period)|design(?:ed)?[- ]in\b)\b[^.]{0,200}\.",
 "長期契約":r"[^.]{0,180}\b(?:(?:contracts?|agreements?) (?:typically |generally |usually )?(?:have|with|for) (?:initial )?terms? of (?:approximately )?(?:one|two|three|four|five|six|seven|\d+)[- ](?:to[- ](?:\w+)[- ])?year|multi[- ]year (?:contracts?|agreements?)|five[- ]year (?:contract|agreement|term)|renewal rate)\b[^.]{0,180}\.",
 "両側実数":r"[^.]{0,180}\b(?:(?:\d[\d,\.]*\s*(?:million|billion))\s+(?:merchants?|cards?|acceptance locations?|active accounts?|financial institutions?|developers?|installed (?:base|systems?)))\b[^.]{0,180}\.",
 "シェア数値":r"[^.]{0,180}\b(?:market share of (?:approximately )?\d|approximately \d{1,2}% (?:market )?share|\d{1,2}% (?:of the (?:global |worldwide )?market|market share))\b[^.]{0,180}\.",
}
out={}
for t in T:
    try: raw=urllib.request.urlopen(urllib.request.Request(url_of(t),headers=HDRS),timeout=90).read().decode("utf-8","ignore")
    except Exception as e: out[t]={"err":str(e)[:100]}; continue
    txt=clean(raw); r={}
    for k,p in PAT.items():
        hits=[re.sub(r'\s+',' ',m).strip()[:290] for m in re.findall(p,txt,re.I)]
        seen=[];
        for h in hits:
            if not any(h[:60]==s[:60] for s in seen): seen.append(h)
        r[k]=seen[:3]
    out[t]=r; time.sleep(0.35)
json.dump(out,open("out/us_v4/evidence2.json","w"),ensure_ascii=False,indent=1)
for t in T:
    print("="*66); print("###",t)
    for k,v in out[t].items():
        if k=="err": print("  ERR",v); continue
        if v:
            print(f"  [{k}]")
            for s in v: print("   *",s)
