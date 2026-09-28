// Same rules as `slugify` / `make_match_id` in src/betting_ml/domain/entities.py: the id must
// match the one built from the official results, so the bet can be settled and get its CLV.

export function slugify(text: string): string {
  const ascii = text
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[^ -~]/g, ""); // drop what is left outside printable ASCII
  return ascii
    .toLowerCase()
    .replace(/['’`.]/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

export function makeMatchId(league: string, date: string, home: string, away: string): string {
  return `${league}-${date}-${slugify(home)}-${slugify(away)}`;
}
