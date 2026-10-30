## Task 3 - API (FastAPI)

```bash
docker compose up -d                       # MySQL + MongoDB (Task 2)
python -m venv .venv && source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements-api.txt
cp .env.example .env                       # set passwords to match docker-compose.yml
uvicorn api.main:app --reload --port 8000  # Swagger UI: http://localhost:8000/docs
python scripts/smoke_test_api.py           # runs every endpoint on both databases
```

| Method | MySQL | MongoDB | Purpose |
|---|---|---|---|
| POST | `/sql/readings` | `/mongo/readings` | Create a reading |
| GET | `/sql/readings/{ts}` | `/mongo/readings/{ts}` | Read one reading |
| PUT | `/sql/readings/{ts}` | `/mongo/readings/{ts}` | Update a reading |
| DELETE | `/sql/readings/{ts}` | `/mongo/readings/{ts}` | Delete a reading |
| GET | `/sql/readings/latest` | `/mongo/readings/latest` | Latest record |
| GET | `/sql/readings/range?start=&end=&resolution=minute\|hour` | `/mongo/readings/range?...` | Records by date range |

## Task 4 - Forecast script

```bash
python scripts/predict.py --source sql --steps 3
python scripts/predict.py --source mongo --model models/best_model.joblib
```
Fetches the last 31 days from the API -> hourly resample + gap filling (as in Task 1) -> builds lag/rolling/calendar
features -> loads `models/best_model.joblib` -> prints the next-hour forecast(s) in kW.
