# Bundled typefaces

Families that real uploaded decks request and Debian does not package. Copied
into `/usr/local/share/fonts` by `backend/Dockerfile` so LibreOffice can resolve
them by name instead of substituting Noto Sans — the substitute's metrics reflow
the text and change how the slide looks. Rationale: `docs/DECISIONS.md` §56.

**Static instances only.** LibreOffice renders a *variable* font at its first
named instance, so `Montserrat[wght].ttf` comes out Thin and
`Merriweather[opsz,wdth,wght].ttf` comes out Light — worse than the substitution
they were meant to replace. Do not swap these for the variable builds.

| Family | Upstream | Copyright |
|---|---|---|
| Montserrat | [JulietaUla/Montserrat](https://github.com/JulietaUla/Montserrat) | 2024 The Montserrat Project Authors |
| Open Sans | [googlefonts/opensans](https://github.com/googlefonts/opensans) | 2020 The Open Sans Project Authors |
| Merriweather | [SorkinType/Merriweather](https://github.com/SorkinType/Merriweather) | 2016 The Merriweather Project Authors |

All three are licensed under the SIL Open Font License 1.1 — see `OFL.txt`.

Adding a family: drop the static `.ttf` files here, extend the table above, and
rebuild the backend image. The `pptx_fonts_missing` warning logged by
`video_service._log_missing_fonts` is what tells you which family to add next.
