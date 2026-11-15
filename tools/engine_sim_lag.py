# Offline check of the firmware line engine (same equations/constants as AllInOne.ino).
# Robot drives in world mm; track = polyline segments; sensors = points on the row.
import math
PITCH=22.0; H=41.0; HWR=55.0; HWRAISE=5.0; TILT=31.0
W=163.0; L=185.0; D=33.0; RPM=300.0; DB=40; SLEW=10
SCALE=0.5; TAU=0.3; REALDB=70; MINPWM=70; FIX=True; BASE=150; MAXS=255; SEARCH=100; KP=0.08; KD=0.6; KI=0.0
LINEW=18.0; FILT=2; GAPMAX=60; GAPC=10; GAPANG=10; JHOLD=40; CMEM=80
PIVM=10; SMAXT=200; PMAX=300; SW0=400; CURVE=0.3; DT=0.005
hw=PITCH+HWR+(H+HWRAISE)*math.tan(math.radians(TILT))
SX=[-2*PITCH,-PITCH,0,PITCH,hw]; SWT=[round(x*1000/PITCH) for x in SX]
VMAX=math.pi*D*RPM/60; MAXANG=math.radians(85)

def segdist(px,py,a,b):
    (ax,ay),(bx,by)=a,b; dx,dy=bx-ax,by-ay; t=max(0,min(1,((px-ax)*dx+(py-ay)*dy)/(dx*dx+dy*dy)))
    return math.hypot(px-(ax+t*dx),py-(ay+t*dy))
def online(px,py,segs): return any(segdist(px,py,a,b)<=LINEW/2+9.0 for a,b in segs)
def eff(c,sc):
    if c==0: return 0
    a=abs(c)*sc
    p=MINPWM+a*(255-MINPWM)/255 if FIX else a
    return -p if c<0 else p
def wheel(p):
    a=abs(p)
    if a<REALDB: return 0
    v=(a-REALDB)/(255-REALDB)*VMAX; return -v if p<0 else v

def run(segs, start, heading, goal, tmax=20, label=""):
    x,y=start; th=heading            # th: heading angle (rad, world), sensor row ahead
    st=dict(cl=0,cr=0,lineX=0,ang=0,prev=0,have=False,lost=False,ld=0,lt=0,lx=0,la=0,sw=None,
            jl=0,sc=1e9,cd=0,le=0,ig=0,filt=[False]*5,cnt=[0]*5)
    events=set(); maxdev=0; t=0.0; lostmax=0; losttime=0
    def setm(l,r):
        l=max(-MAXS,min(MAXS,l)); r=max(-MAXS,min(MAXS,r))
        def sl(c,tg):
            stp=SLEW if ((c>0 and tg<c) or (c<0 and tg>c)) else SLEW
            return c+stp if tg>c+stp else (c-stp if tg<c-stp else tg)
        st['cl']=sl(st['cl'],l); st['cr']=sl(st['cr'],r)
    def steer(e,b):
        d=e-st['le']; st['ig']=max(-1e4,min(1e4,st['ig']+e)); c=KP*e+KI*st['ig']+KD*d; st['le']=e
        setm(b+int(c),b-int(c))
    def piv(d): setm(d*SEARCH,-d*SEARCH)
    def cb(e): return int(BASE*(0.85 if st.get('rec',0)>0 else 1)*(1-CURVE*min(1,abs(e)/2000)))
    while t<tmax:
        t+=DT
        cvL=wheel(eff(st['cl'],SCALE)); cvR=wheel(eff(st['cr'],SCALE))
        k=1.0 if TAU<=0 else min(1.0, DT/TAU)
        st['avL']=st.get('avL',0)+(cvL-st.get('avL',0))*k; st['avR']=st.get('avR',0)+(cvR-st.get('avR',0))*k
        vL,vR=st['avL'],st['avR']
        ds=(vL+vR)/2*DT; dth=(vL-vR)/W*DT
        th-=dth; x+=ds*math.cos(th); y+=ds*math.sin(th)
        ds=(cvL+cvR)/2*DT; dth=(cvL-cvR)/W*DT   # + dth = turn right (clockwise)
        st['lineX']+=ds*math.tan(st['ang'])-L*dth
        st['ang']=max(-MAXANG,min(MAXANG,st['ang']-dth))
        st['sc']+=abs(ds); st['jl']=max(0,st['jl']-abs(ds)); st['rec']=max(0,st.get('rec',0)-abs(ds))
        # sensors: row centre L ahead; +x = right of heading
        cx=x+L*math.cos(th); cy=y+L*math.sin(th); rx,ry=math.sin(th),-math.cos(th)
        mask=0; s=0; n=0; mn=1e9; mx=-1e9
        for i in range(5):
            raw=online(cx+SX[i]*rx, cy+SX[i]*ry, segs)
            if raw!=st['filt'][i]:
                st['cnt'][i]+=1
                if st['cnt'][i]>=FILT: st['filt'][i]=raw; st['cnt'][i]=0
            else: st['cnt'][i]=0
            if st['filt'][i]: mask|=1<<i; s+=SWT[i]; n+=1; mn=min(mn,SX[i]); mx=max(mx,SX[i])
        dev=min(segdist(cx,cy,a,b) for a,b in segs); maxdev=max(maxdev,dev)
        if math.hypot(x-goal[0],y-goal[1])<40: return dict(label=label,ok=True,t=round(t,2),maxdev=round(maxdev,1),ev=sorted(events),lostmax=round(lostmax,2))
        if n:
            pos=int(s/n); mX=pos*PITCH/1000; half=PITCH/2
            ev='L'
            if n>=2 and mx-mn>LINEW+half: ev='J' if (mn<-half and mx>half) else ('>' if mx>half else '<')
            events.add(ev)
            if st['lost']: st['lost']=False; st['le']=pos; st['ig']=0; st['have']=False; losttime=0; st['rec']=30
            if ev=='J': st['jl']=JHOLD; st['lineX']=0; st['ang']=0
            elif ev in '<>':
                st['cd']=1 if ev=='>' else -1; st['sc']=0; st['lineX']=mX; st['ang']=st['cd']*MAXANG; st['have']=False
            else:
                if st['have'] and abs(ds)>0.5:
                    obs=math.atan((mX-st['prev']+L*dth)/ds); st['ang']=max(-MAXANG,min(MAXANG,0.8*st['ang']+0.2*obs))
                st['lineX']=mX; st['prev']=mX; st['have']=True
            if st['jl']>0:
                c=[SWT[i] for i in (1,2,3) if mask&(1<<i)]; steer(int(sum(c)/len(c)) if c else 0,BASE)
            elif ev in '<>': steer(st['cd']*2000,cb(2000))
            else: steer(pos,cb(pos))
            continue
        losttime+=DT; lostmax=max(lostmax,losttime)
        if not st['lost']:
            st.update(lost=True,ld=0,lt=0,lx=st['lineX'],la=st['ang'],sw=None)
        st['ld']+=abs(ds); st['lt']+=abs(math.degrees(dth))
        if st['sc']<CMEM and st['lt']<SMAXT: events.add('corner>'); o=SEARCH; i_=int(SEARCH*-1.0); (setm(o,i_) if st['cd']>0 else setm(i_,o)); continue
        if abs(st['lx'])<GAPC and abs(st['la'])<math.radians(GAPANG) and st['ld']<GAPMAX:
            events.add('gap'); setm(BASE,BASE); continue
        if st['lt']<SMAXT and st['ld']<PMAX:
            events.add('predict')
            if st['lineX']>max(SX)+PIVM: piv(1)
            elif st['lineX']<min(SX)-PIVM: piv(-1)
            else: e=st['lineX']*1000/PITCH; steer(e,min(cb(e),int(BASE*0.8)))
            continue
        events.add('sweep')
        if st['sw'] is None: st['sw']=t
        tt=(t-st['sw'])*1000; ln=SW0; s0=0; d=-1 if st['lineX']>=0 else 1
        while tt>=s0+ln: s0+=ln; ln*=2; d=-d
        piv(d)
    return dict(label=label,ok=False,t=tmax,maxdev=round(maxdev,1),ev=sorted(events),lostmax=round(lostmax,2),end=(round(x),round(y)))

def straight(): return [((0,0),(2000,0))]
def dashed():
    segs=[]; xx=0
    while xx<2000: segs.append(((xx,0),(xx+30,0))); xx+=50   # 30 on / 20 off
    return segs
def corner90(sign): return [((0,0),(800,0)),((800,0),(800,sign*800))]   # sign -1 = right turn
def arc(r,deg,sign):
    pts=[(0,0),(300,0)]; cx,cy=300,sign*r
    for k in range(1,41):
        a=math.radians(deg*k/40); pts.append((cx+r*math.sin(a), cy-sign*r*math.cos(a)))
    ex,ey=pts[-1]; a=math.radians(deg); pts.append((ex+400*math.cos(-sign*a*-1 if False else 0)+0,ey))
    return list(zip(pts[:-2],pts[1:-1]))
def crossing(): return [((0,0),(2000,0)),((800,-300),(800,300))]


