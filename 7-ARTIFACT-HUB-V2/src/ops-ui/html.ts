export function renderOpsHtml(params: { host: string; port: number }): string {
  const { host, port } = params;
  const now = new Date().toISOString();

  return `<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>artifact-hub-v2 ops-ui</title>
    <style>
      body {
        font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        margin: 0;
        padding: 24px;
        background: #0b1020;
        color: #e7eaf3;
      }
      h1,
      h2 {
        margin: 0 0 12px;
      }
      main {
        max-width: 1100px;
      }
      .muted {
        color: #a7b0cc;
      }
      .grid {
        display: grid;
        grid-template-columns: 1fr;
        gap: 16px;
      }
      @media (min-width: 900px) {
        .grid {
          grid-template-columns: 1fr 1fr;
        }
      }
      .panel {
        border: 1px solid rgba(255, 255, 255, 0.12);
        border-radius: 12px;
        padding: 16px;
        background: rgba(255, 255, 255, 0.04);
      }
      .panel.full {
        grid-column: 1 / -1;
      }
      pre {
        margin: 0;
        padding: 12px;
        border-radius: 10px;
        background: rgba(0, 0, 0, 0.35);
        overflow: auto;
        font-size: 12px;
        line-height: 1.5;
      }
      textarea {
        width: 100%;
        min-height: 140px;
        resize: vertical;
        box-sizing: border-box;
        padding: 10px 12px;
        border-radius: 10px;
        border: 1px solid rgba(255, 255, 255, 0.12);
        background: rgba(0, 0, 0, 0.28);
        color: #e7eaf3;
        font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
        font-size: 12px;
        line-height: 1.5;
      }
      input[type="text"] {
        box-sizing: border-box;
        padding: 8px 10px;
        border-radius: 10px;
        border: 1px solid rgba(255, 255, 255, 0.12);
        background: rgba(0, 0, 0, 0.28);
        color: #e7eaf3;
        font-size: 12px;
        line-height: 1.5;
      }
      button {
        padding: 8px 12px;
        border-radius: 10px;
        border: 1px solid rgba(255, 255, 255, 0.18);
        background: rgba(255, 255, 255, 0.08);
        color: #e7eaf3;
        cursor: pointer;
      }
      button:disabled {
        opacity: 0.55;
        cursor: not-allowed;
      }
      .row {
        display: flex;
        gap: 10px;
        align-items: center;
        flex-wrap: wrap;
      }
      .kvs {
        display: grid;
        grid-template-columns: 160px 1fr;
        gap: 8px 12px;
        margin: 0 0 12px;
      }
      .kvs div {
        padding: 2px 0;
      }
      .list {
        display: flex;
        flex-direction: column;
        gap: 8px;
        max-height: 240px;
        overflow: auto;
        padding: 10px;
        border-radius: 10px;
        border: 1px solid rgba(255, 255, 255, 0.12);
        background: rgba(0, 0, 0, 0.18);
      }
      .list button {
        text-align: left;
        width: 100%;
        background: rgba(255, 255, 255, 0.06);
      }
      .list button.active {
        border-color: rgba(255, 255, 255, 0.4);
        background: rgba(255, 255, 255, 0.14);
      }
    </style>
  </head>
  <body>
    <main>
      <h1>artifact-hub-v2 ops-ui</h1>
      <div class="kvs">
        <div class="muted">Listening</div>
        <div>${escapeHtml(host)}:${port}</div>
        <div class="muted">Server now</div>
        <div>${escapeHtml(now)}</div>
        <div class="muted">Last refresh</div>
        <div id="updatedAt" class="muted">-</div>
      </div>

      <div class="grid">
        <section class="panel">
          <h2>Aggregated Health</h2>
          <pre id="healthJson">loading...</pre>
        </section>
        <section class="panel">
          <h2>Queues Snapshot</h2>
          <pre id="queuesJson">loading...</pre>
        </section>
        <section class="panel full">
          <h2>Strategy Stats</h2>
          <pre id="strategyStatsJson">loading...</pre>
        </section>
        <section class="panel full">
          <h2>Route Sandbox</h2>
          <div class="row" style="margin: 0 0 10px">
            <button id="decideBtn" type="button">Decide</button>
            <button id="executeBtn" type="button">Execute</button>
            <span id="routeStatus" class="muted">-</span>
          </div>
          <div style="display: grid; grid-template-columns: 1fr; gap: 12px">
            <div>
              <div class="muted" style="margin: 0 0 6px">Intent JSON</div>
              <textarea id="intentJson">{ "text": "List latest artifacts and decide routing mode" }</textarea>
            </div>
            <div style="display: grid; grid-template-columns: 1fr; gap: 12px">
              <div>
                <div class="muted" style="margin: 0 0 6px">Decide Result</div>
                <pre id="decideJson">-</pre>
              </div>
              <div>
                <div class="muted" style="margin: 0 0 6px">Execute Result</div>
                <pre id="executeJson">-</pre>
              </div>
              <div style="display: grid; grid-template-columns: 1fr; gap: 12px">
                <div>
                  <div class="muted" style="margin: 0 0 6px">DAG Nodes</div>
                  <pre id="dagNodesJson">-</pre>
                </div>
                <div>
                  <div class="muted" style="margin: 0 0 6px">DAG Edges</div>
                  <pre id="dagEdgesJson">-</pre>
                </div>
              </div>
              <div>
                <div class="muted" style="margin: 0 0 6px">Trace</div>
                <pre id="traceJson">-</pre>
              </div>
            </div>
          </div>
        </section>
        <section class="panel full">
          <h2>Classic Strategy Library</h2>
          <div class="row" style="margin: 0 0 10px">
            <input id="strategySearch" type="text" placeholder="Search by title or filename" style="flex: 1; min-width: 220px" />
            <button id="strategyRefreshBtn" type="button">Refresh</button>
            <span id="strategyStatus" class="muted">-</span>
          </div>
          <div style="display: grid; grid-template-columns: 1fr; gap: 12px">
            <div>
              <div class="muted" style="margin: 0 0 6px">List</div>
              <div id="strategyList" class="list">loading...</div>
            </div>
            <div>
              <div class="muted" style="margin: 0 0 6px">Preview (raw markdown)</div>
              <pre id="strategyPreview">-</pre>
            </div>
          </div>
        </section>
      </div>
    </main>
    <script>
      const elUpdatedAt = document.getElementById("updatedAt");
      const elHealth = document.getElementById("healthJson");
      const elQueues = document.getElementById("queuesJson");
      const elStrategyStats = document.getElementById("strategyStatsJson");
      const elIntent = document.getElementById("intentJson");
      const elDecideBtn = document.getElementById("decideBtn");
      const elExecuteBtn = document.getElementById("executeBtn");
      const elRouteStatus = document.getElementById("routeStatus");
      const elDecideJson = document.getElementById("decideJson");
      const elExecuteJson = document.getElementById("executeJson");
      const elDagNodesJson = document.getElementById("dagNodesJson");
      const elDagEdgesJson = document.getElementById("dagEdgesJson");
      const elTraceJson = document.getElementById("traceJson");
      const elStrategySearch = document.getElementById("strategySearch");
      const elStrategyRefreshBtn = document.getElementById("strategyRefreshBtn");
      const elStrategyStatus = document.getElementById("strategyStatus");
      const elStrategyList = document.getElementById("strategyList");
      const elStrategyPreview = document.getElementById("strategyPreview");
      let tracePollTimer = null;
      let tracePollSeq = 0;
      let strategyItems = [];
      let selectedStrategyId = null;

      function safeStringify(x) {
        try {
          return JSON.stringify(x, null, 2);
        } catch {
          return String(x);
        }
      }

      async function fetchJson(url) {
        const res = await fetch(url);
        const text = await res.text();
        try {
          return JSON.parse(text);
        } catch {
          return { ok: false, error: "invalid_json", raw: text };
        }
      }

      function setStatus(text) {
        elRouteStatus.textContent = text;
      }

      function setStrategyStatus(text) {
        elStrategyStatus.textContent = text;
      }

      function readSearchQuery() {
        return ((elStrategySearch.value || "") + "").trim().toLowerCase();
      }

      function formatStrategyLabel(item) {
        const title = item && item.title ? item.title : "-";
        const id = item && item.id ? item.id : "-";
        return title === id ? title : title + " (" + id + ")";
      }

      function renderStrategyList() {
        const q = readSearchQuery();
        const filtered = Array.isArray(strategyItems)
          ? strategyItems.filter((item) => {
              const title = item && item.title ? (item.title + "").toLowerCase() : "";
              const id = item && item.id ? (item.id + "").toLowerCase() : "";
              return q.length === 0 || title.includes(q) || id.includes(q);
            })
          : [];

        elStrategyList.textContent = "";
        if (filtered.length === 0) {
          const empty = document.createElement("div");
          empty.className = "muted";
          empty.textContent = "No strategies";
          elStrategyList.appendChild(empty);
          return;
        }

        for (const item of filtered) {
          const btn = document.createElement("button");
          btn.type = "button";
          btn.textContent = formatStrategyLabel(item);
          if (item && item.id && item.id === selectedStrategyId) btn.classList.add("active");
          btn.addEventListener("click", () => {
            if (!item || !item.id) return;
            selectedStrategyId = item.id;
            renderStrategyList();
            loadStrategyFile(item.id);
          });
          elStrategyList.appendChild(btn);
        }
      }

      async function loadStrategyList() {
        elStrategyRefreshBtn.disabled = true;
        try {
          setStrategyStatus("loading...");
          const data = await fetchJson("/api/ops/strategy-library");
          const items = data && Array.isArray(data.items) ? data.items : [];
          strategyItems = items;
          if (!selectedStrategyId && items.length > 0 && items[0] && items[0].id) {
            selectedStrategyId = items[0].id;
            loadStrategyFile(selectedStrategyId);
          }
          renderStrategyList();
          setStrategyStatus("ok (" + items.length + ")");
        } catch (e) {
          strategyItems = [];
          renderStrategyList();
          setStrategyStatus("error");
          elStrategyPreview.textContent = safeStringify({ ok: false, error: e && e.message ? e.message : String(e) });
        } finally {
          elStrategyRefreshBtn.disabled = false;
        }
      }

      async function loadStrategyFile(id) {
        try {
          setStrategyStatus("loading file...");
          const data = await fetchJson("/api/ops/strategy-library/file?id=" + encodeURIComponent(id));
          if (data && data.ok && data.doc && typeof data.doc.content === "string") {
            elStrategyPreview.textContent = data.doc.content;
            setStrategyStatus("ok");
          } else {
            elStrategyPreview.textContent = safeStringify(data);
            setStrategyStatus("error");
          }
        } catch (e) {
          elStrategyPreview.textContent = safeStringify({ ok: false, error: e && e.message ? e.message : String(e) });
          setStrategyStatus("error");
        }
      }

      function parseIntent() {
        const raw = (elIntent.value || "").trim();
        if (!raw) throw new Error("empty_intent_json");
        return JSON.parse(raw);
      }

      async function postJson(url, body) {
        const res = await fetch(url, {
          method: "POST",
          headers: { "content-type": "application/json; charset=utf-8" },
          body: JSON.stringify(body)
        });
        const text = await res.text();
        try {
          return { ok: res.ok, status: res.status, data: JSON.parse(text) };
        } catch {
          return { ok: false, status: res.status, data: { ok: false, error: "invalid_json", raw: text } };
        }
      }

      function extractDag(plan) {
        const dag = plan && plan.dag ? plan.dag : null;
        return {
          nodes: dag && Array.isArray(dag.nodes) ? dag.nodes : null,
          edges: dag && Array.isArray(dag.edges) ? dag.edges : null
        };
      }

      function stopTracePoll() {
        if (tracePollTimer) clearInterval(tracePollTimer);
        tracePollTimer = null;
      }

      function startTracePoll(traceId) {
        stopTracePoll();
        const seq = ++tracePollSeq;
        let attempts = 0;
        tracePollTimer = setInterval(async () => {
          if (seq !== tracePollSeq) return;
          attempts += 1;
          try {
            const trace = await fetchJson("/api/ops/traces/" + encodeURIComponent(traceId));
            elTraceJson.textContent = safeStringify(trace);
            const decision = trace && trace.decision && trace.decision.decision ? trace.decision.decision : null;
            const dag = extractDag(decision);
            if (dag.nodes) elDagNodesJson.textContent = safeStringify(dag.nodes);
            if (dag.edges) elDagEdgesJson.textContent = safeStringify(dag.edges);
            const events = trace && Array.isArray(trace.events) ? trace.events : [];
            const done = events.some((e) => e && e.type === "result.detected");
            if (done || attempts >= 40) stopTracePoll();
          } catch (e) {
            elTraceJson.textContent = safeStringify({ ok: false, error: e && e.message ? e.message : String(e) });
            if (attempts >= 6) stopTracePoll();
          }
        }, 1500);
      }

      async function doDecide() {
        elDecideBtn.disabled = true;
        elExecuteBtn.disabled = true;
        try {
          setStatus("deciding...");
          const intent = parseIntent();
          const out = await postJson("/api/ops/route/decide", intent);
          elDecideJson.textContent = safeStringify(out);
          const plan = out && out.data ? out.data : null;
          const dag = extractDag(plan);
          elDagNodesJson.textContent = safeStringify(dag.nodes);
          elDagEdgesJson.textContent = safeStringify(dag.edges);
          setStatus("decide done (" + out.status + ")");
        } catch (e) {
          setStatus("decide error");
          elDecideJson.textContent = safeStringify({ ok: false, error: e && e.message ? e.message : String(e) });
        } finally {
          elDecideBtn.disabled = false;
          elExecuteBtn.disabled = false;
        }
      }

      async function doExecute() {
        elDecideBtn.disabled = true;
        elExecuteBtn.disabled = true;
        try {
          setStatus("executing...");
          const intent = parseIntent();
          const out = await postJson("/api/ops/route/execute", intent);
          elExecuteJson.textContent = safeStringify(out);
          const traceId = out && out.data && out.data.trace_id ? out.data.trace_id : null;
          if (traceId) {
            setStatus("execute done (" + out.status + "), polling trace " + traceId);
            startTracePoll(traceId);
          } else {
            setStatus("execute done (" + out.status + ")");
          }
        } catch (e) {
          setStatus("execute error");
          elExecuteJson.textContent = safeStringify({ ok: false, error: e && e.message ? e.message : String(e) });
        } finally {
          elDecideBtn.disabled = false;
          elExecuteBtn.disabled = false;
        }
      }

      async function refresh() {
        const startedAt = Date.now();
        const [health, queues, strategyStats] = await Promise.allSettled([
          fetchJson("/api/ops/health"),
          fetchJson("/api/ops/queues"),
          fetchJson("/api/ops/strategy-stats")
        ]);

        const healthValue = health.status === "fulfilled" ? health.value : { ok: false, error: String(health.reason) };
        const queuesValue = queues.status === "fulfilled" ? queues.value : { ok: false, error: String(queues.reason) };
        const statsValue =
          strategyStats.status === "fulfilled" ? strategyStats.value : { ok: false, error: String(strategyStats.reason) };

        elHealth.textContent = safeStringify(healthValue);
        elQueues.textContent = safeStringify(queuesValue);
        elStrategyStats.textContent = safeStringify(statsValue);
        elUpdatedAt.textContent = new Date().toISOString() + " (" + (Date.now() - startedAt) + "ms)";
      }

      refresh();
      setInterval(refresh, 3000);
      elDecideBtn.addEventListener("click", doDecide);
      elExecuteBtn.addEventListener("click", doExecute);
      elStrategyRefreshBtn.addEventListener("click", loadStrategyList);
      elStrategySearch.addEventListener("input", renderStrategyList);
      loadStrategyList();
    </script>
  </body>
</html>`;
}

function escapeHtml(input: string): string {
  return input
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}
