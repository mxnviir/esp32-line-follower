import math, sys
lag=open("engine_sim_lag.py").read()
CORNER="        if st['sc']<CMEM and st['lt']<SMAXT: events.add('corner>');"
def build(spot,tau,new,kd):
    src=lag.replace("LINEW/2+9.0","LINEW/2+%s"%spot).replace("TAU=0.3;","TAU=%s;"%tau).replace("KD=0.6;","KD=%s;"%kd)
    assert "KD=%s;"%kd in src
    def R(a,b):
        nonlocal src
        assert src.count(a)==1, a[:60]; src=src.replace(a,b)
    R("ds=(cvL+cvR)/2*DT; dth=(cvL-cvR)/W*DT","ds=(cvL+cvR)/2*DT; dth=(cvL-cvR)/W*DT; st['rd']=st.get('rd',0)+max(0,ds); st['rh']=st.get('rh',0)+dth; st['post']=max(0,st.get('post',0)-abs(ds))")
    R("            raw=online(cx+SX[i]*rx, cy+SX[i]*ry, segs)\n",
      "            raw=online(cx+SX[i]*rx, cy+SX[i]*ry, segs)\n            if raw and i==0: st['lseen']=st.get('rd',0)\n            if raw and i==4: st['rseen']=st.get('rd',0)\n")
    PIV = "tpiv" if new else "piv"
    R(CORNER, "        la=st.get('rd',0)-st.get('lseen',-1e9); ra=st.get('rd',0)-st.get('rseen',-1e9)\n        if min(la,ra)<80 and st['lt']<SMAXT: events.add('side'); %s(-1 if la<=ra else 1); continue\n"%PIV+CORNER)
    R("        if not st['lost']:\n            st.update(","        if not st['lost']:\n            st['nl']=st.get('nl',0)+1\n            st.update(")
    R("return dict(label=label,ok=True,","return dict(nl=st.get('nl',0),label=label,ok=True,")
    R("return dict(label=label,ok=False,","return dict(nl=st.get('nl',0),label=label,ok=False,")
    if new:
        R("    def piv(d): setm(d*SEARCH,-d*SEARCH)","""    def piv(d): setm(d*SEARCH,-d*SEARCH)
    def tpiv(d):
        if st.get('td',0)!=d: st['td']=d; st['th0']=st.get('rh',0)
        setm(d*SEARCH,-d*SEARCH)""")
        R("c=KP*e+KI*st['ig']+KD*d; st['le']=e\n        setm(b+int(c),b-int(c))",
          "c=KP*e+KI*st['ig']+KD*d; st['le']=e\n        if st.get('post',0)>0: c=max(-60,min(60,c))\n        setm(b+int(c),b-int(c))")
        R("        if n:\n            pos=int(s/n)","""        if t<st.get('bu',0):
            st['cl']=0; st['cr']=0; continue
        if n and st.get('td',0)!=0:
            turned=abs(math.degrees(st.get('rh',0)-st['th0']))
            if not (mask & 0b01110) and turned<SMAXT:
                sp=int(SEARCH*0.6); setm(st['td']*sp,-st['td']*sp); continue
            st['td']=0; st['bu']=t+0.06; st['post']=60; st['cl']=0; st['cr']=0
            st['lost']=False; st['le']=int(s/n); st['ig']=0; st['have']=False; st['lineX']=(int(s/n))*PITCH/1000
            continue
        if n:
            pos=int(s/n)""")
        R("events.add('corner>'); o=SEARCH; i_=int(SEARCH*-1.0); (setm(o,i_) if st['cd']>0 else setm(i_,o)); continue",
          "events.add('corner>'); tpiv(st['cd']); continue")
        R("            if st['lineX']>max(SX)+PIVM: piv(1)\n            elif st['lineX']<min(SX)-PIVM: piv(-1)\n            else: e=",
          "            if st['lineX']>max(SX)+PIVM: tpiv(1)\n            elif st['lineX']<min(SX)-PIVM: tpiv(-1)\n            else:\n                st['td']=0; e=")
    return src
def arc_track(r,deg,sign):
    pts=[(0.0,0.0),(300.0,0.0)]; cx,cy=300.0,sign*r
    for k in range(1,61):
        a=math.radians(deg*k/60); pts.append((cx+r*math.sin(a), cy-sign*r*math.cos(a)))
    hx,hy=math.cos(math.radians(sign*deg)),math.sin(math.radians(sign*deg))
    ex,ey=pts[-1]; pts.append((ex+600*hx, ey+600*hy))
    return list(zip(pts[:-1],pts[1:])), (ex+500*hx, ey+500*hy)
def tests(ns):
    T=[("straight",ns['straight'](),(-200,8),math.radians(5),(1800,0)),
       ("dashed",ns['dashed'](),(-200,0),0,(1800,0)),
       ("crossing",ns['crossing'](),(-200,0),0,(1800,0)),
       ("90R",ns['corner90'](-1),(-200,0),0,(800,-700)),
       ("90L",ns['corner90'](1),(-200,0),0,(800,700))]
    for r,deg,sg,name in ((300,90,1,"r300L"),(150,90,-1,"r150R"),(100,90,1,"r100L"),(70,90,-1,"r70R"),(100,180,1,"hp100"),(60,180,-1,"hp60")):
        segs,goal=arc_track(r,deg,sg); T.append((name,segs,(-200,0),0,goal))
    return T
if __name__=="__main__":
    print("fails / total time / line losses on the two 90-degree corners / max deviation there")
    for scale in (0.5,1.0):
      for tau in (0.0,0.15):
        for kd in (0.6,0.3):
          line=f"scale {scale} lag {tau:4.2f} Kd {kd} |"
          for new in (False,True):
            ns={}; exec(build(9.0,tau,new,kd), ns); ns['SCALE']=scale
            res=[ns['run'](segs,start,h,goal,tmax=90,label=name) for name,segs,start,h,goal in tests(ns)]
            fails=[r['label'] for r in res if not r['ok']]
            tot=sum(r['t'] for r in res)
            nl90=sum(r['nl'] for r in res if r['label'] in ("90R","90L"))
            mx90=max(r['maxdev'] for r in res if r['label'] in ("90R","90L"))
            line+=f" {'NEW' if new else 'OLD'}: {len(fails)}F {tot:6.1f}s loss90={nl90} dev90={mx90:5.1f} {fails if fails else ''}|"
          print(line, flush=True)
