import math, importlib.util, sys
spec=importlib.util.spec_from_file_location("e","engine_sim.py"); src=open("engine_sim.py").read().split("R=[]")[0]
ns={}; exec(src,ns)
def arc_track(r,deg,sign):
    # straight 300 mm, then arc of radius r turning deg (sign +1 left, -1 right), then straight 600
    pts=[(0.0,0.0),(300.0,0.0)]; cx,cy=300.0,sign*r
    for k in range(1,61):
        a=math.radians(deg*k/60); pts.append((cx+r*math.sin(a), cy-sign*r*math.cos(a)))
    hx,hy=math.cos(math.radians(sign*deg)),math.sin(math.radians(sign*deg))
    ex,ey=pts[-1]; pts.append((ex+600*hx, ey+600*hy))
    return list(zip(pts[:-1],pts[1:])), (ex+500*hx, ey+500*hy)
for scale in (0.5,1.0):
    ns['SCALE']=scale
    print("== motor scale",scale)
    tests=[("straight 8mm/5deg off",ns['straight'](),(-200,8),math.radians(5),(1800,0)),
           ("dashed 30/20",ns['dashed'](),(-200,0),0,(1800,0)),
           ("crossing",ns['crossing'](),(-200,0),0,(1800,0)),
           ("90 right",ns['corner90'](-1),(-200,0),0,(800,-700)),
           ("90 left",ns['corner90'](1),(-200,0),0,(800,700))]
    for r,deg,sg,name in ((300,90,1,"curve r300 left"),(150,90,-1,"curve r150 right"),(100,180,1,"hairpin r100"),(60,180,-1,"hairpin r60")):
        segs,goal=arc_track(r,deg,sg); tests.append((name,segs,(-200,0),0,goal))
    for name,segs,start,h,goal in tests:
        r=ns['run'](segs,start,h,goal,tmax=90,label=name)
        print(f"  {name:24s} {'PASS' if r['ok'] else 'FAIL'}  t={r['t']:6.2f}s maxdev={r['maxdev']:5.1f}mm lost_max={r['lostmax']:.2f}s  {','.join(r['ev'])}")
