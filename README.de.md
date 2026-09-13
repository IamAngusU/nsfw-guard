<p align="center">
  <img src="docs/assets/brand-mark.svg" width="132" alt="NSFW Guard Logo">
</p>

<h1 align="center">NSFW Guard</h1>

<p align="center"><strong>Schnelle, lokale Sicherheits-Triage fuer Bildsammlungen.</strong></p>

<p align="center">
  <a href="README.md">English</a> |
  <a href="START-HERE.md">Schnellstart</a> |
  <a href="docs/FOLDER_SCANNING.md">Ordner-Scans</a> |
  <a href="docs/METRICS.md">Messdaten</a>
</p>

NSFW Guard prueft JPEG-, PNG- und WebP-Bilder lokal und liefert fuer jede Datei
explizit `ALLOW`, `REVIEW`, `BLOCK` oder `ERROR`. Das Werkzeug ist fuer begrenzte
Ordner-Pipelines, menschliche Reviews, Automatisierung und spaetere Integrationen
gebaut.

> Ein Modell-Score ist Evidenz. Er ist kein physikalisch sicheres Urteil.

## Was das Produkt anders macht

- **Lokal:** NSFW Guard laedt Bilddaten nicht in einen fremden Dienst hoch.
- **Nicht destruktiv:** Bilder und ihre Metadaten werden nie veraendert.
- **Fail-closed:** Unlesbare Dateien erhalten ein sichtbares `ERROR`.
- **Begrenzt:** Warteschlange, Metrik-Samples, Bildbytes und Pixel wachsen nicht
  unkontrolliert mit der Sammlung.
- **Nachvollziehbar:** JSONL-Evidenz nennt Modell, Policy, Provider, Lauf und Timing.
- **Einfach reviewbar:** `--links` erzeugt kleine `.url`-Verknuepfungen fuer
  `BLOCK`, `REVIEW` und `ERROR` sowie einen lokalen Lightmode-Index.
- **Ehrlich schnell:** CPU-Vorbereitung laeuft parallel, GPU-Inferenz wird pro Session
  serialisiert. Das aktuelle Modell nutzt Batchgroesse `1`.

NSFW Guard ist Alpha-Software. Es ist fuer Triage und Reviews gedacht, nicht fuer
vollautomatische rechtliche, berufliche oder behoerdliche Entscheidungen.

## In zwei Befehlen starten

Repository klonen oder das GitHub-ZIP entpacken:

```powershell
python scripts\bootstrap.py --runtime cpu
.venv\Scripts\nsfw-guard.exe folder "C:\Bilder" --provider cpu --links
```

Fuer DirectML unter Windows:

```powershell
python scripts\bootstrap.py --runtime directml
.venv\Scripts\nsfw-guard.exe folder "C:\Bilder" --provider directml --links
```

Die virtuelle Umgebung muss nicht aktiviert werden. Alternativ koennen
`Install.cmd`, `Install-DirectML.cmd` und `Scan-Folder.cmd` verwendet werden.

## Ergebnisse

Ohne `--output-root` entsteht im geprueften Ordner `.nsfw-guard`. Jeder Lauf besitzt
eine eigene ID und schreibt atomar:

- `all-results.jsonl` mit jedem Ergebnis
- `flags.jsonl` nur mit `REVIEW`, `BLOCK` und `ERROR`
- `summary.json` mit Hardware, Provider, Modell, Limits, Zeiten, RSS und GPU-Samples
- `status.json` als kleiner maschinenlesbarer Laufstatus
- `metrics.svg` als begrenzte Verlaufskurve fuer Durchsatz, CPU/GPU und Speicher
- `links/` mit optionalen lokalen Verknuepfungen und `index.html`

Das Loeschen einer Verknuepfung loescht niemals das Original. Auch beim Erstellen der
Review-Sammlung werden keine Bilder kopiert oder umbenannt.

## Parallel, aber kontrolliert

Der Easy-Modus waehlt anhand von Provider, logischen CPUs und verfuegbarem RAM eine
konservative Worker-Zahl und begrenzt sie derzeit auf vier. Auf dem Referenzsystem
war das der beste gemessene Durchsatz. Mit `--workers N` kann ein Nutzer bewusst
abweichen. `--memory-budget-mib` hilft bei der Planung, ist aber kein harter
Betriebssystem-RSS-Limiter. Byte- und Pixelgrenzen pro Bild werden hart geprueft.

Bei 200 warm gecachten PNGs auf Windows, Intel Core i9-12900K und NVIDIA RTX 3080
erreichte der automatische Vier-Worker-Lauf am 2026-09-13:

| Provider | Bilder/s | p50 Ende-zu-Ende | Peak RSS | Bewertung |
|---|---:|---:|---:|---|
| CPU | **29,72** | 127,60 ms | 453,5 MiB | headline-faehig |
| DirectML | **82,37** | 39,95 ms | 609,7 MiB | GPU-Vorlast, kein Headline-Wert |
| CUDA | **79,68** | 38,60 ms | 928,9 MiB | headline-faehig |

Gegen einen Worker waren CPU und CUDA `1,92x` beziehungsweise `2,21x` schneller.
Vier Worker optimieren Ordnerdurchsatz, nicht die Latenz eines einzelnen Bildes.
Methodik, Rohdaten und Messqualitaet stehen in [`docs/METRICS.md`](docs/METRICS.md).

![NSFW Guard Performance-Verlauf](docs/assets/performance-history.svg)

## Entscheidungen und Exit Codes

| Ergebnis | Bedeutung |
|---|---|
| `ALLOW` | Policy-Schwelle nicht ueberschritten |
| `REVIEW` | Unsicher oder von der Policy als reviewpflichtig eingestuft |
| `BLOCK` | Block-Schwelle ueberschritten |
| `ERROR` | Keine verlaessliche Klassifikation moeglich |

NSFW Guard verschiebt oder loescht bei keinem Ergebnis eine Datei. Mit
`--fail-on never|error|block|review` wird nur der Prozess-Exit fuer die aufrufende
Automation festgelegt; Standard ist `error`.

Weitere Details: [`START-HERE.md`](START-HERE.md),
[`docs/FOLDER_SCANNING.md`](docs/FOLDER_SCANNING.md),
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md), [`SECURITY.md`](SECURITY.md).

## Grenzen

- Klassifikatoren koennen falsch liegen und Bias enthalten.
- DirectML und CUDA haengen von Betriebssystem, Treiber und Runtime ab.
- WDDM liefert teilweise nur GPU-Gesamtwerte statt verlaesslichem Prozess-VRAM.
- Es gibt keine aktive GitHub Action und keine verpflichtende Telemetrie.
- Das Werkzeug ersetzt keine fuer den Anwendungsfall validierte menschliche Policy.

## Lizenz

Der Anwendungscode steht unter MIT. Modell und optionale Runtimes behalten ihre
jeweiligen Lizenzen, siehe [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).
