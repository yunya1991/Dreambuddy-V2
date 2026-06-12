interface StatsCardProps {
  label: string;
  value: string | number;
  subtext?: string;
  icon?: string;
  tone?: "blue" | "green" | "yellow" | "red" | "purple" | "gray";
}

const toneClasses: Record<string, string> = {
  blue: "bg-blue-50 text-blue-700 border-blue-100",
  green: "bg-green-50 text-green-700 border-green-100",
  yellow: "bg-yellow-50 text-yellow-700 border-yellow-100",
  red: "bg-red-50 text-red-700 border-red-100",
  purple: "bg-purple-50 text-purple-700 border-purple-100",
  gray: "bg-gray-50 text-gray-700 border-gray-200",
};

export function StatsCard({
  label,
  value,
  subtext,
  icon = "📊",
  tone = "blue",
}: StatsCardProps) {
  return (
    <div className={`rounded-lg border p-4 ${toneClasses[tone]} transition-transform hover:scale-[1.02]`}>
      <div className="flex items-start justify-between">
        <div className="flex-1 min-w-0">
          <div className="text-xs font-medium uppercase tracking-wide opacity-80">
            {label}
          </div>
          <div className="text-2xl font-bold mt-1 truncate">{value}</div>
          {subtext && (
            <div className="text-xs mt-1 opacity-70 truncate">{subtext}</div>
          )}
        </div>
        <div className="text-2xl ml-3">{icon}</div>
      </div>
    </div>
  );
}

export function StatsGrid({ children }: { children: React.ReactNode }) {
  return <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">{children}</div>;
}
