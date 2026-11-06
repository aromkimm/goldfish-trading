"""추세·계절성·관심도 지표. 입력은 NAVER API HUB의 월별 상대값과 블로그 글 작성일."""
from __future__ import annotations

from datetime import date, datetime, timedelta


def window(today: date | None = None) -> tuple[str, str]:
    """직전 달까지 12개월(시작일, 종료일). 이번 달은 아직 끝나지 않아 뺀다."""
    today = today or date.today()
    end = today.replace(day=1) - timedelta(days=1)
    start_month = end.month % 12 + 1
    start = date(end.year - (0 if end.month == 12 else 1), start_month, 1)
    return start.isoformat(), end.isoformat()


def growth(series: list[float]) -> float | None:
    """최근 3개월 평균 ÷ 그 전 3개월 평균. 1보다 크면 관심이 늘고 있다. 비교 구간이 0이면 None."""
    if len(series) < 6:
        return None
    recent, before = sum(series[-3:]) / 3, sum(series[-6:-3]) / 3
    return round(recent / before, 2) if before > 0 else None


def season_index(series: list[float]) -> float | None:
    """직전 달 ÷ 12개월 평균. 1보다 크면 지금이 평소보다 수요가 큰 시기다."""
    mean = sum(series) / len(series) if series else 0
    return round(series[-1] / mean, 2) if mean > 0 else None


def months_with_data(series: list[float]) -> int:
    return sum(1 for v in series if v > 0)


def blog_rate(postdates: list[str], today: date | None = None) -> float | None:
    """최신 블로그 글 묶음의 하루 평균 작성 수. 글이 100개 꽉 차면 실제보다 낮게 잡히지 않도록 최신 글 범위로 계산한다."""
    today = today or date.today()
    days = [datetime.strptime(d, "%Y%m%d").date() for d in postdates if len(d) == 8]
    if not days:
        return None
    span = max((today - min(days)).days, 1)
    return round(len(days) / span, 2)
