"""
Employee Attendance & Analytics API - STARTER

Run:  uvicorn app.main:app --port 8000
Env:  MONGO_URI, MONGO_DB (a local .env is loaded for convenience)

This file was written quickly by a colleague who has left the company. The happy path
works, but nobody has reviewed it. Read PROBLEM_STATEMENT.docx for what is expected of you,
openapi.yaml for the contract and DATA_MODEL.md for what is stored in MongoDB.
"""

import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, field_validator
from pymongo import MongoClient, ReturnDocument
from pymongo.errors import DuplicateKeyError

load_dotenv()

client = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017"))
db = client[os.getenv("MONGO_DB", "attendance_db")]

IST = timezone(timedelta(hours=5, minutes=30))

app = FastAPI(title="Employee Attendance & Analytics API", version="2.0.0")


@app.on_event("startup")
def create_indexes():
    db.employees.create_index("emp_code", unique=True)

    db.attendance_logs.create_index(
        [("emp_code", 1), ("date", 1)],
        unique=True,
    )
    db.attendance_logs.create_index(
        [("date", -1), ("status", 1)]
    )
    db.attendance_logs.create_index(
        [("emp_code", 1), ("punch_in", -1)]
    )
    db.employees.create_index(
        [("department", 1), ("joined_on", 1)]
    )

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def compute_late_minutes(punch_in: datetime, shift_start: str) -> int:
    h, m = map(int, shift_start.split(":"))

    start = punch_in.replace(
        hour=h, minute=m, second=0, microsecond=0
    )

    late_seconds = int((punch_in - start).total_seconds())

    if late_seconds <= 10 * 60:
        return 0

    return late_seconds // 60




from decimal import Decimal, ROUND_HALF_UP

def compute_work_hours(punch_in: datetime, punch_out: datetime) -> float:
    seconds = int((punch_out - punch_in).total_seconds())
    hours = Decimal(seconds) / Decimal(3600)

    return float(
        hours.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    )




def compute_overtime(punch_out: datetime, shift_end: str, date_str: str) -> int:
    h, m = map(int, shift_end.split(":"))

    end = datetime.fromisoformat(date_str).replace(
        hour=h, minute=m, second=0, microsecond=0, tzinfo=IST
    )

    overtime_seconds = int((punch_out - end).total_seconds())

    if overtime_seconds < 30 * 60:
        return 0

    return overtime_seconds // 60



# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #

class EmployeeIn(BaseModel):
    emp_code: str
    name: str
    email: str
    department: str
    shift_start: str = "09:30"
    shift_end: str = "18:30"
    joined_on: str

    @field_validator("shift_start", "shift_end")
    @classmethod
    def validate_shift_time(cls, value: str) -> str:
        try:
            datetime.strptime(value, "%H:%M")
        except ValueError:
            raise ValueError("Time must use HH:MM format")
        return value

    @field_validator("joined_on")
    @classmethod
    def validate_joined_on(cls, value: str) -> str:
        try:
            datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            raise ValueError("joined_on must use YYYY-MM-DD format")
        return value


class PunchInIn(BaseModel):
    emp_code: str
    punched_at: Optional[int] = None
    status: str = "PRESENT"

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str) -> str:
        allowed = {"PRESENT", "WFH", "ON_DUTY", "ABSENT", "LEAVE"}
        if value not in allowed:
            raise ValueError("Invalid attendance status")
        return value

    @field_validator("punched_at")
    @classmethod
    def validate_punched_at(cls, value: Optional[int]) -> Optional[int]:
        if value is not None and value <= 0:
            raise ValueError("punched_at must be a positive epoch timestamp in milliseconds")
        return value



class PunchOutIn(BaseModel):
    emp_code: str
    punched_at: Optional[int] = None

    @field_validator("punched_at")
    @classmethod
    def validate_punched_at(cls, value: Optional[int]) -> Optional[int]:
        if value is not None and value <= 0:
            raise ValueError("punched_at must be a positive epoch timestamp in milliseconds")
        return value


class RegularizeRequest(BaseModel):
    status: Optional[str] = None
    punch_in: Optional[int] = None
    punch_out: Optional[int] = None
    reason: str
    regularized_by: str

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and value not in {
            "PRESENT", "WFH", "ON_DUTY", "ABSENT", "LEAVE"
        }:
            raise ValueError("Invalid attendance status")
        return value

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        if not 5 <= len(value) <= 200:
            raise ValueError("reason must be 5–200 characters")
        return value

    @field_validator("regularized_by")
    @classmethod
    def validate_regularized_by(cls, value: str) -> str:
        if not 1 <= len(value) <= 50:
            raise ValueError("regularized_by must be 1–50 characters")
        return value

    @field_validator("punch_in", "punch_out")
    @classmethod
    def validate_timestamps(cls, value: Optional[int]) -> Optional[int]:
        if value is not None and value <= 0:
            raise ValueError("Timestamps must be positive epoch milliseconds")
        return value

# --------------------------------------------------------------------------- #
# Endpoints provided
# --------------------------------------------------------------------------- #

@app.get("/health")
def health():
    try:
        db.command("ping")
        return {"status": "ok"}
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Database unavailable"
        )




@app.post("/employees", status_code=201)
def create_employee(body: EmployeeIn):
    doc = body.model_dump()
    doc["created_at"] = datetime.now(timezone.utc)

    try:
        db.employees.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(
            status_code=409,
            detail="emp_code already exists"
        )

    doc.pop("_id", None)
    return doc



@app.get("/employees")
def list_employees(department: Optional[str] = None, page: int = Query(default=1, ge=1), page_size: int = Query(default=20, ge=1, le=100)):
    q = {}
    if department:
        q["department"] = department
    skip = (page - 1) * page_size
    total = db.employees.count_documents(q)
    items = list(db.employees.find(q, {"_id": 0}).skip(skip).limit(page_size))
    return {"items": items, "total": total, "page": page, "page_size": page_size}



@app.post("/attendance/punch-in", status_code=201)
def punch_in(body: PunchInIn):
    emp = db.employees.find_one({"emp_code": body.emp_code})

    if emp is None:
        raise HTTPException(status_code=404, detail="Employee not found")

    if body.punched_at is not None:
        ts_utc = datetime.fromtimestamp(
            body.punched_at / 1000, tz=timezone.utc
        ).replace(microsecond=0)
    else:
        ts_utc = datetime.now(timezone.utc).replace(microsecond=0)

    ts_ist = ts_utc.astimezone(IST)
    attendance_date = ts_ist.date().isoformat()

    doc = {
        "emp_code": body.emp_code,
        "date": attendance_date,
        "status": body.status,
        "punch_in": ts_utc,
        "punch_out": None,
        "work_hours": None,
        "late_minutes": compute_late_minutes(
            ts_ist, emp["shift_start"]
        ),
        "overtime_minutes": 0,
        "half_day": False,
        "history": [],
    }

    try:
        result = db.attendance_logs.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(
            status_code=409,
            detail="Already punched in for this date",
        )

    doc["id"] = str(result.inserted_id)
    return doc




@app.get("/attendance")
def list_attendance(
    emp_code: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    status: Optional[str] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    q = {}

    if emp_code:
        q["emp_code"] = emp_code

    if date_from or date_to:
        q["date"] = {}
        if date_from:
            q["date"]["$gte"] = date_from
        if date_to:
            q["date"]["$lte"] = date_to

    if status:
        q["status"] = status

    total = db.attendance_logs.count_documents(q)

    docs = list(
        db.attendance_logs.find(q, {"_id": 1, "emp_code": 1, "date": 1,
                                    "status": 1, "punch_in": 1, "punch_out": 1,
                                    "work_hours": 1, "late_minutes": 1,
                                    "overtime_minutes": 1, "half_day": 1,
                                    "history": 1})
        .sort("date", -1)
        .skip((page - 1) * page_size)
        .limit(page_size)
    )

    for doc in docs:
        doc["id"] = str(doc.pop("_id"))

    return {
        "items": docs,
        "total": total,
        "page": page,
        "page_size": page_size,
    }



@app.post("/attendance/punch-out")
def punch_out(body: PunchOutIn):
    emp = db.employees.find_one({"emp_code": body.emp_code})
    if emp is None:
        raise HTTPException(status_code=404, detail="Employee not found")

    if body.punched_at is not None:
        out_utc = datetime.fromtimestamp(
            body.punched_at / 1000, tz=timezone.utc
        ).replace(microsecond=0)
    else:
        out_utc = datetime.now(timezone.utc).replace(microsecond=0)

    # Find the latest punch-in that occurred at or before punch-out.
    record = db.attendance_logs.find_one(
        {
            "emp_code": body.emp_code,
            "punch_in": {"$lte": out_utc},
        },
        sort=[("punch_in", -1)],
    )

    if record is None:
        raise HTTPException(status_code=404, detail="No matching punch-in found")

    in_utc = record["punch_in"]
    if in_utc.tzinfo is None:
        in_utc = in_utc.replace(tzinfo=timezone.utc)

    elapsed_seconds = int((out_utc - in_utc).total_seconds())

    if elapsed_seconds <= 0 or elapsed_seconds > 24 * 60 * 60:
        raise HTTPException(
            status_code=422,
            detail="Punch-out must be after punch-in and within 24 hours",
        )

    work_hours = compute_work_hours(in_utc, out_utc)

    shift_start_h, shift_start_m = map(int, emp["shift_start"].split(":"))
    shift_end_h, shift_end_m = map(int, emp["shift_end"].split(":"))

    shift_end_date = datetime.fromisoformat(record["date"]).date()
    if (shift_end_h, shift_end_m) <= (shift_start_h, shift_start_m):
        from datetime import timedelta as td
        shift_end_date += td(days=1)

    shift_end_ist = datetime.combine(
        shift_end_date,
        datetime.min.time(),
        tzinfo=IST,
    ).replace(hour=shift_end_h, minute=shift_end_m)

    overtime_seconds = int(
        (out_utc.astimezone(IST) - shift_end_ist).total_seconds()
    )
    overtime_minutes = (
        overtime_seconds // 60 if overtime_seconds >= 30 * 60 else 0
    )

    result = db.attendance_logs.update_one(
        {
            "_id": record["_id"],
            "punch_out": None,
        },
        {
            "$set": {
                "punch_out": out_utc,
                "work_hours": work_hours,
                "overtime_minutes": overtime_minutes,
                "half_day": work_hours < 4.50,
            }
        },
    )

    if result.modified_count != 1:
        raise HTTPException(status_code=409, detail="Already punched out")

    updated = db.attendance_logs.find_one({"_id": record["_id"]})
    updated["id"] = str(updated.pop("_id"))
    return updated


@app.patch("/attendance/{emp_code}/{date}")
def regularize_attendance(
    emp_code: str,
    date: str,
    body: RegularizeRequest,
):
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=422, detail="date must be YYYY-MM-DD")

    record = db.attendance_logs.find_one({
        "emp_code": emp_code,
        "date": date,
    })

    if record is None:
        raise HTTPException(status_code=404, detail="Attendance record not found")

    changes = body.model_dump(
        exclude={"reason", "regularized_by"},
        exclude_unset=True,
    )

    if not changes:
        raise HTTPException(status_code=422, detail="No fields to update")

    updates = {}
    history_changes = {}

    for field, value in changes.items():
        if field in ("punch_in", "punch_out"):
            new_value = (
                datetime.fromtimestamp(value / 1000, tz=timezone.utc)
                .replace(microsecond=0)
                if value is not None else None
            )
        else:
            new_value = value

        old_value = record.get(field)
        if old_value != new_value:
            updates[field] = new_value
            history_changes[field] = {
                "before": old_value,
                "after": new_value,
            }

    if not updates:
        raise HTTPException(status_code=422, detail="No values changed")

    merged = {**record, **updates}
    punch_in = merged.get("punch_in")
    punch_out = merged.get("punch_out")

    derived = {
        "late_minutes": 0,
        "overtime_minutes": 0,
        "work_hours": None,
        "half_day": False,
    }

    emp = db.employees.find_one({"emp_code": emp_code})
    if emp is None:
        raise HTTPException(status_code=404, detail="Employee not found")

    if punch_in is not None:
        punch_in_utc = punch_in.replace(tzinfo=timezone.utc) if punch_in.tzinfo is None else punch_in
        punch_in_ist = punch_in_utc.astimezone(IST)
        derived["late_minutes"] = compute_late_minutes(
            punch_in_ist, emp["shift_start"]
        )

    if punch_in is not None and punch_out is not None:
        punch_out_utc = punch_out.replace(tzinfo=timezone.utc) if punch_out.tzinfo is None else punch_out
        elapsed = (punch_out_utc - punch_in_utc).total_seconds()

        if elapsed <= 0 or elapsed > 24 * 60 * 60:
            raise HTTPException(
                status_code=422,
                detail="Punch-out must be after punch-in and within 24 hours",
            )

        derived["work_hours"] = compute_work_hours(punch_in_utc, punch_out_utc)
        derived["half_day"] = derived["work_hours"] < 4.50

        shift_start_h, shift_start_m = map(int, emp["shift_start"].split(":"))
        shift_end_h, shift_end_m = map(int, emp["shift_end"].split(":"))
        shift_end_date = datetime.fromisoformat(date).date()

        if (shift_end_h, shift_end_m) <= (shift_start_h, shift_start_m):
            from datetime import timedelta as td
            shift_end_date += td(days=1)

        shift_end_ist = datetime.combine(
            shift_end_date, datetime.min.time(), tzinfo=IST
        ).replace(hour=shift_end_h, minute=shift_end_m)

        overtime_seconds = int(
            (punch_out_utc.astimezone(IST) - shift_end_ist).total_seconds()
        )
        derived["overtime_minutes"] = (
            overtime_seconds // 60 if overtime_seconds >= 30 * 60 else 0
        )

    history_entry = {
        "at": datetime.now(timezone.utc),
        "by": body.regularized_by,
        "reason": body.reason,
        "changes": history_changes,
    }

    # Atomic append and update; concurrent corrections cannot overwrite history.
    result = db.attendance_logs.update_one(
        {"_id": record["_id"]},
        {
            "$set": {**updates, **derived},
            "$push": {"history": history_entry},
        },
    )

    if result.matched_count != 1:
        raise HTTPException(status_code=404, detail="Attendance record not found")

    updated = db.attendance_logs.find_one({"_id": record["_id"]})
    updated["id"] = str(updated.pop("_id"))
    return updated



@app.get("/analytics/employees/{emp_code}/monthly")
def employee_monthly(
    emp_code: str,
    month: str = Query(..., pattern=r"^\d{4}-\d{2}$"),
):
    # Validate the requested month and calculate its date boundaries.
    try:
        month_start = datetime.strptime(month, "%Y-%m").date()
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid month")

    if month_start.strftime("%Y-%m") != month:
        raise HTTPException(status_code=422, detail="Invalid month")

    if month_start.month == 12:
        next_month = month_start.replace(
            year=month_start.year + 1, month=1
        )
    else:
        next_month = month_start.replace(month=month_start.month + 1)

    start_str = month_start.isoformat()
    end_str = next_month.isoformat()

    pipeline = [
        {"$match": {"emp_code": emp_code}},
        {
            "$set": {
                "_month_start": {
                    "$dateFromString": {
                        "dateString": start_str,
                        "timezone": "Asia/Kolkata",
                    }
                },
                "_month_end": {
                    "$dateFromString": {
                        "dateString": end_str,
                        "timezone": "Asia/Kolkata",
                    }
                },
                "_joined": {
                    "$dateFromString": {
                        "dateString": "$joined_on",
                        "timezone": "Asia/Kolkata",
                    }
                },
            }
        },
        {
            "$set": {
                "_effective_start": {
                    "$max": ["$_month_start", "$_joined"]
                }
            }
        },
        {
            "$set": {
                "_working_day_count": {
                    "$cond": [
                        {"$lt": ["$_effective_start", "$_month_end"]},
                        {
                            "$size": {
                                "$filter": {
                                    "input": {
                                        "$map": {
                                            "input": {
                                                "$range": [
                                                    0,
                                                    {
                                                        "$dateDiff": {
                                                            "startDate": "$_effective_start",
                                                            "endDate": "$_month_end",
                                                            "unit": "day",
                                                        }
                                                    },
                                                ]
                                            },
                                            "as": "offset",
                                            "in": {
                                                "$dateAdd": {
                                                    "startDate": "$_effective_start",
                                                    "unit": "day",
                                                    "amount": "$$offset",
                                                }
                                            },
                                        }
                                    },
                                    "as": "day",
                                    "cond": {
                                        "$not": [
                                            {
                                                "$in": [
                                                    {
                                                        "$dayOfWeek": {
                                                            "date": "$$day",
                                                            "timezone": "Asia/Kolkata",
                                                        }
                                                    },
                                                    [1, 7],
                                                ]
                                            }
                                        ]
                                    },
                                }
                            }
                        },
                        0,
                    ]
                }
            }
        },
        {
            "$lookup": {
                "from": "attendance_logs",
                "let": {"employee_code": "$emp_code"},
                "pipeline": [
                    {
                        "$match": {
                            "$expr": {
                                "$and": [
                                    {"$eq": ["$emp_code", "$$employee_code"]},
                                    {"$gte": ["$date", start_str]},
                                    {"$lt": ["$date", end_str]},
                                ]
                            }
                        }
                    },
                    {
                        "$set": {
                            "_log_date": {
                                "$dateFromString": {
                                    "dateString": "$date",
                                    "timezone": "Asia/Kolkata",
                                }
                            }
                        }
                    },
                ],
                "as": "_logs",
            }
        },
        {
            "$set": {
                "_present_days": {
                    "$sum": {
                        "$map": {
                            "input": "$_logs",
                            "as": "log",
                            "in": {
                                "$cond": [
                                    {
                                        "$and": [
                                            {
                                                "$in": [
                                                    "$$log.status",
                                                    ["PRESENT", "WFH", "ON_DUTY"],
                                                ]
                                            },
                                            {
                                                "$not": [
                                                    {
                                                        "$in": [
                                                            {
                                                                "$dayOfWeek": {
                                                                    "date": "$$log._log_date",
                                                                    "timezone": "Asia/Kolkata",
                                                                }
                                                            },
                                                            [1, 7],
                                                        ]
                                                    }
                                                ]
                                            },
                                        ]
                                    },
                                    {
                                        "$cond": [
                                            {"$eq": ["$$log.half_day", True]},
                                            0.5,
                                            1,
                                        ]
                                    },
                                    0,
                                ]
                            },
                        }
                    }
                },
                "_leave_days": {
                    "$size": {
                        "$filter": {
                            "input": "$_logs",
                            "as": "log",
                            "cond": {"$eq": ["$$log.status", "LEAVE"]},
                        }
                    }
                },
                "_late_count": {
                    "$size": {
                        "$filter": {
                            "input": "$_logs",
                            "as": "log",
                            "cond": {"$gt": ["$$log.late_minutes", 0]},
                        }
                    }
                },
                "_total_late": {"$sum": "$_logs.late_minutes"},
                "_total_overtime": {"$sum": "$_logs.overtime_minutes"},
            }
        },
        {
            "$project": {
                "_id": 0,
                "emp_code": 1,
                "month": {"$literal": month},
                "working_days": "$_working_day_count",
                "present_days": "$_present_days",
                "leave_days": "$_leave_days",
                "late_count": "$_late_count",
                "total_late_minutes": {"$ifNull": ["$_total_late", 0]},
                "total_overtime_minutes": {"$ifNull": ["$_total_overtime", 0]},
                "attendance_pct": {
                    "$cond": [
                        {"$eq": ["$_working_day_count", 0]},
                        None,
                        {
                            "$divide": [
                                {
                                    "$floor": {
                                        "$add": [
                                            {
                                                "$multiply": [
                                                    {
                                                        "$divide": [
                                                            "$_present_days",
                                                            "$_working_day_count",
                                                        ]
                                                    },
                                                    1000000,
                                                ]
                                            },
                                            0.5,
                                        ]
                                    }
                                },
                                10000,
                            ]
                        },
                    ]
                },
            }
        },
    ]

    result = list(db.employees.aggregate(pipeline))
    if not result:
        raise HTTPException(status_code=404, detail="Employee not found")

    return result[0]


@app.get("/analytics/departments/summary")
def department_summary(
    month: str = Query(..., pattern=r"^\d{4}-\d{2}$"),
    department: Optional[str] = None,
):
    try:
        month_start = datetime.strptime(month, "%Y-%m").date()
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid month")

    if month_start.strftime("%Y-%m") != month:
        raise HTTPException(status_code=422, detail="Invalid month")

    if month_start.month == 12:
        next_month = month_start.replace(year=month_start.year + 1, month=1)
    else:
        next_month = month_start.replace(month=month_start.month + 1)

    start_str = month_start.isoformat()
    end_str = next_month.isoformat()

    pipeline = [
        {"$match": {"joined_on": {"$lt": end_str}}},
    ]

    if department is not None:
        pipeline.append({"$match": {"department": department}})

    pipeline.extend([
        {
            "$lookup": {
                "from": "attendance_logs",
                "let": {"code": "$emp_code"},
                "pipeline": [
                    {
                        "$match": {
                            "$expr": {
                                "$and": [
                                    {"$eq": ["$emp_code", "$$code"]},
                                    {"$gte": ["$date", start_str]},
                                    {"$lt": ["$date", end_str]},
                                ]
                            }
                        }
                    },
                    {
                        "$set": {
                            "_log_date": {
                                "$dateFromString": {
                                    "dateString": "$date",
                                    "timezone": "Asia/Kolkata",
                                }
                            }
                        }
                    },
                    {
                        "$set": {
                            "_is_present": {
                                "$in": [
                                    "$status",
                                    ["PRESENT", "WFH", "ON_DUTY"],
                                ]
                            },
                            "_is_weekday": {
                                "$not": [
                                    {
                                        "$in": [
                                            {
                                                "$dayOfWeek": {
                                                    "date": "$_log_date",
                                                    "timezone": "Asia/Kolkata",
                                                }
                                            },
                                            [1, 7],
                                        ]
                                    }
                                ]
                            },
                        }
                    },
                    {
                        "$group": {
                            "_id": None,
                            "present_days": {
                                "$sum": {
                                    "$cond": [
                                        {
                                            "$and": [
                                                "$_is_present",
                                                "$_is_weekday",
                                            ]
                                        },
                                        {
                                            "$cond": [
                                                {"$eq": ["$half_day", True]},
                                                0.5,
                                                1,
                                            ]
                                        },
                                        0,
                                    ]
                                }
                            },
                            "work_hours_sum": {
                                "$sum": {
                                    "$cond": [
                                        {
                                            "$and": [
                                                "$_is_present",
                                                {"$ne": ["$work_hours", None]},
                                            ]
                                        },
                                        "$work_hours",
                                        0,
                                    ]
                                }
                            },
                            "work_hours_count": {
                                "$sum": {
                                    "$cond": [
                                        {
                                            "$and": [
                                                "$_is_present",
                                                {"$ne": ["$work_hours", None]},
                                            ]
                                        },
                                        1,
                                        0,
                                    ]
                                }
                            },
                            "late_count": {
                                "$sum": {
                                    "$cond": [
                                        {"$gt": ["$late_minutes", 0]},
                                        1,
                                        0,
                                    ]
                                }
                            },
                            "total_late_minutes": {
                                "$sum": {"$ifNull": ["$late_minutes", 0]}
                            },
                            "leave_count": {
                                "$sum": {
                                    "$cond": [
                                        {"$eq": ["$status", "LEAVE"]},
                                        1,
                                        0,
                                    ]
                                }
                            },
                            "on_duty_count": {
                                "$sum": {
                                    "$cond": [
                                        {"$eq": ["$status", "ON_DUTY"]},
                                        1,
                                        0,
                                    ]
                                }
                            },
                        }
                    },
                ],
                "as": "_attendance",
            }
        },
        {
            "$set": {
                "_stats": {
                    "$ifNull": [
                        {"$arrayElemAt": ["$_attendance", 0]},
                        {
                            "present_days": 0,
                            "work_hours_sum": 0,
                            "work_hours_count": 0,
                            "late_count": 0,
                            "total_late_minutes": 0,
                            "leave_count": 0,
                            "on_duty_count": 0,
                        },
                    ]
                }
            }
        },
        {
            "$group": {
                "_id": "$department",
                "headcount": {"$sum": 1},
                "present_days": {"$sum": "$_stats.present_days"},
                "work_hours_sum": {"$sum": "$_stats.work_hours_sum"},
                "work_hours_count": {"$sum": "$_stats.work_hours_count"},
                "late_count": {"$sum": "$_stats.late_count"},
                "total_late_minutes": {"$sum": "$_stats.total_late_minutes"},
                "leave_count": {"$sum": "$_stats.leave_count"},
                "on_duty_count": {"$sum": "$_stats.on_duty_count"},
            }
        },
        {
            "$project": {
                "_id": 0,
                "department": "$_id",
                "headcount": 1,
                "present_days": 1,
                "avg_work_hours": {
                    "$cond": [
                        {"$eq": ["$work_hours_count", 0]},
                        None,
                        {
                            "$round": [
                                {
                                    "$divide": [
                                        "$work_hours_sum",
                                        "$work_hours_count",
                                    ]
                                },
                                2,
                            ]
                        },
                    ]
                },
                "late_count": 1,
                "total_late_minutes": 1,
                "leave_count": 1,
                "on_duty_count": 1,
            }
        },
        {"$sort": {"department": 1}},
    ])

    result = list(db.employees.aggregate(pipeline))
    return {"month": month, "items": result}


@app.get("/analytics/leaderboard/late")
def late_leaderboard(
    month: str = Query(..., pattern=r"^\d{4}-\d{2}$"),
    limit: int = Query(10, ge=1, le=50),
    department: Optional[str] = None,
):
    try:
        month_start = datetime.strptime(month, "%Y-%m").date()
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid month")

    if month_start.strftime("%Y-%m") != month:
        raise HTTPException(status_code=422, detail="Invalid month")

    if month_start.month == 12:
        next_month = month_start.replace(year=month_start.year + 1, month=1)
    else:
        next_month = month_start.replace(month=month_start.month + 1)

    start_str = month_start.isoformat()
    end_str = next_month.isoformat()

    pipeline = [
        {
            "$match": {
                "date": {"$gte": start_str, "$lt": end_str},
                "late_minutes": {"$gt": 0},
            }
        },
        {
            "$group": {
                "_id": "$emp_code",
                "total_late_minutes": {"$sum": "$late_minutes"},
                "late_count": {
                    "$sum": {"$cond": [{"$gt": ["$late_minutes", 0]}, 1, 0]}
                },
            }
        },
        {"$match": {"total_late_minutes": {"$gt": 0}}},
        {
            "$lookup": {
                "from": "employees",
                "localField": "_id",
                "foreignField": "emp_code",
                "as": "employee",
            }
        },
        {"$unwind": "$employee"},
    ]

    if department is not None:
        pipeline.append({"$match": {"employee.department": department}})

    pipeline.extend([
        {
            "$setWindowFields": {
                "sortBy": {"total_late_minutes": -1},
                "output": {
                    "rank": {"$rank": {}}
                },
            }
        },
        {"$match": {"rank": {"$lte": limit}}},
        {"$sort": {"total_late_minutes": -1, "_id": 1}},
        {
            "$project": {
                "_id": 0,
                "rank": 1,
                "emp_code": "$_id",
                "name": "$employee.name",
                "department": "$employee.department",
                "total_late_minutes": 1,
                "late_count": 1,
            }
        },
    ])

    items = list(db.attendance_logs.aggregate(pipeline))
    return {"month": month, "items": items}


@app.get("/admin/explain/{endpoint}")
def explain_endpoint(
    endpoint: str,
    emp_code: Optional[str] = None,
    month: Optional[str] = None,
    department: Optional[str] = None,
    limit: int = Query(10, ge=1, le=50),
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    status: Optional[str] = None,
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    allowed = {
        "attendance_list",
        "employee_monthly",
        "department_summary",
        "late_leaderboard",
        "department_trend",
    }
    if endpoint not in allowed:
        raise HTTPException(status_code=422, detail="Invalid endpoint")

    if endpoint == "attendance_list":
        query = {}
        if emp_code:
            query["emp_code"] = emp_code
        if date_from:
            query.setdefault("date", {})["$gte"] = date_from
        if date_to:
            query.setdefault("date", {})["$lte"] = date_to
        if status:
            query["status"] = status

        explain = db.command({
            "explain": {
                "find": "attendance_logs",
                "filter": query,
                "sort": {"date": -1},
                "skip": (page - 1) * page_size,
                "limit": page_size,
            },
            "verbosity": "executionStats",
        })
        collection = "attendance_logs"

    elif endpoint == "employee_monthly":
        if not emp_code or not month:
            raise HTTPException(
                status_code=422,
                detail="emp_code and month are required",
            )
        try:
            start = datetime.strptime(month, "%Y-%m").date()
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid month")
        if start.strftime("%Y-%m") != month:
            raise HTTPException(status_code=422, detail="Invalid month")
        end = (
            start.replace(year=start.year + 1, month=1)
            if start.month == 12
            else start.replace(month=start.month + 1)
        )
        query = {
            "emp_code": emp_code,
            "date": {"$gte": start.isoformat(), "$lt": end.isoformat()},
        }
        explain = db.command({
            "explain": {
                "find": "attendance_logs",
                "filter": query,
            },
            "verbosity": "executionStats",
        })
        collection = "attendance_logs"

    elif endpoint == "department_summary":
        if not month:
            raise HTTPException(status_code=422, detail="month is required")
        try:
            start = datetime.strptime(month, "%Y-%m").date()
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid month")
        if start.strftime("%Y-%m") != month:
            raise HTTPException(status_code=422, detail="Invalid month")
        end = (
            start.replace(year=start.year + 1, month=1)
            if start.month == 12
            else start.replace(month=start.month + 1)
        )
        pipeline = [
            {"$match": {"joined_on": {"$lt": end.isoformat()}}},
        ]
        if department is not None:
            pipeline.append({"$match": {"department": department}})
        pipeline.append({
            "$lookup": {
                "from": "attendance_logs",
                "localField": "emp_code",
                "foreignField": "emp_code",
                "as": "logs",
            }
        })
        explain = db.command({
            "explain": {
                "aggregate": "employees",
                "pipeline": pipeline,
                "cursor": {},
            },
            "verbosity": "executionStats",
        })
        collection = "employees"

    elif endpoint == "late_leaderboard":
        if not month:
            raise HTTPException(status_code=422, detail="month is required")
        try:
            start = datetime.strptime(month, "%Y-%m").date()
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid month")
        if start.strftime("%Y-%m") != month:
            raise HTTPException(status_code=422, detail="Invalid month")
        end = (
            start.replace(year=start.year + 1, month=1)
            if start.month == 12
            else start.replace(month=start.month + 1)
        )
        query = {
            "date": {"$gte": start.isoformat(), "$lt": end.isoformat()},
            "late_minutes": {"$gt": 0},
        }
        explain = db.command({
            "explain": {
                "find": "attendance_logs",
                "filter": query,
            },
            "verbosity": "executionStats",
        })
        collection = "attendance_logs"

    else:  # department_trend
        if not department or not from_date or not to_date:
            raise HTTPException(
                status_code=422,
                detail="department, from, and to are required",
            )
        try:
            datetime.strptime(from_date, "%Y-%m-%d")
            datetime.strptime(to_date, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid date")
        if from_date > to_date:
            raise HTTPException(status_code=422, detail="'from' must be <= 'to'")

        pipeline = [
            {"$match": {"date": {"$gte": from_date, "$lte": to_date}}},
            {
                "$lookup": {
                    "from": "employees",
                    "localField": "emp_code",
                    "foreignField": "emp_code",
                    "as": "employee",
                }
            },
            {"$unwind": "$employee"},
            {"$match": {"employee.department": department}},
        ]
        explain = db.command({
            "explain": {
                "aggregate": "attendance_logs",
                "pipeline": pipeline,
                "cursor": {},
            },
            "verbosity": "executionStats",
        })
        collection = "attendance_logs"

    return {
        "endpoint": endpoint,
        "collection": collection,
        "explain": explain,
    }



@app.get("/analytics/departments/{department}/trend")
def department_trend(
    department: str,
    from_date: str = Query(..., alias="from"),
    to_date: str = Query(..., alias="to"),
):
    try:
        start = datetime.strptime(from_date, "%Y-%m-%d").date()
        end = datetime.strptime(to_date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail="Dates must use YYYY-MM-DD",
        )

    if start.isoformat() != from_date or end.isoformat() != to_date:
        raise HTTPException(status_code=422, detail="Invalid date")

    if end < start or (end - start).days + 1 > 92:
        raise HTTPException(status_code=422, detail="Invalid date range")

    if db.employees.count_documents({"department": department}) == 0:
        raise HTTPException(status_code=404, detail="Department not found")

    start_dt = datetime.combine(start, datetime.min.time())
    end_exclusive = datetime.combine(
        end + timedelta(days=1), datetime.min.time()
    )

    pipeline = [
        {
            "$match": {
                "date": {
                    "$gte": from_date,
                    "$lte": to_date,
                }
            }
        },
        {
            "$lookup": {
                "from": "employees",
                "localField": "emp_code",
                "foreignField": "emp_code",
                "as": "employee",
            }
        },
        {"$unwind": "$employee"},
        {"$match": {"employee.department": department}},
        {
            "$group": {
                "_id": "$date",
                "present_count": {
                    "$sum": {
                        "$cond": [
                            {
                                "$in": [
                                    "$status",
                                    ["PRESENT", "WFH", "ON_DUTY"],
                                ]
                            },
                            {
                                "$cond": [
                                    {"$eq": ["$half_day", True]},
                                    0.5,
                                    1,
                                ]
                            },
                            0,
                        ]
                    }
                },
                "late_count": {
                    "$sum": {
                        "$cond": [
                            {"$gt": ["$late_minutes", 0]},
                            1,
                            0,
                        ]
                    }
                },
            }
        },
        {
            "$project": {
                "_id": 0,
                "date": {
                    "$dateFromString": {"dateString": "$_id"}
                },
                "present_count": 1,
                "late_count": 1,
            }
        },
        {
            "$densify": {
                "field": "date",
                "range": {
                    "step": 1,
                    "unit": "day",
                    "bounds": [start_dt, end_exclusive],
                },
            }
        },
        {
            "$match": {
                "date": {"$gte": start_dt, "$lt": end_exclusive}
            }
        },
        {
            "$set": {
                "date": {
                    "$dateToString": {
                        "format": "%Y-%m-%d",
                        "date": "$date",
                        "timezone": "UTC",
                    }
                },
                "present_count": {"$ifNull": ["$present_count", 0]},
                "late_count": {"$ifNull": ["$late_count", 0]},
            }
        },
        {
            "$lookup": {
                "from": "employees",
                "pipeline": [
                    {"$match": {"department": department}},
                    {"$project": {"_id": 0, "joined_on": 1}},
                ],
                "as": "department_employees",
            }
        },
        {
            "$set": {
                "is_working_day": {
                    "$not": [
                        {
                            "$in": [
                                {
                                    "$dayOfWeek": {
                                        "$dateFromString": {
                                            "dateString": "$date"
                                        }
                                    }
                                },
                                [1, 7],
                            ]
                        }
                    ]
                },
                "headcount": {
                    "$size": {
                        "$filter": {
                            "input": "$department_employees",
                            "as": "emp",
                            "cond": {
                                "$lte": [
                                    "$$emp.joined_on",
                                    "$date",
                                ]
                            },
                        }
                    }
                },
            }
        },
        {
            "$set": {
                "attendance_rate": {
                    "$cond": [
                        {
                            "$and": [
                                "$is_working_day",
                                {"$gt": ["$headcount", 0]},
                            ]
                        },
                        {
                            "$round": [
                                {
                                    "$divide": [
                                        "$present_count",
                                        "$headcount",
                                    ]
                                },
                                4,
                            ]
                        },
                        None,
                    ]
                }
            }
        },
        {
            "$setWindowFields": {
                "sortBy": {"date": 1},
                "output": {
                    "moving_avg_7d": {
                        "$avg": "$attendance_rate",
                        "window": {"documents": [-6, 0]},
                    }
                },
            }
        },
        {
            "$set": {
                "moving_avg_7d": {
                    "$cond": [
                        {"$ne": ["$moving_avg_7d", None]},
                        {"$round": ["$moving_avg_7d", 4]},
                        None,
                    ]
                }
            }
        },
        {"$unset": "department_employees"},
        {"$sort": {"date": 1}},
    ]

    items = list(db.attendance_logs.aggregate(pipeline))

    return {
        "department": department,
        "from": from_date,
        "to": to_date,
        "items": items,
    }


@app.get("/employees/{emp_code}")
def get_employee(emp_code: str):
    employee = db.employees.find_one(
        {"emp_code": emp_code},
        {"_id": 0},
    )

    if employee is None:
        raise HTTPException(
            status_code=404,
            detail="Employee not found",
        )

    return employee


@app.get("/attendance/{emp_code}/history")
def attendance_history(
    emp_code: str,
    limit: int = Query(30, ge=1, le=100),
    skip: int = Query(0, ge=0),
):
    employee = db.employees.find_one(
        {"emp_code": emp_code},
        {"_id": 0, "emp_code": 1, "name": 1},
    )

    if employee is None:
        raise HTTPException(
            status_code=404,
            detail="Employee not found",
        )

    cursor = (
        db.attendance_logs.find(
            {"emp_code": emp_code},
            {"_id": 0},
        )
        .sort("date", -1)
        .skip(skip)
        .limit(limit)
    )

    records = list(cursor)

    return {
        "employee": employee,
        "count": len(records),
        "limit": limit,
        "skip": skip,
        "items": records,
    }


@app.get("/analytics/attendance/overview")
def attendance_overview(
    date: str = Query(..., description="Date in YYYY-MM-DD format"),
):
    try:
        parsed_date = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail="Date must use YYYY-MM-DD",
        )

    if parsed_date.isoformat() != date:
        raise HTTPException(status_code=422, detail="Invalid date")

    pipeline = [
        {"$match": {"date": date}},
        {
            "$group": {
                "_id": None,
                "total_records": {"$sum": 1},
                "present": {
                    "$sum": {
                        "$cond": [
                            {"$in": ["$status", ["PRESENT", "WFH", "ON_DUTY"]]},
                            1,
                            0,
                        ]
                    }
                },
                "absent": {
                    "$sum": {
                        "$cond": [{"$eq": ["$status", "ABSENT"]}, 1, 0]
                    }
                },
                "on_leave": {
                    "$sum": {
                        "$cond": [{"$eq": ["$status", "LEAVE"]}, 1, 0]
                    }
                },
                "late": {
                    "$sum": {
                        "$cond": [{"$gt": ["$late_minutes", 0]}, 1, 0]
                    }
                },
            }
        },
        {"$project": {"_id": 0}},
    ]

    results = list(db.attendance_logs.aggregate(pipeline))

    if not results:
        return {
            "date": date,
            "total_records": 0,
            "present": 0,
            "absent": 0,
            "on_leave": 0,
            "late": 0,
        }

    return {"date": date, **results[0]}


@app.get("/analytics/attendance/today")
def today_attendance():
    today = datetime.now().strftime("%Y-%m-%d")

    pipeline = [
        {"$match": {"date": today}},
        {
            "$group": {
                "_id": None,
                "total_records": {"$sum": 1},
                "present": {
                    "$sum": {
                        "$cond": [
                            {
                                "$in": [
                                    "$status",
                                    ["PRESENT", "WFH", "ON_DUTY"],
                                ]
                            },
                            1,
                            0,
                        ]
                    }
                },
                "absent": {
                    "$sum": {
                        "$cond": [
                            {"$eq": ["$status", "ABSENT"]},
                            1,
                            0,
                        ]
                    }
                },
                "late": {
                    "$sum": {
                        "$cond": [
                            {"$gt": ["$late_minutes", 0]},
                            1,
                            0,
                        ]
                    }
                },
            }
        },
        {"$project": {"_id": 0}},
    ]

    results = list(db.attendance_logs.aggregate(pipeline))

    if not results:
        return {
            "date": today,
            "total_records": 0,
            "present": 0,
            "absent": 0,
            "late": 0,
        }

    return {"date": today, **results[0]}


@app.get("/employees/{emp_code}/attendance-stats")
def employee_attendance_stats(
    emp_code: str,
    month: str = Query(..., pattern=r"^\d{4}-\d{2}$"),
):
    try:
        start = datetime.strptime(month, "%Y-%m").date()
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail="Month must use YYYY-MM format",
        )

    if start.strftime("%Y-%m") != month:
        raise HTTPException(status_code=422, detail="Invalid month")

    employee = db.employees.find_one(
        {"emp_code": emp_code},
        {"_id": 0, "emp_code": 1, "name": 1, "department": 1},
    )

    if employee is None:
        raise HTTPException(status_code=404, detail="Employee not found")

    start_date = start.strftime("%Y-%m-01")
    if start.month == 12:
        next_month = start.replace(year=start.year + 1, month=1)
    else:
        next_month = start.replace(month=start.month + 1)
    end_date = next_month.strftime("%Y-%m-%d")

    pipeline = [
        {
            "$match": {
                "emp_code": emp_code,
                "date": {"$gte": start_date, "$lt": end_date},
            }
        },
        {
            "$group": {
                "_id": None,
                "total_records": {"$sum": 1},
                "present_days": {
                    "$sum": {
                        "$cond": [
                            {"$in": ["$status", ["PRESENT", "WFH", "ON_DUTY"]]},
                            {"$cond": [{"$eq": ["$half_day", True]}, 0.5, 1]},
                            0,
                        ]
                    }
                },
                "absent_days": {
                    "$sum": {
                        "$cond": [{"$eq": ["$status", "ABSENT"]}, 1, 0]
                    }
                },
                "leave_days": {
                    "$sum": {
                        "$cond": [{"$eq": ["$status", "LEAVE"]}, 1, 0]
                    }
                },
                "late_arrivals": {
                    "$sum": {
                        "$cond": [{"$gt": ["$late_minutes", 0]}, 1, 0]
                    }
                },
                "total_late_minutes": {"$sum": "$late_minutes"},
                "total_work_hours": {"$sum": "$work_hours"},
            }
        },
        {"$project": {"_id": 0}},
    ]

    results = list(db.attendance_logs.aggregate(pipeline))

    stats = results[0] if results else {
        "total_records": 0,
        "present_days": 0,
        "absent_days": 0,
        "leave_days": 0,
        "late_arrivals": 0,
        "total_late_minutes": 0,
        "total_work_hours": 0,
    }

    stats["total_work_hours"] = round(stats["total_work_hours"], 2)

    return {
        "employee": employee,
        "month": month,
        "stats": stats,
    }


@app.get("/employees/by-department/{department}")
def employees_by_department(
    department: str,
    limit: int = Query(20, ge=1, le=100),
    skip: int = Query(0, ge=0),
):
    query = {"department": department}

    total = db.employees.count_documents(query)

    employees = list(
        db.employees.find(query, {"_id": 0})
        .sort("emp_code", 1)
        .skip(skip)
        .limit(limit)
    )

    return {
        "department": department,
        "total": total,
        "limit": limit,
        "skip": skip,
        "items": employees,
    }


# --------------------------------------------------------------------------- #
# TODO - the rest of the contract (see openapi.yaml):
#   POST  /attendance/punch-out
#   PATCH /attendance/{emp_code}/{date}
#   GET   /analytics/employees/{emp_code}/monthly
#   GET   /analytics/departments/summary
#   GET   /analytics/leaderboard/late
#   GET   /analytics/departments/{department}/trend
#   GET   /admin/explain/{endpoint}
# --------------------------------------------------------------------------- #
