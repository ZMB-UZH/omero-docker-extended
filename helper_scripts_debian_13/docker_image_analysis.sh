#!/usr/bin/env bash
# shellcheck disable=SC2317

set -Eeuo pipefail
IFS=$'\n\t'
# Generate reports readable by non-root users when script is run via sudo.
# Individual environments can still tighten permissions externally if required.
umask 022

SCRIPT_NAME="$(basename "$0")"
VERSION="1.0.0"
DEFAULT_OUTPUT_DIR="image-inventory-reports"
DEFAULT_PROBE_TIMEOUT_SECONDS="900"
DEFAULT_MAX_REPORT_BYTES="$((50 * 1024 * 1024))"

DEBUG_MODE="false"

log_info() {
  printf '[INFO] %s\n' "$*" >&2
}

log_debug() {
  if [ "${DEBUG_MODE}" = "true" ]; then
    printf '[DEBUG] %s\n' "$*" >&2
  fi
}

log_warn() {
  printf '[WARN] %s\n' "$*" >&2
}

log_error() {
  printf '[ERROR] %s\n' "$*" >&2
}

usage() {
  cat <<EOF
$SCRIPT_NAME v$VERSION

Analyze a Docker image automatically and list installed software versions, including:
- OS package manager inventories (dpkg/rpm/apk/pacman/opkg)
- Python interpreter inventories
- pip package lists for global interpreters
- pip package lists for Python virtual environments (pyvenv.cfg discovery)

Usage:
  $SCRIPT_NAME [options]

Options:
  -i, --image IMAGE_REF      Docker image reference (example: postgres:16.11)
  -o, --output-dir PATH      Output directory for reports (default: $DEFAULT_OUTPUT_DIR)
      --skip-pull            Do not pull the image, inspect local cache only
      --no-json              Do not generate JSON report (text-only)
      --debug                Enable verbose debugging output
      --probe-timeout SEC    Timeout per probe shell attempt (default: $DEFAULT_PROBE_TIMEOUT_SECONDS)
      --max-report-bytes N   Max bytes to keep for raw probe output (default: $DEFAULT_MAX_REPORT_BYTES)
      --self-test            Run internal parser/unit tests and exit
  -h, --help                 Show this help and exit

Behavior:
- If --image is not provided and input is interactive, the script prompts for it.
- Fails fast with actionable errors when Docker is unavailable.
- Uses multiple shell candidates in target containers (/bin/sh, /bin/bash, /busybox/sh, sh, bash).
- Validates Docker daemon access before running image operations.
- Truncates oversized raw probe output defensively to avoid runaway report size.
EOF
}

cleanup_files() {
  if [ "${#TEMP_FILES[@]}" -gt 0 ]; then
    local f
    for f in "${TEMP_FILES[@]}"; do
      rm -f -- "$f" 2>/dev/null || true
    done
  fi
}

TEMP_FILES=()
trap cleanup_files EXIT

require_command() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    log_error "Required command not found: $cmd"
    return 1
  fi
}

iso_utc_timestamp() {
  date -u +"%Y-%m-%dT%H:%M:%SZ"
}

safe_filename_fragment() {
  printf '%s' "$1" | tr '/:@ ' '____' | tr -cd 'A-Za-z0-9._-'
}

validate_positive_integer() {
  local value="$1"
  local name="$2"
  if ! [[ "$value" =~ ^[0-9]+$ ]]; then
    log_error "$name must be a non-negative integer. Got: $value"
    return 1
  fi
  return 0
}

validate_image_reference() {
  local image_ref="$1"
  if [ -z "$image_ref" ]; then
    log_error "Image reference cannot be empty."
    return 1
  fi

  if printf '%s' "$image_ref" | grep -q '[[:space:]]'; then
    log_error "Image reference contains whitespace, which is invalid: $image_ref"
    return 1
  fi

  if printf '%s' "$image_ref" | grep -q '[[:cntrl:]]'; then
    log_error "Image reference contains control characters, which is invalid."
    return 1
  fi

  return 0
}

ensure_output_dir_writable() {
  local output_dir="$1"
  mkdir -p "$output_dir"

  if [ ! -d "$output_dir" ]; then
    log_error "Output path exists but is not a directory: $output_dir"
    return 1
  fi

  if [ ! -w "$output_dir" ]; then
    log_error "Output directory is not writable: $output_dir"
    return 1
  fi

  if ! chmod 755 "$output_dir" 2>/dev/null; then
    log_warn "Could not set output directory permissions to 755: $output_dir"
  fi

  return 0
}

set_report_permissions() {
  local file_path="$1"
  if [ -f "$file_path" ]; then
    if ! chmod 644 "$file_path" 2>/dev/null; then
      log_warn "Could not set report permissions to 644: $file_path"
    fi
  fi
}

docker_preflight() {
  require_command docker || return 1

  if ! docker info >/dev/null 2>&1; then
    log_error "Docker daemon is not reachable. Ensure Docker is running and current user can access it."
    return 1
  fi

  return 0
}

truncate_if_oversized() {
  local file_path="$1"
  local max_bytes="$2"

  if [ ! -f "$file_path" ]; then
    log_error "Cannot truncate missing file: $file_path"
    return 1
  fi

  local current_size
  current_size="$(wc -c <"$file_path")"
  if [ "$current_size" -le "$max_bytes" ]; then
    return 0
  fi

  log_warn "Raw probe output exceeded max size ($current_size > $max_bytes). Truncating report body."

  local tmp
  tmp="$(mktemp)"
  TEMP_FILES+=("$tmp")
  {
    printf '[TRUNCATED] raw probe output exceeded max bytes (%s).\n' "$max_bytes"
    printf '[TRUNCATED] original size bytes: %s\n\n' "$current_size"
    head -c "$max_bytes" "$file_path" || true
  } >"$tmp"
  cp "$tmp" "$file_path"
}

build_probe_script() {
  cat <<'EOS'
set -u

begin_section() {
  printf '###BEGIN:%s###\n' "$1"
}

end_section() {
  printf '###END:%s###\n' "$1"
}

run_section_cmd() {
  section_name="$1"
  shift
  begin_section "$section_name"
  "$@" 2>&1 || true
  end_section "$section_name"
}

begin_section "OS_RELEASE"
if [ -f /etc/os-release ]; then
  cat /etc/os-release
else
  echo "No /etc/os-release found."
fi
end_section "OS_RELEASE"

begin_section "PACKAGE_MANAGER_SUMMARY"
for cmd in dpkg-query rpm apk pacman opkg; do
  if command -v "$cmd" >/dev/null 2>&1; then
    echo "$cmd:available"
  else
    echo "$cmd:missing"
  fi
done
end_section "PACKAGE_MANAGER_SUMMARY"

if command -v dpkg-query >/dev/null 2>&1; then
  run_section_cmd "PACKAGES_DPKG" dpkg-query -W -f='${Package}\t${Version}\n'
fi

if command -v rpm >/dev/null 2>&1; then
  run_section_cmd "PACKAGES_RPM" rpm -qa --qf '%{NAME}\t%{VERSION}-%{RELEASE}\n'
fi

if command -v apk >/dev/null 2>&1; then
  run_section_cmd "PACKAGES_APK" apk info -vv
fi

if command -v pacman >/dev/null 2>&1; then
  run_section_cmd "PACKAGES_PACMAN" pacman -Q
fi

if command -v opkg >/dev/null 2>&1; then
  run_section_cmd "PACKAGES_OPKG" opkg list-installed
fi

begin_section "PYTHON_BINARIES"
for py in python python3 python3.13 python3.12 python3.11 python3.10 python3.9 python3.8 pypy pypy3; do
  if command -v "$py" >/dev/null 2>&1; then
    resolved="$(command -v "$py")"
    version="$($py --version 2>&1 || true)"
    echo "$py\t$resolved\t$version"
  fi
done
end_section "PYTHON_BINARIES"

begin_section "PYTHON_GLOBAL_PIP"
for py in python python3 python3.13 python3.12 python3.11 python3.10 python3.9 python3.8 pypy pypy3; do
  if command -v "$py" >/dev/null 2>&1; then
    echo "@@PYTHON@@ $py"
    "$py" -m pip --version 2>&1 || true
    "$py" -m pip list --format=freeze 2>&1 || true
  fi
done
end_section "PYTHON_GLOBAL_PIP"

begin_section "PYTHON_VENVS"
if command -v find >/dev/null 2>&1; then
  find / -xdev -type f -name pyvenv.cfg 2>/dev/null | while IFS= read -r cfg; do
    venv_dir="$(dirname "$cfg")"
    pybin="$venv_dir/bin/python"
    echo "@@VENV@@ $venv_dir"
    if [ -x "$pybin" ]; then
      "$pybin" --version 2>&1 || true
      "$pybin" -m pip --version 2>&1 || true
      "$pybin" -m pip list --format=freeze 2>&1 || true
    else
      echo "Missing python binary for venv: $venv_dir"
    fi
  done
else
  echo "find command not available; cannot scan pyvenv.cfg files."
fi
end_section "PYTHON_VENVS"
EOS
}

extract_section() {
  local section_name="$1"
  local raw_file="$2"
  awk -v n="$section_name" '
    $0 == "###BEGIN:" n "###" { in_section=1; next }
    $0 == "###END:" n "###" { in_section=0; exit }
    in_section { print }
  ' "$raw_file"
}

write_text_report() {
  local image="$1"
  local shell_used="$2"
  local inspect_file="$3"
  local raw_file="$4"
  local out_txt="$5"

  {
    echo "Docker Image Inventory Report"
    echo "============================="
    echo "Image: $image"
    echo "Generated (UTC): $(iso_utc_timestamp)"
    echo "Probe shell: $shell_used"
    echo
    echo "Image Metadata"
    echo "--------------"
    cat "$inspect_file"

    for section in \
      OS_RELEASE \
      PACKAGE_MANAGER_SUMMARY \
      PACKAGES_DPKG \
      PACKAGES_RPM \
      PACKAGES_APK \
      PACKAGES_PACMAN \
      PACKAGES_OPKG \
      PYTHON_BINARIES \
      PYTHON_GLOBAL_PIP \
      PYTHON_VENVS; do
      echo
      echo "$section"
      printf '%*s\n' "${#section}" '' | tr ' ' '-'
      local body
      body="$(extract_section "$section" "$raw_file")"
      if [ -n "$body" ]; then
        printf '%s\n' "$body"
      else
        echo "(empty or not detected)"
      fi
    done
  } >"$out_txt"
}

generate_json_report() {
  local image="$1"
  local shell_used="$2"
  local inspect_file="$3"
  local raw_file="$4"
  local out_json="$5"

  if command -v python3 >/dev/null 2>&1; then
    python3 - "$image" "$shell_used" "$inspect_file" "$raw_file" "$out_json" <<'PY'
import json
import re
import sys
from pathlib import Path

image, shell_used, inspect_path, raw_path, out_path = sys.argv[1:6]
raw = Path(raw_path).read_text(encoding="utf-8", errors="replace")
inspect = Path(inspect_path).read_text(encoding="utf-8", errors="replace")
sections = {}
pattern = re.compile(r"^###BEGIN:(?P<name>[A-Z0-9_]+)###$\n(?P<body>.*?)^###END:(?P=name)###$", re.MULTILINE | re.DOTALL)
for m in pattern.finditer(raw):
    sections[m.group("name")] = m.group("body").strip()
payload = {
    "image": image,
    "generated_at_utc": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "shell_used": shell_used,
    "docker_inspect_summary": inspect,
    "sections": sections,
}
Path(out_path).write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
PY
    return 0
  fi

  if command -v jq >/dev/null 2>&1; then
    jq -n \
      --arg image "$image" \
      --arg generated_at_utc "$(iso_utc_timestamp)" \
      --arg shell_used "$shell_used" \
      --arg docker_inspect_summary "$(cat "$inspect_file")" \
      --arg raw_output "$(cat "$raw_file")" \
      '{image:$image,generated_at_utc:$generated_at_utc,shell_used:$shell_used,docker_inspect_summary:$docker_inspect_summary,raw_output:$raw_output}' \
      >"$out_json"
    return 0
  fi

  log_warn "Neither python3 nor jq is available. Skipping JSON report generation."
  return 1
}

run_probe_with_shell() {
  local image="$1"
  local shell_path="$2"
  local probe_script="$3"
  local out_file="$4"
  local timeout_seconds="$5"

  local -a run_cmd
  run_cmd=(docker run --rm --entrypoint "$shell_path" "$image" -c "$probe_script")

  if command -v timeout >/dev/null 2>&1; then
    run_cmd=(timeout --signal=KILL "${timeout_seconds}s" "${run_cmd[@]}")
  else
    log_warn "timeout command not available; probe shell run has no hard timeout."
  fi

  if "${run_cmd[@]}" >"$out_file" 2>"${out_file}.stderr"; then
    return 0
  fi
  return 1
}

inspect_image_summary() {
  local image="$1"
  local inspect_json

  if ! inspect_json="$(docker image inspect "$image" --format '{{json .}}' 2>/dev/null)"; then
    log_error "Docker inspect failed for image: $image"
    return 1
  fi

  if [ -z "$inspect_json" ] || [ "$inspect_json" = "null" ]; then
    log_error "Docker inspect returned empty metadata for image: $image"
    return 1
  fi

  if command -v python3 >/dev/null 2>&1; then
    python3 - "$inspect_json" <<'PY'
import json
import sys

data = json.loads(sys.argv[1])
cfg = data.get("Config") or {}

def emit(name, value):
    if isinstance(value, (dict, list)):
        print(f"{name}={json.dumps(value, sort_keys=True)}")
        return
    if value is None:
        print(f"{name}=null")
        return
    if value == "":
        print(f"{name}=null")
        return
    print(f"{name}={value}")

emit("id", data.get("Id"))
emit("repoTags", data.get("RepoTags"))
emit("created", data.get("Created"))
emit("os", data.get("Os"))
emit("architecture", data.get("Architecture"))
emit("variant", data.get("Variant") or "N/A")
emit("entrypoint", cfg.get("Entrypoint"))
emit("cmd", cfg.get("Cmd"))
emit("user", cfg.get("User"))
emit("workingDir", cfg.get("WorkingDir"))
emit("exposedPorts", cfg.get("ExposedPorts"))
emit("volumes", cfg.get("Volumes"))
emit("healthcheck", cfg.get("Healthcheck"))
emit("labels", cfg.get("Labels"))
PY
    return $?
  fi

  if command -v jq >/dev/null 2>&1; then
    printf '%s\n' "$inspect_json" | jq -r '
      def j($v):
        if $v == null or $v == "" then "null"
        elif ($v | type) == "array" or ($v | type) == "object" then ($v | tojson)
        else ($v | tostring)
        end;
      "id=\(j(.Id))",
      "repoTags=\(j(.RepoTags))",
      "created=\(j(.Created))",
      "os=\(j(.Os))",
      "architecture=\(j(.Architecture))",
      "variant=\(if .Variant == null or .Variant == "" then "N/A" else .Variant end)",
      "entrypoint=\(j(.Config.Entrypoint))",
      "cmd=\(j(.Config.Cmd))",
      "user=\(j(.Config.User))",
      "workingDir=\(j(.Config.WorkingDir))",
      "exposedPorts=\(j(.Config.ExposedPorts))",
      "volumes=\(j(.Config.Volumes))",
      "healthcheck=\(j(.Config.Healthcheck))",
      "labels=\(j(.Config.Labels))"'
    return $?
  fi

  log_warn "Neither python3 nor jq available; writing raw docker inspect JSON."
  printf '%s\n' "$inspect_json"
}

run_self_test() {
  log_info "Running self-tests for parser and helpers..."
  local tmp
  tmp="$(mktemp)"
  cat >"$tmp" <<'EOF'
###BEGIN:OS_RELEASE###
NAME=Debian
VERSION=12
###END:OS_RELEASE###
###BEGIN:PYTHON_BINARIES###
python3	/usr/bin/python3	Python 3.11.2
###END:PYTHON_BINARIES###
EOF

  local extracted
  extracted="$(extract_section "OS_RELEASE" "$tmp")"
  if [ "$extracted" != $'NAME=Debian\nVERSION=12' ]; then
    log_error "Self-test failed: OS_RELEASE extraction mismatch"
    rm -f "$tmp"
    return 1
  fi

  extracted="$(extract_section "PYTHON_BINARIES" "$tmp")"
  if [ "$extracted" != $'python3\t/usr/bin/python3\tPython 3.11.2' ]; then
    log_error "Self-test failed: PYTHON_BINARIES extraction mismatch"
    rm -f "$tmp"
    return 1
  fi

  rm -f "$tmp"
  log_info "Self-tests passed."
  return 0
}

main() {
  local image_ref=""
  local output_dir="$DEFAULT_OUTPUT_DIR"
  local skip_pull="false"
  local generate_json="true"
  local debug="false"
  local probe_timeout_seconds="$DEFAULT_PROBE_TIMEOUT_SECONDS"
  local max_report_bytes="$DEFAULT_MAX_REPORT_BYTES"

  while [ "$#" -gt 0 ]; do
    case "$1" in
      -i|--image)
        if [ "$#" -lt 2 ]; then
          log_error "Missing value for $1"
          usage
          return 2
        fi
        image_ref="$2"
        shift 2
        ;;
      -o|--output-dir)
        if [ "$#" -lt 2 ]; then
          log_error "Missing value for $1"
          usage
          return 2
        fi
        output_dir="$2"
        shift 2
        ;;
      --skip-pull)
        skip_pull="true"
        shift
        ;;
      --no-json)
        generate_json="false"
        shift
        ;;
      --debug)
        debug="true"
        shift
        ;;
      --probe-timeout)
        if [ "$#" -lt 2 ]; then
          log_error "Missing value for $1"
          usage
          return 2
        fi
        probe_timeout_seconds="$2"
        shift 2
        ;;
      --max-report-bytes)
        if [ "$#" -lt 2 ]; then
          log_error "Missing value for $1"
          usage
          return 2
        fi
        max_report_bytes="$2"
        shift 2
        ;;
      --self-test)
        run_self_test
        return $?
        ;;
      -h|--help)
        usage
        return 0
        ;;
      *)
        log_error "Unknown argument: $1"
        usage
        return 2
        ;;
    esac
  done

  if [ "$debug" = "true" ]; then
    set -x
  fi
  DEBUG_MODE="$debug"

  validate_positive_integer "$probe_timeout_seconds" "probe timeout seconds" || return 2
  validate_positive_integer "$max_report_bytes" "max report bytes" || return 2

  if [ "$probe_timeout_seconds" -eq 0 ]; then
    log_warn "Probe timeout set to 0 seconds. Container probe commands may fail immediately when timeout is available."
  fi

  log_debug "Using probe timeout seconds: $probe_timeout_seconds"
  log_debug "Using max report bytes: $max_report_bytes"

  if [ -z "$image_ref" ]; then
    if [ -t 0 ]; then
      printf 'Enter Docker image reference (example: postgres:16.11): ' >&2
      IFS= read -r image_ref
      if [ -z "$image_ref" ]; then
        log_error "Image reference cannot be empty."
        return 1
      fi
    else
      log_error "No image reference provided. Use --image in non-interactive mode."
      return 1
    fi
  fi

  validate_image_reference "$image_ref" || return 2

  docker_preflight || return 1

  ensure_output_dir_writable "$output_dir" || return 1

  if [ "$skip_pull" != "true" ]; then
    log_info "Pulling image: $image_ref"
    if ! docker pull "$image_ref"; then
      log_error "Failed to pull image: $image_ref"
      return 1
    fi
  else
    log_info "Skipping pull. Using local image cache for: $image_ref"
  fi

  local inspect_file
  local raw_file
  local stderr_file
  local ts
  local safe_image
  local txt_report
  local json_report

  ts="$(date -u +"%Y-%m-%dT%H-%M-%SZ")"
  safe_image="$(safe_filename_fragment "$image_ref")"
  inspect_file="$output_dir/inventory_${safe_image}_${ts}.inspect.txt"
  raw_file="$output_dir/inventory_${safe_image}_${ts}.probe.raw.txt"
  stderr_file="$output_dir/inventory_${safe_image}_${ts}.probe.stderr.txt"
  txt_report="$output_dir/inventory_${safe_image}_${ts}.txt"
  json_report="$output_dir/inventory_${safe_image}_${ts}.json"

  : >"$stderr_file"
  set_report_permissions "$stderr_file"

  log_info "Inspecting image metadata..."
  if ! inspect_image_summary "$image_ref" >"$inspect_file"; then
    log_warn "Image metadata inspection failed. Continuing with probe-only report."
    {
      echo "inspect_error=failed"
      echo "image=$image_ref"
    } >"$inspect_file"
  fi
  set_report_permissions "$inspect_file"

  local probe_script
  probe_script="$(build_probe_script)"

  local shell_used=""
  local candidate
  for candidate in /bin/sh /bin/bash /busybox/sh sh bash; do
    log_info "Trying probe shell: $candidate"
    if run_probe_with_shell "$image_ref" "$candidate" "$probe_script" "$raw_file" "$probe_timeout_seconds"; then
      shell_used="$candidate"
      break
    fi
    cat "${raw_file}.stderr" >>"$stderr_file" || true
    echo "---" >>"$stderr_file"
  done

  if [ -z "$shell_used" ]; then
    log_error "Probe failed for all shell candidates."
    log_error "Target image may be distroless/scratch or shell-less."
    log_error "See probe stderr log: $stderr_file"
    return 1
  fi

  if ! grep -q '^###BEGIN:' "$raw_file"; then
    log_error "Probe output did not contain expected section markers."
    log_error "Inspect raw probe output: $raw_file"
    return 1
  fi

  truncate_if_oversized "$raw_file" "$max_report_bytes" || return 1
  set_report_permissions "$raw_file"

  write_text_report "$image_ref" "$shell_used" "$inspect_file" "$raw_file" "$txt_report"
  set_report_permissions "$txt_report"

  if [ "$generate_json" = "true" ]; then
    if generate_json_report "$image_ref" "$shell_used" "$inspect_file" "$raw_file" "$json_report"; then
      set_report_permissions "$json_report"
      log_info "JSON report written: $json_report"
    else
      log_warn "JSON report was not generated."
    fi
  fi

  cat "$txt_report"
  echo
  log_info "Text report written: $txt_report"
  log_info "Raw probe output: $raw_file"
  log_info "Probe stderr log: $stderr_file"
  log_info "Image inspect summary: $inspect_file"
}

main "$@"
