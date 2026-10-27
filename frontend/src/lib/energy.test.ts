import { describe, expect, it } from "vitest";
import { energyCsv, parseEnergy } from "./energy";

describe("energy boundary", () => {
  const snapshot = {
    project: "Fixture",
    status: "working",
    records: [{ source: "Solar", production: 125, unit: "kWh" }],
  };
  it("accepts the shared Lambda and FastAPI shape without inventing readings", () => {
    expect(parseEnergy(snapshot).records[0].production).toBe(125);
    expect(parseEnergy({ ...snapshot, records: [] }).records).toEqual([]);
  });
  it.each([
    null,
    {},
    { ...snapshot, records: [{}] },
    {
      ...snapshot,
      records: [{ source: "Solar", production: -1, unit: "kWh" }],
    },
    { ...snapshot, records: [{ source: "Solar", production: 10, unit: "MW" }] },
    { ...snapshot, records: [...snapshot.records, ...snapshot.records] },
  ])("rejects malformed or ambiguous data: %j", (value) => {
    expect(() => parseEnergy(value)).toThrow();
  });
  it("quotes CSV and prevents source names from becoming spreadsheet formulas", () => {
    expect(
      energyCsv([{ source: "=SUM(A1)", production: 4, unit: "kWh" }]),
    ).toContain('"\'=SUM(A1)",4,"kWh"');
    expect(
      energyCsv([{ source: 'A,"B"', production: 4, unit: "kWh" }]),
    ).toContain('"A,""B"""');
  });
});
