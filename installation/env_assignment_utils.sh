#!/usr/bin/env bash

_env_assignment_is_name_start_char() {
    case "${1-}" in
        [A-Za-z_]) return 0 ;;
        *) return 1 ;;
    esac
}


_env_assignment_is_name_char() {
    case "${1-}" in
        [A-Za-z0-9_]) return 0 ;;
        *) return 1 ;;
    esac
}


_env_assignment_find_next_reference() {
    local input="${1-}"
    local input_length="${#input}"
    local index=0
    local name_start=0
    local name_end=0
    local token_length=0
    local name_length=0
    local next_char=""

    ENV_ASSIGNMENT_REF_TOKEN=""
    ENV_ASSIGNMENT_REF_NAME=""

    while [ "${index}" -lt "${input_length}" ]; do
        if [ "${input:index:1}" != "$" ]; then
            index=$((index + 1))
            continue
        fi

        next_char="${input:index+1:1}"
        if [ "${next_char}" = "{" ]; then
            name_start=$((index + 2))
            if [ "${name_start}" -ge "${input_length}" ] || \
                ! _env_assignment_is_name_start_char "${input:name_start:1}"; then
                index=$((index + 1))
                continue
            fi

            name_end=$((name_start + 1))
            while [ "${name_end}" -lt "${input_length}" ] && \
                _env_assignment_is_name_char "${input:name_end:1}"; do
                name_end=$((name_end + 1))
            done

            if [ "${name_end}" -lt "${input_length}" ] && [ "${input:name_end:1}" = "}" ]; then
                token_length=$((name_end - index + 1))
                name_length=$((name_end - name_start))
                ENV_ASSIGNMENT_REF_TOKEN="${input:index:token_length}"
                ENV_ASSIGNMENT_REF_NAME="${input:name_start:name_length}"
                return 0
            fi
        elif _env_assignment_is_name_start_char "${next_char}"; then
            name_start=$((index + 1))
            name_end=$((name_start + 1))
            while [ "${name_end}" -lt "${input_length}" ] && \
                _env_assignment_is_name_char "${input:name_end:1}"; do
                name_end=$((name_end + 1))
            done

            token_length=$((name_end - index))
            name_length=$((name_end - name_start))
            ENV_ASSIGNMENT_REF_TOKEN="${input:index:token_length}"
            ENV_ASSIGNMENT_REF_NAME="${input:name_start:name_length}"
            return 0
        fi

        index=$((index + 1))
    done

    return 1
}


resolve_env_assignment_value() {
    local raw_value="${1-}"
    local value="${raw_value}"
    local quote_mode="unquoted"
    local token=""
    local ref_name=""
    local ref_value=""
    local expansion_count=0
    local max_expansions=1024
    local command_substitution_marker="\$("
    local legacy_command_substitution_marker="\`"
    local arithmetic_expansion_marker="\$["
    local parameter_expansion_marker="\${"

    if [ "${#value}" -ge 2 ] && [ "${value:0:1}" = '"' ] && [ "${value: -1}" = '"' ]; then
        value="${value:1:${#value}-2}"
        quote_mode="double"
    elif [ "${#value}" -ge 2 ] && [ "${value:0:1}" = "'" ] && [ "${value: -1}" = "'" ]; then
        value="${value:1:${#value}-2}"
        quote_mode="single"
    fi

    case "${value}" in
        *"${command_substitution_marker}"*|*"${legacy_command_substitution_marker}"*|*"${arithmetic_expansion_marker}"*)
            echo "ERROR: Unsupported shell expression in env value." >&2
            return 1
            ;;
    esac

    if [ "${quote_mode}" != "single" ]; then
        while _env_assignment_find_next_reference "${value}"; do
            expansion_count=$((expansion_count + 1))
            if [ "${expansion_count}" -gt "${max_expansions}" ]; then
                echo "ERROR: Too many nested env references in env value." >&2
                return 1
            fi
            token="${ENV_ASSIGNMENT_REF_TOKEN}"
            ref_name="${ENV_ASSIGNMENT_REF_NAME}"
            ref_value="${!ref_name-}"
            value="${value/"${token}"/${ref_value}}"
        done

        case "${value}" in
            *"${parameter_expansion_marker}"*)
                echo "ERROR: Unsupported parameter expansion in env value." >&2
                return 1
                ;;
        esac
    fi

    printf '%s' "${value}"
}
