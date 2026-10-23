// Apply the saved theme before the first paint (dark by default). A separate file, not an
// inline script, so the Content-Security-Policy can forbid inline scripts (spec 003, T011).
try {
  if (localStorage.getItem("betting-ml.theme") === "light") {
    document.documentElement.classList.remove("dark");
  }
} catch {
  /* storage unavailable: keep the dark default */
}
