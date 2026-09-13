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

> **Genauigkeitswarnung:** Harmlose Diagramm-Screenshots haben im lokalen Einsatz
> `REVIEW` erhalten. Die mitgelieferten Schwellen sind nicht unabhaengig auf
> repraesentativen Bildern validiert; die Rate uebersehener NSFW-Bilder ist
> unbekannt. `ALLOW` beweist nicht, dass ein Bild unbedenklich ist, und `BLOCK`
> beweist keinen expliziten Inhalt. Keine irreversiblen automatischen Entscheidungen
> damit treffen. Siehe [Accuracy-Evaluation](docs/ACCURACY_EVALUATION.md).

## Was das Produkt anders macht

- **Lokal zuerst:** Basisklassifikator und Ordner-Scan laden keine Bilder hoch.
  Optionale Remote-Vision-Adapter uebertragen Pixel nur nach expliziter Freigabe.
- **Nicht destruktiv:** Bilder und ihre Metadaten werden nie veraendert.
- **Fail-closed:** Unlesbare Dateien erhalten ein sichtbares `ERROR`.
- **Begrenzt:** Warteschlange, Metrik-Samples, Bildbytes und Pixel wachsen nicht
  unkontrolliert mit der Sammlung.
- **Nachvollziehbar:** JSONL-Evidenz nennt Modell, Policy, Provider, Lauf und Timing.
- **Messbare Qualitaet (aktueller Quellcode, noch nicht im a4-Test-Wheel):**
  `evaluate` vergleicht gespeicherte Ergebnisse per Bild-Hash mit unabhaengigen
  menschlichen Labels, ohne Bilder erneut zu oeffnen oder hochzuladen.
- **Einfach reviewbar:** `--links` erzeugt portable HTML-Indexe und Windows-`.url`-
  Verknuepfungen fuer `BLOCK`, `REVIEW` und `ERROR`.
- **Ehrlich schnell:** CPU-Vorbereitung laeuft parallel, GPU-Inferenz wird pro Session
  serialisiert. Das aktuelle Modell nutzt Batchgroesse `1`.

NSFW Guard ist Alpha-Software. Es ist fuer Triage und Reviews gedacht, nicht fuer
vollautomatische rechtliche, berufliche oder behoerdliche Entscheidungen.

<a id="ohne-klonen-ausprobieren-windows-powershell"></a>

## Mit eigenem Bild ausprobieren (Windows CMD oder PowerShell)

Beide Befehle funktionieren ohne installiertes Python. Sie laden das
[Startskript von einem festen Commit](https://github.com/IamAngusU/nsfw-guard/blob/2090a99045729e4ad2c629ada74cf6efc6efd7a9/scripts/try.ps1) und fragen nach einem Bild- oder
Ordnerpfad. **Vor allen weiteren Downloads** zeigt es Dateien, Quellen,
ungefaehre Groessen und den privaten Speicherort. Mit `j`/`y` erlauben, sonst
abbrechen. Klonen, Adminrechte und ein Bild-Upload durch NSFW Guard sind nicht
noetig. Der Einzeiler selbst laedt und startet PowerShell-Code von GitHub; wer
moechte, kann ihn vorher ansehen oder den Hash unten vergleichen.

CMD:

```bat
powershell.exe -NoProfile -Command "& ([scriptblock]::Create((irm 'https://raw.githubusercontent.com/IamAngusU/nsfw-guard/2090a99045729e4ad2c629ada74cf6efc6efd7a9/scripts/try.ps1')))"
```

PowerShell:

```powershell
& ([scriptblock]::Create((irm 'https://raw.githubusercontent.com/IamAngusU/nsfw-guard/2090a99045729e4ad2c629ada74cf6efc6efd7a9/scripts/try.ps1')))
```

In CMD Optionen **vor dem letzten doppelten Anfuehrungszeichen** ergaenzen; in
PowerShell nach den schliessenden Klammern. `-PlanOnly`
zeigt nur den Plan; `-Cleanup` entfernt nach dem Scan die private Test-Installation
samt Modell und Berichten; `-CacheBase 'D:\ein-beschreibbarer-ordner'` legt sie auf
D: ab. `-AcceptDownloads` ueberspringt die Rueckfrage ausdruecklich fuer
Automatisierung. Wenn ein unterstuetztes Python 3.10-3.12 vorhanden ist, wird es
genutzt. Sonst laedt das Skript nach Zustimmung das SHA-256-gepruefte `uv` von
Astrals GitHub-Release und damit ein privates CPython 3.12 aus Astrals
`python-build-standalone`. Weder globaler PATH noch Adminrechte sind noetig. Das
veroeffentlichte Wheel `0.1.0a4` und das Modell sind hashgeprueft;
PyPI-Drittanbieter-Abhaengigkeiten sind nicht per Hash fixiert. Der Ordner-Test
scannt standardmaessig die **ersten 32 Bilder nach Dateinamen**, keine
Zufallsstichprobe; `-MaxFiles 200` erweitert die Vorschau. Der Installer zeigt
Review-Dateinamen, Scores und Schwellen. `REVIEW` bedeutet manuell pruefen, nicht
bestaetigtes NSFW; harmlose Diagramme koennen Fehlalarme sein. Im gepinnten a4-
Release wird sogar ein vollstaendig deckendes PNG mit Alpha-Kanal unnoetig doppelt
berechnet. Das verursacht den Score nicht.
Der Fix liegt auf `main`, noch nicht im gepinnten a4-Wheel. Mit
`-Policy high-threshold-v1` gibt es weniger Reviews, aber auch ein hoeheres Risiko,
relevante Bilder zu uebersehen. Berichte enthalten Pfade und Scores; fuer einen eigenen
Cache einen privaten, nicht synchronisierten Ort waehlen. `main` steht derzeit bei
`0.1.0a5.dev0`.

<details>
<summary>Vor dem Start SHA-256 pruefen</summary>

Das ist dasselbe fest gepinnte Skript, keine Sandbox. Erst die ersten drei Zeilen
ausfuehren, `$trialScript` bei Bedarf ansehen und dann die letzte Zeile starten.
Fuer einen fluechtigen Test `-Cleanup` an die letzte Zeile anhaengen.

```powershell
$trialScript = irm 'https://raw.githubusercontent.com/IamAngusU/nsfw-guard/2090a99045729e4ad2c629ada74cf6efc6efd7a9/scripts/try.ps1'
$sha256 = [BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash([Text.Encoding]::UTF8.GetBytes($trialScript))).Replace('-', '')
if ($sha256 -ne 'F73268B75438F74532C079FAA0634BF2B5B2DE13719C280C7BF0FE768CFA47FE') { throw 'Bootstrap SHA-256 mismatch.' }
& ([scriptblock]::Create($trialScript))
```

</details>

Dieses Startskript verwendet einen neuen Cache, damit eine Installation von vor
der Wheel-Pruefung nicht weiterverwendet wird. Den **alten, markierten Cache ohne
erneuten Scan** mit dem vorherigen, fest gepinnten Skript entfernen:

```powershell
powershell.exe -NoProfile -Command "& ([scriptblock]::Create((irm 'https://raw.githubusercontent.com/IamAngusU/nsfw-guard/ab9fbef7af64d3a08f7309f34ccbb0ceff7178a8/scripts/try.ps1'))) -CleanupOnly"
```

Aeltere Startskripte konnten den Cache in Windows-Dokumente legen; dieser Ordner
kann mit OneDrive synchronisiert sein. Dann an die Bereinigungszeile
`-CacheBase ([Environment]::GetFolderPath('MyDocuments'))` anhaengen. Eine bereits
erfolgte Synchronisierung macht das nicht rueckgaengig.

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

Ohne `--output-dir` entsteht im geprueften Ordner `.nsfw-guard`. Jeder Lauf besitzt
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

## Optionale Vision-Modelle

Mit `nsfw-guard vision init`, `vision doctor` und `vision enrich` kann jedes lokale
Modell hinter einen persistenten JSONL-Adapter gehaengt werden. Ein kompatibler
HTTPS-Endpunkt funktioniert ebenfalls. Tasks und Routen entscheiden einfach, ob ein
Modell alle Bilder oder nur Gruppen wie `REVIEW` und `BLOCK` erhaelt. Die Ergebnisse
landen separat in `vision-results.jsonl` und veraendern nie das NSFW-Grundurteil.

Standard ist `local-only`. Remote-Nutzung verlangt `remote-tls`, HTTPS und eine
ausdrueckliche Bestaetigung der Bildweitergabe. Bilder werden standardmaessig verkleinert
und ohne Originalmetadaten neu kodiert. Das ist verschluesselter Transport, aber keine
falsche E2EE-Behauptung gegenueber dem Modellanbieter. Details stehen in
[`docs/VISION_ADAPTERS.md`](docs/VISION_ADAPTERS.md).

## Grenzen

- Klassifikatoren koennen falsch liegen und Bias enthalten.
- Die mitgelieferten Policy-Schwellenwerte sind Vorgaben, nicht fuer die eigenen
  Daten kalibriert oder validiert. Bevorzuge `low-threshold-v1`,
  `medium-threshold-v1` oder `high-threshold-v1`; alte Namen bleiben gueltig. Siehe
  [`MODEL_CARD.md`](MODEL_CARD.md).
- DirectML und CUDA haengen von Betriebssystem, Treiber und Runtime ab.
- WDDM liefert teilweise nur GPU-Gesamtwerte statt verlaesslichem Prozess-VRAM.
- Es gibt keine aktive GitHub Action und keine verpflichtende Telemetrie.
- Das Werkzeug ersetzt keine fuer den Anwendungsfall validierte menschliche Policy.

## Lizenz

Der Anwendungscode steht ab `0.1.0a3` unter AGPL-3.0-only. Das bereits veroeffentlichte
`0.1.0a1` bleibt MIT. Modell und optionale Runtimes behalten ihre
jeweiligen Lizenzen, siehe [`NOTICE.md`](NOTICE.md).

## Polymorph-Interoperabilitaet

`nsfw-guard bridge` ist eine persistente, versionierte JSONL-Prozessschnittstelle. Polymorph findet
sie ohne zusaetzliches Adapter-Paket:

```powershell
python -m pip install "https://github.com/IamAngusU/polymorph/releases/download/v0.4.0a11/polymorph_bridge-0.4.0a11-py3-none-any.whl" "nsfw-guard[cpu] @ https://github.com/IamAngusU/nsfw-guard/releases/download/v0.1.0a4/nsfw_guard-0.1.0a4-py3-none-any.whl#sha256=754889cf0bd646f8f861c27fe4b1b25cd701c91f3813ac7a2bbb01200368c124"
polymorph guard --doctor
polymorph guard C:\Bilder\beispiel.jpg
```

Der Prozess bleibt warm, Dateiwurzeln sind explizit, Requests koennen an SHA-256 gebunden werden und
Antworten werden korreliert und begrenzt. Nach einem mehrdeutigen Fehler wird kein Retry erfunden.
Erstaunlich viel Zuverlaessigkeit entsteht dadurch, dass Software gelegentlich nicht raet.

Die Protokollspezifikation ist in
[`docs/INTEROPERABILITY.md`](docs/INTEROPERABILITY.md) permissiv lizenziert. Die Implementierung
bleibt ein getrenntes Produkt unter AGPL-3.0-only. Das bereits veroeffentlichte `0.1.0a1` bleibt MIT.

## Gemessene Real-Folder-Baseline, 13.09.2026

Ein Windows-11-Host, i9-12900K, RTX 3080, 32 GiB RAM, 200 SHA-256-eindeutige reale
Screenshots, warmer Dateisystem-Cache, vier Worker, Model-Batchgroesse 1:

| Provider | Durchsatz | Laufzeit | Peak RSS | Beobachtetes Host-VRAM-Delta |
| --- | ---: | ---: | ---: | ---: |
| CPU, automatisch 4 Threads | 24,89 Bilder/s | 8,04 s | 450,2 MiB | nicht anwendbar |
| DirectML | 84,07 Bilder/s | 2,38 s | 612,2 MiB | etwa 103 MiB |
| CUDA, 768-MiB-Arena-Limit | 83,87 Bilder/s | 2,38 s | 925,9 MiB | etwa 312 MiB |

Alle drei Laeufe beendeten 200/200 Dateien ohne Scanfehler. DirectML und CUDA starteten bei 8 Prozent
GPU-Last; CPU bei 8,5 Prozent Host-CPU. Das sind lokale Betriebsmessungen, kein
Geschwindigkeitsvertrag mit jedem jemals gebauten Laptop. Das private Korpus wird nicht
veroeffentlicht und dies ist kein Accuracy-Benchmark.

Der CPU-Auto-Thread-Fix verbesserte exakt diese Last von kontaminierten 5,66 auf 24,89 Bilder/s.
Vollstaendige Evidenz:
[`benchmarks/2026-09-13-real-screenshots-game-off.json`](benchmarks/2026-09-13-real-screenshots-game-off.json).
