from datetime import date

import pytest

from app.services.recurring_service import generate_occurrence_dates


def test_monday_through_selected_date_range():
    # 2026-12-07 is Monday (0)
    # 2026-12-28 is Monday (0)
    start = date(2026, 12, 7)
    end = date(2026, 12, 28)
    dates = generate_occurrence_dates(start, end, day_of_week=0)

    assert len(dates) == 4
    assert dates == [
        date(2026, 12, 7),
        date(2026, 12, 14),
        date(2026, 12, 21),
        date(2026, 12, 28),
    ]
    for d in dates:
        assert d.weekday() == 0


def test_sunday_recurrence():
    # 2026-12-06 is Sunday (6)
    # 2026-12-27 is Sunday (6)
    start = date(2026, 12, 6)
    end = date(2026, 12, 27)
    dates = generate_occurrence_dates(start, end, day_of_week=6)

    assert len(dates) == 4
    assert dates == [
        date(2026, 12, 6),
        date(2026, 12, 13),
        date(2026, 12, 20),
        date(2026, 12, 27),
    ]
    for d in dates:
        assert d.weekday() == 6


def test_start_date_matches_selected_weekday():
    # Tuesday 2026-12-01 (weekday 1)
    start = date(2026, 12, 1)
    end = date(2026, 12, 15)
    dates = generate_occurrence_dates(start, end, day_of_week=1)

    assert dates[0] == start
    assert len(dates) == 3
    assert dates == [date(2026, 12, 1), date(2026, 12, 8), date(2026, 12, 15)]


def test_end_date_matches_selected_weekday():
    # Start on Wednesday 2026-12-02 (weekday 2), request Mondays (0)
    # End on Monday 2026-12-28 (weekday 0)
    start = date(2026, 12, 2)
    end = date(2026, 12, 28)
    dates = generate_occurrence_dates(start, end, day_of_week=0)

    assert dates[-1] == end
    assert dates == [
        date(2026, 12, 7),
        date(2026, 12, 14),
        date(2026, 12, 21),
        date(2026, 12, 28),
    ]


def test_start_date_does_not_match_selected_weekday():
    # Start on Friday 2026-12-04 (weekday 4), day_of_week Monday (0)
    # First matching date should be Monday 2026-12-07
    start = date(2026, 12, 4)
    end = date(2026, 12, 21)
    dates = generate_occurrence_dates(start, end, day_of_week=0)

    assert dates[0] == date(2026, 12, 7)
    assert dates == [
        date(2026, 12, 7),
        date(2026, 12, 14),
        date(2026, 12, 21),
    ]


def test_invalid_weekday():
    start = date(2026, 12, 1)
    end = date(2026, 12, 31)

    with pytest.raises(ValueError, match="day_of_week must be between 0"):
        generate_occurrence_dates(start, end, day_of_week=-1)

    with pytest.raises(ValueError, match="day_of_week must be between 0"):
        generate_occurrence_dates(start, end, day_of_week=7)

    with pytest.raises(ValueError, match="day_of_week must be between 0"):
        generate_occurrence_dates(start, end, day_of_week=10)


def test_end_date_before_start_date():
    start = date(2026, 12, 31)
    end = date(2026, 12, 1)

    with pytest.raises(ValueError, match="end_date cannot be earlier than start_date"):
        generate_occurrence_dates(start, end, day_of_week=0)


def test_date_range_with_no_matching_occurrence():
    # Tuesday to Thursday, request Monday -> no Monday in range
    start = date(2026, 12, 8)  # Tuesday
    end = date(2026, 12, 10)  # Thursday
    dates = generate_occurrence_dates(start, end, day_of_week=0)

    assert dates == []
