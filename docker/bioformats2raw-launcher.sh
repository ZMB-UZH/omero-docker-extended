#!/usr/bin/env bash
set -Eeuo pipefail

readonly java_home="/usr/lib/jvm/jre-17-openjdk"
readonly converter="/opt/bioformats2raw/bin/bioformats2raw"

if [[ ! -x "${java_home}/bin/java" ]]; then
    printf 'ERROR: bioformats2raw requires the bundled Java 17 runtime at %s.\n' "${java_home}" >&2
    exit 1
fi
if [[ ! -x "${converter}" ]]; then
    printf 'ERROR: bioformats2raw executable is missing at %s.\n' "${converter}" >&2
    exit 1
fi

export JAVA_HOME="${java_home}"
exec "${converter}" "$@"
