# DECISIONS.md

1. **Indexes.** I created a unique index on `employees.emp_code` to prevent duplicate employee codes, and a unique compound index on `attendance_logs.emp_code` and `date` to prevent duplicate daily attendance. I added indexes on attendance `date` and `status` for date-based filtering, on `emp_code` and `punch_in` for employee attendance lookups, and on employee `department` and `joined_on` for department analytics. I considered a separate index on `late_minutes`, but did not add it because the current leaderboard also filters by date.

2. **Punch-in race.** If two identical requests arrive together, both may attempt an insert. The unique employee/date index allows only one insert to succeed. The other raises a duplicate-key error, which the API should handle with a clear response rather than creating another record.

3. **Ties.** The leaderboard uses database-side ranking by total late minutes. Employees tied at the cutoff may all be returned if the query filters by rank; this avoids arbitrarily excluding employees with equal scores.

4. **Headcount.** The department summary starts from employees and looks up their attendance logs. Therefore, employees with no logs remain included in the department headcount.

5. **Scaling.** For 100 times more data, I would review query plans and index selectivity, add load testing, and consider archiving older attendance records.
