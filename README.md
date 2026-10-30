# ML Pipeline — Household Power Consumption (Time Series)

Group 8 formative: building a pipeline for time-series data on the
[Individual Household Electric Power Consumption](https://archive.ics.uci.edu/dataset/235/individual+household+electric+power+consumption)
dataset (one household, one reading per minute, Dec 2006 – Nov 2010).

| Part | Where |
|---|---|
| Exploratory analysis, analytical questions | [`dataset.ipynb`](dataset.ipynb) |
| Databases (MySQL + MongoDB) | [`database/`](database/) — design, ERD, queries and results in [`database/README.md`](database/README.md) |

## Running the databases

Both databases run in Docker containers. MySQL loads the full dataset by itself on first start; MongoDB is loaded with a Python script.

### 1. Requirements

- [Docker](https://docs.docker.com/get-docker/) with Docker Compose
- [uv](https://docs.astral.sh/uv/) (Python package manager used by this project)
- The dataset file `household_power_consumption.txt` in the repository root. It is not in Git (127 MB, over GitHub's 100 MB limit). Download it from [Kaggle](https://www.kaggle.com/datasets/uciml/electric-power-consumption-data-set) or [UCI](https://archive.ics.uci.edu/dataset/235/individual+household+electric+power+consumption), unzip it, and place the `.txt` file next to `docker-compose.yml`.

Install the Python dependencies once:

```bash
uv sync
```

### 2. Start MySQL and MongoDB

```bash
docker compose up -d
```

This starts two containers:

| Service | Container | Port | User / password | Database |
|---|---|---|---|---|
| MySQL 8.4 | `power_mysql` | 3306 | `power` / `powerpass` (root: `rootpass`) | `household_power` |
| MongoDB 8.0 | `power_mongo` | 27017 | `root` / `rootpass` (auth database `admin`) | `household_power` |

On the first start, MySQL creates the tables (`database/mysql/01_schema.sql`) and loads all 2,075,259 rows (`database/mysql/02_load_data.sql`). This takes about 2 minutes. Wait until both containers show `healthy`:

```bash
docker compose ps
```

To watch the MySQL load: `docker compose logs -f mysql`.

### 3. Load MongoDB

```bash
uv run database/mongodb/load_mongo.py
```

This takes about 1 minute. It creates the `households`, `readings` and `daily_summaries` collections and can be re-run safely (it drops and recreates them).

### 4. Run the queries

```bash
./database/run_queries.sh
```

This runs the 5 MySQL queries and 5 MongoDB queries inside the containers and saves the output to `database/results/`.

### 5. Open a database shell

```bash
# MySQL
docker compose exec mysql mysql -upower -ppowerpass household_power

# MongoDB
docker compose exec mongo mongosh -u root -p rootpass --authenticationDatabase admin household_power
```

GUI tools can connect with:

- MySQL (e.g. DBeaver, MySQL Workbench): host `localhost`, port `3306`, user `power`, password `powerpass`
- MongoDB (e.g. Compass): `mongodb://root:rootpass@localhost:27017/?authSource=admin`

### 6. Stop or reset

```bash
docker compose down        # stop the containers, keep the data
docker compose down -v     # stop and DELETE all data; the next `up` reloads MySQL from scratch
```


