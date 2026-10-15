# HROne Attendance Management API

A FastAPI application for employee management, attendance tracking, attendance regularization, and workforce analytics using MongoDB.

## Features

- Employee lookup and listing
- Attendance punch-in and punch-out
- Attendance regularization with audit history
- Employee attendance history
- Monthly employee analytics
- Department attendance summaries and trends
- Late-arrival leaderboard
- Attendance overview
- Query execution plan inspection

## Prerequisites

- Python 3.10 or newer
- MongoDB 6.0 or newer
- Git

## Setup

Create and activate a virtual environment.

**Windows PowerShell:**
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Configure the environment variables `MONGO_URI` and `MONGO_DB` for your MongoDB instance. Do not commit credentials or `.env` files.

Seed the sample data if the provided sample fixtures are available:

```bash
python sample_seed.py
```

## Run the application

```bash
uvicorn app.main:app --port 8000
```

Open the interactive API documentation at:

http://127.0.0.1:8000/docs

## Configuration

- `MONGO_URI`: MongoDB connection URI.
- `MONGO_DB`: Database name.

The application creates indexes at startup to support common queries and enforce employee and daily attendance uniqueness.

## Limitations and validation

The application should be tested against the complete assignment contract, including concurrent attendance requests, invalid inputs, large datasets, aggregation accuracy, and execution-plan requirements. Sample data is not sufficient to validate every edge case.

MongoDB must be available and correctly configured before the application starts. Review the API contract and `DECISIONS.md` for business rules and implementation choices.
