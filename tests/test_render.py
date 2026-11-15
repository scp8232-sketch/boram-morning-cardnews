from PIL import Image
import pytest

from src.render import render_morning, render_medical


CATEGORIES = ['정치', '경제', '사회', '국제', '생활/문화']
MED_CATEGORIES = ['건강보험', '보험제도', '보건정책', '의료기술', '건강정보']


def sample(category, i):
    return {
        'category': category,
        'title': f'{category} 분야 편집시연 원고 제목 {i}',
        'headline': f'{category} 분야 편집시연 원고 제목 {i}',
        'summary': '이 문장은 실제 뉴스가 아닌 템플릿의 텍스트 배치를 검증하기 위한 시험용 문장입니다. 실제 발행에는 사용하지 않습니다.',
        'source': '시험',
        'date': '2026-11-12',
    }


def fake_weather():
    return {
        'source': '시험 전용',
        'narrative': '서울과 중부 지방은 구름이 많겠습니다. 아침은 다소 쌀쌀하고 오후에는 기온이 오를 전망입니다.',
        'cities': {name: {'lo': 3+i, 'hi': 12+i} for i, name in enumerate(['서울', '부산', '대구', '광주'])},
    }


def fake_market():
    return {
        'KOSPI': {'value': 3010.1, 'change': 0.35, 'date': '2026-11-12'},
        'KOSDAQ': {'value': 805.2, 'change': -0.15, 'date': '2026-11-12'},
        'USD/KRW': {'value': 1380.2, 'date': '2026-11-12'},
        '휘발유': {'value': 1737.4, 'date': '2026-11-12'},
        '경유': {'value': 1646.2, 'date': '2026-11-12'},
        '순금 24K 1돈(살 때/팔 때)': {'buy': 820000, 'sell': 760000, 'date': '2026-11-12'},
    }


def test_demo_render(tmp_path):
    morning = tmp_path / 'morning.png'
    medical = tmp_path / 'medical.png'
    render_morning(morning, '2026-11-12', '05:30',
                   [sample(cat, i) for i, cat in enumerate(CATEGORIES)],
                   fake_weather(), fake_market(), True)
    render_medical(medical, '2026-11-12', '05:30',
                   [sample(cat, i) for i, cat in enumerate(MED_CATEGORIES)], True)
    for p in [morning, medical]:
        assert p.exists()
        im = Image.open(p)
        assert im.size == (1536, 1980)
        assert im.getpixel((0, 0))[3] == 0  # 둥근 외곽 네 모서리 투명
        assert p.with_name(p.stem+'-preview.jpg').exists()


def test_missing_news_category_blocks_publication(tmp_path):
    with pytest.raises(ValueError, match='필수 분야 누락'):
        render_morning(tmp_path / 'missing.png', '2026-11-12', '05:30',
                       [sample('사회', 1)], fake_weather(), fake_market(), False)


def test_missing_market_value_blocks_publication(tmp_path):
    bad_market = fake_market()
    bad_market['경유'] = None
    with pytest.raises(ValueError, match='시세 검증 실패'):
        render_morning(tmp_path / 'missing-market.png', '2026-11-12', '05:30',
                       [sample(cat, i) for i, cat in enumerate(CATEGORIES)],
                       fake_weather(), bad_market, False)


def test_missing_medical_items_blocks_publication(tmp_path):
    with pytest.raises(ValueError, match='5건 미만'):
        render_medical(tmp_path / 'missing-med.png', '2026-11-12', '05:30',
                       [sample(cat, i) for i, cat in enumerate(MED_CATEGORIES[:4])], False)
