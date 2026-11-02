"""Rebuild the four-page report: reference-inspired title card and two-column body.

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
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, Table, TableStyle

ROOT = Path(__file__).resolve().parents[1]
INK, MUTED, RULE = [colors.HexColor(c) for c in ['#17212b','#52606c','#d3d9e2']]
BLUE, AMBER, TEAL = [colors.HexColor(c) for c in ['#4f73a0','#b3833f','#6e9e90']]
PALE_BLUE, PALE_AMBER, PALE_TEAL = [colors.HexColor(c) for c in ['#eef4fa','#fbf3e6','#edf6f3']]
WHITE = colors.white
W, H, MARGIN, GAP = 612, 792, 54, 18
FULL = W - 2 * MARGIN
COL = (FULL - GAP) / 2

FONT_ROOT=ROOT/'report/assets/fonts'
for family,file in [('PaperSerif','STIXGeneral.ttf'),('PaperSerif-Bold','STIXGeneralBol.ttf'),
                    ('PaperSerif-Italic','STIXGeneralItalic.ttf'),('PaperSerif-BoldItalic','STIXGeneralBolIta.ttf')]:
    pdfmetrics.registerFont(TTFont(family,str(FONT_ROOT/file)))
pdfmetrics.registerFontFamily('PaperSerif',normal='PaperSerif',bold='PaperSerif-Bold',
                              italic='PaperSerif-Italic',boldItalic='PaperSerif-BoldItalic')


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
    d=Drawing(COL,184)
    box(d,(COL-114)/2,155,114,25,'Client / load generator',size=7.5)
    d.add(Rect(2,18,COL-4,127,rx=6,ry=6,fillColor=None,strokeColor=RULE,
               strokeWidth=.8,strokeDashArray=[3,2]))
    text(d,10,133,'ONE SHARED CPU HOST',6.5,MUTED)
    gx=(COL-153)/2
    box(d,gx,88,153,35,'Gateway process',PALE_BLUE,BLUE,
        sub='Admission  |  RR / LO  |  streaming')
    arrow(d,COL/2,155,COL/2,123,BLUE)
    text(d,COL/2+7,148,'HTTP',6.3,MUTED)
    line(d,COL/2,88,COL/2,76,BLUE)
    line(d,58,76,COL-58,76,BLUE)
    for x,label in [(7,'Worker 1'),(COL-110,'Worker 2')]:
        arrow(d,x+51.5,76,x+51.5,67,BLUE)
        d.add(Rect(x,27,103,40,rx=4,ry=4,fillColor=PALE_TEAL,strokeColor=TEAL,strokeWidth=.7))
        text(d,x+51.5,55,label,7.8,font='Helvetica-Bold',anchor='middle')
        text(d,x+51.5,43,'FIFO queue | 4 active slots',6.3,anchor='middle')
        text(d,x+51.5,33,'Qwen replica + own KV',6.3,anchor='middle')
    text(d,COL/2,5,'Traces -> lifecycle / token / cleanup checker',6.6,MUTED,anchor='middle')
    return d


def mechanism():
    d=Drawing(526,126)
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
    scale=FULL/526
    d.scale(scale,scale);d.width=FULL;d.height=126*scale
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
    d=Drawing(FULL,222)
    specs=[('requests_s','Throughput','requests/s',[[0,.5,1,1.5],[0,.5,1,1.5]],1.6,'.3f'),
           ('ttft_p95_ms','P95 first token','seconds',[[0,2,4,6],[0,20,40,60]],None,'.2f'),
           ('latency_p95_ms','P95 completion','seconds',[[0,5,10,15],[0,20,40,60]],None,'.2f')]
    for r,rate in enumerate([1.,3.]):
        y=113 if r==0 else 0
        text(d,0,y+104,f'({"a" if r==0 else "b"})  {int(rate)} request{"s" if rate>1 else ""}/s',8,BLUE,'Helvetica-Bold')
        for j,(metric,title,unit,ticks,ymax,fmt) in enumerate(specs):
            groups=[]
            for policy in ['round_robin','least_outstanding']:
                selected=sorted([q for q in rows if q['rate']==rate and q['routing']==policy],key=lambda q:q['repeat'])
                groups.append([q[metric]/(1000 if metric.endswith('_ms') else 1) for q in selected])
            maxy=ymax or (6.5 if r==0 and j==1 else 17 if r==0 else 65)
            metric_panel(d,j*FULL/3,y,FULL/3-4,96,groups,title,unit,maxy,ticks[r],['RR','LO'],[BLUE,AMBER],fmt,True,False)
    return d


def execution_figure(rows):
    d=Drawing(COL,129)
    for j,(metric,title,unit,ymax,ticks,fmt) in enumerate([
        ('requests_s','Throughput','requests/s',1.4,[0,.5,1.0],'.3f'),
        ('ttft_p95_ms','P95 first token','seconds',25,[0,10,20],'.2f')]):
        groups=[[q[metric]/(1000 if metric.endswith('_ms') else 1)
                 for q in sorted(rows,key=lambda q:q['repeat']) if q['execution']==p]
                for p in ['sequential','selective']]
        metric_panel(d,j*COL/2,0,COL/2,125,groups,title,unit,ymax,ticks,['Ind.','Shared'],[BLUE,AMBER],fmt,True)
    return d


def simulator_figure(rows):
    d=Drawing(COL,129)
    for j,rate in enumerate([6.,18.]):
        groups=[[q['ttft_p95_ms']/1000 for q in sorted(rows,key=lambda q:q['repeat'])
                 if q['rate']==rate and q['scheduling']==p] for p in ['static','continuous']]
        metric_panel(d,j*COL/2,0,COL/2,125,groups,f'{int(rate)} requests/s','P95 TTFT (s)',
                     15,[0,5,10,15],['Static','Cont.'],[BLUE,TEAL],'.2f')
    return d


def formatted(value):
    value=escape(value)
    value=re.sub(r'\*\*(.+?)\*\*',r'<b>\1</b>',value)
    value=re.sub(r'\*(.+?)\*',r'<i>\1</i>',value)
    value=re.sub(r'`(.+?)`',r'<font name="Courier" size="7.2">\1</font>',value)
    value=re.sub(r'10\^(-?\d+)',r'10<super>\1</super>',value)
    value=re.sub(r'\[(\d+(?:, \d+)*)\]',r'<font color="#2379cb">[\1]</font>',value)
    return re.sub(r'\[([^\]]+)\]\((https?://[^)]+)\)',r'<link href="\2" color="#2379cb">\1</link>',value)


BODY=ParagraphStyle('body',fontName='PaperSerif',fontSize=9.7,leading=11.6,
                    alignment=TA_JUSTIFY,textColor=INK,spaceAfter=5,allowWidows=0,allowOrphans=0)
STYLES={
 'body':BODY,
 'abstract':ParagraphStyle('abstract',parent=BODY,fontSize=10.1,leading=12.15),
 'h1':ParagraphStyle('h1',parent=BODY,fontName='Helvetica-Bold',fontSize=11.4,leading=13.5,
                      spaceBefore=7,spaceAfter=5,alignment=TA_LEFT),
 'h2':ParagraphStyle('h2',parent=BODY,fontName='Helvetica-Bold',fontSize=9.9,leading=12,
                      spaceBefore=4,spaceAfter=3,alignment=TA_LEFT),
 'caption':ParagraphStyle('caption',parent=BODY,fontSize=8.2,leading=9.7,spaceAfter=7,alignment=TA_LEFT),
 'ref':ParagraphStyle('ref',parent=BODY,fontSize=8.4,leading=9.8,spaceAfter=4,alignment=TA_LEFT),
 'table':ParagraphStyle('table',parent=BODY,fontSize=7.8,leading=9.3,spaceAfter=0,alignment=TA_LEFT),
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


def draw_title_card(canvas,abstract):
    """Reference-inspired single-column title/abstract block, without annotations."""
    inner=FULL-34
    title=ParagraphStyle('card-title',fontName='Helvetica-Bold',fontSize=18.3,
                         leading=22,textColor=INK,alignment=TA_LEFT)
    author=ParagraphStyle('author',fontName='Helvetica-Bold',fontSize=9.8,leading=12,textColor=INK)
    meta=ParagraphStyle('meta',parent=BODY,fontSize=9.3,leading=11.5,alignment=TA_LEFT)
    items=[
      (Paragraph('TokenFlow: Request Routing and<br/>Iteration-Level LLM Serving',title),11),
      (Paragraph('CHEONG KIN NGAI (Bankey)',author),4),
      (Paragraph('CISC3010 Distributed Systems | Individual Project | Topic 14',meta),15),
      (Paragraph(formatted(abstract.strip()),STYLES['abstract']),14),
      (Paragraph('<font name="Helvetica-Bold" size="8.8">Report:</font> Final submission, 2 November 2026<br/>'
                 '<font name="Helvetica-Bold" size="8.8">Artifacts:</font> Code, recorded demo, raw traces and reproducible figures',meta),0)]
    measured=[(p,p.wrap(inner,1000)[1],gap) for p,gap in items]
    height=34+sum(h+gap for p,h,gap in measured)
    top=730;bottom=top-height
    canvas.setFillColor(colors.HexColor('#f1f3f6'))
    canvas.roundRect(MARGIN,bottom,FULL,height,11,fill=1,stroke=0)
    y=top-17
    for para,h,gap in measured:
        y-=h;para.drawOn(canvas,MARGIN+17,y);y-=gap
    return bottom


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
    expected=['p1-abstract','p1-left','p1-right','p2-top','p2-left','p2-right',
              'p3-top','p3-left','p3-right','p4-left','p4-right']
    if list(regions)!=expected:raise ValueError(f'Regions must appear in order: {expected}')
    target.parent.mkdir(parents=True,exist_ok=True)
    c=Canvas(str(target),pagesize=(W,H),pageCompression=1)
    c.setTitle('TokenFlow: Request Routing and Iteration-Level LLM Serving')
    c.setAuthor('CHEONG KIN NGAI (Bankey)');c.setSubject('CISC3010 Topic 14 - Final project report')
    geometry={
      'p2-top':(MARGIN,730,FULL,440),
      'p2-left':(MARGIN,437,COL,50),'p2-right':(MARGIN+COL+GAP,437,COL,50),
      'p3-top':(MARGIN,730,FULL,540),
      'p3-left':(MARGIN,532,COL,50),'p3-right':(MARGIN+COL+GAP,532,COL,50),
      'p4-left':(MARGIN,730,COL,50),'p4-right':(MARGIN+COL+GAP,730,COL,50)}
    sizes={}
    for page in range(1,5):
        if page==1:
            bottom=draw_title_card(c,regions['p1-abstract'])
            geometry['p1-left']=(MARGIN,bottom-17,COL,50)
            geometry['p1-right']=(MARGIN+COL+GAP,bottom-17,COL,50)
        for name in expected:
            if name.startswith(f'p{page}-') and name!='p1-abstract':
                sizes[name]=draw_region(c,regions[name],*geometry[name],figures,name)
        c.setFillColor(INK);c.setFont('PaperSerif',9);c.drawCentredString(W/2,27,str(page));c.showPage()
    c.save();(assets/'layout-check.json').write_text(json.dumps(sizes,indent=2),encoding='utf-8')
    print(json.dumps({'output':str(target),'regions_used_and_remaining_pt':sizes},indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,default=ROOT/'report/TokenFlow_Final_Report.md')
    parser.add_argument('--output',type=Path,default=ROOT/'report/TokenFlow_Final_Report.pdf')
    args=parser.parse_args();build(args.source,args.output)
