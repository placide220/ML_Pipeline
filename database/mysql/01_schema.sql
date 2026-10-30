-- Task 2 — Relational schema (MySQL 8.4)
-- Dataset: UCI "Individual Household Electric Power Consumption"
--          (1-minute readings, 16/12/2006 – 26/11/2010, 2,075,259 rows)
--
-- Tables
--   households          one row per monitored household (dimension)
--   sub_meters          the three sub-metered circuits of a household (dimension)
--   power_readings      one row per household per minute — whole-house measurements (fact)
--   sub_meter_readings  energy per sub-meter per minute (fact, child of power_readings)
--   daily_consumption   per-day aggregates used for forecasting / reporting (summary)


CREATE DATABASE IF NOT EXISTS household_power;
USE household_power;

SET NAMES utf8mb4;

DROP TABLE IF EXISTS daily_consumption;
DROP TABLE IF EXISTS sub_meter_readings;
DROP TABLE IF EXISTS power_readings;
DROP TABLE IF EXISTS sub_meters;
DROP TABLE IF EXISTS households;


CREATE TABLE households (
    household_id    INT UNSIGNED  NOT NULL AUTO_INCREMENT,
    household_code  VARCHAR(20)   NOT NULL,
    location        VARCHAR(100)  NOT NULL,
    country         CHAR(2)       NOT NULL,
    data_source     VARCHAR(255)  NOT NULL,
    sampling_rate   VARCHAR(20)   NOT NULL DEFAULT '1 minute',
    created_at      TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (household_id),
    UNIQUE KEY uq_households_code (household_code)
) ENGINE = InnoDB;


-- sub_meters: the circuits that are metered separately inside a household.
-- Sub_metering_1/2/3 in the raw file become rows here instead of columns,
-- so adding a fourth circuit is an INSERT, not an ALTER TABLE.

CREATE TABLE sub_meters (
    sub_meter_id    TINYINT UNSIGNED NOT NULL,
    household_id    INT UNSIGNED     NOT NULL,
    meter_code      VARCHAR(30)      NOT NULL,   -- column name in the raw file
    area            VARCHAR(50)      NOT NULL,
    appliances      VARCHAR(255)     NOT NULL,
    unit            VARCHAR(10)      NOT NULL DEFAULT 'Wh',
    PRIMARY KEY (sub_meter_id),
    UNIQUE KEY uq_sub_meters_household_code (household_id, meter_code),
    CONSTRAINT fk_sub_meters_household
        FOREIGN KEY (household_id) REFERENCES households (household_id)
        ON DELETE CASCADE
) ENGINE = InnoDB;


-- power_readings: the time series itself, one row per minute.
-- Missing minutes ('?' in the raw file) are kept as rows with NULL measurements
-- so the regular 1-minute grid is preserved; is_missing flags them.
-- Imputation is left to the ML pipeline (Task 1) — the database stores the
-- source data as recorded.

CREATE TABLE power_readings (
    reading_id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    household_id                INT UNSIGNED    NOT NULL,
    reading_ts                  DATETIME        NOT NULL,
    global_active_power_kw      DECIMAL(6,3)    NULL,     -- prediction target
    global_reactive_power_kvar  DECIMAL(6,3)    NULL,
    voltage_v                   DECIMAL(6,3)    NULL,
    global_intensity_a          DECIMAL(6,3)    NULL,
    is_missing                  BOOLEAN AS (global_active_power_kw IS NULL) STORED,
    PRIMARY KEY (reading_id),
    UNIQUE KEY uq_power_readings_household_ts (household_id, reading_ts),
    CONSTRAINT fk_power_readings_household
        FOREIGN KEY (household_id) REFERENCES households (household_id)
        ON DELETE CASCADE,
    CONSTRAINT chk_power_nonnegative CHECK (global_active_power_kw >= 0 AND global_reactive_power_kvar >= 0),
    CONSTRAINT chk_voltage_range     CHECK (voltage_v BETWEEN 150 AND 300)
) ENGINE = InnoDB;


-- sub_meter_readings: energy recorded by each sub-meter during a minute.
-- Composite PK (reading_id, sub_meter_id) = one value per circuit per minute.
-- Missing minutes have no rows here.

CREATE TABLE sub_meter_readings (
    reading_id      BIGINT UNSIGNED  NOT NULL,
    sub_meter_id    TINYINT UNSIGNED NOT NULL,
    energy_wh       DECIMAL(6,3)     NOT NULL,
    PRIMARY KEY (reading_id, sub_meter_id),
    KEY idx_sub_meter_readings_meter (sub_meter_id),
    CONSTRAINT fk_smr_reading
        FOREIGN KEY (reading_id) REFERENCES power_readings (reading_id)
        ON DELETE CASCADE,
    CONSTRAINT fk_smr_sub_meter
        FOREIGN KEY (sub_meter_id) REFERENCES sub_meters (sub_meter_id),
    CONSTRAINT chk_energy_nonnegative CHECK (energy_wh >= 0)
) ENGINE = InnoDB;


-- daily_consumption: one row per household per day, pre-aggregated from the
-- minute data. Daily totals are the natural input for day-ahead forecasting,
-- lag features and moving averages, and querying 1,442 rows is far cheaper
-- than re-aggregating 2 million minutes every time.
-- Energy: a 1-minute reading of P kW = P/60 kWh.
-- Unmetered = whole-house energy not captured by the three sub-meters.

CREATE TABLE daily_consumption (
    household_id             INT UNSIGNED      NOT NULL,
    reading_date             DATE              NOT NULL,
    observed_minutes         SMALLINT UNSIGNED NOT NULL,
    missing_minutes          SMALLINT UNSIGNED NOT NULL,
    avg_active_power_kw      DECIMAL(7,4)      NULL,
    peak_active_power_kw     DECIMAL(6,3)      NULL,
    min_voltage_v            DECIMAL(6,3)      NULL,
    max_voltage_v            DECIMAL(6,3)      NULL,
    total_active_energy_kwh  DECIMAL(9,4)      NULL,
    kitchen_wh               DECIMAL(10,3)     NULL,
    laundry_wh               DECIMAL(10,3)     NULL,
    water_heater_ac_wh       DECIMAL(10,3)     NULL,
    unmetered_wh             DECIMAL(10,3)     NULL,
    PRIMARY KEY (household_id, reading_date),
    CONSTRAINT fk_daily_consumption_household
        FOREIGN KEY (household_id) REFERENCES households (household_id)
        ON DELETE CASCADE
) ENGINE = InnoDB;


INSERT INTO households (household_id, household_code, location, country, data_source)
VALUES (1, 'SCEAUX-01', 'Sceaux (7 km from Paris)', 'FR',
        'UCI ML Repository / Kaggle — Individual household electric power consumption');

INSERT INTO sub_meters (sub_meter_id, household_id, meter_code, area, appliances) VALUES
    (1, 1, 'Sub_metering_1', 'Kitchen',       'Dishwasher, oven, microwave (hot plates are gas)'),
    (2, 1, 'Sub_metering_2', 'Laundry room',  'Washing machine, tumble-drier, refrigerator, light'),
    (3, 1, 'Sub_metering_3', 'Water heater & AC', 'Electric water-heater and air-conditioner');

