#!/usr/bin/env node
// SPDX-License-Identifier: AGPL-3.0-or-later
if (process.env.CI || process.env.npm_config_loglevel === "silent") process.exit(0);
process.stdout.write(`
LOLM installed — local, open source, and ready for your provider.

  1. lolm setup
  2. lolm doctor
  3. lolm

For real NFET control, clone https://github.com/TheArtOfSound/LOLM and set
LOLM_HOME to that checkout. No LOLM account or hosted plan is required.

`);
