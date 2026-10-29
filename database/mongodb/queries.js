
db = db.getSiblingDB("household_power");

// Print an array of flat objects as a text table, columns in the given order.
function table(title, cols, rows) {
  print("\n" + "=".repeat(100) + "\n" + title + "\n" + "=".repeat(100));
  if (rows.length === 0) { print("(no rows)"); return; }
  const fmt = (v) => v instanceof Date ? v.toISOString().replace("T", " ").replace(".000Z", "")
                                       : v === null || v === undefined ? "NULL" : String(v);
  const widths = cols.map((c) => Math.max(c.length, ...rows.map((r) => fmt(r[c]).length)));
  const line = "+" + widths.map((w) => "-".repeat(w + 2)).join("+") + "+";
  const row = (vals) => "| " + vals.map((v, i) => v.padEnd(widths[i])).join(" | ") + " |";
  print(line); print(row(cols)); print(line);
  rows.forEach((r) => print(row(cols.map((c) => fmt(r[c])))));
  print(line);
  print(rows.length + " row(s)");
}


table(
  "M1. Minute readings, 2008-12-24 18:00 to 18:10 (find + projection + sort)",
  ["ts", "global_active_power_kw", "voltage_v", "kitchen_wh", "laundry_wh", "heater_ac_wh"],
  db.readings.find(
    { "meta.household_id": "SCEAUX-01",
      ts: { $gte: ISODate("2008-12-24T18:00:00Z"), $lt: ISODate("2008-12-24T18:10:00Z") } },
    { _id: 0, ts: 1, global_active_power_kw: 1, voltage_v: 1,
      kitchen_wh: "$sub_metering_wh.kitchen", laundry_wh: "$sub_metering_wh.laundry",
      heater_ac_wh: "$sub_metering_wh.water_heater_ac" }
  ).sort({ ts: 1 }).toArray()
);

table(
  "M2. Monthly energy use in 2009 from 1-minute readings (aggregate: $match, $group, $dateTrunc)",
  ["month", "minutes", "energy_kwh", "avg_power_kw", "peak_power_kw", "heater_ac_kwh", "heater_ac_share_pct"],
  db.readings.aggregate([
    { $match: { ts: { $gte: ISODate("2009-01-01"), $lt: ISODate("2010-01-01") }, is_missing: false } },
    { $group: {
        _id: { $dateTrunc: { date: "$ts", unit: "month" } },
        minutes: { $sum: 1 },
        energy_kwh: { $sum: { $divide: ["$global_active_power_kw", 60] } },
        avg_power_kw: { $avg: "$global_active_power_kw" },
        peak_power_kw: { $max: "$global_active_power_kw" },
        heater_ac_kwh: { $sum: { $divide: ["$sub_metering_wh.water_heater_ac", 1000] } } } },
    { $sort: { _id: 1 } },
    { $project: {
        _id: 0,
        month: { $dateToString: { date: "$_id", format: "%Y-%m" } },
        minutes: 1,
        energy_kwh: { $round: ["$energy_kwh", 1] },
        avg_power_kw: { $round: ["$avg_power_kw", 3] },
        peak_power_kw: 1,
        heater_ac_kwh: { $round: ["$heater_ac_kwh", 1] },
        heater_ac_share_pct: { $round: [{ $multiply: [{ $divide: ["$heater_ac_kwh", "$energy_kwh"] }, 100] }, 1] } } },
  ]).toArray()
);


table(
  "M3. Daily energy with lag-1, lag-7 and 7-day moving average, 2009-12-14 to 2010-01-03 ($setWindowFields)",
  ["date", "energy_kwh", "lag_1_kwh", "lag_7_kwh", "ma_7_kwh", "pct_vs_ma_7"],
  db.daily_summaries.aggregate([
    { $match: { household_id: "SCEAUX-01" } },
    { $setWindowFields: {
        sortBy: { date: 1 },
        output: {
          lag_1_kwh: { $shift: { output: "$total_energy_kwh", by: -1 } },
          lag_7_kwh: { $shift: { output: "$total_energy_kwh", by: -7 } },
          ma_7_kwh: { $avg: "$total_energy_kwh", window: { documents: [-6, 0] } } } } },
    { $match: { date: { $gte: ISODate("2009-12-14"), $lte: ISODate("2010-01-03") } } },
    { $project: {
        _id: 0,
        date: { $dateToString: { date: "$date", format: "%Y-%m-%d" } },
        energy_kwh: { $round: ["$total_energy_kwh", 2] },
        lag_1_kwh: { $round: ["$lag_1_kwh", 2] },
        lag_7_kwh: { $round: ["$lag_7_kwh", 2] },
        ma_7_kwh: { $round: ["$ma_7_kwh", 2] },
        pct_vs_ma_7: { $round: [{ $multiply: [{ $divide: [{ $subtract: ["$total_energy_kwh", "$ma_7_kwh"] }, "$ma_7_kwh"] }, 100] }, 1] } } },
  ]).toArray()
);


table(
  "M4. Average power by hour of day, weekday vs weekend ($unwind embedded hourly array)",
  ["hour", "weekday_kw", "weekend_kw", "weekend_minus_weekday_kw"],
  db.daily_summaries.aggregate([
    { $unwind: "$hourly" },
    { $group: {
        _id: "$hourly.hour",
        weekday_kw: { $avg: { $cond: [{ $lte: ["$day_of_week", 5] }, "$hourly.avg_active_power_kw", "$$REMOVE"] } },
        weekend_kw: { $avg: { $cond: [{ $gte: ["$day_of_week", 6] }, "$hourly.avg_active_power_kw", "$$REMOVE"] } } } },
    { $sort: { _id: 1 } },
    { $project: {
        _id: 0,
        hour: "$_id",
        weekday_kw: { $round: ["$weekday_kw", 3] },
        weekend_kw: { $round: ["$weekend_kw", 3] },
        weekend_minus_weekday_kw: { $round: [{ $subtract: ["$weekend_kw", "$weekday_kw"] }, 3] } } },
  ]).toArray()
);


table(
  "M5. Ten days with the most missing minutes (find + projection + sort + limit)",
  ["date", "missing_minutes", "observed_minutes", "total_energy_kwh"],
  db.daily_summaries.find(
    { missing_minutes: { $gt: 0 } },
    { _id: 0, date: { $dateToString: { date: "$date", format: "%Y-%m-%d" } },
      missing_minutes: 1, observed_minutes: 1, total_energy_kwh: 1 }
  ).sort({ missing_minutes: -1, date: 1 }).limit(10).toArray()
);

// Collection sizes, for reference
table("Collection document counts", ["collection", "documents"], ["households", "readings", "daily_summaries"].map(
  (c) => ({ collection: c, documents: db.getCollection(c).countDocuments({}) })));
