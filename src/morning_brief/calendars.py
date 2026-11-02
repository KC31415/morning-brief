"""Which dates each market is expected to have a row for.

Names are exchange_calendars codes plus three custom calendars for series that no
exchange matches. Choices were checked against two years of real dates; see build notes.
"""
import exchange_calendars as xc
import pandas as pd
from pandas.tseries.holiday import AbstractHolidayCalendar, EasterMonday, GoodFriday, Holiday, USFederalHolidayCalendar


class TargetCalendar(AbstractHolidayCalendar):
    """Days the ECB publishes no reference rate."""
    rules = [Holiday("New Year", month=1, day=1), GoodFriday, EasterMonday, Holiday("Labour Day", month=5, day=1),
             Holiday("Christmas", month=12, day=25), Holiday("Boxing Day", month=12, day=26)]


class FxCalendar(AbstractHolidayCalendar):
    """FX trades around the clock on weekdays, but Yahoo has no row on these two days."""
    rules = [Holiday("New Year", month=1, day=1), Holiday("Christmas", month=12, day=25)]


CUSTOM = {"USFED": USFederalHolidayCalendar, "TARGET": TargetCalendar, "FX": FxCalendar}


def sessions(name: str | None, start: pd.Timestamp, end: pd.Timestamp) -> pd.DatetimeIndex:
    """Expected dates from start to end inclusive. No calendar means plain weekdays."""
    start, end = pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize()
    if name is None:
        return pd.bdate_range(start, end)
    if name in CUSTOM:
        return pd.bdate_range(start, end).difference(CUSTOM[name]().holidays(start, end))
    return xc.get_calendar(name).sessions_in_range(start, end)
