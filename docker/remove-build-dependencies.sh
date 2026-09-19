#!/bin/bash
set -euo pipefail

# Keep the application's virtualenv tooling. Only inherited OS build tools and
# their unused cryptography dependency are removed from the finished image.
readonly candidates=(
    ansible-core
    python3-cryptography
    python3-pip
    python3.11-pip
    python3.12-pip
)
inventory="$(rpm -qa --qf '%{NAME}\n')"
installed=()
for package in "${candidates[@]}"; do
    case $'\n'"${inventory}"$'\n' in
        *$'\n'"${package}"$'\n'*) installed+=("${package}") ;;
    esac
done

if [[ ${#installed[@]} -eq 0 ]]; then
    exit 0
fi

# RPM's transaction test rejects any remaining consumer. Unlike dependency-
# resolving removal, this cannot silently remove an application prerequisite.
rpm -e --test -- "${installed[@]}"
rpm -e -- "${installed[@]}"
inventory="$(rpm -qa --qf '%{NAME}\n')"
for package in "${installed[@]}"; do
    case $'\n'"${inventory}"$'\n' in
        *$'\n'"${package}"$'\n'*)
            printf 'ERROR: Build dependency remains installed: %s\n' "${package}" >&2
            exit 1
            ;;
    esac
done
