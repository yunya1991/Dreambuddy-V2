"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useClassicSystemData } from "../../hooks/useClassicSystemData";
import { ClassicSubTabContent, type ClassicSubTab } from "../../components/ClassicSubTabContent";

const VALID_SUBTABS: ClassicSubTab[] = [
  "library",
  "strategies",
  "sandbox",
  "approvals",
  "signals",
  "filter",
  "execution",
  "exit",
  "arena",
  "universe",
  "macro",
  "evaluation",
];

interface ClassicSubTabPageProps {
  params: { subtab: string };
}

/**
 * 经典系统子 Tab 动态路由页面
 *
 * 根据 URL 中的 subtab 参数渲染对应内容。
 * 数据通过 useClassicSystemData hook 统一加载。
 */
export default function ClassicSubTabPage({ params }: ClassicSubTabPageProps) {
  const router = useRouter();
  const subtab = params.subtab as ClassicSubTab;
  const data = useClassicSystemData();

  // 无效子 tab → 重定向到 library
  useEffect(() => {
    if (!VALID_SUBTABS.includes(subtab)) {
      router.replace("/dashboard/classic/library");
    }
  }, [subtab, router]);

  // 加载经典系统数据
  useEffect(() => {
    if (VALID_SUBTABS.includes(subtab)) {
      data.loadClassicSystemData();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [subtab]);

  if (!VALID_SUBTABS.includes(subtab)) {
    return <div className="text-[#8a8a8a] text-center py-8">跳转中...</div>;
  }

  return <ClassicSubTabContent subTab={subtab} data={data} />;
}
