export type EnergyRecord = {
  id?: number;
  source: string;
  production: number;
  unit: "kWh";
};
export type EnergyResponse = {
  project: string;
  status: string;
  records: EnergyRecord[];
};

export function parseEnergy(value: unknown): EnergyResponse {
  if (!value || typeof value !== "object")
    throw new Error("The energy service returned an invalid response.");
  const data = value as Record<string, unknown>;
  if (
    typeof data.project !== "string" ||
    typeof data.status !== "string" ||
    !Array.isArray(data.records)
  ) {
    throw new Error("The energy service returned an invalid response.");
  }
  const seen = new Set<string>();
  const records = data.records.map((item: unknown): EnergyRecord => {
    if (!item || typeof item !== "object")
      throw new Error("An energy record is invalid.");
    const record = item as Record<string, unknown>;
    if (
      typeof record.source !== "string" ||
      !record.source.trim() ||
      seen.has(record.source) ||
      typeof record.production !== "number" ||
      !Number.isFinite(record.production) ||
      record.production < 0 ||
      record.unit !== "kWh"
    ) {
      throw new Error(
        "An energy record has an invalid source, value, or unit.",
      );
    }
    seen.add(record.source);
    return {
      source: record.source,
      production: record.production,
      unit: record.unit,
    };
  });
  return { project: data.project, status: data.status, records };
}

export function energyCsv(records: EnergyRecord[]) {
  const cell = (value: string) =>
    `"${(/^[=+\-@\t\r]/.test(value) ? "'" : "") + value.replaceAll('"', '""')}"`;
  return [
    "Source,Production,Unit",
    ...records.map(
      (record) =>
        `${cell(record.source)},${record.production},${cell(record.unit)}`,
    ),
  ].join("\r\n");
}

export const formatEnergy = (value: number) =>
  new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 }).format(value);
