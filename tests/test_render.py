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


def test_public_card_fits_verified_125_char_text(tmp_path):
    """A long but verified two-sentence summary must fit without silent clipping.

    The former 98px card/2-line summary layout raised ValueError even though
    the newsroom correctly accepted 70..125 characters.
    """
    summary = ('금융위원회는 구체적인 시행 일정과 적용 대상을 담은 정책을 공개했습니다. '
               '관계 부처는 현장에 적용할 수 있는 세부 기준과 안내 절차를 검토 중이며, '
               '국민들은 공식 안내를 통해 각자의 적용 여부를 확인할 수 있습니다.')
    summary = summary[:125]
    assert 70 <= len(summary) <= 125
    headlines = [
        '정부, 올해 주요 정책 시행 일정과 대상 기관별 안내 계획 공개',
        '금융당국, 시장 개선 조치와 금융소비자 보호 원칙 함께 점검',
        '사회 안전망 정비 계획 발표, 이용 절차와 시행 시점 구분',
        '국제 회의에서 주요 협력 현황과 공동 대응 방안 논의',
        '생활문화 행사 운영 지침 발표, 시민 참여 방식과 안내 사항 공개',
    ]
    rows = []
    for cat, title in zip(CATEGORIES, headlines):
        item = sample(cat, 1)
        item['headline'] = title
        item['summary'] = summary
        rows.append(item)
    target = tmp_path / 'long-verified-morning.png'
    render_morning(target, '2026-11-15', '23:00', rows, fake_weather(), fake_market(), False)
    assert target.exists()


def test_medical_card_fits_verified_125_char_text(tmp_path):
    summary = ('건강보험 보장 기준과 진료비 환급 절차를 안내하는 자료가 공개됐습니다. '
               '가입자는 기존 계약의 보장 범위와 본인부담금을 비교하고, '
               '신청 대상 여부는 담당 기관의 공식 안내에서 확인해야 합니다.')
    summary = (summary + ' 자세한 내용은 공지문을 확인하시기 바랍니다.')[:125]
    assert 70 <= len(summary) <= 125
    rows = []
    for cat in MED_CATEGORIES:
        item = sample(cat, 1)
        item['headline'] = '건강보험 및 의료 제도 변경과 관련한 신청 대상·기간 안내'
        item['summary'] = summary
        rows.append(item)
    target = tmp_path / 'long-verified-medical.png'
    render_medical(target, '2026-11-15', '23:00', rows, False)
    assert target.exists()


def test_actual_overflow_is_not_silently_cut(tmp_path):
    """Grossly oversized unverified content still stops publication."""
    rows = [sample(cat, i) for i, cat in enumerate(CATEGORIES)]
    rows[0]['summary'] = '매우 길어서 카드에 담을 수 없는 문장입니다. ' * 100
    with pytest.raises(ValueError, match='텍스트 초과'):
        render_morning(tmp_path / 'oversize.png', '2026-11-15', '23:00',
                       rows, fake_weather(), fake_market(), False)


def test_long_realistic_international_report_fits_morning(tmp_path):
    """Regression for the 2026-11-15 GitHub Action rendering failure."""
    original = ('젠슨 황 전 엔비디아 최고경영자(CEO)의 퇴진에 미국 중간선거 이후 '
                '여야 갈등이 영향을 미쳤다는 주장이 나왔습니다. 중국 관영매체가 '
                '이러한 관점을 담은 논평을 소개하며 정책 영향 가능성도 거론했습니다.')
    assert 70 <= len(original) <= 125
    rows = [sample(cat, i) for i, cat in enumerate(CATEGORIES)]
    rows[3]['headline'] = '중국 관영매체, 젠슨 황 퇴진 배경으로 미국 정치 갈등 거론'
    rows[3]['summary'] = original
    target = tmp_path / 'repro-news-overflow.png'
    render_morning(target, '2026-11-15', '23:00', rows, fake_weather(), fake_market(), False)
    assert target.exists()


def test_gold_icon_contains_no_stray_letter_pixels():
    from pathlib import Path
    from PIL import Image
    asset=Path(__file__).resolve().parents[1]/'assets'/'gold.png'
    im=Image.open(asset).convert('RGBA')
    assert im.size == (47,39)
    assert all(im.getpixel((x,y))[3] == 0
               for x in range(35,47) for y in range(39))
