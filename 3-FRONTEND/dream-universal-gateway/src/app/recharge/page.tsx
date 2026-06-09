"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";

const RECHARGE_PACKAGES = [
  { id: "basic", name: "基础包", credits: 500, price: 9.9, desc: "适合轻度使用", color: "#0066ff" },
  { id: "standard", name: "标准包", credits: 2000, price: 29.9, desc: "最受欢迎", color: "#00c853", popular: true },
  { id: "pro", name: "专业包", credits: 5000, price: 69.9, desc: "高频用户首选", color: "#ff9500" },
  { id: "enterprise", name: "企业包", credits: 15000, price: 199.9, desc: "不限量使用", color: "#af52de" },
];

export default function RechargePage() {
  const router = useRouter();
  const [selected, setSelected] = useState("standard");
  const [loading, setLoading] = useState(false);

  const current = RECHARGE_PACKAGES.find(p => p.id === selected)!;

  const handleRecharge = async () => {
    setLoading(true);
    // 模拟充值过程
    await new Promise(r => setTimeout(r, 1500));
    setLoading(false);
    alert(`充值成功！已获得 ${current.credits} 积分`);
    router.push("/dashboard");
  };

  return (
    <div className="min-h-screen bg-[#0d0d0d] text-white">
      {/* Header */}
      <header className="bg-[#1a1a1a] border-b border-[#333] px-6 py-4">
        <div className="max-w-4xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-4">
            <Link href="/dashboard" className="text-[#8a8a8a] hover:text-white transition">
              ← 返回
            </Link>
            <span className="text-lg font-semibold">积分充值</span>
          </div>
          <div className="text-sm text-[#8a8a8a]">
            当前积分: <span className="text-yellow-500 font-semibold">1,250 💎</span>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-4xl mx-auto px-6 py-10">
        <div className="text-center mb-10">
          <h1 className="text-2xl font-bold mb-2">选择充值套餐</h1>
          <p className="text-[#8a8a8a]">积分可用于深度分析、策略验证等专业功能</p>
        </div>

        {/* Package Grid */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
          {RECHARGE_PACKAGES.map(pkg => (
            <div
              key={pkg.id}
              onClick={() => setSelected(pkg.id)}
              className={`relative cursor-pointer rounded-xl p-5 transition-all ${
                selected === pkg.id
                  ? "bg-[#1a1a1a] border-2"
                  : "bg-[#141414] border border-[#333] hover:border-[#555]"
              }`}
              style={{ borderColor: selected === pkg.id ? pkg.color : undefined }}
            >
              {pkg.popular && (
                <span className="absolute -top-3 left-1/2 -translate-x-1/2 px-3 py-1 text-[10px] bg-[#00c853] text-white rounded-full font-medium">
                  最受欢迎
                </span>
              )}
              <div className="text-center">
                <div className="text-2xl mb-2" style={{ color: pkg.color }}>
                  {pkg.id === "basic" && "⚡"}
                  {pkg.id === "standard" && "💎"}
                  {pkg.id === "pro" && "🚀"}
                  {pkg.id === "enterprise" && "👑"}
                </div>
                <div className="font-semibold mb-1">{pkg.name}</div>
                <div className="text-2xl font-bold mb-1" style={{ color: pkg.color }}>
                  ¥{pkg.price}
                </div>
                <div className="text-sm text-[#8a8a8a] mb-2">{pkg.desc}</div>
                <div className="text-xs text-[#666]">{pkg.credits.toLocaleString()} 积分</div>
              </div>
            </div>
          ))}
        </div>

        {/* Selected Summary */}
        <div className="bg-[#1a1a1a] rounded-xl p-6 mb-6">
          <div className="flex items-center justify-between">
            <div>
              <div className="text-sm text-[#8a8a8a] mb-1">已选择套餐</div>
              <div className="text-xl font-bold" style={{ color: current.color }}>
                {current.name} · ¥{current.price}
              </div>
            </div>
            <div className="text-right">
              <div className="text-sm text-[#8a8a8a] mb-1">获得积分</div>
              <div className="text-xl font-bold text-yellow-500">
                +{current.credits.toLocaleString()} 💎
              </div>
            </div>
          </div>
        </div>

        {/* Payment Button */}
        <button
          onClick={handleRecharge}
          disabled={loading}
          className="w-full py-4 rounded-xl font-semibold text-lg transition-all disabled:opacity-50"
          style={{ backgroundColor: current.color }}
        >
          {loading ? (
            <span className="flex items-center justify-center gap-2">
              <span className="animate-spin">⏳</span> 处理中...
            </span>
          ) : (
            `立即支付 ¥${current.price}`
          )}
        </button>

        {/* Notice */}
        <div className="mt-6 text-center text-xs text-[#666]">
          <p>• 积分有效期：购买后12个月内有效</p>
          <p>• 如遇问题，请联系客服</p>
        </div>
      </main>
    </div>
  );
}
