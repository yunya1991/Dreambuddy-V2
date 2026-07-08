import { NextRequest, NextResponse } from "next/server";
import * as fs from "fs";
import * as path from "path";
import { ARTIFACTS_DIR } from "@/lib/task-manager";

/**
 * GET /api/artifact?file=<filename>
 * 读取已生成的策略产物文件内容
 *
 * 安全措施：
 * - 文件名必须匹配 ^[a-zA-Z0-9_.-]+$
 * - 禁止 ../ 路径穿越
 * - 只允许在 ARTIFACTS_DIR 目录内访问
 */
export async function GET(request: NextRequest) {
  try {
    const fileName = request.nextUrl.searchParams.get("file") || "";
    if (!fileName) {
      return NextResponse.json(
        { success: false, error: "file parameter is required" },
        { status: 400 }
      );
    }

    // 安全校验：仅允许字母数字下划线中划线点和短横线
    if (!/^[a-zA-Z0-9_\-.]+$/.test(fileName)) {
      return NextResponse.json(
        { success: false, error: "invalid file name" },
        { status: 400 }
      );
    }

    const filePath = path.join(ARTIFACTS_DIR, fileName);

    // 二次防护：解析后的绝对路径必须在 ARTIFACTS_DIR 内
    const resolved = path.resolve(filePath);
    const artifactsRoot = path.resolve(ARTIFACTS_DIR);
    if (!resolved.startsWith(artifactsRoot + path.sep) && resolved !== artifactsRoot) {
      return NextResponse.json(
        { success: false, error: "path traversal detected" },
        { status: 403 }
      );
    }

    if (!fs.existsSync(resolved)) {
      return NextResponse.json(
        { success: false, error: "file not found", file: fileName, path: resolved },
        { status: 404 }
      );
    }

    const content = fs.readFileSync(resolved, "utf-8");
    const stat = fs.statSync(resolved);

    return NextResponse.json({
      success: true,
      file: fileName,
      content,
      size_bytes: stat.size,
      modified_at: stat.mtime.toISOString(),
    });
  } catch (err) {
    return NextResponse.json(
      { success: false, error: err instanceof Error ? err.message : "unknown error" },
      { status: 500 }
    );
  }
}
