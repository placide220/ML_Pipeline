-- Task 2 — Load the raw file into the relational schema (runs on first start).
--
-- 1. LOAD DATA the semicolon-separated file into a staging table, converting
--    'dd/mm/yyyy' + 'hh:mm:ss' into a DATETIME and '?' (missing) into NULL.
-- 2. Split the staging rows into power_readings and sub_meter_readings.
-- 3. Aggregate the minutes into daily_consumption.
-- 4. Drop the staging table.

USE household_power;

SET SESSION unique_checks = 0;
SET SESSION foreign_key_checks = 0;

CREATE TABLE stg_raw (
    id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    reading_ts  DATETIME     NOT NULL,
    gap         DECIMAL(6,3) NULL,
    grp         DECIMAL(6,3) NULL,
    voltage     DECIMAL(6,3) NULL,
    intensity   DECIMAL(6,3) NULL,
    sm1         DECIMAL(6,3) NULL,
    sm2         DECIMAL(6,3) NULL,
    sm3         DECIMAL(6,3) NULL
) ENGINE = InnoDB;

-- The file is in chronological order, so the auto-increment id follows time.
LOAD DATA INFILE '/data/household_power_consumption.txt'
INTO TABLE stg_raw
FIELDS TERMINATED BY ';'
LINES TERMINATED BY '\r\n'
IGNORE 1 LINES
(@d, @t, @gap, @grp, @v, @gi, @sm1, @sm2, @sm3)
SET reading_ts = STR_TO_DATE(CONCAT(@d, ' ', @t), '%d/%m/%Y %H:%i:%s'),
    gap        = NULLIF(@gap, '?'),
    grp        = NULLIF(@grp, '?'),
    voltage    = NULLIF(@v,   '?'),
    intensity  = NULLIF(@gi,  '?'),
    sm1        = NULLIF(@sm1, '?'),
    sm2        = NULLIF(@sm2, '?'),
    sm3        = NULLIF(NULLIF(@sm3, ''), '?');   -- missing rows end with an empty field

-- Whole-house readings: reading_id reuses the staging id so the sub-meter
-- rows below can be inserted without a join.
INSERT INTO power_readings
    (reading_id, household_id, reading_ts,
     global_active_power_kw, global_reactive_power_kvar, voltage_v, global_intensity_a)
SELECT id, 1, reading_ts, gap, grp, voltage, intensity
FROM stg_raw
ORDER BY id;

-- Sub-meter readings: unpivot the three columns into rows.
INSERT INTO sub_meter_readings (reading_id, sub_meter_id, energy_wh)
SELECT id, 1, sm1 FROM stg_raw WHERE sm1 IS NOT NULL
UNION ALL
SELECT id, 2, sm2 FROM stg_raw WHERE sm2 IS NOT NULL
UNION ALL
SELECT id, 3, sm3 FROM stg_raw WHERE sm3 IS NOT NULL;

-- Daily aggregates (AVG/MAX/MIN/SUM ignore NULLs, i.e. missing minutes).
INSERT INTO daily_consumption
    (household_id, reading_date, observed_minutes, missing_minutes,
     avg_active_power_kw, peak_active_power_kw, min_voltage_v, max_voltage_v,
     total_active_energy_kwh, kitchen_wh, laundry_wh, water_heater_ac_wh, unmetered_wh)
SELECT 1,
       DATE(reading_ts),
       COUNT(gap),
       SUM(gap IS NULL),
       AVG(gap),
       MAX(gap),
       MIN(voltage),
       MAX(voltage),
       SUM(gap) / 60,
       SUM(sm1),
       SUM(sm2),
       SUM(sm3),
       SUM(gap * 1000 / 60 - sm1 - sm2 - sm3)
FROM stg_raw
GROUP BY DATE(reading_ts)
ORDER BY DATE(reading_ts);

DROP TABLE stg_raw;

SET SESSION unique_checks = 1;
SET SESSION foreign_key_checks = 1;

ANALYZE TABLE households, sub_meters, power_readings, sub_meter_readings, daily_consumption;
