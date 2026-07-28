# Contributing

Thanks for your interest in improving the Cync Lights integration.

## Reporting a bug

Open an issue at [github.com/sam3gp8/cync-lights-hacs/issues](https://github.com/sam3gp8/cync-lights-hacs/issues) and include:

1. Your Home Assistant version and how you installed the integration (HACS or manual).
2. What you expected to happen and what actually happened.
3. **A diagnostics download.** Go to **Settings → Devices & Services → Cync Lights → the three-dot menu → Download diagnostics** (or the same menu on a specific device page). Credentials and tokens are automatically redacted, so it's safe to attach. This is by far the most useful thing for debugging device-availability issues.
4. Relevant logs. Add this to `configuration.yaml`, restart, reproduce, then copy the log lines:

   ```yaml
   logger:
     logs:
       custom_components.cync_lights: debug
       pycync: info
   ```

## Making a change

1. Fork the repository and create a branch for your change.
2. Keep the integration's structure intact — it must remain a valid Home Assistant custom integration under `custom_components/cync_lights/`.
3. Update `CHANGELOG.md` under a new version heading, and bump `version` in `custom_components/cync_lights/manifest.json` (patch for fixes, minor for new features, major for breaking changes).
4. Open a pull request describing what changed and why.

## Versioning & releases

This project uses [Semantic Versioning](https://semver.org/). HACS installs and updates from published GitHub **Releases**, so a version is only actually available to users once a release tagged to match `manifest.json`'s `version` is published — bumping the manifest alone is not enough.
