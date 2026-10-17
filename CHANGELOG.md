# Changelog

## 1.1.0

- Fix local HTML album maps blocked by the standard OSM tile policy by using
  OpenFreeMap vector maps with visible attribution. Restore the map button on
  loading failures and remove the restrictive referrer policy.
- Check for newer stable releases at startup using the official GitHub Releases
  REST API. Show a nonmodal toast with the available version and a release link,
  with numeric version comparison, conditional requests, timeouts, and rate-limit
  handling. Keep up-to-date results and network errors silent.
- Organize application code and bundled icons under `src/travel_photo_mapper`,
  with an installable package and a `python -m travel_photo_mapper` entry point.
- Save named trips and restore their folder, filters, selected photo, timeline
  view, map overlays, and playback speed. Saved sessions update when switching
  folders or closing the application.
- Reopen, rename, remove, and reconnect saved trips whose source folders moved.
- Export the filtered selection to a portable HTML album with optimized JPEGs,
  responsive gallery, keyboard photo navigation, and optional online map.
- Choose whether to include GPS coordinates. Album image copies omit EXIF
  metadata and the generated page omits original filesystem paths.
- Export albums in the background with progress, cancellation, and cleanup on
  failure, preserving existing exports and original images.
- Provide Italian and English text for all new controls and exported albums.
