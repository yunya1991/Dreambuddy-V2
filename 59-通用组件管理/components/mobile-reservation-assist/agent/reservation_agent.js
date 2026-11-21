/**
 * 手机预约助手 - Auto.js 常驻 Agent v0.2（P1：B站会员购真实选择器）
 *
 * 职责：轮询本地指令网关拉取"预约作业"，按平台真实流程执行，回传结果。
 * 红线：只执行到"官方 App 下单页并预填"，遇验证码/登录/支付一律停下回传 needs_human。
 *
 * P1 变化：
 * - 新增 bilibili（会员购）真实选择器流程：关隐私弹窗→进会员购→搜索→（到登录/下单页停）
 * - 每步失败自动截图到 agent_debug/，便于真机调参
 * - 其余平台仍走通用分发（P0 行为）
 *
 * 部署：/sdcard/脚本/顺风车助手/autojs/reservation_agent.js，配置见 config/mra_agent.json
 */

var CONFIG_PATH = "/sdcard/脚本/顺风车助手/autojs/config/mra_agent.json";
var DEBUG_DIR = "/sdcard/脚本/顺风车助手/autojs/agent_debug/";

var CONFIG = {
    gateway: "http://127.0.0.1:8765",
    token: "",
    device_id: "xiaomi-mra-01",
    poll_interval_ms: 4000,
    limit: 5,
    enabled: true
};

var LOG_FILE = DEBUG_DIR + "agent.log";

function log(msg) {
    var line = "[" + new Date().toLocaleTimeString() + "] " + msg;
    try { console.log("[mra] " + msg); } catch (e) {}
    try { files.ensureDir(DEBUG_DIR); files.append(LOG_FILE, line + "\n"); } catch (e) {}
}

function loadConfig() {
    try {
        if (files.exists(CONFIG_PATH)) {
            var obj = JSON.parse(files.read(CONFIG_PATH));
            for (var k in obj) { if (obj.hasOwnProperty(k)) CONFIG[k] = obj[k]; }
            log("已加载配置 gateway=" + CONFIG.gateway);
        }
    } catch (e) {
        log("读取配置失败，用默认: " + e.message);
    }
}

function httpGetJson(url) {
    try {
        var res = http.get(url, { headers: { "X-MRA-Token": CONFIG.token } });
        if (res.statusCode == 200) return res.body.json();
        log("GET 失败 HTTP " + res.statusCode);
    } catch (e) { log("GET 异常: " + e.message); }
    return null;
}

function httpPostJson(url, payload) {
    try {
        var res = http.postJson(url, payload, { headers: { "X-MRA-Token": CONFIG.token } });
        if (res.statusCode == 200) return res.body.json();
        log("POST 失败 HTTP " + res.statusCode);
    } catch (e) { log("POST 异常: " + e.message); }
    return null;
}

function reportResult(jobId, state, detail) {
    httpPostJson(CONFIG.gateway + "/results", {
        token: CONFIG.token, device_id: CONFIG.device_id,
        job_id: jobId, state: state, detail: detail || {}
    });
    log("回执 job=" + jobId + " state=" + state);
}

// ---------- 调试截图 ----------
function snap(tag) {
    try {
        files.ensureDir(DEBUG_DIR);
        var p = DEBUG_DIR + "job_" + tag + "_" + new Date().getTime() + ".png";
        if (typeof shell === "function") shell("screencap -p " + p, true);
        return p;
    } catch (e) { return ""; }
}

// ---------- 选择器工具 ----------
function waitText(txt, timeout) {
    try { return text(txt).findOne(timeout || 5000); } catch (e) { return null; }
}
function waitContains(txt, timeout) {
    try { return textContains(txt).findOne(timeout || 5000); } catch (e) { return null; }
}
function clickNode(node) {
    try {
        if (!node) return false;
        // 优先无障碍点击（避免坐标手势在部分机型上挂起）
        try { if (node.click()) return true; } catch (e) {}
        var b = node.bounds();
        if (b) { click(b.centerX(), b.centerY()); return true; }
        return false;
    } catch (e) { return false; }
}

// 非阻塞查询：用 find() 取快照再取第一个，避免 findOnce/findOne 在持续动画页面(B站首页)阻塞卡死
function q(selector) {
    try {
        var c = selector.find();
        var n = 0;
        try { n = c.size(); } catch (e) { n = c.length || 0; }
        if (n > 0) { try { return c.get(0); } catch (e) { return c[0]; } }
    } catch (e) {}
    return null;
}

// 多次轮询点击"同意并继续"隐私弹窗（非阻塞查询，兜住冷启动延迟）
function dismissConsent() {
    for (var i = 0; i < 4; i++) {
        var n = q(textContains("同意并继续"));
        if (n) { clickNode(n); log("consent clicked"); return true; }
        if (i < 3) sleep(400);
    }
    return false;
}

// 稳健定位"会员购"入口：text / desc / descContains / textContains 多路（非阻塞）
function findMall() {
    for (var i = 0; i < 12; i++) {
        var n = q(text("会员购")) || q(desc("会员购")) ||
                q(descContains("会员购")) || q(textContains("会员购"));
        if (n) return n;
        sleep(600);
    }
    return null;
}

// 点开会员购顶部"伪搜索条"：它是可点击的宽 LinearLayout，placeholder 是动态热词(如"BLG冠军周边")，
// 不能按"搜索"文字匹配。命中后进入真正的搜索页(含 EditText)。
function openMallSearch() {
    var nodes = null;
    try { nodes = className("android.widget.LinearLayout").clickable(true).find(); } catch (e) { nodes = null; }
    if (nodes) {
        var cnt = 0;
        try { cnt = nodes.size(); } catch (e) { cnt = nodes.length || 0; }
        for (var i = 0; i < cnt; i++) {
            var node = null;
            try { node = nodes.get(i); } catch (e) { node = nodes[i]; }
            var b = null;
            try { b = node.bounds(); } catch (e) { continue; }
            if (!b) continue;
            if (b.width() > 500 && b.height() > 50 && b.height() < 170 &&
                b.centerY() > 240 && b.centerY() < 500) {
                clickNode(node); return true;
            }
        }
    }
    // 兜底坐标（本机 1080x2400，会员购搜索条中心）
    click(446, 335);
    return true;
}

// 会员购内搜索：优先用已出现的 EditText；否则先点开伪搜索条进入搜索页再输入
function searchInMall(entry) {
    var edit = q(className("android.widget.EditText"));
    if (!edit) {
        openMallSearch(); sleep(1500);
        for (var i = 0; i < 10 && !edit; i++) { edit = q(className("android.widget.EditText")); if (!edit) sleep(300); }
    }
    if (!edit) return false;
    clickNode(edit); sleep(500);
    try { edit.setText(entry); } catch (e) { try { setText(entry); } catch (e2) {} }
    sleep(800);
    // 会员购搜索框的"搜索"动作挂在输入法上，ENTER(66) 不触发；点输入法右下角"搜索"键提交
    try {
        var w = device.width, h = device.height;
        click(Math.floor(w * 0.91), Math.floor(h * 0.895));
    } catch (e) {}
    return true;
}

// 等待目标 App 真正到前台，避免 launch 未完成就找控件
function waitPackage(pkg, timeoutMs) {
    var t = Date.now();
    while (Date.now() - t < timeoutMs) {
        try { if (currentPackage() === pkg) return true; } catch (e) {}
        sleep(300);
    }
    return false;
}

// 确保回到 B站主界面（底部有"会员购"标签）：若停在搜索页/详情页则按返回键退出；
// 已在主界面时不按返回；若已不在 B站 则重新拉起，避免退到桌面后找不到入口。
function ensureMainPage(pkg) {
    function hasTab() {
        return !!(q(desc("会员购")) || q(text("会员购")));
    }
    for (var i = 0; i < 3 && !hasTab(); i++) {
        try { if (currentPackage() !== pkg) break; } catch (e) {}
        back(); sleep(800);
    }
    try {
        if (currentPackage() !== pkg) { app.launch(pkg); waitPackage(pkg, 6000); sleep(800); }
    } catch (e) {}
    return hasTab();
}

// ---------- bilibili 会员购真实流程 ----------
function runBilibili(command) {
    var target = command.target || {};
    var detail = { adapter: "bilibili", steps: [] };
    var pkg = command.app || "tv.danmaku.bili";
    function step(name, ok, note) { detail.steps.push({ action: name, ok: ok, note: note || "" }); log("step " + name + " ok=" + ok + " " + (note || "")); }

    // 无障碍未开启则不调用选择器（避免 findOnce 阻塞并跳设置页），直接交人工
    if (!auto.service) {
        log("accessibility off, skip selectors");
        detail.steps.push({ action: "no_accessibility", ok: false, note: "Auto.js 无障碍服务未开启" });
        detail.note = "请在手机 设置→无障碍 开启 Auto.js 服务后重试";
        return { state: "needs_human", detail: detail };
    }

    // 1) 启动 App（等它真正到前台再操作）
    try { app.launch(pkg); } catch (e) {}
    waitPackage(pkg, 6000);
    sleep(1200);
    step("open_app", true, pkg);

    // 2) 隐私弹窗（多次轮询点击，兜住冷启动延迟）
    var consentOk = dismissConsent();
    step("dismiss_consent", consentOk, consentOk ? "已点击同意并继续" : "未见弹窗");
    sleep(1500);

    // 3) 进入会员购（先退回主界面，避免停在搜索页导致找不到底部标签）
    dismissConsent();
    ensureMainPage(pkg);
    var mall = findMall();
    if (!mall) {
        detail.screenshot = snap("bili_mall_missing");
        step("goto_mall", false, "未找到会员购入口");
        return { state: "needs_human", detail: detail };
    }
    clickNode(mall); step("goto_mall", true, "点击会员购"); sleep(2500);
    detail.screenshot = snap("bili_mall");

    // 4) 搜索目标（会员购内搜索）
    var entry = target.target_id || "";
    if (entry && searchInMall(entry)) {
        step("search", true, entry); sleep(2500);
        detail.screenshot = snap("bili_search");
    } else {
        detail.screenshot = snap("bili_search_fail");
        step("search", false, "未找到搜索框或目标为空");
    }

    // 5) 到登录/下单页即停（会员购下单需登录）
    step("stop", true, "await_human_confirm");
    detail.note = "会员购下单需登录账号，已停在可人工操作处";
    return { state: "needs_human", detail: detail };
}

// ---------- 通用分发（P0 行为，占位平台） ----------
function runGeneric(command) {
    var detail = { adapter: command.adapter, steps: [] };
    try {
        var steps = command.steps || [];
        for (var i = 0; i < steps.length; i++) {
            var s = steps[i], a = s.action;
            if (a === "open_app") {
                if (s.app) { try { app.launch(s.app); sleep(2000); } catch (e) {} }
                detail.steps.push({ action: a, ok: true });
            } else if (a === "stop") {
                return { state: "needs_human", detail: detail };
            } else {
                detail.steps.push({ action: a, ok: false, note: "pending_selector" });
            }
        }
        return { state: "needs_human", detail: detail };
    } catch (e) {
        return { state: "error", detail: { error: e.message } };
    }
}

function executeCommand(command) {
    log("exec adapter=" + command.adapter + " job=" + command.job_id);
    try {
        if (command.adapter === "bilibili") return runBilibili(command);
        return runGeneric(command);
    } catch (e) {
        log("exec ERROR " + e.message);
        return { state: "error", detail: { error: e.message, screenshot: snap("error") } };
    }
}

function pollOnce() {
    var url = CONFIG.gateway + "/commands?device_id=" + CONFIG.device_id + "&limit=" + CONFIG.limit;
    var data = httpGetJson(url);
    if (!data || !data.jobs || data.jobs.length === 0) return;
    log("收到 " + data.jobs.length + " 条作业");
    for (var i = 0; i < data.jobs.length; i++) {
        var command = data.jobs[i];
        var result = executeCommand(command);
        reportResult(command.job_id, result.state, result.detail);
        try { if (CONFIG.vibrate !== false) device.vibrate(150); } catch (e) {}
    }
}

function main() {
    // 单实例保护：同一个脚本文件只允许一个实例运行，避免重复点击导致多实例互相抢占
    try {
        var me = engines.myEngine();
        var src = String(me.getSource());
        var all = engines.all();
        for (var i = 0; i < all.length; i++) {
            var e = all[i];
            if (e.getId() !== me.getId() && String(e.getSource()) === src) {
                log("检测到已有实例在运行，退出本实例");
                exit();
                return;
            }
        }
    } catch (e) {}
    loadConfig();
    try { log("accessibility=" + (auto.service ? "on" : "off")); } catch (e) {}
    log("手机预约助手 Agent v0.2 启动，网关=" + CONFIG.gateway);
    while (CONFIG.enabled) {
        try { pollOnce(); } catch (e) { log("轮询异常: " + e.message); }
        sleep(CONFIG.poll_interval_ms);
    }
}

main();
