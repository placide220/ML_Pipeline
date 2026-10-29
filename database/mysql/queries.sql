
-- Task 2 — MySQL queries on the household_power database
-- Run: ./database/run_queries.sh   (results -> database/results/mysql_query_results.txt)

-- Q1. Yearly overview: energy use, peak minute and data completeness per year.
--     (JOIN households + daily_consumption, GROUP BY)

SELECT h.household_code,
       YEAR(d.reading_date)                                        AS year,
       COUNT(*)                                                    AS days,
       ROUND(SUM(d.total_active_energy_kwh), 1)                    AS total_energy_kwh,
       ROUND(AVG(d.total_active_energy_kwh), 2)                    AS avg_daily_kwh,
       MAX(d.peak_active_power_kw)                                 AS peak_minute_kw,
       SUM(d.missing_minutes)                                      AS missing_minutes,
       ROUND(100 * SUM(d.missing_minutes)
             / SUM(d.observed_minutes + d.missing_minutes), 2)     AS missing_pct
FROM daily_consumption d
JOIN households h ON h.household_id = d.household_id
GROUP BY h.household_code, YEAR(d.reading_date)
ORDER BY year;


-- Q2. Lag features and 7-day moving average of daily energy (window functions).
--     Lags/averages are computed over the whole series first, then three weeks
--     around Christmas 2009 are shown, so the first rows have full history.

WITH daily AS (
    SELECT reading_date,
           total_active_energy_kwh                                          AS energy_kwh,
           LAG(total_active_energy_kwh, 1) OVER w                           AS lag_1_kwh,
           LAG(total_active_energy_kwh, 7) OVER w                           AS lag_7_kwh,
           AVG(total_active_energy_kwh) OVER (w ROWS BETWEEN 6 PRECEDING AND CURRENT ROW) AS ma_7_kwh
    FROM daily_consumption
    WHERE household_id = 1
    WINDOW w AS (ORDER BY reading_date)
)
SELECT reading_date,
       DAYNAME(reading_date)                                   AS weekday,
       ROUND(energy_kwh, 2)                                    AS energy_kwh,
       ROUND(lag_1_kwh, 2)                                     AS lag_1_kwh,
       ROUND(lag_7_kwh, 2)                                     AS lag_7_kwh,
       ROUND(ma_7_kwh, 2)                                      AS ma_7_kwh,
       ROUND(100 * (energy_kwh - ma_7_kwh) / ma_7_kwh, 1)      AS pct_vs_ma_7
FROM daily
WHERE reading_date BETWEEN '2009-12-14' AND '2010-01-03'
ORDER BY reading_date;


-- Q3. Where does the energy go at each hour of the day?
--     Average Wh per minute for each sub-metered area, plus the unmetered rest.
--     (3-table JOIN power_readings -> sub_meter_readings -> sub_meters,
--      conditional aggregation pivots the sub-meter rows into columns)

WITH per_minute AS (
    SELECT p.reading_ts,
           p.global_active_power_kw,
           SUM(CASE WHEN m.area = 'Kitchen'           THEN s.energy_wh END) AS kitchen_wh,
           SUM(CASE WHEN m.area = 'Laundry room'      THEN s.energy_wh END) AS laundry_wh,
           SUM(CASE WHEN m.area = 'Water heater & AC' THEN s.energy_wh END) AS heater_ac_wh
    FROM power_readings p
    JOIN sub_meter_readings s ON s.reading_id = p.reading_id
    JOIN sub_meters m         ON m.sub_meter_id = s.sub_meter_id
    WHERE p.household_id = 1
    GROUP BY p.reading_id
)
SELECT HOUR(reading_ts)                                   AS hour_of_day,
       ROUND(AVG(global_active_power_kw), 3)              AS avg_power_kw,
       ROUND(AVG(kitchen_wh), 2)                          AS kitchen_wh_per_min,
       ROUND(AVG(laundry_wh), 2)                          AS laundry_wh_per_min,
       ROUND(AVG(heater_ac_wh), 2)                        AS heater_ac_wh_per_min,
       ROUND(AVG(global_active_power_kw * 1000 / 60
                 - kitchen_wh - laundry_wh - heater_ac_wh), 2) AS unmetered_wh_per_min
FROM per_minute
GROUP BY HOUR(reading_ts)
ORDER BY hour_of_day;

-- Q4. Data quality: the five longest outages (consecutive missing minutes).
--     Gaps-and-islands: within a run of consecutive missing minutes,
--     (minute number - row number) is constant, so it identifies the run.

WITH missing AS (
    SELECT reading_ts,
           TIMESTAMPDIFF(MINUTE, '2006-12-16 00:00:00', reading_ts)
             - ROW_NUMBER() OVER (ORDER BY reading_ts) AS island
    FROM power_readings
    WHERE household_id = 1 AND is_missing
)
SELECT MIN(reading_ts)                 AS outage_start,
       MAX(reading_ts)                 AS outage_end,
       COUNT(*)                        AS missing_minutes,
       ROUND(COUNT(*) / 60, 1)         AS missing_hours
FROM missing
GROUP BY island
ORDER BY missing_minutes DESC
LIMIT 5;

-- Q5. Peak-demand events: the five highest-power minutes with their sub-meter breakdown.
--     (derived table + JOIN + pivot)

SELECT p.reading_ts,
       p.global_active_power_kw                                          AS active_power_kw,
       p.voltage_v,
       p.global_intensity_a                                              AS intensity_a,
       MAX(CASE WHEN s.sub_meter_id = 1 THEN s.energy_wh END)            AS kitchen_wh,
       MAX(CASE WHEN s.sub_meter_id = 2 THEN s.energy_wh END)            AS laundry_wh,
       MAX(CASE WHEN s.sub_meter_id = 3 THEN s.energy_wh END)            AS heater_ac_wh,
       ROUND(p.global_active_power_kw * 1000 / 60 - SUM(s.energy_wh), 2) AS unmetered_wh
FROM (SELECT * FROM power_readings
      WHERE household_id = 1 AND NOT is_missing
      ORDER BY global_active_power_kw DESC
      LIMIT 5) p
JOIN sub_meter_readings s ON s.reading_id = p.reading_id
GROUP BY p.reading_id, p.reading_ts, p.global_active_power_kw, p.voltage_v, p.global_intensity_a
ORDER BY active_power_kw DESC;
