# REVIEW.md

## Defects Found in the Starter Application

The following defects were identified during the review of the attendance management API. Each issue was evaluated based on correctness, validation, concurrency, database performance, and API behavior.

| # | Where (function / line) | What is wrong | How you'd notice it (test, input, or symptom) | How you fixed it |
|---|---|---|---|---|
| 1 | `/health` endpoint | Health check does not verify database connectivity. | Stop MongoDB and call `/health`; it may incorrectly report healthy. | Added a MongoDB ping and return an error status when the database is unavailable. |
| 2 | Employee creation | Duplicate employee codes may be inserted during concurrent requests. | Submit two simultaneous requests with the same `emp_code`. | Added a unique index and handled duplicate-key errors. |
| 3 | Database startup / indexes | Required indexes may be missing, causing slow queries and allowing duplicate records. | Inspect database indexes and execute queries against larger datasets. | Added indexes for employee codes, attendance uniqueness, date/status, punch-in lookup, and department/joining-date queries. |
| 4 | Employee listing | Pagination may not apply `skip` correctly. | Request successive pages and check for repeated records. | Applied validated `skip` and `limit` values to the database query. |
| 5 | Employee listing / count | Total count may ignore active filters. | Filter employees by department and compare the count with the returned results. | Applied the same filter to the count query. |
| 6 | Employee listing | Invalid or excessive pagination values may be accepted. | Try negative offsets, zero limits, or limits above the allowed maximum. | Added query parameter validation and pagination bounds. |
| 7 | `compute_late_minutes` | Incorrect time calculations can produce inaccurate late-arrival durations. | Test an employee arriving before, exactly at, and after shift start. | Corrected the time calculation and validated the expected boundary cases. |
| 8 | `compute_work_hours` | Incorrect punch-in/punch-out calculations can produce inaccurate working hours. | Test known timestamps and compare the result with the expected duration. | Corrected duration calculation and rounding behavior. |
| 9 | `compute_overtime` | Overtime may be calculated incorrectly when working duration is near the configured threshold. | Test durations below, at, and above the overtime threshold. | Corrected overtime calculation using the configured work-duration rules. |
| 10 | Attendance punch-in | Concurrent punch-in requests can create duplicate attendance records. | Submit simultaneous punch-in requests for the same employee and date. | Used the unique employee/date index and handled duplicate-key errors. |
| 11 | Attendance punch-out | A non-atomic update can allow multiple requests to overwrite an existing punch-out. | Send two punch-out requests concurrently. | Used a conditional atomic update so only an eligible attendance record can be punched out. |
| 12 | Attendance regularization | Updating attendance without retaining an audit trail makes corrections difficult to trace. | Change attendance values and inspect the record's history. | Preserved regularization details, including the actor, reason, timestamp, and changes. |
| 13 | Monthly employee analytics | Computing analytics by fetching records and looping in Python does not scale efficiently. | Review the implementation and test it with a larger attendance dataset. | Used MongoDB aggregation to calculate monthly attendance metrics in the database. |
| 14 | Department summary | Joining employees with attendance records incorrectly can inflate or omit department metrics. | Test departments with multiple employees and employees with no attendance records. | Used a lookup and aggregation approach that groups attendance per employee before calculating department totals. |
| 15 | Late leaderboard | Incorrect ranking or limiting can omit employees tied at the cutoff. | Create employees with equal late-minute totals around the requested limit. | Used database-side ranking and deterministic sorting. Verify the tie behavior against the assignment's exact rule. |
| 16 | Department trend | Date densification may omit the requested final date. | Request a seven-day range and count the returned rows. | Extended the exclusive upper boundary by one day and filtered results back to the requested inclusive range. |
| 17 | Department trend | Calculating headcount from employee records loaded into Python violates the database-side aggregation requirement. | Inspect the pipeline for a Python-side `find()` whose results are injected into `$literal`. | Moved employee lookup and headcount calculation into MongoDB aggregation. |
| 18 | Department trend | Missing attendance dates and weekends may be omitted from the response. | Request a date range containing days with no attendance records and weekends. | Used `$densify`, supplied zero counts for missing dates, and identified weekends in the aggregation. |
| 19 | Admin explain endpoint | Explaining a simplified query rather than the actual endpoint query can produce misleading execution plans. | Compare the explain filters, sort, pagination, and pipeline with the real endpoint. | Needs verification: ensure explain uses the actual query or aggregation and reports execution statistics. |

## Items Reviewed and Not Considered Defects

| Item | Why it is not necessarily a defect |
|---|---|
| Returning HTTP 404 for an unknown employee | This is appropriate when the requested employee does not exist. |
| Returning HTTP 422 for invalid input | This is appropriate for invalid dates, malformed parameters, or out-of-range values. |
| Using MongoDB aggregation for analytics | This is appropriate for database-side calculations and large datasets. |
| Returning an empty list when no attendance history exists | This is a valid response when the employee exists but has no attendance records. |
| Excluding weekends from attendance-rate calculations | This is appropriate when the business rules define attendance rates only for working days. |
| Keeping regularization history | This is a useful auditability feature and should not be removed when correcting attendance records. |

## Review Notes

The fixes should be validated with automated tests covering normal requests, invalid inputs, missing records, boundary dates, concurrent writes, pagination, and database query plans.

Items marked as needing verification should not be considered fully resolved until the corresponding implementation and tests have been checked. The final review should reflect defects actually present in the supplied starter application rather than hypothetical issues.
