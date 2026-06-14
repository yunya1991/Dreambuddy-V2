import { headers } from "next/headers";
import { AdminSidebar } from "@/components/admin/AdminSidebar";

export const metadata = {
  title: "Dream 管理系统",
  description: "业务数据中台管理系统",
};

export default function AdminLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const h = headers();
  const pathname = (h.get("x-next-pathname") as string) || "/admin";
  const currentPath = pathname || "/admin";

  return (
    <div className="flex min-h-screen bg-gray-50">
      <AdminSidebar currentPath={currentPath} />
      <div className="flex-1 flex flex-col min-w-0">{children}</div>
    </div>
  );
}
