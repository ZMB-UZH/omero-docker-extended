#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CLEANUP_SCRIPT="${REPO_ROOT}/installation/cleanup_build_containers.sh"
TMP_BASE="$(mktemp -d)"
PASS=0
FAIL=0

cleanup() {
    rm -rf "${TMP_BASE}"
}
trap cleanup EXIT

create_mock_docker() {
    local test_dir="$1"
    local mock_path="${test_dir}/docker"

    cat > "${mock_path}" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail

MOCK_DIR="$(dirname "$0")"
echo "$*" >> "${MOCK_DIR}/docker_calls.log"

case "$1" in
    buildx)
        case "${2:-}" in
            inspect)
                exit 1
                ;;
            use|stop|rm)
                exit 0
                ;;
        esac
        ;;
    container)
        case "${2:-}" in
            inspect)
                shift 2
                format=""
                target=""
                while [[ $# -gt 0 ]]; do
                    case "$1" in
                        -f)
                            shift
                            format="$1"
                            shift
                            ;;
                        *)
                            target="$1"
                            shift
                            ;;
                    esac
                done
                while IFS='|' read -r name cid running; do
                    [[ -z "${name}" ]] && continue
                    if [[ "${target}" == "${cid}" || "${target}" == "${name}" ]]; then
                        if [[ "${format}" == *".State.Status"* ]]; then
                            if [[ "${running}" == "true" ]]; then
                                echo "running"
                            else
                                echo "exited"
                            fi
                        elif [[ "${format}" == *".Image"* ]]; then
                            echo "image-for-${name}"
                        fi
                        exit 0
                    fi
                done < "${MOCK_DIR}/containers.conf"
                exit 1
                ;;
        esac
        ;;
    image)
        case "${2:-}" in
            inspect)
                shift 2
                target="${1:-}"
                while IFS='|' read -r image iid; do
                    [[ -z "${image}" ]] && continue
                    if [[ "${target}" == "${image}" || "${target}" == "${iid}" ]]; then
                        exit 0
                    fi
                done < "${MOCK_DIR}/images.conf"
                exit 1
                ;;
            prune)
                exit 0
                ;;
        esac
        ;;
    volume)
        case "${2:-}" in
            ls|rm)
                exit 0
                ;;
        esac
        ;;
    ps)
        shift
        filter_name=""
        output_format=""
        while [[ $# -gt 0 ]]; do
            case "$1" in
                -aq|-a)
                    shift
                    ;;
                --format)
                    shift
                    output_format="$1"
                    shift
                    ;;
                --filter)
                    shift
                    filter_name="${1#name=}"
                    shift
                    ;;
                *)
                    shift
                    ;;
            esac
        done
        filter_clean="${filter_name#^}"
        filter_clean="${filter_clean%$}"
        filter_clean="${filter_clean#/}"
        while IFS='|' read -r name cid running; do
            [[ -z "${name}" ]] && continue
            if [[ -z "${filter_name}" ]]; then
                matched=1
            else
                case "${name}" in
                    *"${filter_clean}"*) matched=1 ;;
                    *) matched=0 ;;
                esac
            fi
            if [[ "${matched}" = "1" ]]; then
                if [[ -n "${output_format}" ]]; then
                    echo "${cid} ${name}"
                else
                    echo "${cid}"
                fi
            fi
        done < "${MOCK_DIR}/containers.conf"
        ;;
    inspect)
        shift
        format=""
        target=""
        while [[ $# -gt 0 ]]; do
            case "$1" in
                -f)
                    shift
                    format="$1"
                    shift
                    ;;
                *)
                    target="$1"
                    shift
                    ;;
            esac
        done
        while IFS='|' read -r name cid running; do
            [[ -z "${name}" ]] && continue
            if [[ "${target}" == "${cid}" || "${target}" == "${name}" ]]; then
                if [[ "${format}" == *"State.Running"* ]]; then
                    echo "${running}"
                elif [[ "${format}" == *".Name"* ]]; then
                    echo "/${name}"
                fi
                exit 0
            fi
        done < "${MOCK_DIR}/containers.conf"
        exit 1
        ;;
    stop|rm|rmi)
        exit 0
        ;;
    images)
        shift
        if [[ "${1:-}" == "-q" ]]; then
            shift
            target="${1:-}"
            while IFS='|' read -r image iid; do
                [[ -z "${image}" ]] && continue
                if [[ "${target}" == "${image}" ]]; then
                    echo "${iid}"
                    exit 0
                fi
            done < "${MOCK_DIR}/images.conf"
            exit 0
        fi
        if [[ "${1:-}" == "--format" ]]; then
            while IFS='|' read -r image iid; do
                [[ -z "${image}" ]] && continue
                echo "${image}"
            done < "${MOCK_DIR}/images.conf"
            exit 0
        fi
        ;;
esac

exit 0
MOCK

    chmod +x "${mock_path}"
    touch "${test_dir}/docker_calls.log"
}

assert_contains() {
    local output="$1"
    local expected="$2"

    if [[ "${output}" != *"${expected}"* ]]; then
        echo "Expected to find: ${expected}"
        echo "Actual output:"
        echo "${output}"
        return 1
    fi
}

assert_log_has() {
    local log="$1"
    local expected="$2"

    if ! grep -qF "${expected}" "${log}"; then
        echo "Expected log to contain: ${expected}"
        echo "Actual log:"
        cat "${log}"
        return 1
    fi
}

assert_log_not_has() {
    local log="$1"
    local expected="$2"

    if grep -qF "${expected}" "${log}"; then
        echo "Expected log NOT to contain: ${expected}"
        echo "Actual log:"
        cat "${log}"
        return 1
    fi
}

run_case() {
    local name="$1"
    local setup_fn="$2"
    local validate_fn="$3"

    local dir="${TMP_BASE}/${name}"
    mkdir -p "${dir}"
    : > "${dir}/containers.conf"
    : > "${dir}/images.conf"
    create_mock_docker "${dir}"

    "${setup_fn}" "${dir}"

    local output
    local args=()
    if [[ -n "${4:-}" ]]; then
        args+=("$4")
    fi
    output="$(PATH="${dir}:${PATH}" bash "${CLEANUP_SCRIPT}" "${args[@]}" 2>&1 || true)"

    if "${validate_fn}" "${dir}" "${output}"; then
        echo "PASS: ${name}"
        PASS=$((PASS + 1))
    else
        echo "FAIL: ${name}"
        FAIL=$((FAIL + 1))
    fi
}

setup_full() {
    local dir="$1"
    cat > "${dir}/containers.conf" <<'EOF2'
redis-sysctl-init|rid1|false
buildx_buildkit_default|bid1|true
EOF2
    cat > "${dir}/images.conf" <<'EOF2'
redis-sysctl-init:custom|img1
moby/buildkit:buildx-stable-1|img2
EOF2
}

validate_full() {
    local dir="$1"
    local output="$2"
    assert_contains "${output}" "Cleaning up probe containers..." &&
    assert_contains "${output}" "Cleaning container: redis-sysctl-init" &&
    assert_contains "${output}" "Removing docker image id: image-for-redis-sysctl-init (from redis-sysctl-init)" &&
    assert_contains "${output}" "Removing one-shot image: redis-sysctl-init:custom" &&
    assert_contains "${output}" "Cleanup complete." &&
    assert_log_has "${dir}/docker_calls.log" "stop -t 20 redis-sysctl-init" &&
    assert_log_has "${dir}/docker_calls.log" "rm -f redis-sysctl-init" &&
    assert_log_has "${dir}/docker_calls.log" "rmi -f redis-sysctl-init:custom"
}


setup_compose_redis_name() {
    local dir="$1"
    cat > "${dir}/containers.conf" <<'EOF2'
omero-redis-sysctl-init-1|rid9|true
EOF2
    cat > "${dir}/images.conf" <<'EOF2'
redis-sysctl-init:custom|img1
EOF2
}

validate_compose_redis_name() {
    local dir="$1"
    local output="$2"
    assert_contains "${output}" "Cleaning up probe containers..." &&
    assert_contains "${output}" "Removing one-shot image: redis-sysctl-init:custom" &&
    assert_contains "${output}" "Cleanup complete." &&
    assert_log_not_has "${dir}/docker_calls.log" "stop -t 20 omero-redis-sysctl-init-1" &&
    assert_log_not_has "${dir}/docker_calls.log" "rm -f omero-redis-sysctl-init-1"
}

setup_empty() { :; }
validate_empty() {
    local dir="$1"
    local output="$2"
    assert_contains "${output}" "Cleaning up probe containers..." &&
    assert_contains "${output}" "Cleanup complete."
}

run_case "empty" setup_empty validate_empty
run_case "full" setup_full validate_full
run_case "compose_redis_name" setup_compose_redis_name validate_compose_redis_name

echo "Results: ${PASS} passed, ${FAIL} failed"
[[ ${FAIL} -eq 0 ]]
