from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from omeroweb.decorators import login_required
import json
import logging
import re
from ..services.core import (
    get_id,
    get_text,
    collect_images_by_dataset_sorted,
    parse_filename,
)
from ..constants import DEFAULT_VARIABLE_NAMES
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
            separator_mode = request.POST.get("separator_mode", "chars")

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
                    <td style='padding:2px;'>
                        <div class="clamp-2">
                            {ds_label}
                        </div>
                    </td>
                    <td style='padding:2px;'>
                        <div class="nowrap-1">
                            {img_id}
                        </div>
                    </td>
                    <td style='padding:2px;'>
                        <div class="clamp-2">
                            {fname}
                        </div>
                    </td>
                    <td style='padding:2px;'>
                        <div class="clamp-2">
                            {kv}
                        </div>
                    </td>
                </tr>
                """

            var_inputs_html = ""
            for i in range(1, max_vars + 1):
                var_inputs_html += f"""
                <div class="var-row">
                    <div class="var-index">{i}:</div>
                    <input id="var_name_{i}"
                           type="text"
                           value=""
                           class="var-input">
                </div>
                """

            return HttpResponse(f"""
                <div class="omeroweb-filenamemetadata"
                     style='padding:10px; --base-font-size:14px; font-size:var(--base-font-size); min-width:900px; max-width:1200px; margin:0 auto;'>
                    <div style='display:grid; grid-template-columns: 1fr auto 1fr; align-items:center; gap:8px; margin-bottom:10px;'>

                        <div style="display:flex; justify-content:flex-start; align-items:center;">
                            <h2 style='color:#007bff; margin:0;'>
                                <span aria-hidden="true"
                                      style="display:inline-block; margin-right:6px; pointer-events:none;">
                                    📊
                                </span>
                                <span>
                                    Preview parsed filenames
                                </span>
                            </h2>
                        </div>

                        <div style="display:flex; justify-content:center; align-items:center;">
                            <button onclick="goBack()"
                                    style='padding:8px 8px; font-size:12px;'>
                                <span aria-hidden="true"
                                      style="display:inline-block; margin-right:4px; pointer-events:none;">
                                    ←
                                </span>
                                <span>
                                    Go back to project selection
                                </span>
                            </button>
                        </div>

                        <div style="display:flex; justify-content:flex-end; align-items:center;">
                            <button onclick='scrollToBottom()'
                                    style='padding:8px 8px; font-size:12px;'>
                                <span aria-hidden="true"
                                      style="display:inline-block; margin-right:4px; pointer-events:none;">
                                    ↓
                                </span>
                                <span>
                                    Scroll to bottom
                                </span>
                            </button>
                        </div>

                    </div>

                    <p>Project: {project_label} | Separator(s): "{raw_seps}"</p>
                    <p>Previewing {len(preview_rows)} images.</p>
                    <table border='1' style='width:100%; border-collapse:collapse; font-family:"Helvetica Neue", Helvetica, Arial, sans-serif; font-size:12px; margin-bottom:10px;'>
                        <tr style='background:#007bff; color:white;'>
                            <td style='padding:3px;'>Dataset</td>
                            <td style='padding:3px;'>ID</td>
                            <td style='padding:3px;'>Filename</td>
                            <td style='padding:3px;'>Parsed variables</td>
                        </tr>
                        {rows_html}
                    </table>

                    <hr>

                    <div id='var-config' data-var-count='{max_vars}'>
                        <div style='
                                display:grid;
                                grid-template-columns: 300px minmax(0, 1fr);
                                column-gap:15px;
                                align-items:start;
                                width:100%;
                            '>
                            <div style='min-width:300px;'>
                                <label style="font-size:12px; display:block; margin-bottom:6px;">
                                    Variable names: for guidelines see 
                                    <a href="https://www.ebi.ac.uk/bioimage-archive/rembi-help-overview/"
                                       target="_blank"
                                       rel="noopener noreferrer"
                                       style="color:#007bff; font-weight:600; text-decoration:none;
                                              background:rgba(0,123,255,0.12); padding:1px 4px;
                                              border-radius:4px;">
                                        REMBI
                                    </a>
                                </label>

                                <label style="font-size:12px; display:flex; align-items:center; gap:6px;">
                                    <input type="checkbox" id="use_defaults" checked onclick="toggleVarNameInputs()">
                                    Use default names
                                </label>
                                <div id='var_name_inputs' style='margin-top:10px;'>
                                    {var_inputs_html}
                                </div>
                            </div>
                            
                            <div id='variable-set-block'
                                style="
                                       display:grid;
                                       grid-auto-rows:auto;
                                       row-gap:15px;
                                       min-width:0;
                                ">

                                <div>
                                    <label for='variable_set_select'
                                           style='font-size:12px; display:block; margin-bottom:5px;'>
                                        Variable sets in database
                                    </label>

                                <div class="varset-row-3">
                                    <select id='variable_set_select'
                                            class="varset-control">
                                        <option value=''>Select or create…</option>
                                    </select>
                                    <button id='load_variable_set_btn'
                                            onclick='loadVariableSet()'
                                            class="varset-btn varset-btn-blue">
                                        Load from database
                                    </button>
                                    <button id='delete_variable_set_btn'
                                            onclick='deleteVariableSet()'
                                            class="varset-btn varset-btn-red">
                                        Delete from database
                                    </button>
                                </div>

                                </div>

                                <div>
                                    <label for='variable_set_name'
                                           style='font-size:12px; display:block; margin-bottom:5px;'>
                                        Variable set name for saving
                                    </label>

                                    <div class="varset-row-2">
                                        <input id='variable_set_name'
                                               type='text'
                                               placeholder='e.g. Electron microscopy'
                                               class="varset-control">

                                        <button id='save_variable_set_btn'
                                                onclick='saveVariableSet()'
                                                class="varset-btn varset-btn-green">
                                            Save to database
                                        </button>
                                    </div>
                                </div>

                            </div>
                        </div>
                    </div>

                    <!-- HELP BUTTON (GLOBAL APP HELP — NEVER DISABLED) -->
                    <div style="display:flex; justify-content:flex-end; margin-top:6px;">
                        <a href="/omeroweb_filenamemetadata/help/"
                           target="_blank"
                           rel="noopener noreferrer"
                           title="Help"
                           aria-label="Help"
                           class="help-btn">
                            ?
                        </a>
                    </div>

                    <hr>

                    <div style='
                            display:grid;
                            grid-template-columns: 1fr auto 1fr;
                            align-items:center;
                            column-gap:50px;
                            width:100%;
                        '>

                        <div style="display:flex; justify-content:flex-start; align-items:center;">
                            <!-- LEFT SAVE BUTTON -->
                            <button onclick='startSaveJob()'
                                    style='padding:8px 8px; font-size:12px; background:#28a745; color:white;
                                           border:none; border-radius:6px; cursor:pointer;'>
                                <span aria-hidden="true"
                                      style="display:inline-block; margin-right:6px; pointer-events:none;">
                                    💾
                                </span>
                                <span>
                                    Save filename metadata into key-value pairs
                                </span>
                            </button>
                        </div>

                        <div style="display:flex; justify-content:center; align-items:center;">
                            <!-- CENTER ACQ BUTTON -->
                            <button onclick="startAcquisitionMetadataJob()"
                                    style='padding:8px 8px; font-size:12px; background:#0069d9; color:white;
                                           border:none; border-radius:6px; cursor:pointer;'>
                                <span aria-hidden="true"
                                      style="display:inline-block; margin-right:6px; pointer-events:none;">
                                    📥
                                </span>
                                <span>
                                    Copy acquisition metadata into key-value pairs
                                </span>
                            </button>
                        </div>

                        <div style="display:flex; justify-content:flex-end; align-items:center;">
                            <!-- RIGHT DELETE BUTTON (PLUGIN ONLY) -->
                            <button onclick='deletePluginMetadata()'
                                    style='padding:8px 8px; font-size:12px; background:#fd7e14; color:white;
                                           border:none; border-radius:6px; cursor:pointer;'>
                                <span aria-hidden="true"
                                      style="display:inline-block; margin-right:6px; pointer-events:none;">
                                    🗑
                                </span>
                                <span>
                                    Delete ONLY plugin key-value pairs
                                </span>
                            </button>
                        </div>

                    </div>

                    <div style='display:flex; justify-content:space-between; align-items:center; margin-top:20px;'>
                        <div></div>

                        <!-- DELETE ALL BUTTON -->
                        <button onclick='deleteAllMetadata()'
                                style='padding:8px 8px; font-size:12px; background:#dc3545; color:white;
                                       border:none; border-radius:6px; cursor:pointer;'>
                            <span aria-hidden="true"
                                  style="display:inline-block; margin-right:6px; pointer-events:none;">
                                🗑
                            </span>
                            <span>
                                Delete ALL key-value pairs
                            </span>
                        </button>
                    </div>

                    <div style='display:grid; grid-template-columns: 1fr auto 1fr; align-items:center; margin-top:20px;'>

                        <div></div>

                        <div style="display:flex; justify-content:center; align-items:center;">
                            <button onclick="goBack()"
                                    style='padding:8px 8px; font-size:12px;'>
                                <span aria-hidden="true"
                                      style="display:inline-block; margin-right:4px; pointer-events:none;">
                                    ←
                                </span>
                                <span>
                                    Go back to project selection
                                </span>
                            </button>
                        </div>

                        <div style="display:flex; justify-content:flex-end; align-items:center;">
                            <button onclick='scrollToTop()'
                                    style='padding:8px 8px; font-size:12px;'>
                                <span aria-hidden="true"
                                      style="display:inline-block; margin-right:4px; pointer-events:none;">
                                    ↑
                                </span>
                                <span>
                                    Scroll to top
                                </span>
                            </button>
                        </div>

                    </div>

                    <!-- HIDDEN FIELDS -->
                    <input type='hidden' id='project_id' value='{project_id}'>
                    <input type='hidden' id='separator' value='{raw_seps}'>
                    <input type='hidden' id='separator_mode' value='{separator_mode}'>

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

                <!-- NON-BLOCKING MODAL -->
                <div id="nb-modal-overlay"
                     style="display:none; position:fixed; inset:0; background:rgba(0,0,0,0.3);
                            z-index:9999; align-items:center; justify-content:center;">

                    <div style="background:#ffffff; padding:20px 24px; border-radius:8px;
                                box-shadow:0 10px 30px rgba(0,0,0,0.25);
                                font-size:13px; min-width:300px; max-width:500px;">

                        <div id="nb-modal-message"
                             style="margin-bottom:16px;">
                        </div>

                        <div style="text-align:right;">
                            <button onclick="hideNonBlockingModal()"
                                    style="padding:6px 14px; font-size:12px;">
                                OK
                            </button>
                        </div>
                    </div>
                </div>

                <style>
                    html,
                    body {{
                        min-width: 1300px;
                    }}

                    #var_name_inputs {{margin-top: 6px;}}
                    .var-row {{display: grid; grid-template-columns: 2.5em auto; align-items: center; column-gap: 6px; margin-bottom: 4px;}}
                    .var-index {{text-align: right; font-size: 12px; color: #212529;}}
                    .var-input {{font-size: 12px; padding: 4px 8px; width: 200px; border: none; border-radius: 6px; background: #ffffff;
                                 box-shadow: inset 0 0 0 1px #007bff; box-sizing: border-box;}}
                    .omeroweb-filenamemetadata, .omeroweb-filenamemetadata * {{font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;}}
                    .nowrap-1 {{white-space: nowrap; overflow: hidden; text-overflow: ellipsis;}}
                    #variable-set-block * {{min-width: 0;}}
                    .clamp-2 {{display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 2; overflow: hidden; text-overflow: ellipsis;
                               word-break: break-word; white-space: normal; overflow-wrap: anywhere;}}
                    .ui-faded {{opacity: 0.3; filter: grayscale(100%); pointer-events: none;}}
                    .varset-control {{font-size: 12px; width: 240px; max-width: 240px; padding: 8px 8px; border: none; border-radius: 6px;
                                      background: #ffffff; box-shadow: inset 0 0 0 1px #007bff; box-sizing: border-box;}}
                    .varset-btn {{font-size: 12px; width: 140px; min-width: 140px; padding: 8px 8px; white-space: nowrap; color: white;
                                  border: none; border-radius: 6px; cursor: pointer; justify-self: start;}}
                    .varset-btn-blue {{background: #0069d9;}}
                    .varset-btn-red  {{background: #dc3545;}}
                    .varset-btn-green {{background: #28a745;}}
                    .varset-row-3 {{display: grid; grid-template-columns: 240px 140px 140px; column-gap: 15px; row-gap: 10px; align-items: center;
                                   justify-content: start; justify-items: start; width: 100%;}}
                    .varset-row-2 {{display: grid; grid-template-columns: 240px 140px; column-gap: 15px; row-gap: 10px; align-items: center;
                                    justify-content: start; justify-items: start; width: 100%;}}
                    @media (max-width: 900px) {{
                        .varset-row-3 {{
                            grid-template-columns: 240px 140px;
                        }}
                        #delete_variable_set_btn {{
                            grid-column: 2;
                        }}
                    }}

                    @media (max-width: 520px) {{
                        .varset-row-3,
                        .varset-row-2 {{
                            grid-template-columns: 1fr;
                        }}
                        .varset-control {{
                            width: 100%;
                            max-width: none;
                        }}
                        .varset-btn {{
                            width: 100%;
                            min-width: 0;
                        }}
                        #delete_variable_set_btn,
                        #load_variable_set_btn,
                        #save_variable_set_btn {{
                            grid-column: auto;
                        }}
                    }}
                    .help-btn {{width:26px; height:26px; border-radius:50%; background:#007bff; color:white; font-size:14px; font-weight:700;
                                line-height:26px; text-align:center; text-decoration:none; box-shadow:0 1px 4px rgba(0,0,0,0.25); cursor:pointer;
                                transition: background 0.15s ease, transform 0.1s ease;}}
                    .help-btn:hover {{background:#0056b3; transform: translateY(-1px);}}
                </style>

                <script>
                const BASE_URL = "/omeroweb_filenamemetadata";
                const DEFAULT_VARS = {json.dumps(DEFAULT_VARIABLE_NAMES)};
                let availableVariableSets = [];

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

                function setVarSetControlsDisabled(disabled) {{
                    const select = document.getElementById('variable_set_select');
                    const saveBtn = document.getElementById('save_variable_set_btn');
                    const loadBtn = document.getElementById('load_variable_set_btn');
                    const nameInput = document.getElementById('variable_set_name');
                    const block = document.getElementById('variable-set-block');
                    const deleteBtn = document.getElementById('delete_variable_set_btn');
                    [select, saveBtn, loadBtn, deleteBtn, nameInput].forEach(el => {{
                        if (el) {{
                            el.disabled = !!disabled;
                        }}
                    }});
                    if (block) {{
                        if (disabled) {{
                            block.classList.add('ui-faded');
                        }} else {{
                            block.classList.remove('ui-faded');
                        }}
                    }}
                }}

                function toggleVarNameInputs() {{
                    let useDefaults = document.getElementById('use_defaults').checked;
                    let container = document.getElementById('var-config');
                    let count = parseInt(container.getAttribute('data-var-count'));
                    for (let i = 1; i <= count; i++) {{
                        let inp = document.getElementById('var_name_' + i);
                        if (!inp) {{
                            continue;
                        }}
                        if (useDefaults) {{
                            inp.value = DEFAULT_VARS[i - 1] || "empty";
                            inp.disabled = true;
                        }} else {{
                            inp.disabled = false;
                        }}
                    }}
                    setVarSetControlsDisabled(useDefaults);
                }}

                function populateVariableSetDropdown(sets) {{
                    const select = document.getElementById('variable_set_select');
                    if (!select) return;

                    const currentValue = select.value;

                    availableVariableSets = sets || [];
                    select.innerHTML = "";

                    if (!availableVariableSets.length) {{
                        const opt = document.createElement('option');
                        opt.value = "";
                        opt.textContent = "No saved sets";
                        select.appendChild(opt);
                        return;
                    }}

                    const placeholder = document.createElement('option');
                    placeholder.value = "";
                    placeholder.textContent = "Select a saved set";
                    select.appendChild(placeholder);

                    availableVariableSets.forEach(name => {{
                        const opt = document.createElement('option');
                        opt.value = name;
                        opt.textContent = name;
                        if (name === currentValue) {{
                            opt.selected = true;
                        }}
                        select.appendChild(opt);
                    }});
                }}

                function fetchVariableSets() {{
                    fetch(BASE_URL + "/varsets/", {{
                        method: "GET",
                        headers: {{ "Accept": "application/json" }},
                        credentials: "same-origin",
                    }})
                    .then(r => r.json())
                    .then(data => {{
                        if (data.error) {{
                            console.warn("Unable to load variable sets", data.error);
                            populateVariableSetDropdown([]);
                            return;
                        }}

                        populateVariableSetDropdown(data.sets || []);
                    }})
                    .catch(err => {{
                        console.warn("Error loading variable sets", err);
                        populateVariableSetDropdown([]);
                    }});
                }}

                function saveVariableSet() {{
                    const useDefaults = document.getElementById('use_defaults').checked;
                    if (useDefaults) return;

                    const nameInput = document.getElementById('variable_set_name');
                    const setName = (nameInput.value || "").trim();
                    const container = document.getElementById('var-config');
                    const count = parseInt(container.getAttribute('data-var-count'));

                    let varNames = [];
                    for (let i = 1; i <= count; i++) {{
                        const inp = document.getElementById('var_name_' + i);
                        const val = inp ? inp.value.trim() : "";
                        varNames.push(val);
                    }}

                    const nonEmpty = varNames.filter(v => v !== "");
                    if (!nonEmpty.length) {{
                        showNonBlockingModal("Cannot save to database. List of variables empty.");
                        return;
                    }}

                    if (!setName) {{
                        showNonBlockingModal("Please provide a name for this variable set.");
                        return;
                    }}

                    fetch(BASE_URL + "/varsets/save/", {{
                        method: "POST",
                        headers: {{ "Content-Type": "application/json" }},
                        credentials: "same-origin",
                        body: JSON.stringify({{ set_name: setName, var_names: varNames }})
                    }})
                    .then(r => r.json())
                    .then(data => {{
                        if (data.error) {{
                            showNonBlockingModal(data.error);
                            return;
                        }}
                        fetchVariableSets();
                        showNonBlockingModal('Saved variable set "' + setName + '" to database.');
                    }})
                    .catch(err => {{
                        showNonBlockingModal("Error saving variable set: " + err);
                    }});
                }}

                function showNonBlockingModal(message) {{
                    const overlay = document.getElementById("nb-modal-overlay");
                    const msg = document.getElementById("nb-modal-message");

                    if (!overlay || !msg) {{
                        return;
                    }}

                    msg.textContent = message;
                    overlay.style.display = "flex";
                }}

                function hideNonBlockingModal() {{
                    const overlay = document.getElementById("nb-modal-overlay");
                    if (overlay) {{
                        overlay.style.display = "none";
                    }}
                }}

                function loadVariableSet() {{
                    const useDefaults = document.getElementById('use_defaults').checked;
                    if (useDefaults) return;

                    if (!availableVariableSets.length) {{
                        showNonBlockingModal("Your user database is empty. Please save a variable set first.");
                        return;
                    }}

                    const select = document.getElementById('variable_set_select');
                    const selected = select ? (select.value || "").trim() : "";

                    if (!selected) {{
                        showNonBlockingModal("Please select a variable set from the dropdown menu.");
                        return;
                    }}

                    fetch(BASE_URL + "/varsets/load/?set_name=" + encodeURIComponent(selected), {{
                        method: "GET",
                        headers: {{ "Accept": "application/json" }},
                        credentials: "same-origin",
                    }})
                    .then(r => r.json())
                    .then(data => {{
                        if (data.error) {{
                            showNonBlockingModal(data.error);
                            return;
                        }}

                        const container = document.getElementById('var-config');
                        const count = parseInt(container.getAttribute('data-var-count'));
                        const saved = data.var_names || [];

                        for (let i = 1; i <= count; i++) {{
                            const val = saved[i - 1];
                            const inp = document.getElementById('var_name_' + i);
                            if (inp && val && String(val).trim() !== "") {{
                                inp.value = val;
                            }}
                        }}

                        showNonBlockingModal('Loaded variable set "' + selected + '" from database.');
                    }})
                    .catch(err => {{
                        showNonBlockingModal("Error loading variable set: " + err);
                    }});
                }}

                // -------------------------
                // DELETE VARIABLE SET FROM DATABASE
                // -------------------------
                function deleteVariableSet() {{
                    const useDefaults = document.getElementById('use_defaults').checked;
                    if (useDefaults) {{
                        return;
                    }}

                    const select = document.getElementById('variable_set_select');
                    const selected = select ? (select.value || "").trim() : "";

                    if (!selected) {{
                        showNonBlockingModal("Please select a variable set from the dropdown menu.");
                        return;
                    }}

                    if (!window.confirm(
                        "Are you absolutely sure? This action is irreversible."
                    )) {{
                        return;
                    }}

                    fetch(BASE_URL + "/varsets/delete/", {{
                        method: "POST",
                        headers: {{ "Content-Type": "application/json" }},
                        credentials: "same-origin",
                        body: JSON.stringify({{
                            set_name: selected
                        }})
                    }})
                    .then(r => r.json())
                    .then(data => {{
                        if (data.error) {{
                            showNonBlockingModal(data.error);
                            return;
                        }}

                        fetchVariableSets();

                        showNonBlockingModal('Deleted variable set "' + selected + '" from database.');

                    }})
                    .catch(err => {{
                        showNonBlockingModal("Error deleting variable set: " + err);
                    }});
                }}

                toggleVarNameInputs();
                fetchVariableSets();

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
                        showNonBlockingModal("ERROR: " + err);
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
                    progressText.innerText = "Deleting ONLY plugin key-value pairs…";
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
                        showNonBlockingModal("ERROR: " + err);
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
                        showNonBlockingModal("Another job is already running. Please be patient.");
                        return;
                    }}

                    const projectId = document.getElementById('project_id').value;
                    const separator = document.getElementById('separator').value;
                    const separatorMode = document.getElementById('separator_mode').value;

                    const container = document.getElementById('var-config');
                    const count = parseInt(container.getAttribute('data-var-count'));
                    const useDefaults = document.getElementById('use_defaults').checked;

                    let varNames = [];
                    for (let i = 1; i <= count; i++) {{
                        const inp = document.getElementById('var_name_' + i);
                        const val = inp ? inp.value.trim() : "";
                        varNames.push(val);
                    }}

                    // FIX: delete_mode *not* "keep", prevents double saves
                    let payload = {{
                        project_id: projectId,
                        separator: separator,
                        separator_mode: separatorMode,
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
                        showNonBlockingModal("Another job is already running. Please be patient.");
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
            <div class="omeroweb-filenamemetadata"
                 style='padding:40px; max-width:600px; margin:0 auto; --base-font-size:14px; font-size:var(--base-font-size);'>
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
                        <label><strong>Separators:</strong></label><br>

                        <input type='hidden'
                               name='separator_mode'
                               id='separator_mode'
                               value='chars'>

                        <div style='display:flex; align-items:flex-start; gap:14px;'>
                            <input type='text'
                                   name='separator'
                                   value='_-'
                                   style='width:55%;padding:12px;border-radius:6px;border:1px solid #007bff;'>

                            <div style='display:flex; flex-direction:column; gap:8px; padding-top:4px;'>
                                <label style='display:flex; align-items:center; gap:8px; font-weight:600;'>
                                    <input type='checkbox'
                                           id='sep_mode_chars'
                                           checked
                                           onclick='setSeparatorMode("chars")'>
                                    <span>Characters</span>
                                </label>

                                <label style='display:flex; align-items:center; gap:8px; font-weight:600;'>
                                    <input type='checkbox'
                                           id='sep_mode_regex'
                                           onclick='setSeparatorMode("regex")'>
                                    <span>Regex pattern</span>
                                </label>
                            </div>
                        </div>
                    </div>

                    <button type='submit'
                            style='width:100%;padding:18px;font-size:14px;background:#007bff;color:white;
                                   border:none;border-radius:8px;'>
                        Load images & Preview
                    </button>
                </form>

                <script>
                function setSeparatorMode(mode) {
                    const chars = document.getElementById('sep_mode_chars');
                    const regex = document.getElementById('sep_mode_regex');
                    const hidden = document.getElementById('separator_mode');

                    if (mode === 'regex') {
                        regex.checked = true;
                        chars.checked = false;
                        hidden.value = 'regex';
                    } else {
                        chars.checked = true;
                        regex.checked = false;
                        hidden.value = 'chars';
                    }
                }

                // Ensure exactly one mode is selected even if browser restores form state
                (function initSeparatorMode() {
                    const chars = document.getElementById('sep_mode_chars');
                    const regex = document.getElementById('sep_mode_regex');
                    if (regex && regex.checked) {
                        setSeparatorMode('regex');
                    } else {
                        setSeparatorMode('chars');
                    }
                })();
                </script>

            </div>
        """)

    except Exception as e:
        logger.exception("Unhandled error in index(): %s", e)
        return HttpResponse(f"<h2>Error: {e}</h2>")
