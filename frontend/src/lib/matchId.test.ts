import { makeMatchId, slugify } from "./matchId";

test("slugs follow the backend rules", () => {
  expect(slugify("Nott'm Forest")).toBe("nottm-forest");
  expect(slugify("Ath Bilbao")).toBe("ath-bilbao");
  expect(slugify("Bayern Munich")).toBe("bayern-munich");
  expect(slugify("Köln")).toBe("koln");
  expect(slugify("St. Etienne")).toBe("st-etienne");
});

test("match id", () => {
  expect(makeMatchId("SP1", "2026-10-10", "Alaves", "Ath Madrid")).toBe(
    "SP1-2026-10-10-alaves-ath-madrid",
  );
});
