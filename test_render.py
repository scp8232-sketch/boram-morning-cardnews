import os
from pathlib import Path
from PIL import Image
from src.render import render_morning, render_medical


def test_demo_render(tmp_path):
    item = {'category': '사회', 'title': '테스트 제목', 'headline': '테스트 제목',
            'summary': '테스트 문장입니다. 다음 문장은 자연스럽게 이어지는 내용을 확인합니다.',
            'source': '테스트', 'date': '2026-11-12'}
    morning = tmp_path / 'morning.png'
    medical = tmp_path / 'medical.png'
    render_morning(morning, '2026-11-12', '05:30', [item]*5, {'source':'데모', 'cities':{}}, {}, True)
    render_medical(medical, '2026-11-12', '05:30', [item]*4, True)
    for p in [morning, medical]:
        assert p.exists()
        im = Image.open(p)
        assert im.size == (1080, 1900)
        assert im.getpixel((0, 0))[3] == 0  # 가장 바깥 네 모서리 투명
