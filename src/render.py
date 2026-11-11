"""정해진 디자인에 맞춰 세로형 투명 바탕 PNG 두 장을 생성."""
from __future__ import annotations
from pathlib import Path
import os
import re
from PIL import Image, ImageDraw, ImageFont

W, H = 1080, 1900
NAVY = '#172d46'
MUTED = '#597187'
PALE = '#f7f6f0'
BLUE = '#e6eef4'
BORDER = '#abbcc8'
ACCENT = '#355e82'
PALE_BLUE = '#edf4f8'


def font_path(bold: bool = False) -> str:
    candidates = [
        '/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf' if bold else '/usr/share/fonts/truetype/nanum/NanumGothic.ttf',
        '/usr/share/fonts/truetype/nanum/NanumSquareB.ttf' if bold else '/usr/share/fonts/truetype/nanum/NanumSquareR.ttf',
        '/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc' if bold else '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
    ]
    for p in candidates:
        if Path(p).exists():
            return p
    raise RuntimeError('한글 폰트가 없습니다. Ubuntu에서 sudo apt-get install fonts-nanum을 실행하세요.')


def f(size: int, bold: bool = False):
    return ImageFont.truetype(font_path(bold), size=size)


def new_paper(kind: str, date: str, checked: str, demo: bool = False):
    image = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(image)
    d.rounded_rectangle((5, 5, W-5, H-5), radius=46, fill=PALE)
    d.rounded_rectangle((27, 27, W-27, H-27), radius=30, outline=BORDER, width=3)
    d.text((73, 75), '이보람의', font=f(44, True), fill=NAVY)
    if kind == 'morning':
        d.text((73, 125), 'MORNING POST', font=f(72, True), fill=NAVY)
        d.text((77, 223), 'POLITICS  ·  ECONOMY  ·  SOCIETY  ·  WORLD  ·  CULTURE', font=f(20), fill=MUTED)
    else:
        d.text((73, 130), '보험·의료 브리핑', font=f(67, True), fill=NAVY)
        d.text((77, 223), 'INSURANCE  ·  HEALTHCARE  ·  POLICY  ·  TECHNOLOGY', font=f(20), fill=MUTED)
    d.text((W - 310, 78), date, font=f(25, True), fill=ACCENT)
    d.text((W - 310, 117), f'자료 확인 {checked}', font=f(19), fill=MUTED)
    d.line((75, 264, W - 75, 264), fill=NAVY, width=4)
    if demo:
        d.rounded_rectangle((830, 204, 1005, 255), radius=10, fill='#a44949')
        d.text((858, 214), '데모 시안', font=f(26, True), fill='white')
    return image, d


def wrap(d: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int, max_lines: int = 3) -> list[str]:
    # 단어 단위로 자르되 매우 긴 한국어 단어도 폭 내에서 분리
    text = re.sub(r'\s+', ' ', text or '').strip()
    lines = []
    current = ''
    for word in text.split(' '):
        draft = f'{current} {word}'.strip()
        if d.textlength(draft, font=font) <= max_width:
            current = draft
            continue
        if current:
            lines.append(current)
            current = ''
        for char in word:
            if d.textlength(current + char, font=font) > max_width and current:
                lines.append(current)
                current = char
            else:
                current += char
    if current:
        lines.append(current)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        while last and d.textlength(last + '…', font=font) > max_width:
            last = last[:-1]
        lines[-1] = last + '…'
    return lines or ['']


def paragraph(d, xy, text, *, size=29, max_width=830, max_lines=3, line_h=42, color=NAVY, bold=False):
    face = f(size, bold)
    for i, line in enumerate(wrap(d, text, face, max_width, max_lines)):
        d.text((xy[0], xy[1] + i * line_h), line, font=face, fill=color)


def bar(d, category, y, color=ACCENT):
    width = max(112, int(len(category) * 28 + 42))
    d.rounded_rectangle((76, y, 76 + width, y + 43), radius=15, fill=BLUE)
    d.text((92, y + 5), category, font=f(27, True), fill=color)


def render_morning(path: Path, date: str, checked: str, articles: list[dict], weather: dict, market: dict, demo=False):
    im, d = new_paper('morning', date, checked, demo)
    start, step = 291, 215
    for i, article in enumerate(articles[:5]):
        y = start + i * step
        d.rounded_rectangle((66, y, 1014, y + 201), radius=22, fill='white', outline='#d9e2e8', width=2)
        bar(d, article.get('category', '뉴스'), y+15)
        d.text((86, y+69), (article.get('source') or '출처 미확인')[:20] + '  ·  ' + article.get('date', ''), font=f(21), fill=MUTED)
        paragraph(d, (289, y+20), article.get('headline') or article.get('title', ''), size=34, max_width=688, max_lines=2, line_h=42, bold=True)
        paragraph(d, (260, y+107), article.get('summary') or article.get('snippet') or '자세한 사항은 원문을 확인해 주세요.',
                  size=26, max_width=710, max_lines=2, line_h=35, color='#2c3d4d')
    y = 1390
    d.rounded_rectangle((68, y, 1012, y+186), radius=24, fill=PALE_BLUE)
    d.text((91, y+16), '오늘의 날씨', font=f(32, True), fill=NAVY)
    d.text((330, y+24), weather.get('source', '출처 확인 필요'), font=f(20), fill=MUTED)
    for i, city in enumerate(('서울', '대전', '광주', '대구', '부산')):
        x = 92 + i*181
        item = weather.get('cities', {}).get(city)
        d.text((x, y+76), city, font=f(26, True), fill=NAVY)
        if item:
            d.text((x, y+113), f"{item['lo']}°/{item['hi']}°", font=f(25), fill=ACCENT)
            d.text((x, y+148), f"강수 {item.get('rain', '?')}%", font=f(20), fill=MUTED)
        else:
            d.text((x, y+118), '확인 불가', font=f(22), fill=MUTED)
    y = 1600
    d.text((85, y), 'MARKET  주요 지표', font=f(30, True), fill=NAVY)
    rows = [('KOSPI', 'KOSPI'), ('KOSDAQ', 'KOSDAQ'), ('원/달러', 'USD/KRW'),
            ('휘발유', '휘발유'), ('경유', '경유'), ('금 24K 1돈', '순금 24K 1돈(살 때/팔 때)')]
    for i, (label, key) in enumerate(rows):
        c = i % 3
        r = i // 3
        x = 77 + c * 309
        yy = y+52 + r*94
        d.rounded_rectangle((x, yy, x+292, yy+85), radius=12, fill='white', outline='#e0e8ed')
        d.text((x+12, yy+9), label, font=f(20, True), fill=MUTED)
        item = market.get(key)
        if item:
            val = item['value']
            change = item['change']
            shown = f'{val:,.2f}'
            d.text((x+12, yy+31), f'{shown}  ({change:+.1f}%)', font=f(23, True), fill=ACCENT)
            d.text((x+12, yy+65), f"Yahoo Finance · {item.get('date', '?')}", font=f(15), fill=MUTED)
        else:
            d.text((x+12, yy+40), '확인 불가', font=f(24), fill='#7b8390')
    d.text((84, 1844), '※ 기준시각·상세 출처는 카드뉴스 링크에서 확인  |  미확인 수치는 추정하지 않음', font=f(18), fill=MUTED)
    im.save(path)
    thumb = im.convert('RGB')
    thumb.thumbnail((660, 1160))
    thumb.save(path.with_name(path.stem + '-preview.jpg'), 'JPEG', quality=88)


def render_medical(path: Path, date: str, checked: str, articles: list[dict], demo=False):
    im, d = new_paper('medical', date, checked, demo)
    if not articles:
        d.rounded_rectangle((72, 350, 1008, 920), radius=26, fill='white')
        paragraph(d, (120, 480), '확인할 수 있는 새로운 보험·의료 발표가 부족합니다. 최신 소식이 확인되면 다음 발행에 반영합니다.',
                  size=38, max_width=830, max_lines=5, line_h=70)
    else:
        n = min(len(articles), 5)
        step = min(293, int(1430/n))
        for i, article in enumerate(articles[:5]):
            y = 292+i*step
            d.rounded_rectangle((67, y, 1013, y+step-11), radius=23, fill='white', outline='#d9e2e8', width=2)
            bar(d, article.get('category', '보험·의료'), y+15)
            d.text((88, y+70), (article.get('source') or '출처 미확인')[:23] + '  ·  ' + article.get('date', ''), font=f(21), fill=MUTED)
            paragraph(d, (270, y+24), article.get('headline') or article.get('title', ''), size=35,
                      max_width=690, max_lines=2, line_h=44, bold=True)
            paragraph(d, (106, y+117), article.get('summary') or article.get('snippet') or '자세한 내용은 공식 자료를 확인해 주세요.',
                      size=28, max_width=855, max_lines=3, line_h=42)
            d.rounded_rectangle((104, y+step-77, 972, y+step-32), radius=10, fill=PALE_BLUE)
            point = '발표일과 시행일, 대상과 적용 여부는 원문에서 확인하세요.'
            paragraph(d, (118, y+step-73), '다시 읽을 포인트  ·  ' + point, size=20, max_width=830, max_lines=1, color=ACCENT)
    d.text((80, 1843), '※ 법안·검토·확정·시행 및 연구·허가·급여는 구분  |  기사 원문 링크 별도 제공', font=f(19), fill=MUTED)
    im.save(path)
    thumb = im.convert('RGB')
    thumb.thumbnail((660, 1160))
    thumb.save(path.with_name(path.stem + '-preview.jpg'), 'JPEG', quality=88)
