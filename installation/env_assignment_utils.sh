#!/usr/bin/env bash

resolve_env_assignment_value() {
    local raw_value="${1-}"
    local value="${raw_value}"
    local quote_mode="unquoted"
    local token=""
    local ref_name=""
    local ref_value=""
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
        while [[ "${value}" =~ (\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)) ]]; do
            token="${BASH_REMATCH[1]}"
            ref_name="${BASH_REMATCH[2]}"
            if [ -z "${ref_name}" ]; then
                ref_name="${BASH_REMATCH[3]}"
            fi
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
