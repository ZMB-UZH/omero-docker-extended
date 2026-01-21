from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.urls import reverse
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
from ..services.ai_providers import list_ai_provider_options
from ..views.utils import current_username
from ..strings import errors, messages
from ..constants import (
    CHUNK_SIZE,
    DEFAULT_VARIABLE_NAMES,
    MAX_PARSED_VARIABLES,
    MAX_VARIABLE_SET_ENTRIES,
)
logger = logging.getLogger(__name__)


def _get_owner_id(obj):
    if obj is None:
        return None
    try:
        details = obj.getDetails()
        owner = details.getOwner() if details else None
        if owner is not None:
            oid = owner.getId()
            return oid.getValue() if hasattr(oid, "getValue") else oid
    except Exception:
        pass
    try:
        owner = obj.getOwner()
        if owner is not None:
            oid = owner.getId()
            return oid.getValue() if hasattr(oid, "getValue") else oid
    except Exception:
        pass
    return None


def _current_user_id(conn):
    try:
        user = conn.getUser()
        if user is not None:
            uid = user.getId()
            return uid.getValue() if hasattr(uid, "getValue") else uid
    except Exception:
        return None
    return None


def _is_owned_by_user(obj, user_id):
    if obj is None or user_id is None:
        return False
    owner_id = _get_owner_id(obj)
    if owner_id is None:
        return False
    try:
        return int(owner_id) == int(user_id)
    except Exception:
        return False


def _get_owner_username(obj):
    if obj is None:
        return ""
    owner = None
    try:
        details = obj.getDetails()
        owner = details.getOwner() if details else None
    except Exception:
        owner = None
    if owner is None:
        try:
            owner = obj.getOwner()
        except Exception:
            owner = None
    if owner is None:
        return ""
    for attr in ("getOmeName", "getName", "getFirstName"):
        try:
            value = getattr(owner, attr)()
        except Exception:
            continue
        if value:
            return str(value)
    try:
        return str(owner.getId())
    except Exception:
        return ""


def _get_permissions(obj):
    try:
        details = obj.getDetails()
        permissions = details.getPermissions() if details else None
        if permissions is not None:
            return permissions
    except Exception:
        pass
    for attr in ("getPermissions", "permissions"):
        try:
            permissions = getattr(obj, attr)()
        except Exception:
            continue
        if permissions is not None:
            return permissions
    return None


def _permissions_flag(permissions, attr):
    try:
        flag = getattr(permissions, attr)
    except Exception:
        return False
    if callable(flag):
        try:
            return bool(flag())
        except Exception:
            return False
    return bool(flag)


def _has_read_write_permissions(obj):
    permissions = _get_permissions(obj)
    if permissions is None:
        return False
    return _permissions_flag(permissions, "isRead") and _permissions_flag(permissions, "isWrite")


def _has_read_annotate_permissions(obj):
    permissions = _get_permissions(obj)
    if permissions is None:
        return False
    can_read = _permissions_flag(permissions, "isRead")
    can_write = _permissions_flag(permissions, "isWrite")
    can_annotate = _permissions_flag(permissions, "isAnnotate") or _permissions_flag(
        permissions, "canAnnotate"
    )
    return can_read and can_annotate and not can_write


def _iter_accessible_projects(conn):
    if conn is None:
        return
    current_group = None
    try:
        current_group = conn.SERVICE_OPTS.getOmeroGroup()
    except Exception:
        pass
    try:
        conn.SERVICE_OPTS.setOmeroGroup("-1")
        try:
            for proj in conn.getObjects("Project"):
                yield proj
            return
        except Exception as exc:
            logger.warning("Failed to query projects across all groups with SERVICE_OPTS: %s", exc)
        try:
            for proj in conn.getObjects("Project", opts={"group": "-1"}):
                yield proj
            return
        except Exception as exc:
            logger.warning("Failed to query projects with opts group=-1: %s", exc)
    finally:
        if current_group is not None:
            try:
                conn.SERVICE_OPTS.setOmeroGroup(current_group)
            except Exception:
                pass
    try:
        for proj in conn.getObjects("Project"):
            yield proj
        return
    except Exception as exc:
        logger.warning("Failed to query projects in current group: %s", exc)
    try:
        for proj in conn.listProjects():
            yield proj
    except Exception as exc:
        logger.warning("Failed to list projects: %s", exc)
        return


def _iter_member_groups(conn):
    if conn is None:
        return []
    try:
        groups = conn.getGroupsMemberOf()
        if groups:
            return list(groups)
    except Exception:
        pass
    try:
        user = conn.getUser()
        if user is not None:
            groups = user.getGroups()
            if groups:
                return list(groups)
    except Exception:
        pass
    return []


def _group_member_count(conn, group):
    for attr in ("getMemberCount", "getMembers", "getExperimenters", "getExperimenterIds"):
        try:
            value = getattr(group, attr)()
        except Exception:
            continue
        if value is None:
            continue
        if attr == "getMemberCount":
            try:
                return int(value)
            except Exception:
                continue
        try:
            return len(list(value))
        except Exception:
            continue
    group_id = get_id(group)
    if group_id is None:
        return 0
    try:
        members = list(conn.getObjects("Experimenter", opts={"group": str(group_id)}))
        return len(members)
    except Exception:
        return 0


def _group_has_other_members(conn, group):
    count = _group_member_count(conn, group)
    return count > 1


def _group_is_read_write(group):
    """Check if group has read-write permissions (RWRW-- or similar)"""
    permissions = _get_permissions(group)
    if permissions is None:
        return False
    try:
        # OMERO groups use isGroupRead() and isGroupWrite() 
        # Or check the permission level string
        perm_str = str(permissions)
        # Read-write groups have patterns like "rwrw--" or "rwra--"
        return "rw" in perm_str.lower()[:4]  # Check first 4 chars for group perms
    except Exception:
        pass
    # Fallback: try the isGroupRead/isGroupWrite methods if they exist
    try:
        return (_permissions_flag(permissions, "isGroupRead") and 
                _permissions_flag(permissions, "isGroupWrite"))
    except Exception:
        return False


def _group_is_read_annotate(group):
    """Check if group has read-annotate permissions (RWRA-- or similar)"""
    permissions = _get_permissions(group)
    if permissions is None:
        return False
    try:
        perm_str = str(permissions)
        # Read-annotate groups have pattern like "rwra--"
        return "ra" in perm_str.lower()[2:4]  # Check positions 2-3 for group perms
    except Exception:
        pass
    # Fallback
    try:
        return (_permissions_flag(permissions, "isGroupRead") and 
                _permissions_flag(permissions, "isGroupAnnotate") and
                not _permissions_flag(permissions, "isGroupWrite"))
    except Exception:
        return False


def _has_collaboration_groups(conn):
    for group in _iter_member_groups(conn):
        if not _group_has_other_members(conn, group):
            continue
        if _group_is_read_write(group) or _group_is_read_annotate(group):
            return True
    return False


def _get_object_group(obj):
    """Get the group that an object (project/dataset/image) belongs to"""
    try:
        details = obj.getDetails()
        if details:
            group = details.getGroup()
            return group
    except Exception:
        pass
    return None


def _is_user_in_group(conn, group_id, user_id):
    """Check if a user is a member of a specific group"""
    if group_id is None or user_id is None:
        return False
    try:
        for group in _iter_member_groups(conn):
            gid = get_id(group)
            if gid and int(gid) == int(group_id):
                return True
    except Exception:
        pass
    return False


def _collect_project_payload(conn, user_id):
    owned_projects = []
    collab_projects = []
    annotate_projects = []
    collab_available = _has_collaboration_groups(conn)
    try:
        for proj in _iter_accessible_projects(conn):
            pid = get_id(proj)
            pname = get_text(proj.getName())
            if pid is None:
                continue
            entry = {"id": str(pid), "name": pname}
            
            # Check if owned by current user
            if _is_owned_by_user(proj, user_id):
                owned_projects.append(entry)
                continue
            
            # NOT owned by user - check if it's a collaboration project
            # Get the group this project is in
            proj_group = _get_object_group(proj)
            if proj_group is None:
                continue
                
            group_id = get_id(proj_group)
            if group_id is None:
                continue
            
            # Check if we're a member of this project's group
            if not _is_user_in_group(conn, group_id, user_id):
                continue
            
            # We're in the same group - now check the group's permission level
            owner_name = _get_owner_username(proj) or "Unknown user"
            
            if _group_is_read_write(proj_group):
                # This is a read-write group, add as collaboration project
                collab_projects.append({**entry, "owner": owner_name, "access": "read_write"})
            elif _group_is_read_annotate(proj_group):
                # This is a read-annotate group, add as collaboration project
                annotate_projects.append({**entry, "owner": owner_name, "access": "read_annotate"})
            # else: private or read-only group, skip
                
    except Exception as exc:
        logger.exception("Error listing projects: %s", exc)
    return {
        "owned": owned_projects,
        "collab": collab_projects,
        "collab_annotate": annotate_projects,
        "collab_available": collab_available,
    }


def _get_accessible_project(conn, project_id, user_id):
    if not project_id:
        return None, None
    try:
        project = conn.getObject("Project", int(project_id))
    except Exception:
        project = None
    if project is None:
        return None, None
    if _is_owned_by_user(project, user_id):
        return project, "owned"
    proj_group = _get_object_group(project)
    if proj_group is None:
        return None, None
    group_id = get_id(proj_group)
    if not _is_user_in_group(conn, group_id, user_id):
        return None, None
    if _group_is_read_write(proj_group):
        return project, "read_write"
    if _group_is_read_annotate(proj_group):
        return project, "read_annotate"
    return None, None


def _suggest_separator_regex(filenames):
    return suggest_separator_regex(filenames)


@csrf_exempt
@login_required()
def index(request, conn=None, url=None, **kwargs):
    """
    OMP filename+metadata harverster UI
    """

    try:
        username = current_username(request, conn)
        user_id = _current_user_id(conn)

        def build_index_context(extra=None):
            context = {
                "projects": projects,
                "chunk_size": CHUNK_SIZE,
                "default_variable_names_json": json.dumps(DEFAULT_VARIABLE_NAMES),
                "max_parsed_variables": MAX_PARSED_VARIABLES,
                "max_variable_sets": MAX_VARIABLE_SET_ENTRIES,
                "messages_json": json.dumps(messages.index_messages()),
                "user_id": user_id,
                "ai_provider_options_json": json.dumps(list_ai_provider_options()),
                "project_list_url": reverse("omeroweb_omp_plugin_projects"),
            }
            if extra:
                context.update(extra)
            return context

        # ----------------------------------------------------
        # Load projects
        # ----------------------------------------------------
        projects = _collect_project_payload(conn, user_id)

        # ----------------------------------------------------
        # LIST DATASETS - NO RATE LIMIT (read-only, just listing)
        # ----------------------------------------------------
        if request.method == "POST" and request.POST.get("action") == "list_datasets":
            project_id = request.POST.get("project")
            if not project_id:
                return JsonResponse({"error": errors.select_project_first()}, status=400)

            if user_id is None:
                return JsonResponse({"error": errors.unable_to_determine_username()}, status=400)

            project, project_access = _get_accessible_project(conn, project_id, user_id)
            if project is None:
                return JsonResponse({"error": errors.select_project_first()}, status=400)

            # NO RATE LIMIT - just listing datasets
            owner_filter = user_id if project_access == "owned" else None
            dataset_rows = collect_dataset_summaries(conn, project_id, owner_id=owner_filter)
            dataset_rows = sorted(
                dataset_rows,
                key=lambda row: (row.get("name") or "").casefold(),
            )
            return JsonResponse({"datasets": dataset_rows})

        if request.method == "POST" and request.POST.get("action") == "ai_regex":
            project_id = request.POST.get("project")
            selected_dataset_ids_raw = request.POST.get("selected_datasets", "")
            provider = (request.POST.get("provider") or "local").strip().lower()
            model = (request.POST.get("model") or "").strip()

            if not project_id:
                return JsonResponse({"error": errors.select_project_first()}, status=400)
            if user_id is None:
                return JsonResponse({"error": errors.unable_to_determine_username()}, status=400)
            project, project_access = _get_accessible_project(conn, project_id, user_id)
            if project is None:
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
                return JsonResponse(
                    {"error": build_rate_limit_message(remaining)},
                    status=429,
                )

            ds_list = collect_images_by_selected_datasets(
                conn,
                project_id,
                selected_dataset_ids,
                limit=200,
                owner_id=user_id if project_access == "owned" else None,
            )

            filenames = []
            for _, images in ds_list:
                for img in images:
                    try:
                        filenames.append(get_text(img.getName()))
                    except Exception:
                        continue

            if not filenames:
                return JsonResponse({"error": errors.no_filenames_available()}, status=400)

            if provider == "local":
                regex = _suggest_separator_regex(filenames)
                return JsonResponse({"regex": regex, "source": "local"})

            username = current_username(request, conn)
            if not username:
                return JsonResponse(
                    {"error": errors.unable_to_determine_username()},
                    status=400,
                )

            try:
                api_key = (get_ai_credential(username, provider) or "").strip()
            except AiCredentialStoreError as e:
                return JsonResponse({"error": str(e)}, status=500)

            if not api_key:
                return JsonResponse(
                    {"error": errors.ai_api_key_required()},
                    status=400,
                )

            try:
                result = generate_ai_regex(provider, api_key, filenames, model=model or None)
            except AiAssistError as e:
                return JsonResponse({"error": str(e)}, status=400)
            except Exception as e:
                logger.exception("AI regex provider failure: %s", e)
                return JsonResponse(
                    {"error": errors.unable_to_process_filenames()},
                    status=500,
                )

            return JsonResponse(result)

        if request.method == "POST" and request.POST.get("action") == "ai_parse":
            project_id = request.POST.get("project")
            selected_dataset_ids_raw = request.POST.get("selected_datasets", "")
            provider = (request.POST.get("provider") or "").strip().lower()
            model = (request.POST.get("model") or "").strip()

            if provider == "local":
                return JsonResponse(
                    {"error": errors.provider_required()},
                    status=400,
                )

            if not project_id:
                return JsonResponse({"error": errors.select_project_first()}, status=400)
            if user_id is None:
                return JsonResponse({"error": errors.unable_to_determine_username()}, status=400)
            project, project_access = _get_accessible_project(conn, project_id, user_id)
            if project is None:
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
                owner_id=user_id if project_access == "owned" else None,
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
                    {"error": errors.provider_required()},
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
                result = generate_ai_parsed_values(provider, api_key, filenames, model=model or None)
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
                    "omeroweb_omp_plugin/index.html",
                    build_index_context(
                        {
                            "error_message": errors.select_project_first(),
                        }
                    ),
                )
            if user_id is None:
                return render(
                    request,
                    "omeroweb_omp_plugin/index.html",
                    build_index_context(
                        {
                            "error_message": errors.unable_to_determine_username(),
                        }
                    ),
                )

            project, project_access = _get_accessible_project(conn, project_id, user_id)
            if project is None:
                return render(
                    request,
                    "omeroweb_omp_plugin/index.html",
                    build_index_context(
                        {
                            "error_message": errors.select_project_first(),
                        }
                    ),
                )

            if separator_mode != "ai_parse" and (not raw_seps or not raw_seps.strip()):
                return render(
                    request,
                    "omeroweb_omp_plugin/index.html",
                    build_index_context(
                        {
                            "error_message": errors.filename_input_empty(),
                        }
                    ),
                )

            if not selected_dataset_ids_raw.strip():
                return render(
                    request,
                    "omeroweb_omp_plugin/index.html",
                    build_index_context(
                        {
                            "error_message": errors.datasets_required(),
                        }
                    ),
                )

            project_label = f"{get_text(project.getName())} (ID {project_id})"

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
                    "omeroweb_omp_plugin/index.html",
                    build_index_context(
                        {
                            "error_message": errors.datasets_required(),
                        }
                    ),
                )

            # RATE LIMIT - preview is a major action (loads lots of data)
            allowed, remaining = check_major_action_rate_limit(request, conn)
            if not allowed:
                return render(
                    request,
                    "omeroweb_omp_plugin/index.html",
                    build_index_context(
                        {
                            "error_message": build_rate_limit_message(remaining),
                        }
                    ),
                )

            ds_list = collect_images_by_selected_datasets(
                conn,
                project_id,
                selected_dataset_ids,
                limit=50,
                owner_id=user_id if project_access == "owned" else None,
            )

            total_images = sum(len(images) for _, images in ds_list)
            if total_images == 0:
                return render(
                    request,
                    "omeroweb_omp_plugin/index.html",
                    build_index_context(
                        {
                            "error_message": errors.no_data_to_process(),
                        }
                    ),
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
                "user_id": user_id,
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
            build_index_context(),
        )

    except Exception as e:
        logger.exception("Unhandled error in index(): %s", e)
        return HttpResponse(f"<h2>Error: {e}</h2>")


@login_required()
def list_projects(request, conn=None, url=None, **kwargs):
    user_id = _current_user_id(conn)
    payload = _collect_project_payload(conn, user_id)
    return JsonResponse(payload)


@login_required()
def root_status(request, conn=None, url=None, **kwargs):
    username = current_username(request, conn)
    return JsonResponse({"is_root_user": username == "root"})
