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
from ..services.ai_assist import AiAssistError, generate_ai_regex, generate_ai_parsed_values
from ..services.data_store import AiCredentialStoreError, get_ai_credential
from ..services.rate_limit import build_rate_limit_message, check_major_action_rate_limit
from ..services.filename_utils import suggest_separator_regex
from ..views.utils import current_username
from ..strings import errors, messages
from ..constants import (
    CHUNK_SIZE,
    DEFAULT_VARIABLE_NAMES,
    MAX_PARSED_VARIABLES,
    MAX_VARIABLE_SET_ENTRIES,
)
logger = logging.getLogger(__name__)


def _suggest_separator_regex(filenames):
    return suggest_separator_regex(filenames)


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
                return JsonResponse({"error": errors.select_project_first()}, status=400)

            # NO RATE LIMIT - just listing datasets
            dataset_rows = collect_dataset_summaries(conn, project_id)
            dataset_rows = sorted(
                dataset_rows,
                key=lambda row: (row.get("name") or "").casefold(),
            )
            return JsonResponse({"datasets": dataset_rows})

        if request.method == "POST" and request.POST.get("action") == "ai_parse":
            project_id = request.POST.get("project")
            selected_dataset_ids_raw = request.POST.get("selected_datasets", "")
            provider = (request.POST.get("provider") or "").strip().lower()

            if provider == "local":
                return JsonResponse(
                    {"error": errors.choose_provider()},
                    status=400,
                )

            if not project_id:
                return JsonResponse({"error": errors.select_project_first()}, status=400)
            if not selected_dataset_ids_raw.strip():
                return JsonResponse({"error": errors.datasets_required()}, status=400)

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
                return JsonResponse({"error": errors.datasets_required()}, status=400)

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
            image_ids = []

            for _, images in ds_list:
                for img in images:
                    try:
                        filenames.append(get_text(img.getName()))
                        image_ids.append(int(get_id(img)))
                    except Exception:
                        continue

            if not filenames:
                return JsonResponse({"error": errors.no_filenames_available()}, status=400)

            if provider == "local":
                return JsonResponse(
                    {"error": errors.choose_provider()},
                    status=400,
                )

            username = current_username(request, conn)
            if not username:
                return JsonResponse({"error": errors.unable_to_determine_username()}, status=400)

            try:
                api_key = (get_ai_credential(username, provider) or "").strip()
            except AiCredentialStoreError as e:
                return JsonResponse({"error": str(e)}, status=500)

            if not api_key:
                return JsonResponse({"error": errors.ai_api_key_required()}, status=400)

            try:
                result = generate_ai_parsed_values(provider, api_key, filenames)
            except AiAssistError as e:
                return JsonResponse({"error": str(e)}, status=400)
            except Exception as e:
                logger.exception("AI parse provider failure: %s", e)
                return JsonResponse({"error": errors.unable_to_process_filenames()}, status=500)

            rows_with_ids = []
            for img_id, row in zip(image_ids, result.get("rows", [])):
                rows_with_ids.append(
                    {
                        "img_id": img_id,
                        "values": row.get("values", []),
                    }
                )

            return JsonResponse(
                {
                    "rows": rows_with_ids,
                    "source": result.get("source"),
                }
            )

        # ----------------------------------------------------
        # PREVIEW MODE - WITH RATE LIMIT (major action)
        # ----------------------------------------------------
        if request.method == "POST" and request.POST.get("action") != "save_job":
            project_id = request.POST.get("project")
            raw_seps = request.POST.get("separator", "_")
            separator_mode = request.POST.get("separator_mode", "chars")
            selected_dataset_ids_raw = request.POST.get("selected_datasets", "")
            
            # READ USER SETTINGS FROM REQUEST
            user_chunk_size = request.POST.get("user_chunk_size")
            user_max_parsed = request.POST.get("user_max_parsed")
            user_max_sets = request.POST.get("user_max_sets")
            
            # Parse with fallback to constants
            try:
                chunk_size = int(user_chunk_size) if user_chunk_size else CHUNK_SIZE
            except (ValueError, TypeError):
                chunk_size = CHUNK_SIZE
                
            try:
                max_parsed = int(user_max_parsed) if user_max_parsed else MAX_PARSED_VARIABLES
            except (ValueError, TypeError):
                max_parsed = MAX_PARSED_VARIABLES
                
            try:
                max_sets = int(user_max_sets) if user_max_sets else MAX_VARIABLE_SET_ENTRIES
            except (ValueError, TypeError):
                max_sets = MAX_VARIABLE_SET_ENTRIES

            if not project_id:
                return render(
                    request,
                    "index.html",
                    {
                        "projects": projects,
                        "error_message": errors.select_project_first(),
                        "chunk_size": CHUNK_SIZE,
                        "default_variable_names_json": json.dumps(DEFAULT_VARIABLE_NAMES),
                        "max_parsed_variables": MAX_PARSED_VARIABLES,
                        "max_variable_sets": MAX_VARIABLE_SET_ENTRIES,
                        "messages_json": json.dumps(messages.index_messages()),
                    },
                )

            if separator_mode != "ai_parse" and (not raw_seps or not raw_seps.strip()):
                return render(
                    request,
                    "index.html",
                    {
                        "projects": projects,
                        "error_message": errors.filename_input_empty(),
                        "chunk_size": CHUNK_SIZE,
                        "default_variable_names_json": json.dumps(DEFAULT_VARIABLE_NAMES),
                        "max_parsed_variables": MAX_PARSED_VARIABLES,
                        "max_variable_sets": MAX_VARIABLE_SET_ENTRIES,
                        "messages_json": json.dumps(messages.index_messages()),
                    },
                )

            if not selected_dataset_ids_raw.strip():
                return render(
                    request,
                    "index.html",
                    {
                        "projects": projects,
                        "error_message": errors.datasets_required(),
                        "chunk_size": CHUNK_SIZE,
                        "default_variable_names_json": json.dumps(DEFAULT_VARIABLE_NAMES),
                        "max_parsed_variables": MAX_PARSED_VARIABLES,
                        "max_variable_sets": MAX_VARIABLE_SET_ENTRIES,
                        "messages_json": json.dumps(messages.index_messages()),
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

            ai_parsed_map = None
            sep_pattern = None

            if separator_mode == "ai_parse":

                raw_ai_parsed = (request.POST.get("ai_parsed_json") or "").strip()

                if not raw_ai_parsed:
                    return HttpResponse(
                        "<h2 style='color:red;'>AI parsing data missing</h2>"
                        "<p>Please run the AI-assisted filename parsing routine first.</p>"
                        "<a href='.'>Back</a>"
                    )

                try:
                    parsed_rows = json.loads(raw_ai_parsed)
                except json.JSONDecodeError as e:
                    return HttpResponse(
                        "<h2 style='color:red;'>Invalid AI parsing data</h2>"
                        f"<p>{e}</p>"
                        "<a href='.'>Back</a>"
                    )

                ai_parsed_map = {}

                for row in parsed_rows:

                    try:
                        img_id = int(row["img_id"])
                        values = [str(v) for v in row.get("values", []) if str(v).strip()]
                    except (KeyError, ValueError, TypeError):
                        continue

                    ai_parsed_map[img_id] = values

                sep_pattern = None


            elif separator_mode in ("regex", "ai_regex"):

                sep_pattern = raw_seps

                try:
                    re.compile(sep_pattern)
                except re.error as e:
                    return HttpResponse(
                        f"<h2 style='color:red;'>{errors.invalid_regex_pattern_title()}</h2>"
                        f"<p>{e}</p>"
                        "<a href='.'>Back</a>"
                    )


            else:
                # character-based separators
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
                        "error_message": errors.datasets_required(),
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
                        "error_message": errors.no_data_to_process(),
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
                        if separator_mode == "ai_parse" and ai_parsed_map is not None:
                            parts = ai_parsed_map.get(iid, [])
                        else:
                            parts = parse_filename(fname, sep_pattern)

                        # Track actual max before capping
                        max_vars_uncapped = max(max_vars_uncapped, len(parts))
                        
                        # Cap at MAX_PARSED_VARIABLES
                        parts_capped = parts[:max_parsed]
                        max_vars = max(max_vars, len(parts_capped))
                        
                        vars_dict = {f"Var{i+1}": p for i, p in enumerate(parts_capped)}
                        preview_rows.append((ds_label, iid, fname, vars_dict))
                    except Exception:
                        continue

            if max_vars == 0:
                max_vars = 1

            # Check if any filenames exceeded the limit
            vars_limit_exceeded = max_vars_uncapped > max_parsed
            preview_rows.sort(
                key=lambda row: (row[0] or "").casefold(),
            )

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
                "max_parsed_variables": max_parsed,
                "vars_limit_exceeded": vars_limit_exceeded,
                "max_vars_uncapped": max_vars_uncapped,
                "chunk_size": chunk_size,
                "max_variable_sets": max_sets,
                "messages_json": json.dumps(
                    messages.build_message_payload(messages.PREVIEW_MESSAGE_NAMES)
                ),
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
            {
                "projects": projects,
                "chunk_size": CHUNK_SIZE,
                "default_variable_names_json": json.dumps(DEFAULT_VARIABLE_NAMES),
                "max_parsed_variables": MAX_PARSED_VARIABLES,
                "max_variable_sets": MAX_VARIABLE_SET_ENTRIES,
                "messages_json": json.dumps(messages.index_messages()),
            },
        )

    except Exception as e:
        logger.exception("Unhandled error in index(): %s", e)
        return HttpResponse(f"<h2>Error: {e}</h2>")
