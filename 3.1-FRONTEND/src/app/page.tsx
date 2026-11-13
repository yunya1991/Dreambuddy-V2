import { redirect } from "next/navigation";

// SPEC-52 F1：Agent 工作台为平台默认入口
export default function V3Root() {
  redirect("/dashboard/agent");
}
