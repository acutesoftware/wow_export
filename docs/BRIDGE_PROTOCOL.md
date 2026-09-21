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

The bridge must finish writing and close all files before responding. It must never accept remote connections.

## Export map tiles

`POST /v1/exports/map` receives `interface`, an absolute temporary `output_dir`,
`format: "obj"`, a numeric `map_id`, and a non-empty `tiles` array containing `x`
and `y` ADT coordinates. It returns every generated terrain, WMO/M2 object, texture,
placement, heightmap, and metadata file:

```json
{"status":"complete","files":["tile_32_32.obj","terrain.png","placements.json"],"entries":[{"path":"tile_32_32.obj","kind":"terrain","tile":{"x":32,"y":32}}]}
```

An `entries` item with `kind` equal to `wmo`, `m2`, or `object` is represented in
the stable scene manifest as a placed object. Other model files are terrain. Entry
metadata may include `position`, `rotation`, `scale`, `tile`, and `source_id`.
