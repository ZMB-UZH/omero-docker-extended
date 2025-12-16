from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from omeroweb.decorators import login_required
import logging
import re

from ..services.core import (
    get_id,
    get_text,
    collect_images_by_dataset_sorted,
    parse_filename,
)

logger = logging.getLogger(__name__)


@csrf_exempt
@login_required()
def index(request, conn=None, url=None, **kwargs):
    """
    Filename metadata UI
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
        if request.method == "POST" and request.POST.get("action") != "save_job":
            project_id = request.POST.get("project")
            raw_seps = request.POST.get("separator", "_")

            if not project_id:
                return HttpResponse(
                    "<h2 style='color:red;'>Select a project first.</h2>"
                    "<a href='.'>Back</a>"
                )

            try:
                prj = conn.getObject("Project", int(project_id))
                if prj:
                    project_label = f"{get_text(prj.getName())} (ID {project_id})"
                else:
                    project_label = f"ID {project_id}"
            except Exception:
                project_label = f"ID {project_id}"

            seps_escaped = "".join(re.escape(c) for c in raw_seps)
            sep_pattern = f"[{seps_escaped}]+"

            ds_list = collect_images_by_dataset_sorted(conn, project_id, limit=50)

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

            rows_html = ""
            for ds_label, img_id, fname, vars_dict in preview_rows:
                kv = " | ".join(f"{k[3:]}='{v}'" for k, v in vars_dict.items())
                rows_html += f"""
                <tr>
                    <td style='padding:6px;'>{ds_label}</td>
                    <td style='padding:6px;'>{img_id}</td>
                    <td style='padding:6px;'>{fname}</td>
                    <td style='padding:6px;'><code>{kv}</code></td>
                </tr>
                """

            var_inputs_html = ""
            for i in range(1, max_vars + 1):
                var_inputs_html += f"""
                <div style='margin-bottom:6px;'>
                    <label style="display:inline-block; width:120px;">{i}:</label>
                    <input id='var_name_{i}' type='text' value='Var{i}'
                           style='padding:4px 8px; margin-left:6px; width:200px;'>
                </div>
                """

            return HttpResponse(f"""
                <div style='padding:30px; font-family:sans-serif; max-width:1200px; margin:0 auto;'>

                    <div style='display:flex; justify-content:flex-end; margin-bottom:10px;'>
                        <button onclick='scrollToBottom()'
                                style='padding:10px 18px; font-size:14px;'>
                            ↓ Scroll to bottom
                        </button>
                    </div>

                    <h2 style='color:#007bff;'>📊 Preview parsed filenames</h2>
                    <p><em>Project: {project_label} | Separator(s): "{raw_seps}"</em></p>
                    <p>Previewing {len(preview_rows)} images.</p>

                    <table border='1' style='width:100%; border-collapse:collapse; font-family:monospace; margin-bottom:20px;'>
                        <tr style='background:#007bff; color:white;'>
                            <th style='padding:6px;'>Dataset</th>
                            <th style='padding:6px;'>ID</th>
                            <th style='padding:6px;'>Filename</th>
                            <th style='padding:6px;'>Parsed variables</th>
                        </tr>
                        {rows_html}
                    </table>

                    <hr>

                    <div id='var-config' data-var-count='{max_vars}'>
                        <h3>Variable names</h3>
                        <label>
                            <input type='checkbox' id='use_defaults' checked onclick='toggleVarNameInputs()'>
                            Use default names
                        </label>
                        <div id='var_name_inputs' style='margin-top:10px;'>
                            {var_inputs_html}
                        </div>
                    </div>

                    <hr>

                    <div style='display:flex; justify-content:space-between; align-items:center; margin-top:20px;'>

                        <!-- LEFT SAVE BUTTON -->
                        <button onclick='startSaveJob()'
                                style='padding:8px 8px; font-size:14px; background:#28a745; color:white;
                                       border:none; border-radius:6px; cursor:pointer;'>
                            💾 Save filename metadata into key-value pairs
                        </button>

                        <!-- CENTER ACQ BUTTON -->
                        <button onclick="startAcquisitionMetadataJob()"
                                style='padding:8px 8px; font-size:14px; background:#0069d9; color:white;
                                       border:none; border-radius:6px; cursor:pointer;'>
                            📥 Copy acquisition metadata into key-value pairs
                        </button>

                        <!-- RIGHT DELETE BUTTON (PLUGIN ONLY) -->
                        <button onclick='deletePluginMetadata()'
                                style='padding:8px 8px; font-size:14px; background:#fd7e14; color:white;
                                       border:none; border-radius:6px; cursor:pointer;'>
                            🗑 Delete ONLY internal key-value pairs
                        </button>

                    </div>

                    <div style='display:flex; justify-content:space-between; align-items:center; margin-top:20px;'>
                        <div></div>

                        <!-- DELETE ALL BUTTON -->
                        <button onclick='deleteAllMetadata()'
                                style='padding:10px 18px; font-size:14px; background:#dc3545; color:white;
                                       border:none; border-radius:6px; cursor:pointer;'>
                            🗑 Delete ALL key-value pairs
                        </button>
                    </div>

                    <div style='display:flex; justify-content:space-between; align-items:center; margin-top:20px;'>
                        <!-- BACK BUTTON -->
                        <button onclick="goBack()"
                                style='padding:10px 18px; font-size:14px;'>
                            ← Go back to project selection
                        </button>

                        <!-- SCROLL TO TOP BUTTON -->
                        <button onclick='scrollToTop()'
                                style='padding:10px 18px; font-size:14px;'>
                            ↑ Scroll to top
                        </button>
                    </div>

                    <!-- HIDDEN FIELDS -->
                    <input type='hidden' id='project_id' value='{project_id}'>
                    <input type='hidden' id='separator' value='{raw_seps}'>

                    <div id='progress-section' style='margin-top:30px; display:none;'>
                        <h3>Progress</h3>
                        <div style='width:100%; background:#e9ecef; border-radius:6px; overflow:hidden;'>
                            <div id='progress-bar'
                                 style='width:0%; background:#17a2b8; color:white; padding:6px 0; text-align:center;'>
                                0%
                            </div>
                        </div>

                        <p id='progress-text' style='margin-top:8px;'>Waiting to start…</p>

                        <pre id='progress-log'
                             style='margin-top:10px; background:#f8f9fa; padding:10px; max-height:250px; overflow:auto;'></pre>
                    </div>
                </div>

                <script>
                const BASE_URL = "/omeroweb_filenamemetadata";
                const DEFAULT_VARS = ["A", "B", "C", "E", "F", "G", "H", "I", "J", "K", "L", "M", "N", "O", "P", "Q", "R", "S", "T", "U", "V", "W", "X", "Y", "Z"];

                function goBack() {{
                    window.location.href = BASE_URL + "/";
                }}

                function scrollToBottom() {{
                    const target = document.documentElement.scrollHeight;
                    window.scrollTo({{ top: target, behavior: "smooth" }});
                }}

                function scrollToTop() {{
                    window.scrollTo({{ top: 0, behavior: "smooth" }});
                }}

                function toggleVarNameInputs() {{
                    let useDefaults = document.getElementById('use_defaults').checked;
                    let container = document.getElementById('var-config');
                    let count = parseInt(container.getAttribute('data-var-count'));

                    for (let i = 1; i <= count; i++) {{
                        let inp = document.getElementById('var_name_' + i);
                        if (!inp) continue;
                        if (useDefaults) {{
                            inp.value = DEFAULT_VARS[i-1] || ("Var" + i);
                            inp.disabled = true;
                        }} else {{
                            inp.disabled = false;
                        }}
                    }}
                }}
                toggleVarNameInputs();


                // Utility helpers for the progress UI (defensive to avoid breaking buttons)
                function resetProgressSection(initialText) {{
                    const section = document.getElementById("progress-section");
                    if (section) {{
                        section.style.display = "block";
                    }}

                    setProgress(0, initialText || "Working…");

                    const logEl = document.getElementById("progress-log");
                    if (logEl) {{
                        logEl.textContent = "";
                    }}
                }}

                function setProgress(percent, text) {{
                    const pctVal = Math.max(0, Math.min(100, Number(percent) || 0));
                    const pctLabel = pctVal.toFixed(1) + "%";

                    const bar = document.getElementById("progress-bar");
                    if (bar) {{
                        bar.style.width = pctLabel;
                        bar.innerText = pctLabel;
                    }}

                    if (text) {{
                        const textEl = document.getElementById("progress-text");
                        if (textEl) textEl.innerText = text;
                    }}
                }}

                function appendProgressLog(line) {{
                    const logEl = document.getElementById("progress-log");
                    if (!logEl) return;

                    logEl.textContent += line + "\n";
                    logEl.scrollTop = logEl.scrollHeight;
                }}


                // -------------------------
                // DELETE ALL ANNOTATIONS
                // -------------------------
                function deleteAllMetadata() {{
                    const projectId = document.getElementById('project_id').value;

                    const pwd = window.prompt("Enter your Omero password to delete ALL key-value pairs:");
                    if (!pwd) return;

                    if (!window.confirm("Are you absolutely sure? This action is irreversible.")) return;

                    const ctrls = document.querySelectorAll("button,input,select");
                    ctrls.forEach(x => x.disabled = true);

                    resetProgressSection("Preparing to delete ALL key-value pairs…");
                    setProgress(5, "Logging into OMERO…");
                    appendProgressLog("Requested full deletion for project " + projectId + " …");

                    fetch(BASE_URL + "/delete_all/", {{
                        method: "POST",
                        headers: {{ "Content-Type": "application/json" }},
                        credentials: "same-origin",
                        body: JSON.stringify({{
                            project_id: projectId,
                            password: pwd
                        }})
                    }})
                    .then(r => {{
                        appendProgressLog("OMERO CLI HTTP status: " + r.status);
                        return r.json();
                    }})
                    .then(data => {{
                        if (data.error) {{
                            setProgress(0, "Error deleting annotations.");
                            appendProgressLog("ERROR: " + data.error);
                            return;
                        }}

                        setProgress(50, "Processing OMERO CLI response…");
                        appendProgressLog("OMERO CLI responded. Deleted annotations for " + data.deleted_count + " images.");

                        if (data.errors && data.errors.length > 0) {{
                            appendProgressLog("Encountered " + data.errors.length + " errors during deletion.");
                            data.errors.slice(0, 5).forEach((err, idx) => {{
                                appendProgressLog("Error " + (idx + 1) + ": " + JSON.stringify(err));
                            }});
                            setProgress(100, "Deletion completed with errors. See log for details.");
                        }} else {{
                            setProgress(100, "Deletion complete. Processed " + data.deleted_count + " images.");
                        }}
                    }})
                    .catch(err => {{
                        setProgress(0, "Error deleting annotations.");
                        appendProgressLog("ERROR: " + err);
                    }})
                    .finally(() => {{
                        ctrls.forEach(x => x.disabled = false);
                    }});
                }}


                // -------------------------
                // DELETE ONLY PLUGIN ANNOTATIONS
                // -------------------------
                function deletePluginMetadata() {{
                    const projectId = document.getElementById('project_id').value;

                    const pwd = window.prompt("Enter your Omero password to delete ONLY plugin key-value pairs:");
                    if (!pwd) return;

                    if (!window.confirm("Are you absolutely sure? This action is irreversible.")) return;

                    const ctrls = document.querySelectorAll("button,input,select");
                    ctrls.forEach(x => x.disabled = true);

                    resetProgressSection("Deleting ONLY plugin-generated key-value pairs…");
                    setProgress(5, "Logging into OMERO…");
                    appendProgressLog("Requested plugin-only deletion for project " + projectId + " …");

                    fetch(BASE_URL + "/delete_plugin/", {{
                        method: "POST",
                        headers: {{ "Content-Type": "application/json" }},
                        credentials: "same-origin",
                        body: JSON.stringify({{
                            project_id: projectId,
                            password: pwd
                        }})
                    }})
                    .then(r => {{
                        appendProgressLog("OMERO CLI HTTP status: " + r.status);
                        return r.json();
                    }})
                    .then(data => {{
                        if (data.error) {{
                            setProgress(0, "Error deleting plugin annotations.");
                            appendProgressLog("ERROR: " + data.error);
                            return;
                        }}

                        setProgress(50, "Processing OMERO CLI response…");
                        appendProgressLog("OMERO CLI responded. Deleted " + data.deleted_annotations + " annotations across " + data.deleted_images + " images.");

                        if (data.errors && data.errors.length > 0) {{
                            appendProgressLog("Encountered " + data.errors.length + " errors during deletion.");
                            data.errors.slice(0, 5).forEach((err, idx) => {{
                                appendProgressLog("Error " + (idx + 1) + ": " + JSON.stringify(err));
                            }});
                            setProgress(100, "Plugin-only deletion completed with errors. See log for details.");
                        }} else {{
                            setProgress(100, "Plugin-only deletion complete. Processed " + data.deleted_images + " images.");
                        }}
                    }})
                    .catch(err => {{
                        setProgress(0, "Error deleting plugin annotations.");
                        appendProgressLog("ERROR: " + err);
                    }})
                    .finally(() => {{
                        ctrls.forEach(x => x.disabled = false);
                    }});
                }}


                // -------------------------
                // START SAVE JOB (FIXED)
                // -------------------------
                let currentJobId = null;
                let totalImages = 0;
                let pollInterval = null;

                function startSaveJob() {{
                    if (currentJobId) {{
                        alert("Job already running.");
                        return;
                    }}

                    const projectId = document.getElementById('project_id').value;
                    const separator = document.getElementById('separator').value;

                    const container = document.getElementById('var-config');
                    const count = parseInt(container.getAttribute('data-var-count'));
                    const useDefaults = document.getElementById('use_defaults').checked;

                    let varNames = [];
                    for (let i = 1; i <= count; i++) {{
                        let name = useDefaults ? ("Var" + i)
                                               : document.getElementById('var_name_' + i).value.trim() || ("Var" + i);
                        varNames.push(name);
                    }}

                    // FIX: delete_mode *not* "keep", prevents double saves
                    let payload = {{
                        project_id: projectId,
                        separator: separator,
                        var_names: varNames,
                        delete_mode: "all"
                    }};

                    resetProgressSection("Starting job…");

                    fetch(BASE_URL + "/start_job/", {{
                        method: "POST",
                        headers: {{ "Content-Type": "application/json" }},
                        body: JSON.stringify(payload)
                    }})
                    .then(r => r.json())
                    .then(data => {{
                        if (data.error) {{
                            document.getElementById("progress-text").innerText = "Error: " + data.error;
                            return;
                        }}

                        currentJobId = data.job_id;
                        totalImages = data.total;

                        setProgress(0, "Job started for " + totalImages + " images.");
                        pollInterval = setInterval(pollProgress, 500);
                    }});
                }}

                // -------------------------
                // START ACQUISITION JOB
                // -------------------------
                function startAcquisitionMetadataJob() {{
                    if (currentJobId) {{
                        alert("Job already running.");
                        return;
                    }}

                    const projectId = document.getElementById('project_id').value;

                    let payload = {{
                        project_id: projectId
                    }};

                    resetProgressSection("Starting acquisition metadata job…");

                    fetch(BASE_URL + "/start_acq_job/", {{
                        method: "POST",
                        headers: {{ "Content-Type": "application/json" }},
                        body: JSON.stringify(payload)
                    }})
                    .then(r => r.json())
                    .then(data => {{
                        if (data.error) {{
                            document.getElementById("progress-text").innerText =
                                "Error: " + data.error;
                            return;
                        }}

                        currentJobId = data.job_id;
                        totalImages = data.total;

                        pollInterval = setInterval(pollProgress, 500);
                    }});
                }}

                function pollProgress() {{
                    if (!currentJobId) return;

                    fetch(BASE_URL + "/progress/" + currentJobId + "/", {{
                        method: "GET",
                        headers: {{ "Accept": "application/json" }}
                    }})
                    .then(r => r.json())
                    .then(data => {{
                        if (data.error) {{
                            clearInterval(pollInterval);
                            pollInterval = null;
                            document.getElementById("progress-text").innerText = "Error: " + data.error;
                            return;
                        }}

                        let done = data.done;
                        let total = data.total;
                        let percent = data.percent;

                        setProgress(percent, "Processed " + done + " of " + total + " images (unique IDs).");

                        if (data.last_log) {{
                            let logEl = document.getElementById("progress-log");
                            logEl.textContent += data.last_log + "\\n";
                            logEl.scrollTop = logEl.scrollHeight;
                        }}

                        if (data.finished) {{
                            clearInterval(pollInterval);
                            pollInterval = null;
                            document.getElementById("progress-text").innerText =
                                "Completed. Processed " + done + " images.";
                        }}
                    }});
                }}
                </script>
            """)

        # ----------------------------------------------------
        # LANDING PAGE
        # ----------------------------------------------------
        project_options = "".join(
            f"<option value='{pid}'>{name}</option>" for pid, name in projects
        )

        return HttpResponse(f"""
            <div style='padding:40px; max-width:600px; margin:0 auto; font-family:sans-serif;'>
                <h1 style='color:#007bff;'>Filename-Metadata plugin</h1>

                <form method='POST'
                      style='background:#f8f9fa;padding:30px;border-radius:10px;border:2px solid #007bff;'>
                    <div style='margin-bottom:20px;'>
                        <label><strong>Project:</strong></label><br>
                        <select name='project'
                                style='width:100%;padding:12px;border-radius:6px;border:1px solid #007bff;'>
                            <option value=''>Select project…</option>
                            {project_options}
                        </select>
                    </div>

                    <div style='margin-bottom:20px;'>
                        <label><strong>Separators (chars):</strong></label><br>
                        <input type='text' name='separator' value='_-'
                               style='width:100%;padding:12px;border-radius:6px;border:1px solid #007bff;'>
                    </div>

                    <button type='submit'
                            style='width:100%;padding:18px;font-size:18px;background:#007bff;color:white;
                                   border:none;border-radius:8px;'>
                        Load images & Preview
                    </button>
                </form>
            </div>
        """)

    except Exception as e:
        logger.exception("Unhandled error in index(): %s", e)
        return HttpResponse(f"<h2>Error: {e}</h2>")

