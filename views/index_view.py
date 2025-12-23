from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.utils.html import escape
from django.utils.safestring import mark_safe
from django.views.decorators.csrf import csrf_exempt
from omeroweb.decorators import login_required
import json
import logging
import re
from ..services.core import (
    get_id,
    get_text,
    collect_images_by_dataset_sorted,
    collect_images_by_selected_datasets,
    collect_dataset_summaries,
    parse_filename,
)
from ..services.rate_limit import build_rate_limit_message, check_major_action_rate_limit
from ..constants import DEFAULT_VARIABLE_NAMES
logger = logging.getLogger(__name__)


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
        # PREVIEW MODE
        # ----------------------------------------------------
        if request.method == "POST" and request.POST.get("action") == "list_datasets":
            project_id = request.POST.get("project")
            if not project_id:
                return JsonResponse({"error": "Select a project first."}, status=400)

            allowed, remaining = check_major_action_rate_limit(request)
            if not allowed:
                return JsonResponse(
                    {"error": build_rate_limit_message(remaining)},
                    status=429,
                )

            dataset_rows = collect_dataset_summaries(conn, project_id)
            return JsonResponse({"datasets": dataset_rows})

        if request.method == "POST" and request.POST.get("action") != "save_job":
            project_id = request.POST.get("project")
            raw_seps = request.POST.get("separator", "_")
            separator_mode = request.POST.get("separator_mode", "chars")
            selected_dataset_ids_raw = request.POST.get("selected_datasets", "")

            if not project_id:
                return render(
                    request,
                    "omeroweb_omp_plugin/index.html",
                    {
                        "projects": projects,
                        "error_message": "Select a project first.",
                    },
                )

            if not raw_seps or not raw_seps.strip():
                return render(
                    request,
                    "omeroweb_omp_plugin/index.html",
                    {
                        "projects": projects,
                        "error_message": "The input field for filename parsing cannot be empty.",
                    },
                )
            if not selected_dataset_ids_raw.strip():
                return render(
                    request,
                    "omeroweb_omp_plugin/index.html",
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
                    "omeroweb_omp_plugin/index.html",
                    {
                        "projects": projects,
                        "error_message": "Please select one or more datasets.",
                    },
                )

            allowed, remaining = check_major_action_rate_limit(request)
            if not allowed:
                return render(
                    request,
                    "omeroweb_omp_plugin/index.html",
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
                    "omeroweb_omp_plugin/index.html",
                    {
                        "projects": projects,
                        "error_message": "No data to process is available in the selected dataset(s).",
                    },
                )

            preview_rows = []
            max_vars = 0

            for ds, images in ds_list:
                ds_name = get_text(ds.getName())
                ds_id = get_id(ds)
                ds_label = f"{ds_name} [{ds_id}]"

                for img in images:
                    try:
                        iid = int(get_id(img))
                        fname = get_text(img.getName())
                        parts = parse_filename(fname, sep_pattern)
                        max_vars = max(max_vars, len(parts))
                        vars_dict = {f"Var{i+1}": p for i, p in enumerate(parts)}
                        preview_rows.append((ds_label, iid, fname, vars_dict))
                    except Exception:
                        continue

            if max_vars == 0:
                max_vars = 1

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
            }

            return render(
                request,
                "omeroweb_omp_plugin/preview.html",
                context,
            )

        # ----------------------------------------------------
        # LANDING PAGE
        # ----------------------------------------------------
        return render(
            request,
            "omeroweb_omp_plugin/index.html",
            {"projects": projects},
        )

    except Exception as e:
        logger.exception("Unhandled error in index(): %s", e)
        return HttpResponse(f"<h2>Error: {e}</h2>")
