import datetime as D, hashlib, html, json, os, subprocess, sys, tempfile, time
from pathlib import Path
from urllib.parse import quote, urlparse
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

TARGET='https://github.com/kivymd/KivyMD'; OUT=Path('kivymd-program-result.json'); PAGE=Path('kivymd-program-view.html')
app=FastAPI(title='ProjectAtlas',version='1.0')
class Req(BaseModel): input:str
def now(): return D.datetime.now(D.UTC).isoformat()
def resolve(u):
 p=urlparse(u); a=[x for x in p.path.split('/') if x]
 if p.scheme not in ('http','https') or (p.hostname or '').lower() not in ('github.com','www.github.com') or len(a)<2: raise ValueError('GitHub URL required')
 o,r=a[0],a[1].removesuffix('.git'); c=f'https://github.com/{o}/{r}'
 return {'id':'res_'+hashlib.sha256(c.encode()).hexdigest()[:20],'canonical_url':c,'type':'repository','name':f'{o}/{r}','owner':o,'repo':r}
def get(c,src,url,**kw):
 x=c.get(url,**kw)
 if x.status_code>=400: raise RuntimeError(f'{src} HTTP {x.status_code}: {x.text[:160]}')
 return x.json()
def analyze(res):
 obs={}; err=[]
 def add(k,v,s,u):
  if v is not None: obs[k]={'value':v,'source':s,'source_url':u,'confidence':1.0,'observed_at':now()}
 h={'User-Agent':'ProjectAtlas-KivyMD-Live/1.0','Accept':'application/json'}
 if os.getenv('GITHUB_TOKEN'): h['Authorization']='Bearer '+os.environ['GITHUB_TOKEN']
 with httpx.Client(timeout=30,headers=h,follow_redirects=True) as c:
  u=f"https://api.github.com/repos/{res['owner']}/{res['repo']}"
  try:
   d=get(c,'github',u,headers={'X-GitHub-Api-Version':'2022-11-28'}); m={'full_name':'repository.full_name','description':'repository.description','stargazers_count':'repository.stars','forks_count':'repository.forks','open_issues_count':'repository.open_issues','archived':'repository.archived','default_branch':'repository.default_branch','language':'repository.language','topics':'repository.topics','created_at':'repository.created_at','updated_at':'repository.updated_at','pushed_at':'repository.pushed_at','homepage':'repository.homepage','visibility':'repository.visibility','size':'repository.size_kb','subscribers_count':'repository.subscribers','watchers_count':'repository.watchers','fork':'repository.is_fork'}
   for x,k in m.items(): add(k,d.get(x),'github',u)
   add('repository.license',(d.get('license')or{}).get('spdx_id'),'github',u); add('repository.owner',(d.get('owner')or{}).get('login'),'github',u); add('repository.owner_type',(d.get('owner')or{}).get('type'),'github',u)
  except Exception as e: err.append({'provider':'github','message':str(e)})
  u=f"https://repos.ecosyste.ms/api/v1/hosts/GitHub/repositories/{quote(res['owner']+'/'+res['repo'],safe='')}"
  try:
   d=get(c,'ecosyste.ms',u); add('ecosystems.score',d.get('score'),'ecosyste.ms',u); add('ecosystems.status',d.get('status'),'ecosyste.ms',u); add('ecosystems.last_synced_at',d.get('last_synced_at'),'ecosyste.ms',u); add('ecosystems.metadata',d,'ecosyste.ms',u)
  except Exception as e: err.append({'provider':'ecosyste.ms','message':str(e)})
  u=f"https://api.securityscorecards.dev/projects/github.com/{res['owner']}/{res['repo']}"
  try:
   d=get(c,'scorecard',u); add('scorecard.score',d.get('score'),'scorecard',u); add('scorecard.date',d.get('date'),'scorecard',u); add('scorecard.checks',{x.get('name'):x.get('score') for x in d.get('checks',[])},'scorecard',u)
  except Exception as e: err.append({'provider':'scorecard','message':str(e)})
 return obs,err
def V(o,k,d=None): return (o.get(k)or{}).get('value',d)
def present(r,o,e,status):
 src=sorted({x['source'] for x in o.values()}); keys=[]
 for x in [V(o,'repository.language'),*(V(o,'repository.topics',[])or[])]:
  if x and x not in keys: keys.append(x)
 return {'title':V(o,'repository.full_name',r['name']),'type_label':'GitHub-projekt','status':status,'description':V(o,'repository.description','Ingen verifierad beskrivning.'),'category':'Programvaruutveckling → UI-ramverk och komponentbibliotek','keywords':keys,'metrics':{'stars':V(o,'repository.stars'),'forks':V(o,'repository.forks'),'watchers':V(o,'repository.watchers'),'open_issues':V(o,'repository.open_issues'),'scorecard':V(o,'scorecard.score')},'project':{'owner':V(o,'repository.owner'),'owner_type':V(o,'repository.owner_type'),'language':V(o,'repository.language'),'license':V(o,'repository.license'),'default_branch':V(o,'repository.default_branch'),'archived':V(o,'repository.archived'),'created_at':V(o,'repository.created_at'),'updated_at':V(o,'repository.updated_at'),'pushed_at':V(o,'repository.pushed_at'),'homepage':V(o,'repository.homepage')},'verification':{'level':'E2' if len(src)>1 else 'E1','status':'Verifierad' if status=='completed' else 'Delvis verifierad','detail':'ProjectAtlas hämtade repositorymetadata, oberoende ekosystemmetadata och publicerad OpenSSF Scorecard för samma repository.'},'sources':src,'errors':e,'canonical_url':r['canonical_url'],'checked_at':now(),'resource_id':r['id'],'observation_count':len(o),'scorecard_checks':V(o,'scorecard.checks',{})}
def render(p):
 E=lambda x:html.escape(str(x)) if x is not None else '—'; ms=''.join(f"<div class=m><small>{E(n)}</small><b>{E(p['metrics'][k])}</b></div>" for k,n in [('stars','Stjärnor'),('forks','Forks'),('watchers','Watchers'),('open_issues','Öppna ärenden'),('scorecard','Scorecard')]); tags=''.join(f'<i>{E(x)}</i>' for x in p['keywords']); facts=''.join(f'<p><span>{E(a)}</span><b>{E(b)}</b></p>' for a,b in [('Ägare',p['project']['owner']),('Huvudspråk',p['project']['language']),('Licens',p['project']['license']),('Standardgren',p['project']['default_branch']),('Arkiverat','Ja' if p['project']['archived'] else 'Nej'),('Senaste push',p['project']['pushed_at']),('Kontrollerad',p['checked_at'])]); checks=''.join(f'<tr><td>{E(k)}</td><td>{E(v)}</td></tr>' for k,v in sorted(p['scorecard_checks'].items())); sources=' · '.join(E(x) for x in p['sources'])
 return f'''<!doctype html><html lang=sv><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>{E(p['title'])}</title><style>*{{box-sizing:border-box}}body{{margin:0;background:#f3f5f8;color:#182033;font:15px/1.55 system-ui}}main{{max-width:1050px;margin:45px auto;padding:20px}}section{{background:white;border:1px solid #dde2e9;border-radius:18px;padding:28px;margin:16px 0;box-shadow:0 10px 30px #14213d10}}h1{{font-size:38px;margin:5px 0}}h2{{margin-top:0}}.ok{{display:inline-block;background:#e8f7f1;color:#137657;padding:7px 12px;border-radius:99px;font-weight:700}}.lead{{font-size:18px;max-width:800px}}i{{display:inline-block;background:#edf0ff;color:#4052c8;border-radius:99px;padding:6px 10px;margin:3px;font-style:normal}}.metrics{{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin-top:20px}}.m{{border:1px solid #dde2e9;border-radius:12px;padding:14px}}.m small{{display:block;color:#657085}}.m b{{font-size:24px}}.grid{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}.facts p{{display:flex;justify-content:space-between;border-bottom:1px solid #eee;padding:9px 0}}.facts span{{color:#657085}}table{{width:100%;border-collapse:collapse}}td{{border-bottom:1px solid #eee;padding:8px}}td:last-child{{text-align:right;font-weight:700}}pre{{white-space:pre-wrap;background:#111827;color:#e5e7eb;padding:15px;border-radius:12px;font-size:12px}}@media(max-width:750px){{.grid{{grid-template-columns:1fr}}.metrics{{grid-template-columns:repeat(2,1fr)}}}}</style><main><section><small>GITHUB-PROJEKT · PROJECTATLAS-ANALYS</small><h1>{E(p['title'])}</h1><span class=ok>● {E(p['verification']['status'])}</span><p class=lead>{E(p['description'])}</p><p><b>Kategori:</b> {E(p['category'])}</p>{tags}<div class=metrics>{ms}</div></section><div class=grid><section><h2>Projektinformation</h2><div class=facts>{facts}</div></section><section><h2>Verifiering</h2><p><b>{E(p['verification']['level'])} · flera källor</b></p><p>{E(p['verification']['detail'])}</p><p><b>Källor:</b> {sources}</p><a href="{E(p['canonical_url'])}">Öppna repository →</a></section></div><section><h2>OpenSSF Scorecard</h2><table>{checks}</table></section><section><details><summary><b>Tekniska detaljer och evidens</b></summary><pre>{E(json.dumps(p,ensure_ascii=False,indent=2))}</pre></details></section></main></html>'''
@app.get('/health/ready')
def health(): return {'status':'ready'}
@app.post('/v1/analyze')
def endpoint(q:Req):
 try:r=resolve(q.input)
 except ValueError as e: raise HTTPException(422,str(e))
 o,e=analyze(r); status='completed' if not e else ('partial' if o else 'failed'); p=present(r,o,e,status); return {'resource':r,'analysis':{'id':'run_'+hashlib.sha256((r['canonical_url']+now()).encode()).hexdigest()[:20],'status':status,'errors':e,'completed_at':now()},'observations':o,'presentation':p}
@app.post('/v1/render',response_class=HTMLResponse)
def view(q:Req):
 x=endpoint(q); return HTMLResponse(render(x['presentation']))
def validate():
 env=os.environ.copy(); s=subprocess.Popen([sys.executable,__file__,'serve'],env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
 try:
  with httpx.Client(timeout=45) as c:
   for _ in range(120):
    try:
     if c.get('http://127.0.0.1:8000/health/ready').status_code==200: break
    except: pass
    time.sleep(.25)
   x=c.post('http://127.0.0.1:8000/v1/analyze',json={'input':TARGET}); x.raise_for_status(); d=x.json(); required={'repository.full_name','repository.description','repository.stars','repository.forks','ecosystems.metadata','scorecard.score','scorecard.checks'}; missing=sorted(required-set(d['observations']))
   if d['analysis']['status']!='completed' or d['analysis']['errors'] or missing: raise RuntimeError(f"incomplete: {d['analysis']} missing={missing}")
   h=c.post('http://127.0.0.1:8000/v1/render',json={'input':TARGET}); h.raise_for_status(); OUT.write_text(json.dumps(d,ensure_ascii=False,indent=2)); PAGE.write_text(h.text); print(json.dumps({'status':'passed','analysis':d['analysis'],'presentation':d['presentation'],'fields':sorted(d['observations'])},ensure_ascii=False,indent=2))
 finally:s.terminate(); s.wait(timeout=10)
if __name__=='__main__':
 if len(sys.argv)>1 and sys.argv[1]=='serve':
  import uvicorn; uvicorn.run(app,host='127.0.0.1',port=8000)
 else: validate()
