import { redirect } from "next/navigation";

/**
 * /dashboard/classic 默认重定向到策略库子 tab
 */
export default function ClassicIndexPage() {
  redirect("/dashboard/classic/library");
}
