# wow.export bridge protocol v1

Phase 2 uses a deliberately small HTTP interface so fork-specific wow.export code remains outside the exporter. The service **must bind only to `127.0.0.1`**. The exporter rejects any other hostname and accepts output files only from the requested temporary directory.

Base URL: `http://127.0.0.1:17890`

## Capabilities

`GET /v1/capabilities`

```json
{"interface":"wow-timecapsule-bridge/v1","wow_export_version":"1.0.0","formats":["glb"]}
```

## Open installation

`POST /v1/installations/open`

```json
{"interface":"wow-timecapsule-bridge/v1","installation":"C:\\Games\\World of Warcraft\\_retail_","product":"retail"}
```

The response is `{"status":"ready"}` or an HTTP error with a JSON `error` value.

## Export character

`POST /v1/exports/character` receives `interface`, absolute temporary `output_dir`, `format: "glb"`, and a `character` using schema `wow-timecapsule-character/v1`. It returns paths relative to `output_dir`:

```json
{"status":"complete","files":["character.glb","preview.png","wow-export-metadata.json"]}
```

## Export creature

`POST /v1/exports/creature` receives `interface`, `output_dir`, `format`, and `display_id`. Its response has the same shape as character export.

The bridge must finish writing and close all files before responding. It must never accept remote connections. Map export is reserved at `POST /v1/exports/map` for Phase 3.

