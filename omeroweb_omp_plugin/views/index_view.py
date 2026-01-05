from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.utils.html import escape
from django.utils.safestring import mark_safe
from django.views.decorators.csrf import csrf_exempt
from omeroweb.decorators import login_required
import json
import logging
import re
from collections import Counter
from ..services.core import (
    get_id,
    get_text,
    collect_images_by_dataset_sorted,
    collect_images_by_selected_datasets,
    collect_dataset_summaries,
    parse_filename,
)
from ..services.ai_assist import AiAssistError, generate_ai_regex
from ..services.data_store import AiCredentialStoreError, get_ai_credential
from ..services.rate_limit import build_rate_limit_message, check_major_action_rate_limit
from ..constants import DEFAULT_VARIABLE_NAMES, MAX_PARSED_VARIABLES
logger = logging.getLogger(__name__)


def _extract_base_name(filename):
    match = re.search(r"\[(.+?)\]", filename)
    if match:
        return match.group(1)
    sanitized = filename.replace("\t", " ")
    match = re.search(r".*\s+(.+?)\s*$", sanitized)
    if match:
        return match.group(1).rsplit(".", 1)[0]
    return filename.rsplit(".", 1)[0]


def _regex_for_separators(separators, label_tokens=None):
    tokens = []
    has_whitespace = False
    for char in separators:
        if char.isspace():
            has_whitespace = True
        elif char == "-":
            tokens.append(r"-(?![A-Za-z]+\d)")
        else:
            tokens.append(re.escape(char))
    if has_whitespace:
        tokens.append(r"\s")
    if not tokens:
        return r"(?<=\D)(?=\d)|(?<=\d)(?=\D)"
    sep_pattern = "(?:" + "|".join(tokens) + ")+"
    if not label_tokens:
        return sep_pattern
    label_pattern = "(?:" + "|".join(re.escape(token) for token in label_tokens) + ")"
    return (
        "(?:"
        + sep_pattern
        + label_pattern
        + sep_pattern
        + "|"
        + sep_pattern
        + "|^"
        + label_pattern
        + sep_pattern
        + "|"
        + sep_pattern
        + label_pattern
        + "$)"
    )


def _suggest_separator_regex(filenames):
    counts = Counter()
    token_counts = Counter()
    for name in filenames:
        base = _extract_base_name(name)
        for char in base:
            if not char.isalnum():
                counts[char] += 1
        for token in re.findall(r"[A-Za-z0-9]+", base):
            if token.isalpha():
                token_counts[token] += 1
    if not counts:
        return _regex_for_separators([])
    top = counts.most_common()
    max_count = top[0][1]
    candidates = [char for char, count in top if count >= max_count * 0.4]
    label_min_count = max(2, int(len(filenames) * 0.4))
    label_candidates = [
        token
        for token, count in token_counts.items()
        if count >= label_min_count and 1 < len(token) <= 4
    ]
    return _regex_for_separators(candidates[:5], label_candidates[:6])


def _current_username(request, conn):
    try:
        user = conn.getUser()
        if user:
            return user.getName()
    except Exception:
        pass

    try:
        return request.user.username
    except Exception:
        return None


@csrf_exempt
@login_required()
def index(request, conn=None, url=None, **kwargs):
    """
    OMP filename+metadata harverster UI
    """

    try:
        # ----------------------------------------------------
        # Load projects
        # ----------------------------------------------------
        projects = []
        try:
            for proj in conn.listProjects():
                pid = get_id(proj)
                pname = get_text(proj.getName())
                projects.append((str(pid), pname))
        except Exception as e:
            logger.exception("Error listing projects: %s", e)

        # ----------------------------------------------------
        # LIST DATASETS - NO RATE LIMIT (read-only, just listing)
        # ----------------------------------------------------
        if request.method == "POST" and request.POST.get("action") == "list_datasets":
            project_id = request.POST.get("project")
            if not project_id:
                return JsonResponse({"error": "Select a project first."}, status=400)

            # NO RATE LIMIT - just listing datasets
            dataset_rows = collect_dataset_summaries(conn, project_id)
            return JsonResponse({"datasets": dataset_rows})

        if request.method == "POST" and request.POST.get("action") == "ai_regex":
            project_id = request.POST.get("project")
            selected_dataset_ids_raw = request.POST.get("selected_datasets", "")
            provider = (request.POST.get("provider") or "local").strip().lower()

            if not project_id:
                return JsonResponse({"error": "Select a project first."}, status=400)
            if not selected_dataset_ids_raw.strip():
                return JsonResponse({"error": "Please select one or more datasets."}, status=400)

            selected_dataset_ids = []
            for ds_id in selected_dataset_ids_raw.split(","):
                ds_id = ds_id.strip()
                if not ds_id:
                    continue
                try:
                    selected_dataset_ids.append(int(ds_id))
                except ValueError:
                    continue

            if not selected_dataset_ids:
                return JsonResponse({"error": "Please select one or more datasets."}, status=400)

            allowed, remaining = check_major_action_rate_limit(request, conn)
            if not allowed:
                return JsonResponse({"error": build_rate_limit_message(remaining)}, status=429)

            ds_list = collect_images_by_selected_datasets(
                conn,
                project_id,
                selected_dataset_ids,
                limit=200,
            )
            filenames = []
            for _, images in ds_list:
                for img in images:
                    try:
                        filenames.append(get_text(img.getName()))
                    except Exception:
                        continue

            if not filenames:
                return JsonResponse({"error": "No filenames available in the selected datasets."}, status=400)

            if provider == "local":
                regex = _suggest_separator_regex(filenames)
                return JsonResponse({"regex": regex})

            username = _current_username(request, conn)
            if not username:
                return JsonResponse({"error": "Unable to determine username."}, status=400)

            try:
                api_key = (get_ai_credential(username, provider) or "").strip()
            except AiCredentialStoreError as e:
                return JsonResponse({"error": str(e)}, status=500)

            if not api_key:
                return JsonResponse({"error": "Please add an API key for this provider in Settings."}, status=400)

            try:
                regex = generate_ai_regex(provider, api_key, filenames)
            except AiAssistError as e:
                return JsonResponse({"error": str(e)}, status=400)
            except Exception as e:
                logger.exception("AI regex provider failure: %s", e)
                return JsonResponse({"error": "Unable to process filenames."}, status=500)

            return JsonResponse({"regex": regex})

        # ----------------------------------------------------
        # PREVIEW MODE - WITH RATE LIMIT (major action)
        # ----------------------------------------------------
        if request.method == "POST" and request.POST.get("action") != "save_job":
            project_id = request.POST.get("project")
            raw_seps = request.POST.get("separator", "_")
            separator_mode = request.POST.get("separator_mode", "chars")
            selected_dataset_ids_raw = request.POST.get("selected_datasets", "")

            if not project_id:
                return render(
                    request,
                    "index.html",
                    {
                        "projects": projects,
                        "error_message": "Select a project first.",
                    },
                )

            if not raw_seps or not raw_seps.strip():
                return render(
                    request,
                    "index.html",
                    {
                        "projects": projects,
                        "error_message": "The input field for filename parsing cannot be empty.",
                    },
                )
            if not selected_dataset_ids_raw.strip():
                return render(
                    request,
                    "index.html",
                    {
                        "projects": projects,
                        "error_message": "Please select one or more datasets.",
                    },
                )

            try:
                prj = conn.getObject("Project", int(project_id))
                if prj:
                    project_label = f"{get_text(prj.getName())} (ID {project_id})"
                else:
                    project_label = f"ID {project_id}"
            except Exception:
                project_label = f"ID {project_id}"

            if separator_mode == "regex":
                sep_pattern = raw_seps
                try:
                    re.compile(sep_pattern)
                except re.error as e:
                    return HttpResponse(
                        "<h2 style='color:red;'>Invalid regex pattern.</h2>"
                        f"<p>{e}</p>"
                        "<a href='.'>Back</a>"
                    )
            else:
                sep_pattern = f"(?:{'|'.join(re.escape(c) for c in raw_seps)})+"

            selected_dataset_ids = []
            if selected_dataset_ids_raw:
                for ds_id in selected_dataset_ids_raw.split(","):
                    ds_id = ds_id.strip()
                    if not ds_id:
                        continue
                    try:
                        selected_dataset_ids.append(int(ds_id))
                    except ValueError:
                        continue

            if not selected_dataset_ids:
                return render(
                    request,
                    "index.html",
                    {
                        "projects": projects,
                        "error_message": "Please select one or more datasets.",
                    },
                )

            # RATE LIMIT - preview is a major action (loads lots of data)
            allowed, remaining = check_major_action_rate_limit(request, conn)
            if not allowed:
                return render(
                    request,
                    "index.html",
                    {
                        "projects": projects,
                        "error_message": build_rate_limit_message(remaining),
                    },
                )

            ds_list = collect_images_by_selected_datasets(
                conn,
                project_id,
                selected_dataset_ids,
                limit=50,
            )

            total_images = sum(len(images) for _, images in ds_list)
            if total_images == 0:
                return render(
                    request,
                    "index.html",
                    {
                        "projects": projects,
                        "error_message": "No data to process is available in the selected dataset(s).",
                    },
                )

            preview_rows = []
            max_vars = 0
            max_vars_uncapped = 0  # Track actual max before capping

            for ds, images in ds_list:
                ds_name = get_text(ds.getName())
                ds_id = get_id(ds)
                ds_label = f"{ds_name} [{ds_id}]"

                for img in images:
                    try:
                        iid = int(get_id(img))
                        fname = get_text(img.getName())
                        parts = parse_filename(fname, sep_pattern)
                        
                        # Track actual max before capping
                        max_vars_uncapped = max(max_vars_uncapped, len(parts))
                        
                        # Cap at MAX_PARSED_VARIABLES
                        parts_capped = parts[:MAX_PARSED_VARIABLES]
                        max_vars = max(max_vars, len(parts_capped))
                        
                        vars_dict = {f"Var{i+1}": p for i, p in enumerate(parts_capped)}
                        preview_rows.append((ds_label, iid, fname, vars_dict))
                    except Exception:
                        continue

            if max_vars == 0:
                max_vars = 1

            # Check if any filenames exceeded the limit
            vars_limit_exceeded = max_vars_uncapped > MAX_PARSED_VARIABLES

            preview_rows_payload = []
            for ds_label, img_id, fname, vars_dict in preview_rows:
                kv = " | ".join(
                    f"{k[3:]}='{escape(v)}'" for k, v in vars_dict.items()
                )
                preview_rows_payload.append(
                    {
                        "ds_label": ds_label,
                        "img_id": img_id,
                        "filename": fname,
                        "vars_display": mark_safe(kv),
                    }
                )

            context = {
                "project_label": project_label,
                "separator_mode": separator_mode,
                "raw_seps": raw_seps,
                "preview_count": len(preview_rows_payload),
                "preview_rows": preview_rows_payload,
                "max_vars": max_vars,
                "var_range": range(1, max_vars + 1),
                "project_id": project_id,
                "default_vars_json": json.dumps(DEFAULT_VARIABLE_NAMES),
                "max_parsed_variables": MAX_PARSED_VARIABLES,
                "vars_limit_exceeded": vars_limit_exceeded,
                "max_vars_uncapped": max_vars_uncapped,
            }

            return render(
                request,
                "preview.html",
                context,
            )

        # ----------------------------------------------------
        # LANDING PAGE
        # ----------------------------------------------------
        return render(
            request,
            "index.html",
            {"projects": projects},
        )

    except Exception as e:
        logger.exception("Unhandled error in index(): %s", e)
        return HttpResponse(f"<h2>Error: {e}</h2>")
