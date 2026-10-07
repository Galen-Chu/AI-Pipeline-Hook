"""Tests for runner/cron_schedule.py (5-field cron parsing and due logic)."""
from datetime import UTC, datetime

import pytest

from runner.cron_schedule import is_due, last_fire_time, matches, parse_cron

# 2026-10-07 is a Wednesday, 2026-10-04 a Sunday.


class TestParseCron:
    def test_star(self):
        spec = parse_cron("* * * * *")
        assert spec["minute"] == set(range(60))
        assert spec["dow"] == set(range(7))

    def test_step(self):
        assert parse_cron("*/15 * * * *")["minute"] == {0, 15, 30, 45}

    def test_list_and_range(self):
        spec = parse_cron("0,30 7-9 1 * *")
        assert spec["minute"] == {0, 30}
        assert spec["hour"] == {7, 8, 9}

    def test_dow_7_normalized_to_sunday(self):
        assert parse_cron("* * * * 7")["dow"] == {0}

    def test_vixie_single_value_with_step(self):
        # "5/15" in minutes ≡ 5,20,35,50
        assert parse_cron("5/15 * * * *")["minute"] == {5, 20, 35, 50}

    def test_wrong_field_count(self):
        with pytest.raises(ValueError):
            parse_cron("* * * *")

    def test_out_of_range(self):
        with pytest.raises(ValueError):
            parse_cron("61 * * * *")

    def test_zero_step(self):
        with pytest.raises(ValueError):
            parse_cron("*/0 * * * *")


class TestMatches:
    def test_weekday_schedule(self):
        spec = parse_cron("30 7 * * 1-5")
        assert matches(spec, datetime(2026, 10, 7, 7, 30))      # Wed 07:30
        assert not matches(spec, datetime(2026, 10, 7, 7, 31))  # wrong minute
        assert not matches(spec, datetime(2026, 10, 10, 7, 30))  # Saturday

    def test_dom_dow_or_semantics(self):
        spec = parse_cron("0 0 1 * 1")  # 1st of month OR any Monday
        assert matches(spec, datetime(2026, 10, 1, 0, 0))   # Thursday, dom=1
        assert matches(spec, datetime(2026, 10, 5, 0, 0))   # Monday
        assert not matches(spec, datetime(2026, 10, 7, 0, 0))

    def test_every_minute_matches(self):
        assert matches(parse_cron("* * * * *"), datetime(2026, 10, 7, 13, 59))


class TestLastFireTime:
    def test_same_day(self):
        fire = last_fire_time("30 7 * * 1-5", datetime(2026, 10, 7, 9, 0))
        assert fire == datetime(2026, 10, 7, 7, 30)

    def test_rolls_back_to_previous_day(self):
        fire = last_fire_time("30 7 * * 1-5", datetime(2026, 10, 7, 6, 0))
        assert fire == datetime(2026, 10, 6, 7, 30)

    def test_sunday_via_dow_7(self):
        fire = last_fire_time("0 9 * * 7", datetime(2026, 10, 7, 10, 0))
        assert fire == datetime(2026, 10, 4, 9, 0)

    def test_no_match_in_window_returns_none(self):
        assert last_fire_time("0 5 1 1 *", datetime(2026, 10, 7, 9, 0)) is None


class TestIsDue:
    SCHEDULE = "30 7 * * 1-5"

    def test_never_run_after_first_fire_is_due(self):
        assert is_due(self.SCHEDULE, None, datetime(2026, 10, 7, 9, 0))

    def test_ran_after_fire_not_due(self):
        # 09:56 local (= 01:56 UTC) is after today's 07:30 fire
        assert not is_due(self.SCHEDULE, "2026-10-07T01:56:00+00:00", datetime(2026, 10, 7, 9, 0))

    def test_ran_before_fire_is_due(self):
        assert is_due(self.SCHEDULE, "2026-10-06T22:00:00+00:00", datetime(2026, 10, 7, 9, 0))

    def test_aware_now(self):
        # every-minute schedule: due in any timezone as long as last_run predates now
        assert is_due("* * * * *", "2026-10-06T22:00:00+00:00",
                      datetime(2026, 10, 7, 9, 0, tzinfo=UTC))

    def test_invalid_schedule_raises(self):
        with pytest.raises(ValueError):
            is_due("not a cron", None, datetime(2026, 10, 7, 9, 0))
