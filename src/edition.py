"""One dated, approved manuscript for chat previews, rendering and Kakao delivery.

This module never fetches news or rewrites an approved article.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date as Date, datetime
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

GENERAL = ('정치', '경제', '사회', '국제', '생활/문화')
MEDICAL = ('건강보험', '보험제도', '보건정책', '의료기술', '건강정보')
FILES = ('morning.png', 'medical.png', 'morning-preview.jpg', 'medical-preview.jpg',
         'edition.json', 'verification.json', 'index.html')


class EditionError(RuntimeError):
    pass


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def encoded(edition: dict) -> bytes:
    return (json.dumps(edition, ensure_ascii=False, sort_keys=True, indent=2)+'\n').encode('utf-8')


def validate(edition: dict, day: str) -> dict:
    if not isinstance(edition, dict) or edition.get('date') != day:
        raise EditionError('확정 원고의 발행일이 요청 날짜와 다릅니다.')
    try:
        Date.fromisoformat(day)
        datetime.strptime(edition.get('checked', ''), '%H:%M')
    except (ValueError, TypeError) as exc:
        raise EditionError('발행일 또는 자료 확인 시각 형식이 잘못됐습니다.') from exc
    for key, categories in (('articles', GENERAL), ('medical', MEDICAL)):
        rows = edition.get(key)
        if not isinstance(rows, list) or len(rows) != len(categories):
            raise EditionError(f'{key}: 확정 기사 5건이 필요합니다.')
        labels = [a.get('category') for a in rows if isinstance(a, dict)]
        if len(labels) != 5 or any(not isinstance(label, str) or not label for label in labels):
            raise EditionError(f'{key}: 기사 분류가 없습니다.')
        if len(set(labels)) != 5 or (key == 'articles' and set(labels) != set(categories)):
            raise EditionError(f'{key}: 필수 분야 누락 또는 중복입니다.')
        for article in rows:
            title, body = article.get('headline'), article.get('summary')
            if not isinstance(title, str) or not 12 <= len(title) <= 56:
                raise EditionError('헤드라인은 12~56자로 작성하세요.')
            if not isinstance(body, str) or not 120 <= len(body) <= 180:
                raise EditionError('본문은 120~180자로 작성하세요. 시안의 3~4줄 분량을 유지합니다.')
            if not body.endswith('니다.'):
                raise EditionError('본문은 완결된 존댓말 문장으로 작성하세요.')
            if not isinstance(article.get('date'), str):
                raise EditionError('기사 발표일이 필요합니다.')
            try:
                published = Date.fromisoformat(article['date'])
            except ValueError as exc:
                raise EditionError('기사 발표일 형식이 잘못됐습니다.') from exc
            if published > Date.fromisoformat(day):
                raise EditionError('미래 발표 기사를 게시할 수 없습니다.')
            sources = article.get('sources')
            if not isinstance(sources, list) or len(sources) < 2:
                raise EditionError('기사별 교차 확인 출처 URL이 두 개 이상 필요합니다.')
            hosts = set()
            for url in sources:
                if not isinstance(url, str):
                    raise EditionError('출처 URL은 문자열이어야 합니다.')
                parsed = urlsplit(url)
                host = (parsed.hostname or '').lower().removeprefix('www.')
                if parsed.scheme != 'https' or not host or parsed.username or parsed.password:
                    raise EditionError('출처에는 인증정보 없는 HTTPS URL을 사용하세요.')
                hosts.add(host)
            if len(hosts) < 2:
                raise EditionError('동일 사이트 링크 두 개는 교차 확인으로 인정하지 않습니다.')
            if article.get('url') not in sources:
                raise EditionError('주 출처 URL은 교차 확인 출처 목록에 포함돼야 합니다.')
    for key in ('weather', 'market'):
        if not isinstance(edition.get(key), dict) or not edition[key]:
            raise EditionError(f'{key} 확정 자료가 없습니다.')
    return deepcopy(edition)


def load(root: Path, day: str) -> dict:
    path = root / 'editions' / f'{day}.json'
    if not path.is_file():
        raise EditionError(f'오늘 확정 원고가 없습니다: editions/{day}.json. 다른 기사를 자동 생성하지 않습니다.')
    try:
        edition = json.loads(path.read_text(encoding='utf-8'))
    except (ValueError, OSError) as exc:
        raise EditionError('확정 원고를 읽지 못했습니다.') from exc
    return validate(edition, day)


def seal(folder: Path, edition: dict) -> None:
    """Save the unchanged manuscript and bind all deliverables to its hash."""
    (folder / 'edition.json').write_bytes(encoded(edition))
    manifest = {'date': edition['date'], 'manuscript_sha256': digest(encoded(edition)),
                'files': {name: digest((folder / name).read_bytes()) for name in FILES}}
    (folder / 'publication.json').write_text(json.dumps(manifest, indent=2)+'\n', encoding='utf-8')


def verify(root: Path, day: str) -> dict:
    folder = root / 'docs' / day
    try:
        manifest = json.loads((folder / 'publication.json').read_text(encoding='utf-8'))
        edition = load(root, day)
        if manifest.get('date') != day or manifest.get('manuscript_sha256') != digest(encoded(edition)):
            raise EditionError('확정 원고와 배포본이 다릅니다. 다시 렌더링해야 합니다.')
        expected = manifest.get('files', {})
        for name in FILES:
            if expected.get(name) != digest((folder / name).read_bytes()):
                raise EditionError(f'확정 원고의 배포 파일이 변경됐습니다: {name}')
        if (folder / 'edition.json').read_bytes() != encoded(edition):
            raise EditionError('배포 원고와 확정 원고가 다릅니다.')
        return manifest
    except (OSError, ValueError, TypeError) as exc:
        raise EditionError('확정 원고와 이미지 일치 확인에 실패했습니다.') from exc
