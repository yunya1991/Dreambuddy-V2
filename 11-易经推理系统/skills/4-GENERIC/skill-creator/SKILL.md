---
name: skill-creator
description: Guide for creating effective skills with mandatory multi-domain research.
  Use when users want to create a new skill or update an existing skill that extends
  Claude's capabilities with specialized knowledge, workflows, or tool integrations.
  Enforces 5-domain research (AI/finance/product/engineering/GitHub) before skill
  formation per project hard constraint VM-1790765308904.
version: 2.0.0
created: 2026-09-21
updated: 2026-10-01
license: Complete terms in LICENSE.txt
status: active
category: tooling
triggers:
- 创建 skill
- 新建 skill
- 生成 skill
- 更新 skill
- skill-creator
- 创建技能
depends_on:
- dream-skill-index-governance
provides:
- skill-creation
- skill-iteration
- multi-domain-research
cognitive_links:
- VM-1790765308904-4f460e48
- VM-1790864180936-faa44e02
---

## Autonomy Boundary

可自主执行：
- 治理规则检查与合规报告
- SKILL 索引与生命周期管理
- 架构同步校验
- 代码审查与合并建议

需用户确认：
- 执行代码合并（merge 到主分支）
- 修改治理规则本身
- 执行系统级重启或部署

禁止：
- 未经审查直接合并到主分支
- 修改核心治理规则而不经过审批


# Skill Creator

This skill provides guidance for creating effective skills.

## About Skills

Skills are modular, self-contained packages that extend Claude's capabilities by providing
specialized knowledge, workflows, and tools. Think of them as "onboarding guides" for specific
domains or tasks—they transform Claude from a general-purpose agent into a specialized agent
equipped with procedural knowledge that no model can fully possess.

### What Skills Provide

1. Specialized workflows - Multi-step procedures for specific domains
2. Tool integrations - Instructions for working with specific file formats or APIs
3. Domain expertise - Company-specific knowledge, schemas, business logic
4. Bundled resources - Scripts, references, and assets for complex and repetitive tasks

## Core Principles

### Concise is Key

The context window is a public good. Skills share the context window with everything else Claude needs: system prompt, conversation history, other Skills' metadata, and the actual user request.

**Default assumption: Claude is already very smart.** Only add context Claude doesn't already have. Challenge each piece of information: "Does Claude really need this explanation?" and "Does this paragraph justify its token cost?"

Prefer concise examples over verbose explanations.

### Set Appropriate Degrees of Freedom

Match the level of specificity to the task's fragility and variability:

**High freedom (text-based instructions)**: Use when multiple approaches are valid, decisions depend on context, or heuristics guide the approach.

**Medium freedom (pseudocode or scripts with parameters)**: Use when a preferred pattern exists, some variation is acceptable, or configuration affects behavior.

**Low freedom (specific scripts, few parameters)**: Use when operations are fragile and error-prone, consistency is critical, or a specific sequence must be followed.

Think of Claude as exploring a path: a narrow bridge with cliffs needs specific guardrails (low freedom), while an open field allows many routes (high freedom).

### Anatomy of a Skill

Every skill consists of a required SKILL.md file and optional bundled resources:

```
skill-name/
├── SKILL.md (required)
│   ├── YAML frontmatter metadata (required)
│   │   ├── name: (required)
│   │   └── description: (required)
│   └── Markdown instructions (required)
└── Bundled Resources (optional)
    ├── scripts/          - Executable code (Python/Bash/etc.)
    ├── references/       - Documentation intended to be loaded into context as needed
    └── assets/           - Files used in output (templates, icons, fonts, etc.)
```

#### SKILL.md (required)

Every SKILL.md consists of:

- **Frontmatter** (YAML): Contains `name` and `description` fields. These are the only fields that Claude reads to determine when the skill gets used, thus it is very important to be clear and comprehensive in describing what the skill is, and when it should be used.
- **Body** (Markdown): Instructions and guidance for using the skill. Only loaded AFTER the skill triggers (if at all).

#### Bundled Resources (optional)

##### Scripts (`scripts/`)

Executable code (Python/Bash/etc.) for tasks that require deterministic reliability or are repeatedly rewritten.

- **When to include**: When the same code is being rewritten repeatedly or deterministic reliability is needed
- **Example**: `scripts/rotate_pdf.py` for PDF rotation tasks
- **Benefits**: Token efficient, deterministic, may be executed without loading into context
- **Note**: Scripts may still need to be read by Claude for patching or environment-specific adjustments

##### References (`references/`)

Documentation and reference material intended to be loaded as needed into context to inform Claude's process and thinking.

- **When to include**: For documentation that Claude should reference while working
- **Examples**: `references/finance.md` for financial schemas, `references/mnda.md` for company NDA template, `references/policies.md` for company policies, `references/api_docs.md` for API specifications
- **Use cases**: Database schemas, API documentation, domain knowledge, company policies, detailed workflow guides
- **Benefits**: Keeps SKILL.md lean, loaded only when Claude determines it's needed
- **Best practice**: If files are large (>10k words), include grep search patterns in SKILL.md
- **Avoid duplication**: Information should live in either SKILL.md or references files, not both. Prefer references files for detailed information unless it's truly core to the skill—this keeps SKILL.md lean while making information discoverable without hogging the context window. Keep only essential procedural instructions and workflow guidance in SKILL.md; move detailed reference material, schemas, and examples to references files.

##### Assets (`assets/`)

Files not intended to be loaded into context, but rather used within the output Claude produces.

- **When to include**: When the skill needs files that will be used in the final output
- **Examples**: `assets/logo.png` for brand assets, `assets/slides.pptx` for PowerPoint templates, `assets/frontend-template/` for HTML/React boilerplate, `assets/font.ttf` for typography
- **Use cases**: Templates, images, icons, boilerplate code, fonts, sample documents that get copied or modified
- **Benefits**: Separates output resources from documentation, enables Claude to use files without loading them into context

#### What to Not Include in a Skill

A skill should only contain essential files that directly support its functionality. Do NOT create extraneous documentation or auxiliary files, including:

- README.md
- INSTALLATION_GUIDE.md
- QUICK_REFERENCE.md
- CHANGELOG.md
- etc.

The skill should only contain the information needed for an AI agent to do the job at hand. It should not contain auxilary context about the process that went into creating it, setup and testing procedures, user-facing documentation, etc. Creating additional documentation files just adds clutter and confusion.

### Progressive Disclosure Design Principle

Skills use a three-level loading system to manage context efficiently:

1. **Metadata (name + description)** - Always in context (~100 words)
2. **SKILL.md body** - When skill triggers (<5k words)
3. **Bundled resources** - As needed by Claude (Unlimited because scripts can be executed without reading into context window)

#### Progressive Disclosure Patterns

Keep SKILL.md body to the essentials and under 500 lines to minimize context bloat. Split content into separate files when approaching this limit. When splitting out content into other files, it is very important to reference them from SKILL.md and describe clearly when to read them, to ensure the reader of the skill knows they exist and when to use them.

**Key principle:** When a skill supports multiple variations, frameworks, or options, keep only the core workflow and selection guidance in SKILL.md. Move variant-specific details (patterns, examples, configuration) into separate reference files.

**Pattern 1: High-level guide with references**

```markdown
# PDF Processing

## Quick start

Extract text with pdfplumber:
[code example]

## Advanced features

- **Form filling**: See [FORMS.md](FORMS.md) for complete guide
- **API reference**: See [REFERENCE.md](REFERENCE.md) for all methods
- **Examples**: See [EXAMPLES.md](EXAMPLES.md) for common patterns
```

Claude loads FORMS.md, REFERENCE.md, or EXAMPLES.md only when needed.

**Pattern 2: Domain-specific organization**

For Skills with multiple domains, organize content by domain to avoid loading irrelevant context:

```
bigquery-skill/
├── SKILL.md (overview and navigation)
└── reference/
    ├── finance.md (revenue, billing metrics)
    ├── sales.md (opportunities, pipeline)
    ├── product.md (API usage, features)
    └── marketing.md (campaigns, attribution)
```

When a user asks about sales metrics, Claude only reads sales.md.

Similarly, for skills supporting multiple frameworks or variants, organize by variant:

```
cloud-deploy/
├── SKILL.md (workflow + provider selection)
└── references/
    ├── aws.md (AWS deployment patterns)
    ├── gcp.md (GCP deployment patterns)
    └── azure.md (Azure deployment patterns)
```

When the user chooses AWS, Claude only reads aws.md.

**Pattern 3: Conditional details**

Show basic content, link to advanced content:

```markdown
# DOCX Processing

## Creating documents

Use docx-js for new documents. See [DOCX-JS.md](DOCX-JS.md).

## Editing documents

For simple edits, modify the XML directly.

**For tracked changes**: See [REDLINING.md](REDLINING.md)
**For OOXML details**: See [OOXML.md](OOXML.md)
```

Claude reads REDLINING.md or OOXML.md only when the user needs those features.

**Important guidelines:**

- **Avoid deeply nested references** - Keep references one level deep from SKILL.md. All reference files should link directly from SKILL.md.
- **Structure longer reference files** - For files longer than 100 lines, include a table of contents at the top so Claude can see the full scope when previewing.

## Skill Creation Process

Skill creation involves these steps:

1. Understand the skill with concrete examples
2. **Multi-domain research** (mandatory — project hard constraint VM-1790765308904)
3. Plan reusable skill contents (scripts, references, assets)
4. Initialize the skill (run init_skill.py)
5. Edit the skill (implement resources and write SKILL.md)
6. Package the skill (run package_skill.py)
7. Iterate based on real usage

Follow these steps in order, skipping only if there is a clear reason why they are not applicable. **Step 2 (multi-domain research) is mandatory and cannot be skipped** — it ensures the skill draws on industry best practices rather than narrow design.

### Step 1: Understanding the Skill with Concrete Examples

Skip this step only when the skill's usage patterns are already clearly understood. It remains valuable even when working with an existing skill.

To create an effective skill, clearly understand concrete examples of how the skill will be used. This understanding can come from either direct user examples or generated examples that are validated with user feedback.

For example, when building an image-editor skill, relevant questions include:

- "What functionality should the image-editor skill support? Editing, rotating, anything else?"
- "Can you give some examples of how this skill would be used?"
- "I can imagine users asking for things like 'Remove the red-eye from this image' or 'Rotate this image'. Are there other ways you imagine this skill being used?"
- "What would a user say that should trigger this skill?"

To avoid overwhelming users, avoid asking too many questions in a single message. Start with the most important questions and follow up as needed for better effectiveness.

Conclude this step when there is a clear sense of the functionality the skill should support.

### Step 2: Multi-Domain Research (Mandatory)

> **Project hard constraint** (VM-1790765308904): Before forming any skill, you MUST research corresponding multi-domain experiences based on the skill's category. Skipping this step results in narrow skill design lacking industry best-practice support.

**Purpose**: Draw on mature patterns from 5 domains to ensure the new skill is robust, well-structured, and aligned with industry standards.

**Research matrix by skill category**:

| Skill Category | Domains to Research | Key References |
|----------------|---------------------|----------------|
| AI / Agent / Orchestration | AI赛道 + 技术开发 + GitHub生态 | LangChain/CrewAI/MAF multi-agent patterns, LLM orchestration, AI-assisted classification; Linux Kernel MAINTAINERS, K8s Diátaxis; open-source doc tree, OWNERS mechanism |
| Trading / Finance / Risk | 传统金融 + 技术开发 + AI赛道 | Bloomberg tiered release, Goldman data governance, SOX WORM retention, Basel III compliance; code standards; agent frameworks |
| Product / Workflow / Process | 产品管理 + 传统金融 + 技术开发 | Amazon PR/FAQ, Google Design Doc lifecycle, Atlassian content classification; retention policies; Diátaxis four-type |
| Engineering / DevOps / Infra | 技术开发 + GitHub生态 + 产品管理 | Linux Kernel MAINTAINERS Status, K8s Diátaxis, Microsoft Purview; OWNERS, contributor docs; Design Doc lifecycle |
| Research / Analysis | AI赛道 + 产品管理 + GitHub生态 | LLM reasoning patterns, AI classification; PR/FAQ, Design Doc; open-source research docs |
| Generic / Meta (e.g. this skill) | All 5 domains | Full matrix above |

**Execution**:

1. Identify the skill's primary category from the matrix above
2. Research at least 2 of the listed domains (3+ preferred for complex skills)
3. Extract 2-3 concrete patterns/principles from each domain that apply to this skill
4. Document the research findings in the skill's `references/` directory (e.g. `references/domain-research.md`) or inline in SKILL.md
5. Map the findings to skill design decisions (triggers, workflow steps, validation gates)

**Output**: A short research note listing the domains consulted, key patterns extracted, and how they influenced the skill design.

### Step 3: Planning the Reusable Skill Contents

To turn concrete examples into an effective skill, analyze each example by:

1. Considering how to execute on the example from scratch
2. Identifying what scripts, references, and assets would be helpful when executing these workflows repeatedly

Example: When building a `pdf-editor` skill to handle queries like "Help me rotate this PDF," the analysis shows:

1. Rotating a PDF requires re-writing the same code each time
2. A `scripts/rotate_pdf.py` script would be helpful to store in the skill

Example: When designing a `frontend-webapp-builder` skill for queries like "Build me a todo app" or "Build me a dashboard to track my steps," the analysis shows:

1. Writing a frontend webapp requires the same boilerplate HTML/React each time
2. An `assets/hello-world/` template containing the boilerplate HTML/React project files would be helpful to store in the skill

Example: When building a `big-query` skill to handle queries like "How many users have logged in today?" the analysis shows:

1. Querying BigQuery requires re-discovering the table schemas and relationships each time
2. A `references/schema.md` file documenting the table schemas would be helpful to store in the skill

To establish the skill's contents, analyze each concrete example to create a list of the reusable resources to include: scripts, references, and assets.

### Step 4: Initializing the Skill

At this point, it is time to actually create the skill.

Skip this step only if the skill being developed already exists, and iteration or packaging is needed. In this case, continue to the next step.

When creating a new skill from scratch, always run the `init_skill.py` script. The script conveniently generates a new template skill directory that automatically includes everything a skill requires, making the skill creation process much more efficient and reliable.

Usage:

```bash
scripts/init_skill.py <skill-name> --path <output-directory>
```

The script:

- Creates the skill directory at the specified path
- Generates a SKILL.md template with proper frontmatter and TODO placeholders
- Creates example resource directories: `scripts/`, `references/`, and `assets/`
- Adds example files in each directory that can be customized or deleted

After initialization, customize or remove the generated SKILL.md and example files as needed.

### Step 5: Edit the Skill

When editing the (newly-generated or existing) skill, remember that the skill is being created for another instance of Claude to use. Include information that would be beneficial and non-obvious to Claude. Consider what procedural knowledge, domain-specific details, or reusable assets would help another Claude instance execute these tasks more effectively.

#### Learn Proven Design Patterns

Consult these helpful guides based on your skill's needs:

- **Multi-step processes**: See references/workflows.md for sequential workflows and conditional logic
- **Specific output formats or quality standards**: See references/output-patterns.md for template and example patterns

These files contain established best practices for effective skill design.

#### Start with Reusable Skill Contents

To begin implementation, start with the reusable resources identified above: `scripts/`, `references/`, and `assets/` files. Note that this step may require user input. For example, when implementing a `brand-guidelines` skill, the user may need to provide brand assets or templates to store in `assets/`, or documentation to store in `references/`.

Added scripts must be tested by actually running them to ensure there are no bugs and that the output matches what is expected. If there are many similar scripts, only a representative sample needs to be tested to ensure confidence that they all work while balancing time to completion.

Any example files and directories not needed for the skill should be deleted. The initialization script creates example files in `scripts/`, `references/`, and `assets/` to demonstrate structure, but most skills won't need all of them.

#### Update SKILL.md

**Writing Guidelines:** Always use imperative/infinitive form.

##### Frontmatter

Write the YAML frontmatter with `name` and `description` as core fields, plus project lifecycle fields:

- `name`: The skill name
- `description`: This is the primary triggering mechanism for your skill, and helps Claude understand when to use the skill.
  - Include both what the Skill does and specific triggers/contexts for when to use it.
  - Include all "when to use" information here - Not in the body. The body is only loaded after triggering, so "When to Use This Skill" sections in the body are not helpful to Claude.
  - Example description for a `docx` skill: "Comprehensive document creation, editing, and analysis with support for tracked changes, comments, formatting preservation, and text extraction. Use when Claude needs to work with professional documents (.docx files) for: (1) Creating new documents, (2) Modifying or editing content, (3) Working with tracked changes, (4) Adding comments, or any other document tasks"

**Project lifecycle fields** (recommended for all dream-* skills, enables governance by `dream-skill-index-governance`):

```yaml
---
name: my-skill
description: "...what it does + when to use..."
version: 0.1.0
created: YYYY-MM-DD
updated: YYYY-MM-DD
license: Internal
status: proposed        # proposed → shadow → active → deprecated → archived
category: other          # trading|technical|orchestration|research|meta|bugfix|development|other
triggers: [触发词1, 触发词2]
depends_on: []           # skills this one depends on
provides: []             # capabilities this skill provides
cognitive_links: []      # VM-xxx memory IDs from cognitive system
---
```

> Note: The generic Claude skill spec only requires `name` and `description`. The extended fields above are project conventions that enable lifecycle management, conflict detection, and cognitive integration. They are optional but strongly recommended.

##### Body

Write instructions for using the skill and its bundled resources.

### Step 6: Packaging a Skill

Once development of the skill is complete, it must be packaged into a distributable .skill file that gets shared with the user. The packaging process automatically validates the skill first to ensure it meets all requirements:

```bash
scripts/package_skill.py <path/to/skill-folder>
```

Optional output directory specification:

```bash
scripts/package_skill.py <path/to/skill-folder> ./dist
```

The packaging script will:

1. **Validate** the skill automatically, checking:

   - YAML frontmatter format and required fields
   - Skill naming conventions and directory structure
   - Description completeness and quality
   - File organization and resource references

2. **Package** the skill if validation passes, creating a .skill file named after the skill (e.g., `my-skill.skill`) that includes all files and maintains the proper directory structure for distribution. The .skill file is a zip file with a .skill extension.

If validation fails, the script will report the errors and exit without creating a package. Fix any validation errors and run the packaging command again.

### Step 7: Iterate

After testing the skill, users may request improvements. Often this happens right after using the skill, with fresh context of how the skill performed.

**Iteration workflow:**

1. Use the skill on real tasks
2. Notice struggles or inefficiencies
3. Identify how SKILL.md or bundled resources should be updated
4. Implement changes and test again

### Step 8: Register to Governance System (Mandatory · 双保险·AI层)

> **硬约束（不可跳过）**：新 SKILL 创建完成后，必须注册到治理系统，否则不得宣称"创建完成"。
> 本步骤与 git post-commit hook（机器层）构成双保险，任一触发即完成注册。

**执行命令**（在项目根目录）：

```bash
# 显式注册新创建的 SKILL（推荐）
python3 1-ARCHITECTURE/skills/dream-skill-index-governance/auto_register_skill.py \
    --no-auto-detect \
    .trae/skills/<skill-name>

# 若使用双位置存储，两个位置都会被自动扫描，只需指定其中一个即可
```

**注册成功标志**：
- 报告 `status: success` 或 `completed_with_red_flags`
- `registry.json` 中 `total_count` 增加
- 新 SKILL 出现在 `registry.json` 中，`parse_error: null`

**若注册失败**：
1. 检查 SKILL.md frontmatter 格式（必填字段 name/description/version）
2. 检查双位置存储是否一致（`.trae/skills/` 与 `1-ARCHITECTURE/skills/`）
3. 修复后重新运行注册命令

**日志**：`1-ARCHITECTURE/skills/dream-skill-index-governance/auto_register.log`

