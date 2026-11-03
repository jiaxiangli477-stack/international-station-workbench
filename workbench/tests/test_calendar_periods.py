from datetime import date
import unittest
import task_store

class CalendarPeriodsTests(unittest.TestCase):
    def test_week_defaults_to_last_complete_monday_sunday(self):
        self.assertEqual(task_store.period(None,today=date(2026,10,20))['start'],'2026-10-12')
        self.assertEqual(task_store.period('previous_week',today=date(2026,10,20))['end'],'2026-10-18')
    def test_month_is_complete_calendar_month_not_30_days(self):
        self.assertEqual(task_store.period('previous_month',today=date(2026,11,3))['start'],'2026-10-01')
        self.assertEqual(task_store.period('previous_month',today=date(2026,11,3))['end'],'2026-10-31')
    def test_leap_february_and_year_boundary(self):
        self.assertEqual(task_store.period('previous_month',today=date(2024,3,1))['end'],'2024-02-29')
        self.assertEqual(task_store.period('previous_week',today=date(2027,1,1))['start'],'2026-12-21')
    def test_rolling_and_partial_periods_rejected(self):
        for mode in ['last7','this_week']:
            with self.assertRaises(ValueError):task_store.period(mode,today=date(2026,10,20))
        with self.assertRaises(ValueError):task_store.period('custom','2026-10-13','2026-10-19',today=date(2026,10,20))
    def test_explicit_calendar_month_allowed(self):
        self.assertEqual(task_store.period('custom','2026-09-01','2026-09-30',today=date(2026,10,20))['end'],'2026-09-30')
    def test_dashboard_month_is_not_anchored_to_last_weeks_month(self):
        from calendar_periods import dashboard_windows
        d=dashboard_windows(date(2026,10,1))
        self.assertEqual(d['months'][0]['month_start'],'2026-09-01')
        self.assertEqual(len(d['months']),1)
        self.assertEqual(d['weeks'][0]['week_end'],'2026-09-27')

if __name__=='__main__':unittest.main()
