function escapeHtml(s: string): string {
  return s
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function renderKeyValueRow(k: string, v: string): string {
  return `<tr><td style="padding:6px 10px;border:1px solid #eee;background:#fafafa;">${escapeHtml(
    k
  )}</td><td style="padding:6px 10px;border:1px solid #eee;">${escapeHtml(v)}</td></tr>`;
}

export function renderDashboard(input: { tasks: any | null; rewards: any | null }): string {
  const tasksIndex = input.tasks;
  const rewardsIndex = input.rewards;

  const generatedAt = String(tasksIndex?.generated_at || rewardsIndex?.generated_at || "");
  const openTaskIds: string[] = Array.isArray(tasksIndex?.open_tasks) ? tasksIndex.open_tasks : [];
  const taskRecords: any[] = Array.isArray(tasksIndex?.tasks) ? tasksIndex.tasks : [];
  const rewardRecords: any[] = Array.isArray(rewardsIndex?.reward_records) ? rewardsIndex.reward_records : [];

  const taskById = new Map<string, any>();
  for (const t of taskRecords) taskById.set(String(t.task_id || ""), t);

  const openTasks = openTaskIds
    .map((id) => ({ id, t: taskById.get(id) }))
    .map(({ id, t }) => ({
      id,
      title: String(t?.title || ""),
      status: String(t?.status || ""),
      owner: String(t?.owner_agent || ""),
      workspace: String(t?.workspace_path || ""),
    }));

  const recentTasks = taskRecords
    .slice()
    .reverse()
    .slice(0, 8)
    .map((t) => ({
      id: String(t.task_id || ""),
      title: String(t.title || ""),
      status: String(t.status || ""),
      workspace: String(t.workspace_path || ""),
    }));

  const recentRewards = rewardRecords.slice().reverse().slice(0, 8).map((r) => ({
    taskId: String(r.task_id || ""),
    finalReward: String(r.final_reward ?? ""),
    creditedAgent: String(r.credited_agent || ""),
    creditedAt: String(r.credited_at || ""),
  }));

  const missing =
    !tasksIndex && !rewardsIndex ? "ledger index not found" : (!tasksIndex ? "tasks index not found" : "");

  const body = `
  <h1 style="margin:0 0 10px 0;font:600 20px/1.2 system-ui;">ops-ui / ledger</h1>
  <div style="color:#666;font:12px/1.4 system-ui;margin-bottom:12px;">${escapeHtml(
    missing ? missing : generatedAt ? `generated_at: ${generatedAt}` : ""
  )}</div>
  <table style="border-collapse:collapse;width:100%;font:13px/1.4 system-ui;margin-bottom:18px;">
    ${renderKeyValueRow("open_tasks", String(openTaskIds.length))}
    ${renderKeyValueRow("tasks_total", String(taskRecords.length))}
    ${renderKeyValueRow("rewards_total", String(rewardRecords.length))}
  </table>

  <h2 style="font:600 14px/1.3 system-ui;margin:18px 0 8px 0;">open tasks</h2>
  <table style="border-collapse:collapse;width:100%;font:13px/1.4 system-ui;">
    <thead>
      <tr>
        <th style="text-align:left;padding:6px 10px;border:1px solid #eee;background:#f5f5f5;">task_id</th>
        <th style="text-align:left;padding:6px 10px;border:1px solid #eee;background:#f5f5f5;">title</th>
        <th style="text-align:left;padding:6px 10px;border:1px solid #eee;background:#f5f5f5;">status</th>
        <th style="text-align:left;padding:6px 10px;border:1px solid #eee;background:#f5f5f5;">owner</th>
        <th style="text-align:left;padding:6px 10px;border:1px solid #eee;background:#f5f5f5;">workspace</th>
      </tr>
    </thead>
    <tbody>
      ${
        openTasks.length
          ? openTasks
              .map(
                (t) => `<tr>
        <td style="padding:6px 10px;border:1px solid #eee;">${escapeHtml(t.id)}</td>
        <td style="padding:6px 10px;border:1px solid #eee;">${escapeHtml(t.title)}</td>
        <td style="padding:6px 10px;border:1px solid #eee;">${escapeHtml(t.status)}</td>
        <td style="padding:6px 10px;border:1px solid #eee;">${escapeHtml(t.owner)}</td>
        <td style="padding:6px 10px;border:1px solid #eee;">${escapeHtml(t.workspace)}</td>
      </tr>`
              )
              .join("")
          : `<tr><td colspan="5" style="padding:8px 10px;border:1px solid #eee;color:#666;">(empty)</td></tr>`
      }
    </tbody>
  </table>

  <h2 style="font:600 14px/1.3 system-ui;margin:18px 0 8px 0;">recent tasks</h2>
  <table style="border-collapse:collapse;width:100%;font:13px/1.4 system-ui;">
    <thead>
      <tr>
        <th style="text-align:left;padding:6px 10px;border:1px solid #eee;background:#f5f5f5;">task_id</th>
        <th style="text-align:left;padding:6px 10px;border:1px solid #eee;background:#f5f5f5;">title</th>
        <th style="text-align:left;padding:6px 10px;border:1px solid #eee;background:#f5f5f5;">status</th>
        <th style="text-align:left;padding:6px 10px;border:1px solid #eee;background:#f5f5f5;">workspace</th>
      </tr>
    </thead>
    <tbody>
      ${
        recentTasks.length
          ? recentTasks
              .map(
                (t) => `<tr>
        <td style="padding:6px 10px;border:1px solid #eee;">${escapeHtml(t.id)}</td>
        <td style="padding:6px 10px;border:1px solid #eee;">${escapeHtml(t.title)}</td>
        <td style="padding:6px 10px;border:1px solid #eee;">${escapeHtml(t.status)}</td>
        <td style="padding:6px 10px;border:1px solid #eee;">${escapeHtml(t.workspace)}</td>
      </tr>`
              )
              .join("")
          : `<tr><td colspan="4" style="padding:8px 10px;border:1px solid #eee;color:#666;">(empty)</td></tr>`
      }
    </tbody>
  </table>

  <h2 style="font:600 14px/1.3 system-ui;margin:18px 0 8px 0;">recent rewards</h2>
  <table style="border-collapse:collapse;width:100%;font:13px/1.4 system-ui;">
    <thead>
      <tr>
        <th style="text-align:left;padding:6px 10px;border:1px solid #eee;background:#f5f5f5;">task_id</th>
        <th style="text-align:left;padding:6px 10px;border:1px solid #eee;background:#f5f5f5;">final_reward</th>
        <th style="text-align:left;padding:6px 10px;border:1px solid #eee;background:#f5f5f5;">credited_agent</th>
        <th style="text-align:left;padding:6px 10px;border:1px solid #eee;background:#f5f5f5;">credited_at</th>
      </tr>
    </thead>
    <tbody>
      ${
        recentRewards.length
          ? recentRewards
              .map(
                (r) => `<tr>
        <td style="padding:6px 10px;border:1px solid #eee;">${escapeHtml(r.taskId)}</td>
        <td style="padding:6px 10px;border:1px solid #eee;">${escapeHtml(r.finalReward)}</td>
        <td style="padding:6px 10px;border:1px solid #eee;">${escapeHtml(r.creditedAgent)}</td>
        <td style="padding:6px 10px;border:1px solid #eee;">${escapeHtml(r.creditedAt)}</td>
      </tr>`
              )
              .join("")
          : `<tr><td colspan="4" style="padding:8px 10px;border:1px solid #eee;color:#666;">(empty)</td></tr>`
      }
    </tbody>
  </table>
  `;

  return `<!doctype html><html><head><meta charset="utf-8" /><title>ops-ui ledger</title></head><body style="margin:18px;max-width:1200px;">${body}</body></html>`;
}
