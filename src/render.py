"""2026-11-15 고객 승인 레이아웃. 아침뉴스/보험의료 브리핑 각각 세로형 PNG.

오래된 샘플의 텍스트/시세를 배경으로 쓰지 않는다. 승인 이미지에서 배경 사진과
뉴스 주제 아이콘 일부만 추출해 사용한다. 기사/날짜/시세는 반드시 새 값으로 렌더링한다.
"""
from __future__ import annotations
from pathlib import Path
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont
import math
import re

BW, BH, SCALE = 768, 1110, 2
W, H = BW*SCALE, BH*SCALE
NAVY = '#071b40'
INK = '#101d30'
MUTED = '#566d86'
PALE = '#fbfdff'
LINE = '#b4d5f5'
DARKBLUE = '#137ad0'
LIGHTBLUE = '#e7f3fe'
BADGE_GRAY = '#e9eaed'
ASSETS = Path(__file__).resolve().parents[1] / 'assets'


def font_path(bold: bool=False) -> str:
    for p in (
      ('/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc' if bold else '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'),
      ('/usr/share/fonts/truetype/nanum/NanumSquareB.ttf' if bold else '/usr/share/fonts/truetype/nanum/NanumSquareR.ttf'),
      ('/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf' if bold else '/usr/share/fonts/truetype/nanum/NanumGothic.ttf'),
      ('/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc' if bold else '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'),
    ):
        if Path(p).exists(): return p
    raise RuntimeError('한글 글꼴이 없습니다. GitHub Actions에서 fonts-nanum을 설치하세요.')


def f(sz: float, bold: bool=False):
    return ImageFont.truetype(font_path(bold), max(9,int(round(sz*SCALE))))


def rect(d,box, radius=0, **kwargs):
    xy=tuple(int(round(v*SCALE)) for v in box)
    d.rounded_rectangle(xy,radius=int(radius*SCALE),**{k:(v*SCALE if k=='width' else v) for k,v in kwargs.items()})


def line(d,points,fill,width=1):
    d.line(tuple(int(v*SCALE) for v in points),fill=fill,width=int(width*SCALE))


def txt(d, pos, value, size=16, bold=False, color=INK, anchor=None):
    d.text((int(pos[0]*SCALE),int(pos[1]*SCALE)),str(value),font=f(size,bold),fill=color,anchor=anchor)


def wrap(d, value: str, ft, max_width: float):
    value=re.sub(r'\s+',' ',str(value or '')).strip()
    words=value.split()
    rows=[]; acc=''
    for word in words:
        test=(acc+' '+word).strip()
        if d.textlength(test,font=ft)<=max_width*SCALE:
            acc=test;continue
        if acc:rows.append(acc);acc=''
        for char in word:
            if acc and d.textlength(acc+char,font=ft)>max_width*SCALE:
                rows.append(acc);acc=char
            else:acc+=char
    if acc:rows.append(acc)
    return rows


def block(d, pos, value, max_width, max_lines, sz, lh, bold=False, color=INK,
          min_size=None):
    if not str(value or '').strip():
        raise ValueError('빈 제목 또는 본문을 고객용 카드에 게시하지 않습니다.')
    floor=min_size if min_size is not None else sz-3
    for size in [sz-0.5*i for i in range(int(2*(sz-floor))+1)]:
        ft=f(size,bold)
        rows=wrap(d,value,ft,max_width)
        if len(rows)<=max_lines:
            for ix,row in enumerate(rows):txt(d,(pos[0],pos[1]+ix*lh),row,size,bold,color)
            return len(rows)
    raise ValueError(f'고객용 카드 텍스트 초과(자동 잘림 금지): {str(value)[:65]}')


def asset(name):
    file=ASSETS/(name+'.png')
    if not file.exists():raise RuntimeError(f'디자인 원본 그림이 없습니다: {name}')
    return Image.open(file).convert('RGBA')


def paste(icon, canvas, x, y, w, h=None, opacity=1.0):
    im=asset(icon)
    h=h or (im.height*w/im.width)
    im=im.resize((int(w*SCALE),int(h*SCALE)),Image.Resampling.LANCZOS)
    if opacity!=1:
        a=im.getchannel('A').point(lambda p:int(p*opacity));im.putalpha(a)
    canvas.alpha_composite(im,(int(x*SCALE),int(y*SCALE)))


def rounded_paper():
    im=Image.new('RGBA',(W,H),(0,0,0,0))
    d=ImageDraw.Draw(im)
    rect(d,(3,3,BW-3,BH-3),radius=29,fill='#fdfdfd',outline='#316db0',width=1)
    return im,d


def sky_header(im, d, kind, date):
    # Gentle pale sky gradient; pure graphics from the final user-approved reference.
    for j in range(154):
        q=j/153
        c=tuple(round((1-q)*a+q*b) for a,b in zip((246,250,255),(226,241,251)))
        d.line((6*SCALE,j*SCALE,(BW-6)*SCALE,j*SCALE),fill=(*c,255),width=SCALE)
    sky='left_header_sky' if kind=='morning' else 'right_header_medical'
    # Paste with feathering on the left edge so no hard boundary meets the headline.
    graphic=asset(sky)
    if kind=='morning':
        x=395; targetw=BW-x-5; height=155
    else:
        x=432; targetw=BW-x-5; height=167
    graphic=graphic.resize((targetw*SCALE,height*SCALE),Image.Resampling.LANCZOS)
    alpha=graphic.getchannel('A')
    mask=Image.new('L',graphic.size,0);mp=mask.load()
    for xx in range(graphic.width):
        edge=min(1,xx/(58*SCALE))
        for yy in range(graphic.height):
            fade=min(1,yy/(8*SCALE),(graphic.height-yy)/(13*SCALE))
            # The old reference crop includes a masked text rectangle near
            # its left foot. Do not composite that block into a new header.
            leftover = (xx < (82 if kind=='medical' else 30)*SCALE
                        and 105*SCALE <= yy <= 154*SCALE)
            mp[xx,yy]=0 if leftover else round(255*max(0,edge)*max(0,fade))
    graphic.putalpha(mask)
    im.alpha_composite(graphic,(x*SCALE,6*SCALE))
    d=ImageDraw.Draw(im)
    # Background artwork contains an old date pill; completely cover that region.
    rect(d,(564,12,747,60),radius=23,fill='#f9fcff',outline='#c0d8ef',width=1)
    txt(d,(581,24),'▦',17,True,'#237bb9')
    date=human_date(date)
    txt(d,(604,25),date,17.5,True,NAVY)
    if kind=='morning':
        txt(d,(45,25),'이보람의',22,True,NAVY)
        txt(d,(45,58),'MORNING POST',39,True,NAVY)
        txt(d,(45,121),'오늘의 주요 뉴스, 꼭 필요한 정보만 전해드립니다.',14.4,False,NAVY)
    else:
        txt(d,(45,25),'이보람의',22,True,NAVY)
        txt(d,(45,61),'보험·의료 브리핑',34,True,NAVY)
        txt(d,(45,121),'건강과 보장, 제도와 변화까지 꼭 필요한 소식을 전해드립니다.',14.3,False,NAVY)
    return d


def human_date(stamp):
    try:
        dt=datetime.strptime(stamp[:10],'%Y-%m-%d')
        return f'{dt.month}월 {dt.day}일 ({"월화수목금토일"[dt.weekday()]})'
    except ValueError:
        return stamp


def card_frame(d, y, h):
    rect(d,(15,y,BW-15,y+h),radius=17,fill='#ffffff',outline=LINE,width=1)


def draw_left_articles(im,d,articles):
    cats=['정치','경제','사회','국제','생활/문화']
    imgs=['politics','economy','society','international','culture']
    by_cat={a.get('category'):a for a in articles}
    for i,(cat,img) in enumerate(zip(cats,imgs)):
        art=by_cat.get(cat)
        if not art:raise ValueError(f'아침뉴스 필수 분야 누락: {cat}')
        # Five rows share the 166..689px news area. 104px cards keep the
        # approved layout but accommodate a verified 70..125-character summary.
        # Never cut text with ellipses or silently discard a verified fact.
        y=166+i*128
        card_frame(d,y,126)
        rect(d,(25,y+6,183,y+120),radius=15,fill=BADGE_GRAY)
        paste(img,im,37,y+25,53,52)
        d=ImageDraw.Draw(im)
        if cat=='생활/문화':
            txt(d,(109,y+23),'생활',20,True,'#34383e')
            txt(d,(109,y+47),'문화',20,True,'#34383e')
        else:
            txt(d,(104,y+29),cat,22,True,'#34383e')
        head=art.get('headline') or art.get('title')
        summary=art.get('summary')
        n=block(d,(197,y+5),head,554,2,20,23,bold=True,min_size=17)
        # Keep one readable body size across all five categories. Approved
        # 120..180-character text uses 3..4 lines; never shorten the manuscript.
        body_y = y+34 if n==1 else y+51
        block(d,(197,body_y),summary,548,4,14.6,17.5,min_size=14.6)


def _market_entry(m, key):
    value=m.get(key)
    if not isinstance(value,dict):
        raise ValueError('시세 검증 실패, 발행 중단: '+key)
    return value


def _num(v,decimals=2):
    return f'{float(v):,.{decimals}f}'


def draw_weather_market(im,d,weather,market):
    # Offset the unchanged panel below the taller news section.
    panel = Image.new('RGBA', im.size, (0,0,0,0))
    target = im
    im = panel
    d = ImageDraw.Draw(im)
    rect(d,(20,691,349,969),radius=18,fill='#ffffff',outline='#9dcbf3',width=1)
    rect(d,(356,691,750,969),radius=18,fill='#ffffff',outline='#9dcbf3',width=1)
    # Soft blue cap band like approved sample.
    rect(d,(21,692,348,753),radius=17,fill='#f0f7fe')
    rect(d,(357,692,749,753),radius=17,fill='#f0f7fe')
    paste('sun',im,31,697,56,54)
    paste('chart',im,377,700,45,44)
    d=ImageDraw.Draw(im)
    txt(d,(100,708),'오늘의 날씨',25,True,NAVY)
    txt(d,(432,708),'오늘의 시세',24,True,NAVY)
    narrative=weather.get('narrative','')
    block(d,(38,768),narrative,294,5,16,24,min_size=13.3)
    valid=weather.get('cities') or {}
    cities=['서울','대전','광주','대구','부산']
    # Weather is a supplementary panel, not evidence for the news stories.
    # An unavailable city forecast must never become fabricated numbers or
    # prevent an otherwise verified news issue from being delivered.
    paste('thermometer',im,28,907,26,41)
    d=ImageDraw.Draw(im)
    for i,city in enumerate(cities):
        x=61+56*i
        entry=valid.get(city)
        txt(d,(x,909),city,15,True,NAVY)
        temperatures = (isinstance(entry,dict)
                        and isinstance(entry.get('lo'),(int,float))
                        and isinstance(entry.get('hi'),(int,float))
                        and math.isfinite(entry['lo']) and math.isfinite(entry['hi']))
        if temperatures:
            label=f'{entry["lo"]}/{entry["hi"]}°C'
            txt(d,(x,934),label,13.7,True,NAVY)
        else:
            txt(d,(x,934),'확인 불가',12.2,False,MUTED)
        if i and i<=3:line(d,(x-9,906,x-9,960),fill='#d6e4ef',width=1)
    # Each number has independently confirmed date in verification.json and HTML source panel.
    kospi=_market_entry(market,'KOSPI')
    kosdaq=_market_entry(market,'KOSDAQ')
    usd=_market_entry(market,'USD/KRW')
    petrol=_market_entry(market,'휘발유')
    diesel=_market_entry(market,'경유')
    gold=_market_entry(market,'순금 24K 1돈(살 때/팔 때)')
    txt(d,(626,713),'(증시: '+str(kospi.get('date',''))[5:].replace('-','/')+')',11.2,False,MUTED)
    # labels and values fit one column; image is reviewed before publication.
    def market_row(y,label,val,change=None):
        txt(d,(378,y),label,16.8,True,NAVY)
        txt(d,(484,y),val,17.6,True,NAVY)
        if change is not None:
            color='#e04039' if float(change)>=0 else '#2376b2'
            c=f'{float(change):+.2f}%'
            txt(d,(650,y+2),c,13.0,True,color)
    market_row(750,'코스피',_num(kospi['value']),kospi.get('change'))
    market_row(784,'코스닥',_num(kosdaq['value']),kosdaq.get('change'))
    market_row(818,'원/달러',_num(usd['value'])+'원')
    line(d,(375,844,738,844),'#e2eaf1')
    paste('fuel',im,378,850,31,51)
    d=ImageDraw.Draw(im)
    txt(d,(414,849),'휘발유(L)',15,True,NAVY)
    txt(d,(538,850),f'{float(petrol["value"]):,.1f}원',16,True,NAVY)
    txt(d,(414,875),'경유(L)',15,True,NAVY)
    txt(d,(538,875),f'{float(diesel["value"]):,.1f}원',16,True,NAVY)
    line(d,(375,908,738,908),'#e2eaf1')
    paste('gold',im,380,917,32,35)
    d=ImageDraw.Draw(im)
    txt(d,(417,915),'금(1돈)',14.5,True,NAVY)
    txt(d,(493,914),f'살 때 {int(gold["buy"]):,}원',13.5,True,NAVY)
    txt(d,(493,939),f'팔 때 {int(gold["sell"]):,}원',13.5,True,NAVY)
    txt(d,(375,958),'금 24K 3.75g · 살 때 부가세 포함',9,False,MUTED)

    target.alpha_composite(panel,(0,120*SCALE))


def _medical_image(article,i):
    data=(str(article.get('headline') or article.get('title') or '')+' '+str(article.get('summary') or '')).lower()
    if any(x in data for x in ['환급','미청구','청구','보험금']):return 'medical_refund'
    if any(x in data for x in ['독감','예방접종','백신','인플루엔자']):return 'medical_vaccine'
    if any(x in data for x in ['비대면','원격진료','온라인 진료']):return 'medical_online'
    if any(x in data for x in ['중증','병원','응급','의약품']):return 'medical_hospital'
    if any(x in data for x in ['실손','보험료','보험계약','보장']):return 'medical_insurance'
    return ['medical_insurance','medical_refund','medical_vaccine','medical_hospital','medical_online'][i]


def draw_right_articles(im,d,articles):
    if len(articles)<5:
        raise ValueError('보험·의료 검증 기사 5건 미만: 발행하지 않음')
    for i,a in enumerate(articles[:5]):
        y=181+i*175
        card_frame(d,y,170)
        paste(_medical_image(a,i),im,798-768,y+16,135,115)
        d=ImageDraw.Draw(im)
        line(d,(183,y+13,183,y+134),'#d8e7f4',1)
        head=a.get('headline') or a.get('title')
        summary=a.get('summary')
        n=block(d,(191,y+18),head,558,2,20.8,25,bold=True,min_size=18)
        body_y = y+60 if n==1 else y+80
        block(d,(191,body_y),summary,552,4,15.4,20,min_size=15.4)


def save_img(im,path):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    im.save(path)
    thumbnail=im.copy()
    thumbnail.thumbnail((720,900),Image.Resampling.LANCZOS)
    preview=Image.new('RGB',thumbnail.size,'white')
    preview.paste(thumbnail,mask=thumbnail.getchannel('A'))
    preview.save(path.with_name(path.stem+'-preview.jpg'),'JPEG',quality=89,subsampling=0)


def render_morning(path:Path,date:str,checked:str,articles:list[dict],weather:dict,market:dict,demo=False):
    im,d=rounded_paper();d=sky_header(im,d,'morning',date)
    txt(d,(45,143),f'자료 확인 {checked} KST',9,False,MUTED)
    draw_left_articles(im,d,articles)
    draw_weather_market(im,d,weather,market)
    if demo:
        rect(ImageDraw.Draw(im),(616,950,745,976),radius=8,fill='#c0392b')
        txt(ImageDraw.Draw(im),(628,953),'디자인 시험용',15,True,'white')
    save_img(im,path)


def render_medical(path:Path,date:str,checked:str,articles:list[dict],demo=False):
    im,d=rounded_paper();d=sky_header(im,d,'medical',date)
    txt(d,(45,143),f'자료 확인 {checked} KST',9,False,MUTED)
    draw_right_articles(im,d,articles)
    if demo:
        rect(ImageDraw.Draw(im),(610,947,745,975),radius=8,fill='#c0392b')
        txt(ImageDraw.Draw(im),(616,951),'디자인 시험용',15,True,'white')
    save_img(im,path)

