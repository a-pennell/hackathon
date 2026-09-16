/** A human label for any id, never the raw id: the labels map first, then the kind the prefix names. */
const KIND: Record<string, string> = { prob: "problem", obs: "result", med: "medication", enc: "visit", note: "note", lnk: "link", ins: "insight", doc: "document", ord: "order", plan: "plan item", pt: "patient" };
export const labelOf = (labels: Record<string, string>, id: string): string => {
  const hit = labels[id];
  if (hit) return hit;
  if (id.startsWith("LOINC:")) return `${id.slice(6)} series`;
  const prefix = id.split("_")[0];
  return KIND[prefix] ? `${KIND[prefix]} ${id.slice(prefix.length + 1)}` : id;
};
