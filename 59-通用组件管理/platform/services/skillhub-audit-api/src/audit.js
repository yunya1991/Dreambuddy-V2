'use strict';

const MAX_SKILL_MD_BYTES = 200 * 1024;
const MAX_FILES = 200;
const MAX_TOTAL_BYTES = 10 * 1024 * 1024;
const SLUG_RE = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const SEMVER_RE = /^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$/;
const SECRET_PATTERNS = [
  { id: 'skh', re: /skh_[0-9a-f]{20,}/i, label: 'SkillHub Token' },
  { id: 'openai', re: /sk-[A-Za-z0-9]{20,}/, label: 'OpenAI 风格密钥' },
  { id: 'aws', re: /AKIA[0-9A-Z]{16}/, label: 'AWS AccessKey' },
  { id: 'pem', re: /BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY/, label: '私钥' }
];
const PAY_MARKERS = ['skillpay', 'pay skill', '付费', '按次', '收费', '定价', '订阅'];
const PAID_PROTOCOL = [
  { id: 'PAY001', title: '402 账单下发', re: /\b402\b/, hint: '未付款需返回 HTTP 402' },
  { id: 'PAY002', title: 'Payment-Needed 账单头', re: /Payment-Needed/i, hint: '在响应头下发 Base64URL 账单' },
  { id: 'PAY003', title: 'Payment-Proof 凭证重试', re: /Payment-Proof/i, hint: '付款后携带凭证重试原请求' },
  { id: 'PAY004', title: '服务端验付调用', re: /(payment\.verify|payment_verify|验付)/i, hint: '调用支付宝验付接口，不得只校验本地状态' },
  { id: 'PAY005', title: '履约确认', re: /(fulfillment\.confirm|fulfillment_confirm|履约确认)/i, hint: '交付资源后回传履约确认' }
];

function auditSkill(input) {
  const skillMd = String(input.skill_md || '');
  const files = Array.isArray(input.files) ? input.files : null;
  const target = input.target === 'pay' || input.target === 'free' ? input.target : 'auto';
  const checks = [];

  if (Buffer.byteLength(skillMd, 'utf8') > MAX_SKILL_MD_BYTES) {
    checks.push(fail('DOC001', 'SKILL.md 体积', `超过 200KB 上限（${Buffer.byteLength(skillMd, 'utf8')} 字节）`));
  } else if (skillMd.length === 0) {
    checks.push(fail('DOC001', 'SKILL.md 内容', '内容为空，无法体检'));
  } else if (skillMd.trim().length < 200) {
    checks.push(warn('DOC001', 'SKILL.md 内容', '正文过短（<200 字符），Agent 可能无法正确执行'));
  } else {
    checks.push(pass('DOC001', 'SKILL.md 内容', '长度正常'));
  }

  const front = parseFrontmatter(skillMd);
  if (!front.ok) {
    checks.push(fail('FM000', 'Frontmatter', '缺少合法 frontmatter（首行 --- 起始块）'));
  } else {
    checks.push(pass('FM000', 'Frontmatter', '已解析 frontmatter'));
    const meta = front.data;

    if (!meta.slug) {
      checks.push(fail('FM001', 'slug', '缺少 slug（发布必填）'));
    } else if (!SLUG_RE.test(meta.slug) || meta.slug.length < 2 || meta.slug.length > 128) {
      checks.push(fail('FM001', 'slug', `slug 非法：${meta.slug}（需 kebab-case，2–128 字符）`));
    } else {
      checks.push(pass('FM001', 'slug', meta.slug));
    }

    if (!meta.version) {
      checks.push(fail('FM002', 'version', '缺少 version（发布必填）'));
    } else if (!SEMVER_RE.test(meta.version)) {
      checks.push(fail('FM002', 'version', `version 非法：${meta.version}（需 SemVer）`));
    } else {
      checks.push(pass('FM002', 'version', meta.version));
    }

    if (!meta.displayname && !meta.displayName) {
      checks.push(fail('FM003', 'displayName', '缺少 displayName（发布必填）'));
    } else {
      checks.push(pass('FM003', 'displayName', meta.displayname || meta.displayName));
    }

    if (!meta.summary && !meta.description) {
      checks.push(warn('FM004', 'summary / description', '建议补 summary 与 description，详情页可读性更好'));
    } else {
      checks.push(pass('FM004', 'summary / description', '已填写'));
    }

    if (!meta.license) {
      checks.push(warn('FM005', 'license', '建议声明 license（如 MIT）'));
    } else {
      checks.push(pass('FM005', 'license', meta.license));
    }
  }

  const isPay = target === 'pay' || (target === 'auto' && PAY_MARKERS.some((m) => skillMd.toLowerCase().includes(m)));
  if (isPay) {
    for (const item of PAID_PROTOCOL) {
      if (item.re.test(skillMd)) {
        checks.push(pass(item.id, item.title, '文档中已声明'));
      } else {
        checks.push(fail(item.id, item.title, `${item.hint}；仅写文案不等于已实现，必须指向真实可用的收费后端`));
      }
    }
    checks.push(
      pass(
        'PAY100',
        '收费后端形态',
        '付费 Skill 必须依赖独立部署的后端服务；本次体检只能核对文档与结构，无法验证后端真实可用性'
      )
    );
  } else {
    checks.push(pass('PAY000', '发布类型', '按免费 Skill 体检；如要按次收费请以 Pay Skill 流程重新体检'));
  }

  if (files) {
    if (files.length > MAX_FILES) {
      checks.push(fail('PKG001', '文件数量', `${files.length} 个，超过 200 上限`));
    } else {
      checks.push(pass('PKG001', '文件数量', `${files.length} 个`));
    }
    const totalBytes = files.reduce((sum, f) => sum + (Number(f.size) || 0), 0);
    if (totalBytes > MAX_TOTAL_BYTES) {
      checks.push(fail('PKG002', '包体积', `${(totalBytes / 1048576).toFixed(2)}MB，超过 10MB 上限`));
    } else {
      checks.push(pass('PKG002', '包体积', `${(totalBytes / 1048576).toFixed(2)}MB`));
    }
    const risky = files
      .map((f) => String(f.path || ''))
      .filter((p) => /(^|\/)(\.env[^/]*|id_rsa|id_ed25519|credentials\.json)$/i.test(p) || /\.(pem|key|p12|pfx)$/i.test(p));
    if (risky.length) {
      checks.push(fail('SEC001', '敏感文件', `包内包含敏感文件：${risky.slice(0, 5).join(', ')}`));
    } else {
      checks.push(pass('SEC001', '敏感文件', '未发现敏感文件名'));
    }
  }

  const absolutePaths = skillMd.match(/(\/Users\/[^\s)`'"]+|\/home\/[^\s)`'"]+|\/root\/[^\s)`'"]+)/g);
  if (absolutePaths) {
    checks.push(fail('SEC002', '内部绝对路径', `文档泄露本机路径：${[...new Set(absolutePaths)].slice(0, 3).join(', ')}`));
  } else {
    checks.push(pass('SEC002', '内部绝对路径', '未发现本机绝对路径'));
  }

  const leaked = SECRET_PATTERNS.filter((p) => p.re.test(skillMd));
  if (leaked.length) {
    checks.push(fail('SEC003', '密钥泄露', `疑似包含：${leaked.map((p) => p.label).join('、')}`));
  } else {
    checks.push(pass('SEC003', '密钥泄露', '未命中常见密钥特征'));
  }

  const errors = checks.filter((c) => c.status === 'fail').length;
  const warnings = checks.filter((c) => c.status === 'warn').length;
  const score = Math.max(0, 100 - errors * 15 - warnings * 5);
  const verdict = errors > 0 ? 'fail' : warnings > 0 ? 'needs_work' : 'pass';

  return {
    service: 'SkillHub Skill 上架体检',
    verdict,
    score,
    publish_type: isPay ? 'pay' : 'free',
    summary:
      verdict === 'pass'
        ? '结构与合规检查通过，可按计划提交发布'
        : verdict === 'needs_work'
          ? '存在建议项，修正后收益更高'
          : '存在阻断项，不能直接发布',
    counts: { error: errors, warning: warnings, total: checks.length },
    checks,
    next_actions: checks.filter((c) => c.status !== 'pass').map((c) => `${c.id} ${c.title}：${c.detail}`),
    disclaimer: '本报告基于提交内容做结构与合规体检，不替代 SkillHub 官方审核，也不能证明收费后端已真实可用。',
    audited_at: new Date().toISOString()
  };
}

function parseFrontmatter(md) {
  const match = /^\uFEFF?---\r?\n([\s\S]*?)\r?\n---\r?\n?/.exec(md);
  if (!match) return { ok: false, data: {} };
  const data = {};
  for (const line of match[1].split(/\r?\n/)) {
    const kv = /^([A-Za-z0-9_-]+)\s*:\s*(.*)$/.exec(line.trim());
    if (!kv) continue;
    data[kv[1].toLowerCase()] = kv[2].replace(/^['"]|['"]$/g, '').trim();
  }
  return { ok: true, data };
}

function pass(id, title, detail) {
  return { id, title, status: 'pass', detail };
}

function warn(id, title, detail) {
  return { id, title, status: 'warn', detail };
}

function fail(id, title, detail) {
  return { id, title, status: 'fail', detail };
}

module.exports = { auditSkill };
