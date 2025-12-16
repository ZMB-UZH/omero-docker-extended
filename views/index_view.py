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
                    <td style='padding:2px;'>{ds_label}</td>
                    <td style='padding:2px;'>{img_id}</td>
                    <td style='padding:2px;'>{fname}</td>
                    <td style='padding:2px;'><code>{kv}</code></td>
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
                <div style='padding:10px; font-family:"Helvetica Neue", Helvetica, Arial, sans-serif; --base-font-size:14px; font-size:var(--base-font-size); max-width:1200px; margin:0 auto;'>
                    <div style='display:flex; justify-content:space-between; align-items:center; gap:8px; margin-bottom:10px;'>
                        <h2 style='color:#007bff; margin:0;'>📊 Preview parsed filenames</h2>
                        <button onclick='scrollToBottom()'
                                style='padding:8px 8px; font-size:14px;'>
                            ↓ Scroll to bottom
                        </button>
                    </div>
                    <p>Project: {project_label} | Separator(s): "{raw_seps}"</p>
                    <p>Previewing {len(preview_rows)} images.</p>
                    <table border='1' style='width:100%; border-collapse:collapse; font-family:"Helvetica Neue", Helvetica, Arial, sans-serif; margin-bottom:10px;'>
                        <tr style='background:#007bff; color:white;'>
                            <th style='padding:2px;'>Dataset</th>
                            <th style='padding:2px;'>ID</th>
                            <th style='padding:2px;'>Filename</th>
                            <th style='padding:2px;'>Parsed variables</th>
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
                                style='padding:8px 8px; font-size:14px; background:#dc3545; color:white;
                                       border:none; border-radius:6px; cursor:pointer;'>
                            🗑 Delete ALL key-value pairs
                        </button>
                    </div>

                    <div style='display:flex; justify-content:space-between; align-items:center; margin-top:20px;'>
                        <!-- BACK BUTTON -->
                        <button onclick="goBack()"
                                style='padding:8px 8px; font-size:14px;'>
                            ← Go back to project selection
                        </button>

                        <!-- SCROLL TO TOP BUTTON -->
                        <button onclick='scrollToTop()'
                                style='padding:8px 8px; font-size:14px;'>
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


                // -------------------------
                // DELETE ALL KEY-VALUE PAIRS
                // -------------------------
                function showImmediateCompletionLog(lines) {{
                    const progressSection = document.getElementById("progress-section");
                    const progressText = document.getElementById("progress-text");
                    const progressBar = document.getElementById("progress-bar");
                    const progressLog = document.getElementById("progress-log");

                    progressSection.style.display = "block";

                    progressBar.style.width = "100%";
                    progressBar.innerText = "100%";

                    progressText.innerText = "Completed.";

                    progressLog.textContent = "";
                    for (let i = 0; i < lines.length; i++) {{
                        progressLog.textContent += lines[i] + "\\n";
                    }}
                }}


                function deleteAllMetadata() {{
                    const projectId = document.getElementById('project_id').value;

                    const pwd = window.prompt("Enter your Omero password to delete ALL key-value pairs:");
                    if (!pwd) return;

                    if (!window.confirm("Are you absolutely sure? This action is irreversible.")) return;

                    const ctrls = document.querySelectorAll("button,input,select");
                    ctrls.forEach(x => x.disabled = true);

                    const progressSection = document.getElementById("progress-section");
                    const progressText = document.getElementById("progress-text");
                    const progressBar = document.getElementById("progress-bar");
                    const progressLog = document.getElementById("progress-log");

                    progressSection.style.display = "block";
                    progressBar.style.width = "0%";
                    progressBar.innerText = "0%";
                    progressText.innerText = "Deleting ALL key-value pairs…";
                    progressLog.textContent = "";

                    fetch(BASE_URL + "/delete_all/", {{
                        method: "POST",
                        headers: {{ "Content-Type": "application/json" }},
                        credentials: "same-origin",
                        body: JSON.stringify({{
                            project_id: projectId,
                            password: pwd
                        }})
                    }})
                    .then(r => r.json())
                    .then(data => {{
                        ctrls.forEach(x => x.disabled = false);

                        let logLines = [];

                        if (data.errors && data.errors.length) {{
                            logLines.push("Completed with errors.");
                            for (let i = 0; i < data.errors.length; i++) {{
                                logLines.push(
                                    "ERROR ids=" +
                                    (data.errors[i].ids || []).join(",")
                                );
                            }}
                        }} else {{
                            logLines.push(
                                "Deleted annotations for " +
                                data.deleted_count +
                                " images."
                            );
                        }}

                        showImmediateCompletionLog(logLines);
                    }})
                    .catch(err => {{
                        ctrls.forEach(x => x.disabled = false);
                        alert("ERROR: " + err);
                    }});
                }}


                // -------------------------
                // DELETE ONLY PLUGIN KEY-VALUE PAIRS
                // -------------------------
                function deletePluginMetadata() {{
                    const projectId = document.getElementById('project_id').value;

                    const pwd = window.prompt("Enter your Omero password to delete ONLY plugin key-value pairs:");
                    if (!pwd) return;

                    if (!window.confirm("Are you absolutely sure? This action is irreversible.")) return;

                    const ctrls = document.querySelectorAll("button,input,select");
                    ctrls.forEach(x => x.disabled = true);

                    const progressSection = document.getElementById("progress-section");
                    const progressText = document.getElementById("progress-text");
                    const progressBar = document.getElementById("progress-bar");
                    const progressLog = document.getElementById("progress-log");

                    progressSection.style.display = "block";
                    progressBar.style.width = "0%";
                    progressBar.innerText = "0%";
                    progressText.innerText = "Deleting plugin key-value pairs…";
                    progressLog.textContent = "";

                    fetch(BASE_URL + "/delete_plugin/", {{
                        method: "POST",
                        headers: {{ "Content-Type": "application/json" }},
                        credentials: "same-origin",
                        body: JSON.stringify({{
                            project_id: projectId,
                            password: pwd
                        }})
                    }})
                    .then(r => r.json())
                    .then(data => {{
                        ctrls.forEach(x => x.disabled = false);

                        let logLines = [];

                        if (data.error) {{
                            logLines.push("ERROR: " + data.error);
                            showImmediateCompletionLog(logLines);
                            return;
                        }}

                        logLines.push(
                            "Deleted plugin annotations for " +
                            data.deleted_images +
                            " images (" +
                            data.deleted_annotations +
                            " MapAnnotations)."
                        );

                        if (data.errors && data.errors.length) {{
                            for (let i = 0; i < data.errors.length; i++) {{
                                logLines.push(
                                    "ERROR image=" +
                                    data.errors[i].image +
                                    " annotation=" +
                                    data.errors[i].annotation
                                );
                            }}
                        }}

                        showImmediateCompletionLog(logLines);
                    }})
                    .catch(err => {{
                        ctrls.forEach(x => x.disabled = false);
                        alert("ERROR: " + err);
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

                    document.getElementById("progress-section").style.display = "block";
                    document.getElementById("progress-text").innerText = "Starting job…";

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

                        document.getElementById("progress-text").innerText =
                            "Job started for " + totalImages + " images.";

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

                    document.getElementById("progress-section").style.display = "block";
                    document.getElementById("progress-text").innerText =
                        "Starting acquisition metadata job…";

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
                            currentJobId = null;
                            document.getElementById("progress-text").innerText = "Error: " + data.error;
                            return;
                        }}

                        let done = data.done;
                        let total = data.total;
                        let percent = data.percent;

                        let bar = document.getElementById("progress-bar");
                        bar.style.width = percent.toFixed(1) + "%";
                        bar.innerText = percent.toFixed(1) + "%";

                        document.getElementById("progress-text").innerText =
                            "Processed " + done + " of " + total + " images (unique IDs).";

                        if (data.last_log) {{
                            let logEl = document.getElementById("progress-log");
                            logEl.textContent += data.last_log + "\\n";
                            logEl.scrollTop = logEl.scrollHeight;
                        }}

                        if (data.finished) {{
                            clearInterval(pollInterval);
                            pollInterval = null;
                            currentJobId = null;
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
            <div style='padding:40px; max-width:600px; margin:0 auto; font-family:"Helvetica Neue", Helvetica, Arial, sans-serif; --base-font-size:14px; font-size:var(--base-font-size);'>
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
