/* AUTO-GENERATED from contracts/skill-quality-rules.yaml — 禁止手改
 * source-sha256: 65da95acfa59eba8870c0778d38dfa9bdc3e84d9e92830b23ce1aba128ed911b
 * rules-version: 3 | score-formula: v2
 */
'use strict';

module.exports = {
  "source_sha256": "65da95acfa59eba8870c0778d38dfa9bdc3e84d9e92830b23ce1aba128ed911b",
  "version": 3,
  "updated_at": "2026-11-20",
  "changelog": [
    {
      "version": 3,
      "summary": "FM006 改 enforce；必填项禁止灰度；新增 patchable/patches；结构校验",
      "changed": [
        "FM006 enforce",
        "FM001/002/003/006 required_by_platform",
        "新增 patches 交付"
      ]
    }
  ],
  "score": {
    "formula": "v2",
    "weights": {
      "blocker": 15,
      "warn": 5,
      "info": 1
    }
  },
  "dimensions": {
    "convention": {
      "label": "规范性"
    },
    "trust": {
      "label": "可信任度（安全子项）"
    }
  },
  "limits": {
    "max_skill_md_bytes": 204800,
    "max_files": 200,
    "max_total_bytes": 10485760
  },
  "pay_markers": [
    "skillpay",
    "pay skill",
    "付费",
    "按次",
    "收费",
    "定价",
    "订阅"
  ],
  "rules": [
    {
      "id": "DOC001",
      "title": "SKILL.md 内容",
      "severity": "blocker",
      "stage": "enforce",
      "required_by_platform": false,
      "dimension": "convention",
      "applies_to": [
        "free",
        "pay"
      ],
      "public": true,
      "group": "content",
      "patchable": false,
      "check": {
        "type": "text_length",
        "max_bytes": 204800,
        "warn_below": 200
      },
      "messages": {
        "pass": "长度正常",
        "fail_oversize": "超过 200KB 上限（{count} 字节）",
        "fail_empty": "内容为空，无法体检",
        "warn_short": "正文过短（<200 字符），Agent 可能无法正确执行",
        "fix": "补全 SKILL.md 正文，保持在 200 字符以上、200KB 以内",
        "no_patch_reason": "正文需作者改写，无法自动生成补丁"
      },
      "site": {
        "category": "结构",
        "item": "SKILL.md 内容与体积",
        "consequence": "内容为空或超过 200KB，无法完成体检"
      }
    },
    {
      "id": "FM000",
      "title": "Frontmatter",
      "type": "frontmatter_parse",
      "severity": "blocker",
      "stage": "enforce",
      "required_by_platform": false,
      "dimension": "convention",
      "applies_to": [
        "free",
        "pay"
      ],
      "public": true,
      "group": "frontmatter",
      "on_fail": "skip_group",
      "patchable": false,
      "messages": {
        "pass": "已解析 frontmatter",
        "fail": "缺少合法 frontmatter（首行 --- 起始块）",
        "fix": "在 SKILL.md 首行补 --- 包裹的 frontmatter，至少含 name/description/version",
        "no_patch_reason": "缺少 frontmatter 时无法定位字段，需人工补齐"
      },
      "site": {
        "category": "结构",
        "item": "frontmatter 是否可解析",
        "consequence": "平台无法解析，直接退回"
      }
    },
    {
      "id": "FM001",
      "title": "slug",
      "severity": "blocker",
      "stage": "enforce",
      "required_by_platform": true,
      "dimension": "convention",
      "applies_to": [
        "free",
        "pay"
      ],
      "public": true,
      "group": "frontmatter",
      "depends_on": [
        "FM000"
      ],
      "patchable": true,
      "patch": {
        "kind": "frontmatter_field",
        "field": "slug"
      },
      "check": {
        "type": "frontmatter",
        "field": "slug",
        "required": true,
        "pattern": "^[a-z0-9]+(?:-[a-z0-9]+)*$",
        "min_len": 2,
        "max_len": 128
      },
      "messages": {
        "pass": "{value}",
        "fail_missing": "缺少 slug（发布必填）",
        "fail_invalid": "slug 非法：{value}（需 kebab-case，2–128 字符）",
        "fix": "在 frontmatter 增加 slug，使用小写连字符形式"
      },
      "site": {
        "category": "结构",
        "item": "slug 格式与长度（kebab-case，2–128）",
        "consequence": "无法生成稳定标识，直接退回"
      }
    },
    {
      "id": "FM002",
      "title": "version",
      "severity": "blocker",
      "stage": "enforce",
      "required_by_platform": true,
      "dimension": "convention",
      "applies_to": [
        "free",
        "pay"
      ],
      "public": true,
      "group": "frontmatter",
      "depends_on": [
        "FM000"
      ],
      "patchable": true,
      "patch": {
        "kind": "frontmatter_field",
        "field": "version"
      },
      "check": {
        "type": "frontmatter",
        "field": "version",
        "required": true,
        "pattern": "^\\d+\\.\\d+\\.\\d+(?:-[0-9A-Za-z.-]+)?$"
      },
      "messages": {
        "pass": "{value}",
        "fail_missing": "缺少 version（发布必填）",
        "fail_invalid": "version 非法：{value}（需 SemVer）",
        "fix": "补 version 字段，使用 x.y.z 语义化版本"
      },
      "site": {
        "category": "结构",
        "item": "version 语义化版本",
        "consequence": "版本不可比较，升级与回滚链路失效"
      }
    },
    {
      "id": "FM003",
      "title": "displayName",
      "severity": "blocker",
      "stage": "enforce",
      "required_by_platform": true,
      "dimension": "convention",
      "applies_to": [
        "free",
        "pay"
      ],
      "public": true,
      "group": "frontmatter",
      "depends_on": [
        "FM000"
      ],
      "patchable": true,
      "patch": {
        "kind": "frontmatter_field",
        "field": "displayName"
      },
      "check": {
        "type": "frontmatter",
        "any_of": [
          "displayName",
          "display_name"
        ],
        "required": true
      },
      "messages": {
        "pass": "{value}",
        "fail_missing": "缺少 displayName（发布必填）",
        "fix": "增加 displayName，写用户可读的名称"
      },
      "site": {
        "category": "结构",
        "item": "displayName 必填",
        "consequence": "列表页无法展示，直接退回"
      }
    },
    {
      "id": "FM004",
      "title": "summary / description",
      "severity": "warn",
      "stage": "enforce",
      "required_by_platform": false,
      "dimension": "convention",
      "applies_to": [
        "free",
        "pay"
      ],
      "public": true,
      "group": "frontmatter",
      "depends_on": [
        "FM000"
      ],
      "patchable": true,
      "patch": {
        "kind": "frontmatter_field",
        "field": "summary"
      },
      "check": {
        "type": "frontmatter",
        "any_of": [
          "summary",
          "description"
        ]
      },
      "messages": {
        "pass": "已填写",
        "fail_missing": "建议补 summary 与 description，详情页可读性更好",
        "fix": "增加 summary 或 description，一句话说明解决什么问题"
      },
      "site": {
        "category": "描述",
        "item": "summary / description 完整",
        "consequence": "检索与详情页可读性差，转化低"
      }
    },
    {
      "id": "FM005",
      "title": "license",
      "severity": "warn",
      "stage": "enforce",
      "required_by_platform": false,
      "dimension": "convention",
      "applies_to": [
        "free",
        "pay"
      ],
      "public": true,
      "group": "frontmatter",
      "depends_on": [
        "FM000"
      ],
      "patchable": true,
      "patch": {
        "kind": "frontmatter_field",
        "field": "license"
      },
      "check": {
        "type": "frontmatter",
        "field": "license"
      },
      "messages": {
        "pass": "{value}",
        "fail_missing": "建议声明 license（如 MIT）",
        "fix": "增加 license 字段，例如 MIT"
      },
      "site": {
        "category": "描述",
        "item": "license 声明",
        "consequence": "授权不明，分发受阻"
      }
    },
    {
      "id": "FM006",
      "title": "name",
      "severity": "blocker",
      "stage": "enforce",
      "required_by_platform": true,
      "dimension": "convention",
      "applies_to": [
        "free",
        "pay"
      ],
      "public": true,
      "group": "frontmatter",
      "depends_on": [
        "FM000"
      ],
      "patchable": true,
      "patch": {
        "kind": "frontmatter_field",
        "field": "name"
      },
      "check": {
        "type": "frontmatter",
        "field": "name",
        "required": true,
        "pattern": "^[a-z0-9]+(?:-[a-z0-9]+)*$",
        "max_len": 64,
        "exclude_words": [
          "anthropic",
          "claude"
        ]
      },
      "messages": {
        "pass": "name 合法",
        "fail_missing": "缺少 name（平台发布必填）",
        "fail_invalid": "name 非法：{value}（需 ≤64 字符 kebab-case）",
        "fail_reserved": "name 含平台保留词：{value}",
        "fix": "将 name 改为小写连字符形式，例如 my-skill"
      },
      "site": {
        "category": "结构",
        "item": "name 规范（≤64、kebab-case、无保留词）",
        "consequence": "与平台命名规则冲突，直接退回"
      }
    },
    {
      "id": "FM007",
      "title": "description 触发短语",
      "severity": "warn",
      "stage": "gray",
      "required_by_platform": false,
      "dimension": "convention",
      "applies_to": [
        "free",
        "pay"
      ],
      "public": true,
      "group": "frontmatter",
      "depends_on": [
        "FM000"
      ],
      "patchable": true,
      "patch": {
        "kind": "description_rewrite"
      },
      "check": {
        "type": "frontmatter",
        "field": "description",
        "min_len": 1,
        "max_len": 1024,
        "must_include_any": [
          "当",
          "用于",
          "使用",
          "触发",
          "适用于",
          "when",
          "use"
        ]
      },
      "messages": {
        "pass": "description 长度与触发短语正常",
        "fail_missing": "缺少 description（建议 1–1024 且含触发短语）",
        "fail_invalid": "description 需 1–1024 字符（当前 {count}）",
        "fail_trigger": "缺少触发短语，例如「当用户说……时使用」",
        "fix": "在 description 中补「当……时使用」类触发短语"
      },
      "site": {
        "category": "描述",
        "item": "description 长度与触发短语",
        "consequence": "检索命中低，用户不知道何时触发"
      }
    },
    {
      "id": "FM008",
      "title": "name 与目录名一致",
      "severity": "warn",
      "stage": "gray",
      "required_by_platform": false,
      "dimension": "convention",
      "applies_to": [
        "free",
        "pay"
      ],
      "public": false,
      "group": "frontmatter",
      "depends_on": [
        "FM000"
      ],
      "patchable": false,
      "check": {
        "type": "frontmatter_name_matches_dir",
        "field": "name",
        "requires": "package_root"
      },
      "messages": {
        "pass": "name 与包目录名一致",
        "fail": "name({value}) 与包目录名({expected}) 不一致",
        "fix": "将 frontmatter name 改为与包目录同名",
        "no_patch_reason": "目录名由作者自行决定，不自动改写"
      }
    },
    {
      "id": "DOC002",
      "title": "使用 / 示例 / 限制结构",
      "severity": "warn",
      "stage": "gray",
      "required_by_platform": false,
      "dimension": "convention",
      "applies_to": [
        "free",
        "pay"
      ],
      "public": true,
      "group": "docs",
      "patchable": false,
      "check": {
        "type": "section_present",
        "scope": "headings",
        "groups": [
          [
            "使用",
            "用法",
            "快速开始",
            "快速上手"
          ],
          [
            "示例",
            "例子",
            "Example"
          ],
          [
            "限制",
            "边界",
            "注意事项",
            "Limitations"
          ]
        ],
        "group_labels": [
          "使用说明",
          "示例",
          "限制说明"
        ]
      },
      "messages": {
        "pass": "使用 / 示例 / 限制三段结构完整",
        "fail": "缺少章节：{values}",
        "fix": "补充「使用」「示例」「限制」小节",
        "no_patch_reason": "章节内容需作者撰写"
      },
      "site": {
        "category": "文档",
        "item": "使用、示例、限制三段结构",
        "consequence": "安装后无法自助上手"
      }
    },
    {
      "id": "EX001",
      "title": "可执行示例",
      "severity": "warn",
      "stage": "gray",
      "required_by_platform": false,
      "dimension": "convention",
      "applies_to": [
        "free",
        "pay"
      ],
      "public": true,
      "group": "docs",
      "patchable": false,
      "check": {
        "type": "regex_present",
        "pattern": "```|^\\s*(?:python3?|bash|sh|node|curl|npm|npx|make)\\s",
        "flags": "m"
      },
      "messages": {
        "pass": "文档中已有可执行示例",
        "fail": "未发现代码块或命令示例",
        "fix": "补一个可直接运行的最小示例",
        "no_patch_reason": "示例需结合作者实现编写"
      },
      "site": {
        "category": "文档",
        "item": "提供代码块或命令示例",
        "consequence": "用户与审核都难以验证可用性"
      }
    },
    {
      "id": "FAQ001",
      "title": "FAQ",
      "severity": "info",
      "stage": "gray",
      "required_by_platform": false,
      "dimension": "convention",
      "applies_to": [
        "free",
        "pay"
      ],
      "public": true,
      "group": "docs",
      "patchable": false,
      "check": {
        "type": "section_present",
        "scope": "headings",
        "file_any": "FAQ\\.md|faq\\.md",
        "groups": [
          [
            "FAQ",
            "常见问题",
            "问答"
          ]
        ],
        "group_labels": [
          "FAQ"
        ]
      },
      "messages": {
        "pass": "已提供 FAQ",
        "fail": "未发现 FAQ 文件或段落",
        "fix": "增加 FAQ 段落或 FAQ.md",
        "no_patch_reason": "FAQ 内容需作者撰写"
      },
      "site": {
        "category": "文档",
        "item": "FAQ 段落或文件",
        "consequence": "常见问题无人解答，支持成本高"
      }
    },
    {
      "id": "SEC001",
      "title": "敏感文件",
      "severity": "blocker",
      "stage": "enforce",
      "required_by_platform": true,
      "dimension": "trust",
      "applies_to": [
        "free",
        "pay"
      ],
      "public": true,
      "group": "security",
      "patchable": false,
      "check": {
        "type": "files",
        "kind": "filename_match",
        "requires": "files",
        "flags": "i",
        "patterns": [
          "(^|/)(\\.env[^/]*|id_rsa|id_ed25519|credentials\\.json)$",
          "\\.(pem|key|p12|pfx)$"
        ]
      },
      "messages": {
        "pass": "未发现敏感文件名",
        "fail": "包内包含敏感文件：{values}",
        "fix": "从包内移除 .env、私钥与证书文件",
        "no_patch_reason": "敏感文件必须由作者移出仓库，不可自动打包"
      },
      "site": {
        "category": "安全",
        "item": "敏感文件（.env、私钥、证书）",
        "consequence": "泄露凭据，禁止上架"
      }
    },
    {
      "id": "SEC002",
      "title": "内部绝对路径",
      "severity": "blocker",
      "stage": "enforce",
      "required_by_platform": true,
      "dimension": "trust",
      "applies_to": [
        "free",
        "pay"
      ],
      "public": true,
      "group": "security",
      "patchable": false,
      "check": {
        "type": "regex_absent",
        "pattern": "(?:/Users/|/home/|/root/)[^\\s)`'\"]+",
        "collect": true
      },
      "messages": {
        "pass": "未发现本机绝对路径",
        "fail": "文档泄露本机路径：{values}",
        "fix": "把本机绝对路径换成 ~ 或相对路径",
        "no_patch_reason": "路径需按各人环境改写"
      },
      "site": {
        "category": "安全",
        "item": "本机绝对路径（/Users、/home、/root）",
        "consequence": "泄露环境信息，审核阻断"
      }
    },
    {
      "id": "SEC003",
      "title": "密钥泄露",
      "severity": "blocker",
      "stage": "enforce",
      "required_by_platform": true,
      "dimension": "trust",
      "applies_to": [
        "free",
        "pay"
      ],
      "public": true,
      "group": "security",
      "patchable": false,
      "check": {
        "type": "regex_absent",
        "patterns": [
          {
            "pattern": "skh_[0-9a-f]{20,}",
            "flags": "i",
            "label": "SkillHub Token"
          },
          {
            "pattern": "sk-[A-Za-z0-9]{20,}",
            "label": "OpenAI 风格密钥"
          },
          {
            "pattern": "AKIA[0-9A-Z]{16}",
            "label": "AWS AccessKey"
          },
          {
            "pattern": "BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY",
            "label": "私钥"
          }
        ]
      },
      "messages": {
        "pass": "未命中常见密钥特征",
        "fail": "疑似包含：{labels}",
        "fix": "立即吊销并移除密钥，改用环境变量",
        "no_patch_reason": "密钥必须由作者吊销后移除"
      },
      "site": {
        "category": "安全",
        "item": "常见密钥特征（AK、私钥、Token）",
        "consequence": "严重违规，禁止上架"
      }
    },
    {
      "id": "PKG001",
      "title": "文件数量",
      "severity": "blocker",
      "stage": "enforce",
      "required_by_platform": false,
      "dimension": "convention",
      "applies_to": [
        "free",
        "pay"
      ],
      "public": true,
      "group": "package",
      "patchable": true,
      "patch": {
        "kind": "package_tree"
      },
      "check": {
        "type": "files",
        "kind": "count",
        "requires": "files",
        "max": 200
      },
      "messages": {
        "pass": "{count} 个",
        "fail": "{count} 个，超过 200 上限",
        "fix": "拆分或清理包内文件，控制在 200 个以内"
      },
      "site": {
        "category": "规模",
        "item": "文件数量上限（200）",
        "consequence": "包过大，安装与解析失败"
      }
    },
    {
      "id": "PKG002",
      "title": "包体积",
      "severity": "warn",
      "stage": "enforce",
      "required_by_platform": false,
      "dimension": "convention",
      "applies_to": [
        "free",
        "pay"
      ],
      "public": true,
      "group": "package",
      "patchable": true,
      "patch": {
        "kind": "package_tree"
      },
      "check": {
        "type": "files",
        "kind": "total_bytes",
        "requires": "files",
        "max": 10485760
      },
      "messages": {
        "pass": "{value}MB",
        "fail": "{value}MB，超过 10MB 上限",
        "fix": "移除大文件或拆分组件包"
      },
      "site": {
        "category": "规模",
        "item": "包体积上限（10MB）",
        "consequence": "包过大，安装与解析失败"
      }
    },
    {
      "id": "PAY001",
      "title": "402 账单下发",
      "severity": "blocker",
      "stage": "enforce",
      "required_by_platform": true,
      "dimension": "trust",
      "applies_to": [
        "pay"
      ],
      "public": true,
      "group": "pay",
      "patchable": false,
      "check": {
        "type": "regex_present",
        "pattern": "\\b402\\b"
      },
      "messages": {
        "pass": "文档中已声明",
        "fail": "未付款需返回 HTTP 402；仅写文案不等于已实现，必须指向真实可用的收费后端",
        "fix": "在未付款分支返回 HTTP 402 与账单头",
        "no_patch_reason": "收费协议需真实后端实现"
      },
      "site": {
        "category": "计费",
        "item": "402 账单下发",
        "consequence": "无法进入付费链路"
      }
    },
    {
      "id": "PAY002",
      "title": "Payment-Needed 账单头",
      "severity": "blocker",
      "stage": "enforce",
      "required_by_platform": true,
      "dimension": "trust",
      "applies_to": [
        "pay"
      ],
      "public": true,
      "group": "pay",
      "patchable": false,
      "check": {
        "type": "regex_present",
        "pattern": "Payment-Needed"
      },
      "messages": {
        "pass": "文档中已声明",
        "fail": "在响应头下发 Base64URL 账单；仅写文案不等于已实现",
        "fix": "未付款响应头补 Payment-Needed",
        "no_patch_reason": "收费协议需真实后端实现"
      },
      "site": {
        "category": "计费",
        "item": "Payment-Needed 账单头",
        "consequence": "客户端拿不到账单"
      }
    },
    {
      "id": "PAY003",
      "title": "Payment-Proof 凭证重试",
      "severity": "blocker",
      "stage": "enforce",
      "required_by_platform": true,
      "dimension": "trust",
      "applies_to": [
        "pay"
      ],
      "public": true,
      "group": "pay",
      "patchable": false,
      "check": {
        "type": "regex_present",
        "pattern": "Payment-Proof"
      },
      "messages": {
        "pass": "文档中已声明",
        "fail": "付款后需携带凭证重试原请求",
        "fix": "支持 Payment-Proof 重试并幂等取回结果",
        "no_patch_reason": "收费协议需真实后端实现"
      },
      "site": {
        "category": "计费",
        "item": "Payment-Proof 凭证重试",
        "consequence": "付款后无法取回结果"
      }
    },
    {
      "id": "PAY004",
      "title": "服务端验付调用",
      "severity": "blocker",
      "stage": "enforce",
      "required_by_platform": true,
      "dimension": "trust",
      "applies_to": [
        "pay"
      ],
      "public": true,
      "group": "pay",
      "patchable": false,
      "check": {
        "type": "regex_present",
        "pattern": "(?:payment\\.verify|payment_verify|验付)",
        "flags": "i"
      },
      "messages": {
        "pass": "文档中已声明",
        "fail": "需调用支付宝验付接口，不得只校验本地状态",
        "fix": "服务端调用验付接口确认支付",
        "no_patch_reason": "收费协议需真实后端实现"
      },
      "site": {
        "category": "计费",
        "item": "服务端验付",
        "consequence": "无法确认支付真实性"
      }
    },
    {
      "id": "PAY005",
      "title": "履约确认",
      "severity": "blocker",
      "stage": "enforce",
      "required_by_platform": true,
      "dimension": "trust",
      "applies_to": [
        "pay"
      ],
      "public": true,
      "group": "pay",
      "patchable": false,
      "check": {
        "type": "regex_present",
        "pattern": "(?:fulfillment\\.confirm|fulfillment_confirm|履约确认)"
      },
      "messages": {
        "pass": "文档中已声明",
        "fail": "交付资源后需回传履约确认",
        "fix": "交付完成后调用履约确认",
        "no_patch_reason": "收费协议需真实后端实现"
      },
      "site": {
        "category": "计费",
        "item": "履约确认",
        "consequence": "交付无法对账"
      }
    }
  ]
};
