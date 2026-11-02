"""Rebuild the four-page, two-column report and vector figures from saved evidence.

Only ReportLab is required. No network, model inference or local run directory
is used. Every figure is rebuilt from the submitted ZIP/CSV evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import statistics as stats
import zipfile
from html import escape
from pathlib import Path

from reportlab.graphics import renderPDF, renderSVG
from reportlab.graphics.shapes import Drawing, Rect, Line, String, Polygon, Circle
from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY, TA_LEFT
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Paragraph, Table, TableStyle

ROOT = Path(__file__).resolve().parents[1]
INK, MUTED, RULE = [colors.HexColor(c) for c in ['#17212b','#52606c','#cbd2d9']]
BLUE, AMBER, TEAL = [colors.HexColor(c) for c in ['#2366a1','#c37a24','#247f78']]
PALE_BLUE, PALE_AMBER, PALE_TEAL = [colors.HexColor(c) for c in ['#eef4fa','#fbf3e6','#edf6f3']]
WHITE = colors.white
W, H, MARGIN, GAP = 612, 792, 43, 20
FULL = W - 2 * MARGIN
COL = (FULL - GAP) / 2


def text(d, x, y, value, size=8, color=INK, font='Helvetica', anchor='start'):
    d.add(String(x,y,str(value),fontName=font,fontSize=size,fillColor=color,textAnchor=anchor))


def line(d,x1,y1,x2,y2,color=RULE,width=.65):
    d.add(Line(x1,y1,x2,y2,strokeColor=color,strokeWidth=width))


def arrow(d,x1,y1,x2,y2,color=MUTED,width=.8,head=4):
    line(d,x1,y1,x2,y2,color,width)
    a=math.atan2(y2-y1,x2-x1)
    d.add(Polygon([x2,y2,x2-head*math.cos(a-.5),y2-head*math.sin(a-.5),
                   x2-head*math.cos(a+.5),y2-head*math.sin(a+.5)],fillColor=color,strokeColor=None))


def box(d,x,y,w,h,label,fill=WHITE,stroke=RULE,size=8,sub=None):
    d.add(Rect(x,y,w,h,rx=3,ry=3,fillColor=fill,strokeColor=stroke,strokeWidth=.7))
    text(d,x+w/2,y+h/2+(3 if sub else -2.7),label,size,font='Helvetica-Bold',anchor='middle')
    if sub:text(d,x+w/2,y+h/2-9,sub,6.7,MUTED,anchor='middle')


def architecture():
    d=Drawing(COL,221)
    box(d,70,190,113,27,'Client / load generator',size=7.5)
    d.add(Rect(2,20,COL-4,157,rx=4,ry=4,fillColor=None,strokeColor=RULE,
               strokeWidth=.75,strokeDashArray=[3,2]))
    text(d,10,165,'ONE SHARED CPU HOST',6.6,MUTED)
    box(d,50,115,153,38,'Gateway process',PALE_BLUE,BLUE,
        sub='Admission limits  |  RR / LO  |  streaming')
    arrow(d,126.5,190,126.5,154,BLUE)
    text(d,134,180,'HTTP',6.5,MUTED)
    line(d,126.5,115,126.5,103,BLUE);line(d,62,103,191,103,BLUE)
    arrow(d,62,103,62,93,BLUE);arrow(d,191,103,191,93,BLUE)
    for x,label in [(10,'Worker 1'),(139,'Worker 2')]:
        d.add(Rect(x,31,104,62,rx=3,ry=3,fillColor=PALE_TEAL,strokeColor=TEAL,strokeWidth=.7))
        text(d,x+52,78,label,8,font='Helvetica-Bold',anchor='middle')
        text(d,x+52,57,'FIFO queue + 4 active slots',6.6,anchor='middle')
        text(d,x+52,45,'Qwen replica + own KV state',6.6,anchor='middle')
    text(d,COL/2,8,'Traces: assignment, model steps, tokens, terminal state',6.8,MUTED,anchor='middle')
    return d


def mechanism():
    d=Drawing(FULL,126)
    text(d,0,113,'TOKEN PIECES',7,MUTED,'Helvetica-Bold')
    for y,label,fill,stroke in [(80,'A: decode (1)',PALE_BLUE,BLUE),
                               (51,'B: decode (1)',PALE_BLUE,BLUE),
                               (22,'C: prefill chunk',PALE_AMBER,AMBER)]:
        box(d,0,y,83,23,label,fill,stroke,size=7)
        arrow(d,83,y+11.5,102,62,MUTED,head=3)
    box(d,105,35,91,53,'Norm + Q / K / V',PALE_BLUE,BLUE,size=7.6,sub='Concatenated token rows')
    arrow(d,196,61.5,212,61.5)
    text(d,219,113,'REQUEST-LOCAL ATTENTION',7,MUTED,'Helvetica-Bold')
    for y,label in [(80,'A: own KV + positions'),(51,'B: own KV + positions'),
                     (22,'C: own KV + causal mask')]:
        box(d,219,y,123,23,label,PALE_TEAL,TEAL,size=6.8)
        arrow(d,211,61.5,219,y+11.5,MUTED,head=3)
        arrow(d,342,y+11.5,359,61.5,MUTED,head=3)
    box(d,363,35,99,53,'O + Norm + MLP',PALE_BLUE,BLUE,size=7.6,sub='Merge token rows again')
    arrow(d,462,61.5,482,61.5)
    text(d,486,65,'Next',8,font='Helvetica-Bold');text(d,486,53,'layer',8,font='Helvetica-Bold')
    text(d,105,6,'Repeat per transformer layer; output logits only at token-producing positions.',7,MUTED)
    return d


def suite(archive,path):
    with zipfile.ZipFile(archive) as z:return json.loads(z.read(path))


def metric_panel(d,x,y,w,h,groups,title,ylabel,ymax,ticks,labels,palette,fmt='.2f',paired=False,show_values=True):
    """Points are trials; heavy marks and whiskers are mean +/- sample SD."""
    left,right,bottom,top=x+30,x+w-8,y+25,y+h-22
    text(d,x+w/2,y+h-8,title,8.1,font='Helvetica-Bold',anchor='middle')
    text(d,left,top+3,ylabel,6.6,MUTED)
    for t in ticks:
        yy=bottom+(top-bottom)*t/ymax
        line(d,left,yy,right,yy,RULE,.35)
        text(d,left-5,yy-2.2,f'{t:g}',6.8,MUTED,anchor='end')
    line(d,left,bottom,left,top,MUTED,.6);line(d,left,bottom,right,bottom,MUTED,.6)
    xs=[left+(i+.5)*(right-left)/len(groups) for i in range(len(groups))]
    if paired and len(groups)==2:
        for a,b in zip(groups[0],groups[1]):
            line(d,xs[0]-5,bottom+(top-bottom)*a/ymax,xs[1]-5,
                 bottom+(top-bottom)*b/ymax,colors.HexColor('#c5cbd1'),.55)
    for i,values in enumerate(groups):
        mean=stats.mean(values);sd=stats.stdev(values) if len(values)>1 else 0;xx=xs[i]
        for j,value in enumerate(values):
            jitter=0 if paired else (j-(len(values)-1)/2)*2.4
            d.add(Circle(xx-5+jitter,bottom+(top-bottom)*value/ymax,1.9,
                         fillColor=WHITE,strokeColor=palette[i],strokeWidth=.85))
        yy=bottom+(top-bottom)*mean/ymax
        lo=bottom+(top-bottom)*(mean-sd)/ymax;hi=bottom+(top-bottom)*(mean+sd)/ymax
        line(d,xx+5,lo,xx+5,hi,palette[i],1.1)
        line(d,xx+2,lo,xx+8,lo,palette[i],1);line(d,xx+2,hi,xx+8,hi,palette[i],1)
        line(d,xx+1,yy,xx+9,yy,palette[i],2.2)
        text(d,xx,bottom-11,labels[i],6.8,MUTED,anchor='middle')
        if show_values:
            label_y=min(top+4,max(hi,bottom+(top-bottom)*max(values)/ymax)+7)
            text(d,xx,label_y,format(mean,fmt),7,palette[i],font='Helvetica-Bold',anchor='middle')


def routing_figure(rows):
    d=Drawing(FULL,240)
    specs=[('requests_s','Throughput','requests/s',[[0,.5,1,1.5],[0,.5,1,1.5]],1.6,'.3f'),
           ('ttft_p95_ms','P95 first token','seconds',[[0,2,4,6],[0,20,40,60]],None,'.2f'),
           ('latency_p95_ms','P95 completion','seconds',[[0,5,10,15],[0,20,40,60]],None,'.2f')]
    for r,rate in enumerate([1.,3.]):
        y=121 if r==0 else 0
        text(d,0,y+113,f'({"a" if r==0 else "b"})  {int(rate)} request{"s" if rate>1 else ""}/s',8,BLUE,'Helvetica-Bold')
        for j,(metric,title,unit,ticks,ymax,fmt) in enumerate(specs):
            groups=[]
            for policy in ['round_robin','least_outstanding']:
                selected=sorted([q for q in rows if q['rate']==rate and q['routing']==policy],key=lambda q:q['repeat'])
                groups.append([q[metric]/(1000 if metric.endswith('_ms') else 1) for q in selected])
            maxy=ymax or (6.5 if r==0 and j==1 else 17 if r==0 else 65)
            metric_panel(d,j*FULL/3,y,FULL/3-4,103,groups,title,unit,maxy,ticks[r],['RR','LO'],[BLUE,AMBER],fmt,True,False)
    return d


def execution_figure(rows):
    d=Drawing(COL,151)
    for j,(metric,title,unit,ymax,ticks,fmt) in enumerate([
        ('requests_s','Throughput','requests/s',1.4,[0,.5,1.0],'.3f'),
        ('ttft_p95_ms','P95 first token','seconds',25,[0,10,20],'.2f')]):
        groups=[[q[metric]/(1000 if metric.endswith('_ms') else 1)
                 for q in sorted(rows,key=lambda q:q['repeat']) if q['execution']==p]
                for p in ['sequential','selective']]
        metric_panel(d,j*COL/2,0,COL/2,145,groups,title,unit,ymax,ticks,['Ind.','Shared'],[BLUE,AMBER],fmt,True)
    return d


def simulator_figure(rows):
    d=Drawing(COL,151)
    for j,rate in enumerate([6.,18.]):
        groups=[[q['ttft_p95_ms']/1000 for q in sorted(rows,key=lambda q:q['repeat'])
                 if q['rate']==rate and q['scheduling']==p] for p in ['static','continuous']]
        metric_panel(d,j*COL/2,0,COL/2,145,groups,f'{int(rate)} requests/s','P95 TTFT (s)',
                     15,[0,5,10,15],['Static','Cont.'],[BLUE,TEAL],'.2f')
    return d


def formatted(value):
    value=escape(value)
    value=re.sub(r'\*\*(.+?)\*\*',r'<b>\1</b>',value)
    value=re.sub(r'\*(.+?)\*',r'<i>\1</i>',value)
    value=re.sub(r'`(.+?)`',r'<font name="Courier" size="7.2">\1</font>',value)
    value=re.sub(r'10\^(-?\d+)',r'10<super>\1</super>',value)
    return re.sub(r'\[([^\]]+)\]\((https?://[^)]+)\)',r'<link href="\2" color="#2366a1">\1</link>',value)


BODY=ParagraphStyle('body',fontName='Times-Roman',fontSize=9.5,leading=11.35,
                    alignment=TA_JUSTIFY,textColor=INK,spaceAfter=5.8,allowWidows=0,allowOrphans=0)
STYLES={
 'body':BODY,
 'abstract':ParagraphStyle('abstract',parent=BODY,fontSize=9.2,leading=10.9),
 'h1':ParagraphStyle('h1',parent=BODY,fontName='Times-Bold',fontSize=11.6,leading=13.4,
                      spaceBefore=7,spaceAfter=4,alignment=TA_LEFT),
 'h2':ParagraphStyle('h2',parent=BODY,fontName='Times-Bold',fontSize=9.8,leading=11.6,
                      spaceBefore=4,spaceAfter=3,alignment=TA_LEFT),
 'caption':ParagraphStyle('caption',parent=BODY,fontSize=8.1,leading=9.6,spaceAfter=7,alignment=TA_LEFT),
 'ref':ParagraphStyle('ref',parent=BODY,fontSize=8.1,leading=9.4,spaceAfter=6,alignment=TA_LEFT),
 'table':ParagraphStyle('table',parent=BODY,fontSize=7.8,leading=9.2,spaceAfter=0,alignment=TA_LEFT),
}


def draw_region(canvas,content,x,top,width,bottom,figures,label):
    y=top
    for raw_block in re.split(r'\n\s*\n',content.strip()):
        block=' '.join(q.strip() for q in raw_block.splitlines())
        if not block:continue
        match=re.fullmatch(r'!\[(.*)\]\(assets/([a-z-]+)\.svg\)',block)
        if match:
            caption,key=match.groups();d=figures[key]
            assert abs(d.width-width)<1,(key,d.width,width)
            y-=d.height;renderPDF.draw(d,canvas,x,y)
            para=Paragraph(formatted(caption),STYLES['caption']);_,height=para.wrap(width,1000)
            y-=height+4;para.drawOn(canvas,x,y);y-=7
        elif block.startswith('|'):
            rows=[]
            for row in raw_block.splitlines():
                cells=[q.strip() for q in row.strip('| ').split('|')]
                if all(re.fullmatch(r'[-: ]+',q) for q in cells):continue
                rows.append([Paragraph(formatted(q),STYLES['table']) for q in cells])
            table=Table(rows,colWidths=[width*.42,width*.29,width*.29])
            table.setStyle(TableStyle([
                ('LINEABOVE',(0,0),(-1,0),.8,INK),('LINEBELOW',(0,0),(-1,0),.45,INK),
                ('LINEBELOW',(0,-1),(-1,-1),.8,INK),('VALIGN',(0,0),(-1,-1),'TOP'),
                ('LEFTPADDING',(0,0),(-1,-1),2),('RIGHTPADDING',(0,0),(-1,-1),2),
                ('TOPPADDING',(0,0),(-1,-1),4),('BOTTOMPADDING',(0,0),(-1,-1),4)]))
            _,height=table.wrap(width,1000);y-=height;table.drawOn(canvas,x,y);y-=6
        else:
            kind='body'
            for prefix,key in [('## ','h1'),('### ','h2'),('CAPTION: ','caption'),
                               ('REF: ','ref'),('ABSTRACT: ','abstract')]:
                if block.startswith(prefix):kind=key;block=block[len(prefix):];break
            if block.startswith('Serving requests with different lengths'):kind='abstract'
            if block.startswith('**Table '):kind='caption'
            if re.match(r'^\[\d+\]',block):kind='ref'
            style=STYLES[kind];y-=style.spaceBefore
            para=Paragraph(formatted(block),style);_,height=para.wrap(width,1000)
            y-=height;para.drawOn(canvas,x,y);y-=style.spaceAfter
        if y<bottom-.1:raise ValueError(f'{label} exceeds frame by {bottom-y:.1f} pt; revise prose/layout')
    return round(top-y,1),round(y-bottom,1)


def build(source,target):
    assets=source.parent/'assets';assets.mkdir(exist_ok=True)
    routing=suite(ROOT/'evidence/routing/raw-routing.zip','random-suite/results.json')
    additional=ROOT/'evidence/additional/raw-additional-experiments.zip'
    execution=suite(additional,'experiment-a501f3f100/results.json')
    simulator=suite(additional,'experiment-submission-20261028/results.json')
    figures={'architecture':architecture(),'routing':routing_figure(routing),
             'mechanism':mechanism(),'execution':execution_figure(execution),'simulator':simulator_figure(simulator)}
    for key,d in figures.items():renderSVG.drawToFile(d,str(assets/f'{key}.svg'))
    sources=['evidence/routing/raw-routing.zip','evidence/routing/paired-effects.csv',
             'evidence/additional/raw-additional-experiments.zip','evidence/additional/simulator-rerun-summary.csv']
    provenance={'sources':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in sources},
                'routing_trials':routing,'execution_trials':execution,'simulator_trials':simulator,
                'plot_convention':'Trials; heavy marks/whiskers are mean +/- sample SD. Gray lines connect routing/execution repeat pairs.'}
    (assets/'figure-data.json').write_text(json.dumps(provenance,indent=2),encoding='utf-8')
    raw=source.read_text(encoding='utf-8')
    regions=dict(re.findall(r'<!-- REGION ([a-z0-9-]+) -->\s*(.*?)(?=<!-- REGION|\Z)',raw,re.S))
    expected=['p1-left','p1-right','p2-top','p2-left','p2-right','p3-top','p3-left','p3-right','p4-left','p4-right']
    if list(regions)!=expected:raise ValueError(f'Regions must appear in order: {expected}')
    target.parent.mkdir(parents=True,exist_ok=True)
    c=Canvas(str(target),pagesize=(W,H),pageCompression=1)
    c.setTitle('TokenFlow: Request Routing and Iteration-Level Execution for Local LLM Serving')
    c.setAuthor('CHEONG KIN NGAI (Bankey)');c.setSubject('CISC3010 Topic 14 - Final project report')
    geometry={
      'p1-left':(MARGIN,648,COL,48),'p1-right':(MARGIN+COL+GAP,648,COL,48),
      'p2-top':(MARGIN,744,FULL,445),
      'p2-left':(MARGIN,440,COL,48),'p2-right':(MARGIN+COL+GAP,440,COL,48),
      'p3-top':(MARGIN,744,FULL,553),
      'p3-left':(MARGIN,548,COL,48),'p3-right':(MARGIN+COL+GAP,548,COL,48),
      'p4-left':(MARGIN,744,COL,48),'p4-right':(MARGIN+COL+GAP,744,COL,48)}
    sizes={}
    for page in range(1,5):
        c.setFillColor(MUTED);c.setFont('Helvetica',7)
        c.drawString(MARGIN,767,'TOKENFLOW  /  CISC3010 TOPIC 14');c.drawRightString(W-MARGIN,767,'FINAL PROJECT REPORT')
        c.setStrokeColor(RULE);c.setLineWidth(.5);c.line(MARGIN,760,W-MARGIN,760)
        if page==1:
            c.setFillColor(INK);c.setFont('Times-Bold',19.5)
            c.drawCentredString(W/2,724,'TokenFlow: Request Routing and Iteration-Level')
            c.drawCentredString(W/2,701,'Execution for Local LLM Serving')
            c.setFont('Times-Roman',10.5);c.drawCentredString(W/2,678,'CHEONG KIN NGAI (Bankey)')
            c.setFont('Helvetica',8);c.drawCentredString(W/2,663,'Distributed Systems  |  Individual Project  |  Topic 14')
        for name in expected:
            if name.startswith(f'p{page}-'):
                sizes[name]=draw_region(c,regions[name],*geometry[name],figures,name)
        c.setFillColor(MUTED);c.setFont('Times-Roman',8);c.drawCentredString(W/2,27,str(page));c.showPage()
    c.save();(assets/'layout-check.json').write_text(json.dumps(sizes,indent=2),encoding='utf-8')
    print(json.dumps({'output':str(target),'regions_used_and_remaining_pt':sizes},indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,default=ROOT/'report/TokenFlow_Final_Report.md')
    parser.add_argument('--output',type=Path,default=ROOT/'report/TokenFlow_Final_Report.pdf')
    args=parser.parse_args();build(args.source,args.output)
