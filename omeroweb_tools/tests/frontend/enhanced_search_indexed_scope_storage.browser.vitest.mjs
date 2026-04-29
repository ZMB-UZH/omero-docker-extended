(() => {
  const { beforeEach, describe, expect, it } = globalThis;

  const scriptUrl =
    "/__preview_static__/omeroweb_tools/enhanced_search_indexed_scope.js";
  const stylesUrl = "/__preview_static__/omeroweb_tools/styles.css";

  /** Loads the indexed-scope persistence script into the preview page. */
  async function loadPersistenceScript() {
    window.OmeroEnhancedSearchIndexedScope = undefined;
    const response = await fetch(scriptUrl);
    expect(response.ok).toBe(true);
    const source = await response.text();
    Function(source)();
    expect(window.OmeroEnhancedSearchIndexedScope).toBeTruthy();
  }

  /** Installs the minimal indexed-scope form fixture used by persistence tests. */
  function installFixture({ search = "", storageKey = "scope-key" } = {}) {
    window.history.replaceState({}, "", `/${search}`);
    document.body.innerHTML = `
    <script id="tools-search-indexed-scope-storage-key" type="application/json">${JSON.stringify(storageKey)}</script>
    <select id="indexed_scope">
      <option value="omero_builtin">OMERO index</option>
      <option value="acquisition_metadata">Universal metadata index</option>
      <option value="all_indexed_scopes">All searchable sources</option>
    </select>
  `;
    window.localStorage.clear();
    return document.getElementById("indexed_scope");
  }

  /** Loads Enhanced Search styles into the preview page for layout assertions. */
  async function loadStyles() {
    const response = await fetch(stylesUrl);
    expect(response.ok).toBe(true);
    const style = document.createElement("style");
    style.textContent = await response.text();
    document.head.appendChild(style);
  }

  describe("Enhanced Search indexed-scope browser persistence", () => {
    beforeEach(async () => {
      await loadPersistenceScript();
    });

    it("restores a valid stored scope when no server-backed query is present", () => {
      const select = installFixture();
      window.localStorage.setItem("scope-key", "acquisition_metadata");

      const applied = [];
      const handle = window.OmeroEnhancedSearchIndexedScope.init({
        onStoredScopeApplied: (value) => applied.push(value),
      });

      expect(handle.storageKey).toBe("scope-key");
      expect(select.value).toBe("acquisition_metadata");
      expect(window.localStorage.getItem("scope-key")).toBe(
        "acquisition_metadata",
      );
      expect(applied).toEqual(["acquisition_metadata"]);
    });

    it("lets explicit URL state win and writes that selection back to storage", () => {
      const select = installFixture({ search: "?indexed_scope=omero_builtin" });
      select.value = "all_indexed_scopes";
      window.localStorage.setItem("scope-key", "acquisition_metadata");

      window.OmeroEnhancedSearchIndexedScope.init();

      expect(select.value).toBe("all_indexed_scopes");
      expect(window.localStorage.getItem("scope-key")).toBe(
        "all_indexed_scopes",
      );
    });

    it("removes stale stored values and persists later user changes", () => {
      const select = installFixture();
      window.localStorage.setItem("scope-key", "deleted_scope");

      window.OmeroEnhancedSearchIndexedScope.init();

      expect(window.localStorage.getItem("scope-key")).toBe("omero_builtin");
      select.value = "all_indexed_scopes";
      select.dispatchEvent(new Event("change", { bubbles: true }));
      expect(window.localStorage.getItem("scope-key")).toBe(
        "all_indexed_scopes",
      );
    });

    it("keeps the real result-table header fixed only when a result table exists", async () => {
      await loadStyles();
      document.body.innerHTML = `
      <div class="tools-search-results-body" style="height: 180px; overflow-y: auto;">
        <table class="tools-search-results">
          <thead>
            <tr>
              <th>Preview</th>
              <th>Image</th>
              <th>Project / Dataset</th>
              <th>Acquisition</th>
              <th>Channel(s)</th>
            </tr>
          </thead>
          <tbody>
            ${Array.from(
              { length: 30 },
              (_, index) => `
              <tr>
                <td>Preview ${index}</td>
                <td>Image ${index}</td>
                <td>Dataset ${index}</td>
                <td>Date ${index}</td>
                <td>Channel ${index}</td>
              </tr>
            `,
            ).join("")}
          </tbody>
        </table>
      </div>
    `;
      const scroller = document.querySelector(".tools-search-results-body");
      const header = document.querySelector(".tools-search-results thead th");
      const initialTop = header.getBoundingClientRect().top;
      const style = getComputedStyle(header);

      expect(style.position).toBe("sticky");
      expect(style.top).toBe("0px");
      scroller.scrollTop = 240;
      await new Promise((resolve) => requestAnimationFrame(resolve));

      expect(
        Math.abs(header.getBoundingClientRect().top - initialTop),
      ).toBeLessThan(1);

      document.body.innerHTML =
        '<p class="tools-search-empty">No matching images were found.</p>';
      expect(document.querySelector(".tools-search-results thead")).toBeNull();
    });

    it("uses the compact card gap and constrained results height", async () => {
      await loadStyles();
      document.body.innerHTML = `
      <main class="tools-search-layout">
        <section class="tools-search-card">Search</section>
        <section class="tools-search-card">Index</section>
        <section class="tools-search-card tools-search-card--results">
          <div class="tools-search-results-body"></div>
        </section>
      </main>
    `;

      expect(
        getComputedStyle(document.querySelector(".tools-search-layout")).gap,
      ).toBe("14px");
      expect(
        getComputedStyle(document.querySelector(".tools-search-card--results"))
          .maxHeight,
      ).toBe("640px");
    });
  });
})();
